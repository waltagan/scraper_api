#!/usr/bin/env python3
"""
Análise estatística de logs de batch scraping.
Uso: python analyze_batch_logs.py [batch_id] [log_file]
"""

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def parse_log_line(line: str) -> dict | None:
    try:
        return json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def find_batch_id(logs: list[dict]) -> str | None:
    for entry in logs:
        m = re.search(r'\[Batch (\w+)\] Iniciando:', entry.get('message', ''))
        if m:
            return m.group(1)
    return None


def analyze_batch(log_file: str, target_batch: str | None = None):
    print(f"Lendo {log_file}...")
    raw_lines = Path(log_file).read_text(encoding='utf-8', errors='replace').splitlines()
    
    entries = []
    for line in raw_lines:
        parsed = parse_log_line(line)
        if parsed:
            entries.append(parsed)
    
    print(f"  {len(entries):,} entradas de log parseadas")
    
    if not target_batch:
        for entry in reversed(entries):
            m = re.search(r'\[Batch (\w+)\] Iniciando:', entry.get('message', ''))
            if m:
                target_batch = m.group(1)
                break
    
    if not target_batch:
        print("ERRO: Nenhum batch encontrado nos logs")
        return
    
    print(f"  Analisando batch: {target_batch}\n")
    
    batch_tag = f"[Batch {target_batch}]"
    company_tag = f"[B{target_batch}]"
    
    # ─── Tempos de processamento por empresa ───
    company_times_ms = []
    company_pages = []
    company_success_pages = []
    
    # ─── Tempos de subpage batches ───
    subpage_batch_times_ms = []
    subpage_batch_sizes = []
    
    # ─── Erros ───
    error_types = Counter()
    unreachable_urls = []
    main_page_failures = []
    strategy_failures = []
    
    # ─── Proxy ───
    proxy_selected = 0
    proxy_unavailable = 0
    
    # ─── Circuit Breaker ───
    circuit_opens = []
    
    # ─── Domínios lentos ───
    slow_domains = []
    
    # ─── Curl fallbacks ───
    curl_fallback_count = 0
    curl_fallback_domains = Counter()
    
    # ─── Batch timing ───
    batch_start_time = None
    batch_end_time = None
    batch_total_seconds = None
    
    # ─── Producer ───
    producer_loads = []
    
    # ─── Flush ───
    flush_events = []
    
    # ─── Chunks ───
    chunk_tokens = []
    
    for entry in entries:
        msg = entry.get('message', '')
        ts = entry.get('timestamp', '')
        level = entry.get('level', '')
        
        # Batch start/end
        if batch_tag in msg and 'Iniciando:' in msg:
            batch_start_time = ts
        if batch_tag in msg and 'Concluido em' in msg:
            batch_end_time = ts
            m = re.search(r'Concluido em (\d+)s', msg)
            if m:
                batch_total_seconds = int(m.group(1))
        
        # Per-company total time
        if company_tag in msg and 'scrape_all_subpages concluído:' in msg:
            m = re.search(r'(\d+) páginas \((\d+) sucesso\) em ([\d.]+)ms', msg)
            if m:
                pages = int(m.group(1))
                success = int(m.group(2))
                time_ms = float(m.group(3))
                company_times_ms.append(time_ms)
                company_pages.append(pages)
                company_success_pages.append(success)
        
        # Subpage batch times
        if company_tag in msg and 'Scrape de' in msg and 'subpages concluído em' in msg:
            m = re.search(r'Scrape de (\d+) subpages concluído em ([\d.]+)ms', msg)
            if m:
                subpage_batch_sizes.append(int(m.group(1)))
                subpage_batch_times_ms.append(float(m.group(2)))
        
        # URL inacessível
        if company_tag in msg and 'URL inacessível:' in msg:
            m = re.search(r'URL inacessível: (.+?) - (.+)', msg)
            if m:
                unreachable_urls.append({'url': m.group(1), 'reason': m.group(2)})
                error_types['url_inacessivel'] += 1
        
        # Main page failure
        if company_tag in msg and 'Falha ao obter main page de' in msg:
            m = re.search(r'Falha ao obter main page de (.+?) - (.+)', msg)
            if m:
                main_page_failures.append({'url': m.group(1), 'reason': m.group(2)})
                reason = m.group(2)
                if 'NO_RESPONSE' in reason:
                    error_types['no_response'] += 1
                elif 'CLOUDFLARE' in reason:
                    error_types['cloudflare'] += 1
                elif 'BLOCKED' in reason:
                    error_types['blocked'] += 1
                elif 'TIMEOUT' in reason:
                    error_types['timeout'] += 1
                elif 'EMPTY_CONTENT' in reason:
                    error_types['empty_content'] += 1
                elif 'SSL_ERROR' in reason:
                    error_types['ssl_error'] += 1
                elif 'NOT_FOUND' in reason:
                    error_types['not_found'] += 1
                else:
                    error_types['other_main_page_fail'] += 1
        
        # All strategies failed
        if company_tag in msg and 'Todas estratégias falharam para' in msg:
            m = re.search(r'Todas estratégias falharam para (.+)', msg)
            if m:
                strategy_failures.append(m.group(1))
        
        # Proxy selected
        if company_tag in msg and 'Proxy selecionado:' in msg:
            proxy_selected += 1
        
        # Proxy unavailable
        if 'Nenhum proxy disponível' in msg or 'Nenhum proxy saudável' in msg:
            proxy_unavailable += 1
        
        # Circuit breaker
        if 'Circuit OPEN para' in msg:
            m = re.search(r'Circuit OPEN para (.+?) \(', msg)
            if m:
                circuit_opens.append(m.group(1))
        
        # Slow domains
        if 'Domínio marcado como lento:' in msg:
            m = re.search(r'Domínio marcado como lento: (.+)', msg)
            if m:
                slow_domains.append(m.group(1))
        
        # Curl fallback
        if 'Curl com headers falhou para' in msg:
            curl_fallback_count += 1
            m = re.search(r'falhou para (https?://[^\s,]+)', msg)
            if m:
                from urllib.parse import urlparse
                domain = urlparse(m.group(1)).netloc
                curl_fallback_domains[domain] += 1
        
        # Producer loads
        if batch_tag in msg and 'Producer:' in msg:
            producer_loads.append(msg)
        
        # Flush events
        if batch_tag in msg and 'Flush #' in msg:
            flush_events.append(msg)
        
        # Chunk tokens
        if 'Chunking concluído:' in msg:
            m = re.search(r'total: ([\d,]+) tokens', msg)
            if m:
                chunk_tokens.append(int(m.group(1).replace(',', '')))
    
    # ═══════════════════════════════════════════
    # RESULTADOS
    # ═══════════════════════════════════════════
    
    print("=" * 70)
    print(f"  ANÁLISE DO BATCH {target_batch}")
    print("=" * 70)
    
    # ─── Resumo geral ───
    print("\n📊 RESUMO GERAL")
    print("-" * 50)
    if batch_start_time:
        print(f"  Início:           {batch_start_time}")
    if batch_end_time:
        print(f"  Fim:              {batch_end_time}")
    if batch_total_seconds:
        mins = batch_total_seconds / 60
        print(f"  Duração total:    {batch_total_seconds}s ({mins:.1f} min)")
    elif batch_start_time and company_times_ms:
        # Estimar pela diferença de timestamps
        pass
    
    total_companies = len(company_times_ms)
    print(f"  Empresas com tempo medido: {total_companies}")
    if total_companies and batch_total_seconds:
        print(f"  Throughput:       {total_companies / (batch_total_seconds / 60):.1f} empresas/min")
    
    # ─── Percentis de tempo total por empresa ───
    if company_times_ms:
        company_times_ms.sort()
        n = len(company_times_ms)
        
        def percentile(data, p):
            idx = int(len(data) * p / 100)
            idx = min(idx, len(data) - 1)
            return data[idx]
        
        print(f"\n⏱️  TEMPO DE PROCESSAMENTO POR EMPRESA (ms)")
        print("-" * 50)
        print(f"  Total amostras:  {n}")
        print(f"  Mínimo:          {company_times_ms[0]:,.0f} ms ({company_times_ms[0]/1000:.1f}s)")
        print(f"  P10:             {percentile(company_times_ms, 10):,.0f} ms ({percentile(company_times_ms, 10)/1000:.1f}s)")
        print(f"  P25:             {percentile(company_times_ms, 25):,.0f} ms ({percentile(company_times_ms, 25)/1000:.1f}s)")
        print(f"  P50 (mediana):   {percentile(company_times_ms, 50):,.0f} ms ({percentile(company_times_ms, 50)/1000:.1f}s)")
        print(f"  P70:             {percentile(company_times_ms, 70):,.0f} ms ({percentile(company_times_ms, 70)/1000:.1f}s)")
        print(f"  P75:             {percentile(company_times_ms, 75):,.0f} ms ({percentile(company_times_ms, 75)/1000:.1f}s)")
        print(f"  P90:             {percentile(company_times_ms, 90):,.0f} ms ({percentile(company_times_ms, 90)/1000:.1f}s)")
        print(f"  P95:             {percentile(company_times_ms, 95):,.0f} ms ({percentile(company_times_ms, 95)/1000:.1f}s)")
        print(f"  P99:             {percentile(company_times_ms, 99):,.0f} ms ({percentile(company_times_ms, 99)/1000:.1f}s)")
        print(f"  Máximo:          {company_times_ms[-1]:,.0f} ms ({company_times_ms[-1]/1000:.1f}s)")
        avg = sum(company_times_ms) / n
        print(f"  Média:           {avg:,.0f} ms ({avg/1000:.1f}s)")
        
        # Distribuição por faixas
        print(f"\n  Distribuição por faixa:")
        bins = [(0, 5000), (5000, 15000), (15000, 30000), (30000, 60000),
                (60000, 120000), (120000, 300000), (300000, float('inf'))]
        labels = ['< 5s', '5-15s', '15-30s', '30-60s', '60-120s', '120-300s', '> 300s']
        for (lo, hi), label in zip(bins, labels):
            count = sum(1 for t in company_times_ms if lo <= t < hi)
            pct = count / n * 100
            bar = '█' * int(pct / 2)
            print(f"    {label:>10s}: {count:>5d} ({pct:5.1f}%) {bar}")
    
    # ─── Páginas por empresa ───
    if company_pages:
        print(f"\n📄 PÁGINAS POR EMPRESA")
        print("-" * 50)
        avg_pages = sum(company_pages) / len(company_pages)
        avg_success = sum(company_success_pages) / len(company_success_pages)
        print(f"  Média de páginas:     {avg_pages:.1f}")
        print(f"  Média de sucesso:     {avg_success:.1f}")
        print(f"  Taxa sucesso/página:  {avg_success/avg_pages*100:.1f}%")
    
    # ─── Subpage batch times ───
    if subpage_batch_times_ms:
        subpage_batch_times_ms.sort()
        n = len(subpage_batch_times_ms)
        print(f"\n📦 TEMPO DE BATCH DE SUBPAGES (ms)")
        print("-" * 50)
        print(f"  Total batches:   {n}")
        print(f"  P50:             {percentile(subpage_batch_times_ms, 50):,.0f} ms")
        print(f"  P90:             {percentile(subpage_batch_times_ms, 90):,.0f} ms")
        print(f"  P99:             {percentile(subpage_batch_times_ms, 99):,.0f} ms")
        print(f"  Média:           {sum(subpage_batch_times_ms)/n:,.0f} ms")
        if subpage_batch_sizes:
            avg_batch_size = sum(subpage_batch_sizes) / len(subpage_batch_sizes)
            print(f"  Média subpages/batch: {avg_batch_size:.1f}")
    
    # ─── Erros ───
    total_errors = sum(error_types.values()) + len(unreachable_urls)
    if total_errors or main_page_failures:
        print(f"\n❌ ERROS ({total_errors} total)")
        print("-" * 50)
        
        # URL inacessíveis
        url_error_types = Counter()
        for u in unreachable_urls:
            reason = u['reason']
            if 'DNS' in reason:
                url_error_types['DNS não resolve'] += 1
            elif 'Timeout' in reason or 'timeout' in reason:
                url_error_types['Timeout conexão'] += 1
            elif 'Conexão recusada' in reason or 'refused' in reason:
                url_error_types['Conexão recusada'] += 1
            elif 'SSL' in reason:
                url_error_types['Erro SSL'] += 1
            elif 'BLOCKED' in reason or 'bloqueio' in reason:
                url_error_types['Bloqueado'] += 1
            elif 'redirect' in reason.lower():
                url_error_types['Redirect loop'] += 1
            else:
                url_error_types['Outro'] += 1
        
        print(f"\n  Erro por tipo (URL inacessível):")
        for err_type, count in url_error_types.most_common():
            pct = count / max(total_errors, 1) * 100
            print(f"    {err_type:>25s}: {count:>4d} ({pct:5.1f}%)")
        
        print(f"\n  Erro por tipo (main page):")
        for err_type, count in error_types.most_common():
            pct = count / max(total_errors, 1) * 100
            print(f"    {err_type:>25s}: {count:>4d} ({pct:5.1f}%)")
    
    # ─── Proxy ───
    print(f"\n🔐 PROXIES")
    print("-" * 50)
    print(f"  Proxy selecionado:    {proxy_selected} vezes")
    print(f"  Proxy indisponível:   {proxy_unavailable} vezes")
    if proxy_selected + proxy_unavailable > 0:
        success_rate = proxy_selected / (proxy_selected + proxy_unavailable) * 100
        print(f"  Taxa de disponibilidade: {success_rate:.1f}%")
    
    # ─── Circuit Breaker ───
    if circuit_opens:
        print(f"\n🔌 CIRCUIT BREAKER")
        print("-" * 50)
        cb_counter = Counter(circuit_opens)
        print(f"  Total aberturas: {len(circuit_opens)}")
        print(f"  Domínios únicos: {len(cb_counter)}")
        print(f"  Top domínios:")
        for domain, count in cb_counter.most_common(10):
            print(f"    {domain}: {count}x")
    
    # ─── Domínios lentos ───
    if slow_domains:
        print(f"\n🐢 DOMÍNIOS LENTOS")
        print("-" * 50)
        print(f"  Total: {len(slow_domains)} domínios marcados como lentos")
    
    # ─── Curl fallbacks ───
    if curl_fallback_count:
        print(f"\n🔄 CURL FALLBACK (headers falharam)")
        print("-" * 50)
        print(f"  Total fallbacks: {curl_fallback_count}")
        print(f"  Domínios únicos: {len(curl_fallback_domains)}")
        print(f"  Top domínios:")
        for domain, count in curl_fallback_domains.most_common(10):
            print(f"    {domain}: {count}x")
    
    # ─── Strategy failures ───
    if strategy_failures:
        print(f"\n💀 ESTRATÉGIAS ESGOTADAS (todas falharam)")
        print("-" * 50)
        print(f"  Total: {len(strategy_failures)} sites")
    
    # ─── Chunks/Tokens ───
    if chunk_tokens:
        chunk_tokens.sort()
        n = len(chunk_tokens)
        print(f"\n📝 TOKENS POR CHUNK")
        print("-" * 50)
        print(f"  Total chunks:    {n}")
        print(f"  P50:             {percentile(chunk_tokens, 50):,} tokens")
        print(f"  P90:             {percentile(chunk_tokens, 90):,} tokens")
        print(f"  Média:           {sum(chunk_tokens)//n:,} tokens")
        print(f"  Total tokens:    {sum(chunk_tokens):,}")
    
    # ─── Flush ───
    if flush_events:
        print(f"\n💾 FLUSH EVENTS")
        print("-" * 50)
        for event in flush_events:
            print(f"  {event}")
    
    # ─── Top 10 empresas mais lentas ───
    if company_times_ms:
        print(f"\n🐌 TOP 10 EMPRESAS MAIS LENTAS")
        print("-" * 50)
        for i, t in enumerate(company_times_ms[-10:][::-1], 1):
            print(f"  {i:>2d}. {t:>10,.0f} ms ({t/1000:.1f}s)")
    
    # ─── Resumo final ───
    if company_times_ms:
        print(f"\n{'=' * 70}")
        print(f"  RESUMO EXECUTIVO")
        print(f"{'=' * 70}")
        
        success_count = sum(1 for p, s in zip(company_pages, company_success_pages) if s > 0)
        error_count = total_companies - success_count
        
        print(f"  Empresas processadas:  {total_companies}")
        
        avg_ms = sum(company_times_ms) / len(company_times_ms)
        p50 = percentile(company_times_ms, 50)
        p90 = percentile(company_times_ms, 90)
        p99 = percentile(company_times_ms, 99)
        
        print(f"  Tempo médio:           {avg_ms/1000:.1f}s")
        print(f"  Tempo P50:             {p50/1000:.1f}s")
        print(f"  Tempo P90:             {p90/1000:.1f}s")
        print(f"  Tempo P99:             {p99/1000:.1f}s")
        
        under_30 = sum(1 for t in company_times_ms if t < 30000)
        under_60 = sum(1 for t in company_times_ms if t < 60000)
        over_120 = sum(1 for t in company_times_ms if t >= 120000)
        
        print(f"  < 30s:                 {under_30}/{total_companies} ({under_30/total_companies*100:.1f}%)")
        print(f"  < 60s:                 {under_60}/{total_companies} ({under_60/total_companies*100:.1f}%)")
        print(f"  > 120s (outliers):     {over_120}/{total_companies} ({over_120/total_companies*100:.1f}%)")
        
        if proxy_unavailable > 0:
            print(f"\n  ⚠️  Proxy indisponível {proxy_unavailable}x")
        if len(circuit_opens) > 0:
            print(f"  ⚠️  Circuit breaker aberto {len(circuit_opens)}x")
        if over_120 > total_companies * 0.05:
            print(f"  ⚠️  {over_120} empresas > 120s ({over_120/total_companies*100:.1f}%) - possível gargalo em sites lentos/retries")
    
    print()


if __name__ == '__main__':
    log_file = sys.argv[2] if len(sys.argv) > 2 else 'logs/server_20260219.log'
    batch_id = sys.argv[1] if len(sys.argv) > 1 else None
    analyze_batch(log_file, batch_id)
