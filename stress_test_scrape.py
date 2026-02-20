#!/usr/bin/env python3
"""
Stress test & diagnóstico do pipeline de scraping.

Testa cada fase individualmente para identificar gargalos.
Foco nos top 10 sites mais lentos que já foram scrapados.

Uso: python stress_test_scrape.py [batch_id] [log_file]
"""

import asyncio
import json
import os
import re
import subprocess
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SEPARATOR = "━" * 75


def ms_fmt(ms: float) -> str:
    if ms >= 60000:
        return f"{ms/60000:.1f}min"
    if ms >= 1000:
        return f"{ms/1000:.1f}s"
    return f"{ms:.0f}ms"


def pct(a: float, b: float) -> str:
    if b == 0:
        return "N/A"
    return f"{a/b*100:.0f}%"


# ═══════════════════════════════════════════════════════════
# 1. EXTRAÇÃO DE URLs DOS LOGS (top lentos + amostra)
# ═══════════════════════════════════════════════════════════

def extract_test_urls_from_logs(log_file: str, batch_id: str) -> List[Dict]:
    """
    Correlaciona 'Analisando site: URL' com 'scrape_all_subpages concluído'
    usando proximidade temporal para encontrar os mais lentos.
    """
    entries = []
    for line in Path(log_file).read_text(errors="replace").splitlines():
        try:
            entries.append(json.loads(line.strip()))
        except (json.JSONDecodeError, ValueError):
            pass

    tag = f"[B{batch_id}]"
    analyze_events = []
    complete_events = []
    url_inaccessible = []

    for e in entries:
        msg = e.get("message", "")
        ts = e.get("timestamp", "")
        if tag not in msg:
            continue
        m = re.search(r"Analisando site: (.+)", msg)
        if m:
            analyze_events.append({"url": m.group(1), "ts": ts, "idx": len(analyze_events)})
        m = re.search(r"scrape_all_subpages concluído: (\d+) páginas \((\d+) sucesso\) em ([\d.]+)ms", msg)
        if m:
            complete_events.append({
                "pages": int(m.group(1)),
                "success": int(m.group(2)),
                "time_ms": float(m.group(3)),
                "ts": ts,
            })
        m = re.search(r"URL inacessível: (.+?) -", msg)
        if m:
            url_inaccessible.append(m.group(1))

    complete_events.sort(key=lambda x: x["time_ms"], reverse=True)
    analyzed_urls = [a["url"] for a in analyze_events]

    top_slow_urls = []
    seen = set()

    for c in complete_events[:30]:
        ts_prefix = c["ts"][:16]
        for a in reversed(analyze_events):
            if a["ts"][:16] <= ts_prefix and a["url"] not in seen:
                top_slow_urls.append({
                    "url": a["url"],
                    "time_ms": c["time_ms"],
                    "pages": c["pages"],
                    "success": c["success"],
                })
                seen.add(a["url"])
                break

    fast_urls = []
    for c in sorted(complete_events, key=lambda x: x["time_ms"])[:10]:
        ts_prefix = c["ts"][:16]
        for a in reversed(analyze_events):
            if a["ts"][:16] <= ts_prefix and a["url"] not in seen:
                fast_urls.append({
                    "url": a["url"],
                    "time_ms": c["time_ms"],
                    "pages": c["pages"],
                    "success": c["success"],
                })
                seen.add(a["url"])
                break

    for url in url_inaccessible[:5]:
        if url not in seen:
            top_slow_urls.append({"url": url, "time_ms": -1, "pages": 0, "success": 0})
            seen.add(url)

    return top_slow_urls[:10], fast_urls[:5], analyzed_urls


# ═══════════════════════════════════════════════════════════
# 2. TESTES INDIVIDUAIS POR FASE
# ═══════════════════════════════════════════════════════════

async def test_dns(hostname: str) -> Dict:
    start = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
        results = await asyncio.wait_for(loop.getaddrinfo(hostname, None), timeout=5.0)
        ms = (time.perf_counter() - start) * 1000
        return {"ok": True, "ms": ms, "ip": results[0][4][0] if results else "?"}
    except asyncio.TimeoutError:
        return {"ok": False, "ms": (time.perf_counter() - start) * 1000, "error": "TIMEOUT"}
    except Exception as e:
        return {"ok": False, "ms": (time.perf_counter() - start) * 1000, "error": str(e)[:50]}


async def test_raw_curl(url: str, proxy: str = None, timeout: int = 10) -> Dict:
    """Curl raw com métricas detalhadas de timing."""
    fmt = "%{http_code}|%{time_namelookup}|%{time_connect}|%{time_appconnect}|%{time_starttransfer}|%{time_total}|%{size_download}"
    cmd = [
        "curl", "-s", "-L", "-k", "--compressed",
        "--max-time", str(timeout), "-o", "/dev/null", "-w", fmt,
        "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0",
    ]
    if proxy:
        cmd.extend(["-x", proxy])
    cmd.append(url)

    start = time.perf_counter()
    try:
        res = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=timeout + 5
        )
        wall_ms = (time.perf_counter() - start) * 1000
        if res.returncode == 0 and "|" in res.stdout:
            parts = res.stdout.strip().split("|")
            return {
                "ok": True, "wall_ms": wall_ms,
                "status": int(parts[0]) if parts[0].isdigit() else 0,
                "dns_s": float(parts[1]), "connect_s": float(parts[2]),
                "tls_s": float(parts[3]), "ttfb_s": float(parts[4]),
                "total_s": float(parts[5]),
                "size_bytes": int(float(parts[6])),
            }
        return {"ok": False, "wall_ms": wall_ms, "error": f"exit={res.returncode}"}
    except Exception as e:
        return {"ok": False, "wall_ms": (time.perf_counter() - start) * 1000, "error": str(e)[:60]}


async def test_curl_cffi(url: str, proxy: str = None, timeout: int = 10) -> Dict:
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        return {"ok": False, "error": "curl_cffi not installed"}

    start = time.perf_counter()
    try:
        async with AsyncSession(
            impersonate="chrome120", proxy=proxy, timeout=timeout, verify=False
        ) as session:
            resp = await session.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            ms = (time.perf_counter() - start) * 1000
            return {
                "ok": True, "wall_ms": ms,
                "status": resp.status_code,
                "size_chars": len(resp.text) if resp.text else 0,
            }
    except Exception as e:
        return {"ok": False, "wall_ms": (time.perf_counter() - start) * 1000, "error": str(e)[:80]}


async def test_prober_phases(url: str) -> Dict:
    """
    Testa o URL prober decompondo em fases:
    1. Teste direto da URL original
    2. Geração de variações
    3. Teste de cada variação individualmente
    """
    result = {"url": url, "phases": [], "total_ms": 0}
    overall_start = time.perf_counter()

    try:
        from curl_cffi.requests import AsyncSession as _AS
        HAS_CFFI = True
    except ImportError:
        HAS_CFFI = False

    parsed = urlparse(url if "://" in url else f"https://{url}")

    # Phase 1: teste direto com HEAD
    start = time.perf_counter()
    direct_ok = False
    direct_status = 0
    if HAS_CFFI:
        try:
            async with _AS(impersonate="chrome120", timeout=10, verify=False, max_redirects=5) as sess:
                resp = await sess.head(url, allow_redirects=True)
                direct_status = resp.status_code
                if direct_status < 400:
                    direct_ok = True
                elif direct_status == 403:
                    resp = await sess.get(url, allow_redirects=True)
                    direct_status = resp.status_code
                    direct_ok = direct_status < 400
        except Exception as e:
            direct_status = 0
    direct_ms = (time.perf_counter() - start) * 1000
    result["phases"].append({
        "name": "HEAD direto", "url": url, "ms": direct_ms,
        "ok": direct_ok, "status": direct_status
    })

    # Phase 2: gerar variações
    from app.services.scraper.url_prober import URLProber
    prober = URLProber()
    variations = prober._generate_variations(url)
    other_vars = [v for v in variations if v != url]
    result["variations"] = variations

    if direct_ok:
        result["total_ms"] = (time.perf_counter() - overall_start) * 1000
        result["winner"] = url
        result["winner_phase"] = "HEAD direto"
        return result

    # Phase 3: testar cada variação
    for var_url in other_vars:
        start = time.perf_counter()
        var_ok = False
        var_status = 0
        method = "HEAD"
        if HAS_CFFI:
            try:
                async with _AS(impersonate="chrome120", timeout=10, verify=False, max_redirects=5) as sess:
                    resp = await sess.head(var_url, allow_redirects=True)
                    var_status = resp.status_code
                    if var_status < 400:
                        var_ok = True
                    elif var_status == 403:
                        method = "GET"
                        resp = await sess.get(var_url, allow_redirects=True)
                        var_status = resp.status_code
                        var_ok = var_status < 400
            except Exception:
                var_status = 0
        var_ms = (time.perf_counter() - start) * 1000
        result["phases"].append({
            "name": f"{method} variação", "url": var_url, "ms": var_ms,
            "ok": var_ok, "status": var_status
        })
        if var_ok and "winner" not in result:
            result["winner"] = var_url
            result["winner_phase"] = f"{method} {var_url}"

    result["total_ms"] = (time.perf_counter() - overall_start) * 1000
    return result


async def test_full_probe(url: str) -> Dict:
    """Testa o prober completo como é usado no pipeline."""
    from app.services.scraper.url_prober import url_prober, URLNotReachable
    url_prober._cache.clear()

    start = time.perf_counter()
    try:
        best_url, probe_time = await url_prober.probe(url)
        ms = (time.perf_counter() - start) * 1000
        return {"ok": True, "wall_ms": ms, "best_url": best_url, "probe_reported_ms": probe_time}
    except URLNotReachable as e:
        ms = (time.perf_counter() - start) * 1000
        log_msg = e.get_log_message() if hasattr(e, "get_log_message") else str(e)
        return {"ok": False, "wall_ms": ms, "error": log_msg[:80]}
    except Exception as e:
        return {"ok": False, "wall_ms": (time.perf_counter() - start) * 1000, "error": str(e)[:80]}


async def test_analyzer(url: str) -> Dict:
    """Testa o site analyzer."""
    from app.services.scraper.site_analyzer import SiteAnalyzer
    analyzer = SiteAnalyzer(timeout=10.0, probe_attempts=1)

    start = time.perf_counter()
    try:
        profile = await analyzer.analyze(url)
        ms = (time.perf_counter() - start) * 1000
        return {
            "ok": profile.status_code == 200, "wall_ms": ms,
            "status": profile.status_code,
            "site_type": profile.site_type.value,
            "protection": profile.protection_type.value,
            "strategy": profile.best_strategy.value,
            "content_len": profile.content_length,
            "has_reusable_html": bool(profile.raw_html and len(profile.raw_html or "") > 100),
        }
    except Exception as e:
        return {"ok": False, "wall_ms": (time.perf_counter() - start) * 1000, "error": str(e)[:80]}


async def test_proxy_pool(n: int = 30) -> Dict:
    """Testa velocidade e disponibilidade do pool de proxy."""
    from app.core.proxy import proxy_manager
    from app.services.scraper_manager.proxy_manager import proxy_pool
    proxy_pool.set_source_manager(proxy_manager)
    await proxy_manager._refresh_proxies()

    times = []
    found = 0
    proxies_seen = set()
    for _ in range(n):
        start = time.perf_counter()
        proxy = await proxy_pool.get_healthy_proxy()
        ms = (time.perf_counter() - start) * 1000
        times.append(ms)
        if proxy:
            found += 1
            proxies_seen.add(proxy)

    return {
        "total_in_pool": len(proxy_manager.proxies),
        "attempts": n, "found": found,
        "unique_proxies": len(proxies_seen),
        "avg_ms": statistics.mean(times) if times else 0,
        "p50_ms": sorted(times)[len(times) // 2] if times else 0,
        "max_ms": max(times) if times else 0,
        "sample_proxy": list(proxies_seen)[0][:50] if proxies_seen else None,
    }


async def test_proxy_latency_to_site(url: str, proxy: str) -> Dict:
    """Compara tempo direto vs via proxy para uma URL."""
    direct = await test_raw_curl(url, timeout=10)
    via_proxy = await test_raw_curl(url, proxy=proxy, timeout=15)
    return {"direct": direct, "proxy": via_proxy}


# ═══════════════════════════════════════════════════════════
# 3. TESTE DO PIPELINE COMPLETO
# ═══════════════════════════════════════════════════════════

async def test_full_pipeline(url: str) -> Dict:
    """
    Testa o pipeline completo com timing de cada fase.
    probe -> analyze -> main_page -> subpages
    """
    result = {"url": url, "timings": {}}
    total_start = time.perf_counter()

    # Fase 1: Probe
    probe_result = await test_full_probe(url)
    result["timings"]["probe"] = probe_result
    best_url = probe_result.get("best_url", url) if probe_result.get("ok") else url

    if not probe_result.get("ok"):
        result["timings"]["total_ms"] = (time.perf_counter() - total_start) * 1000
        result["blocked_at"] = "probe"
        return result

    # Fase 2: Analyze
    analyze_result = await test_analyzer(best_url)
    result["timings"]["analyzer"] = analyze_result

    if not analyze_result.get("ok") and not analyze_result.get("has_reusable_html"):
        result["timings"]["total_ms"] = (time.perf_counter() - total_start) * 1000
        return result

    # Fase 3: Main page (simular cffi_scrape_safe)
    main_start = time.perf_counter()
    cffi_result = await test_curl_cffi(best_url, timeout=10)
    result["timings"]["main_page_cffi"] = cffi_result
    result["timings"]["main_page_cffi"]["wall_ms"] = (time.perf_counter() - main_start) * 1000

    result["timings"]["total_ms"] = (time.perf_counter() - total_start) * 1000
    return result


# ═══════════════════════════════════════════════════════════
# 4. RELATÓRIOS
# ═══════════════════════════════════════════════════════════

def print_prober_report(probe_detail: Dict):
    """Mostra breakdown do prober por variação."""
    phases = probe_detail.get("phases", [])
    winner = probe_detail.get("winner")
    total = probe_detail.get("total_ms", 0)

    print(f"    Variações testadas: {len(phases)}")
    wasted = 0
    for p in phases:
        icon = "✅" if p["ok"] else "❌"
        is_winner = " ⭐" if p.get("url") == winner else ""
        print(f"      {icon} {p['name']:15s} {p['ms']:>7.0f}ms  status={p['status']}  {p['url'][:50]}{is_winner}")
        if not p["ok"]:
            wasted += p["ms"]

    if wasted > 0:
        print(f"    ⚠️  Tempo desperdiçado em tentativas falhas: {ms_fmt(wasted)} ({pct(wasted, total)} do total)")


def print_url_report(url_data: Dict, probe_detail: Dict, analyze: Dict,
                      pipeline: Dict, proxy_comparison: Optional[Dict],
                      dns_result: Optional[Dict] = None):
    url = url_data["url"]
    prev_time = url_data.get("time_ms", 0)

    print(f"\n{SEPARATOR}")
    if prev_time > 0:
        print(f"  🌐 {url}")
        print(f"  Tempo no batch anterior: {ms_fmt(prev_time)} ({url_data['success']}/{url_data['pages']} páginas)")
    else:
        print(f"  🌐 {url}")
        print(f"  Status no batch anterior: inacessível")
    print(SEPARATOR)

    # DNS
    dns = dns_result or {"ok": False, "ms": 0, "error": "not tested"}
    icon = "✅" if dns["ok"] else "❌"
    print(f"\n  1. DNS: {icon}  {dns['ms']:>.0f}ms  {dns.get('ip', dns.get('error', ''))}")

    if not dns["ok"]:
        print(f"     ⛔ DNS falhou - skip imediato recomendado")
        return

    # Prober detail
    print(f"\n  2. URL PROBER: {ms_fmt(probe_detail['total_ms'])}")
    print_prober_report(probe_detail)

    # Full probe (como o pipeline usa)
    probe = pipeline["timings"].get("probe", {})
    print(f"\n  3. PROBE (pipeline real): {'✅' if probe.get('ok') else '❌'}  {ms_fmt(probe.get('wall_ms', 0))}")
    if probe.get("best_url") and probe["best_url"] != url:
        print(f"     Melhor URL: {probe['best_url']}")

    # Analyzer
    a = analyze
    print(f"\n  4. ANALYZER: {'✅' if a.get('ok') else '❌'}  {ms_fmt(a.get('wall_ms', 0))}")
    if a.get("ok"):
        print(f"     tipo={a['site_type']}  proteção={a['protection']}  "
              f"estratégia={a['strategy']}  html_reutilizável={'✅' if a.get('has_reusable_html') else '❌'}")

    # Main page
    main = pipeline["timings"].get("main_page_cffi", {})
    print(f"\n  5. MAIN PAGE (curl_cffi): {'✅' if main.get('ok') else '❌'}  {ms_fmt(main.get('wall_ms', 0))}")
    if main.get("ok"):
        print(f"     status={main['status']}  conteúdo={main.get('size_chars', 0):,} chars")

    # Proxy comparison
    if proxy_comparison:
        d = proxy_comparison["direct"]
        p = proxy_comparison["proxy"]
        print(f"\n  6. PROXY COMPARISON:")
        if d.get("ok"):
            print(f"     Direto:    {ms_fmt(d['wall_ms'])}  ttfb={d['ttfb_s']:.2f}s  total={d['total_s']:.2f}s  status={d['status']}")
        else:
            print(f"     Direto:    ❌ {d.get('error', '')}")
        if p.get("ok"):
            overhead = p["wall_ms"] - d.get("wall_ms", 0) if d.get("ok") else 0
            print(f"     Proxy:     {ms_fmt(p['wall_ms'])}  ttfb={p['ttfb_s']:.2f}s  total={p['total_s']:.2f}s  status={p['status']}  overhead={overhead:+.0f}ms")
        else:
            print(f"     Proxy:     ❌ {p.get('error', '')}")

    # Sumário
    probe_ms = probe.get("wall_ms", 0)
    analyze_ms = a.get("wall_ms", 0)
    main_ms = main.get("wall_ms", 0)
    pipeline_total = pipeline["timings"].get("total_ms", 0)

    print(f"\n  📊 BREAKDOWN DE TEMPO (só fases iniciais, sem subpages):")
    print(f"     Probe:          {ms_fmt(probe_ms):>8s}  ({pct(probe_ms, pipeline_total)})")
    print(f"     Analyzer:       {ms_fmt(analyze_ms):>8s}  ({pct(analyze_ms, pipeline_total)})")
    print(f"     Main page:      {ms_fmt(main_ms):>8s}  ({pct(main_ms, pipeline_total)})")
    print(f"     ────────────────────────────")
    print(f"     Total pipeline: {ms_fmt(pipeline_total):>8s}")

    if a.get("has_reusable_html"):
        saved = main_ms
        print(f"     💡 Se reutilizar HTML do analyzer: economiza ~{ms_fmt(saved)}")

    if prev_time > 0 and pipeline_total > 0:
        subpage_estimated = prev_time - pipeline_total
        if subpage_estimated > 0:
            print(f"     📌 Tempo estimado em subpages: ~{ms_fmt(subpage_estimated)} ({pct(subpage_estimated, prev_time)} do total)")


def print_summary(all_results: List[Dict]):
    print(f"\n{'='*75}")
    print(f"  TABELA COMPARATIVA - BREAKDOWN POR FASE")
    print(f"{'='*75}")

    header = f"  {'URL':30s} {'Batch':>8s} {'Probe':>8s} {'Analyz':>8s} {'Main':>8s} {'Pipeline':>8s} {'Overhead':>8s}"
    print(header)
    print(f"  {'─'*73}")

    pipeline_totals = []
    probe_totals = []
    analyze_totals = []
    main_totals = []

    for r in all_results:
        url = urlparse(r["url_data"]["url"]).netloc[:30]
        batch_ms = r["url_data"].get("time_ms", 0)
        p = r["pipeline"]["timings"]
        probe_ms = p.get("probe", {}).get("wall_ms", 0)
        analyze_ms = p.get("analyzer", {}).get("wall_ms", 0)
        main_ms = p.get("main_page_cffi", {}).get("wall_ms", 0)
        total_ms = p.get("total_ms", 0)
        overhead = total_ms - main_ms if main_ms else total_ms

        print(f"  {url:30s} {ms_fmt(batch_ms):>8s} {ms_fmt(probe_ms):>8s} "
              f"{ms_fmt(analyze_ms):>8s} {ms_fmt(main_ms):>8s} {ms_fmt(total_ms):>8s} {ms_fmt(overhead):>8s}")

        if total_ms > 0:
            pipeline_totals.append(total_ms)
        if probe_ms > 0:
            probe_totals.append(probe_ms)
        if analyze_ms > 0:
            analyze_totals.append(analyze_ms)
        if main_ms > 0:
            main_totals.append(main_ms)

    print(f"\n  📈 MÉDIAS:")
    if probe_totals:
        print(f"     Probe:     P50={ms_fmt(sorted(probe_totals)[len(probe_totals)//2])}, "
              f"avg={ms_fmt(statistics.mean(probe_totals))}, max={ms_fmt(max(probe_totals))}")
    if analyze_totals:
        print(f"     Analyzer:  P50={ms_fmt(sorted(analyze_totals)[len(analyze_totals)//2])}, "
              f"avg={ms_fmt(statistics.mean(analyze_totals))}, max={ms_fmt(max(analyze_totals))}")
    if main_totals:
        print(f"     Main page: P50={ms_fmt(sorted(main_totals)[len(main_totals)//2])}, "
              f"avg={ms_fmt(statistics.mean(main_totals))}, max={ms_fmt(max(main_totals))}")
    if pipeline_totals:
        print(f"     Pipeline:  P50={ms_fmt(sorted(pipeline_totals)[len(pipeline_totals)//2])}, "
              f"avg={ms_fmt(statistics.mean(pipeline_totals))}, max={ms_fmt(max(pipeline_totals))}")
        overhead_totals = [p - m for p, m in zip(pipeline_totals, main_totals)] if len(main_totals) == len(pipeline_totals) else []
        if overhead_totals:
            print(f"     Overhead:  avg={ms_fmt(statistics.mean(overhead_totals))} "
                  f"({pct(statistics.mean(overhead_totals), statistics.mean(pipeline_totals))} do pipeline)")


def print_recommendations(all_results: List[Dict], proxy_info: Dict):
    print(f"\n{'='*75}")
    print(f"  DIAGNÓSTICO & RECOMENDAÇÕES")
    print(f"{'='*75}")

    findings = []

    # Probe analysis
    probe_times = [r["pipeline"]["timings"].get("probe", {}).get("wall_ms", 0) for r in all_results if r["pipeline"]["timings"].get("probe", {}).get("ok")]
    if probe_times:
        avg_probe = statistics.mean(probe_times)
        if avg_probe > 5000:
            findings.append(
                f"  🔴 CRÍTICO: Probe médio = {ms_fmt(avg_probe)}\n"
                f"     O URL prober testa até 4 variações (http/https × www/sem-www) sequencialmente.\n"
                f"     Cada tentativa pode levar até 10s (timeout). Se a URL original falha,\n"
                f"     espera as 3 variações - podendo chegar a 40s só no probe.\n"
                f"     SUGESTÃO: Reduzir timeout do prober para 5s, testar variações em paralelo,\n"
                f"     ou cachear DNS failures para skip imediato."
            )
        elif avg_probe > 2000:
            findings.append(
                f"  🟡 ATENÇÃO: Probe médio = {ms_fmt(avg_probe)}\n"
                f"     Tempo aceitável mas pode ser otimizado com cache de DNS."
            )

    # Prober wasted time
    total_wasted = 0
    total_probe_time = 0
    for r in all_results:
        pd = r.get("probe_detail", {})
        for phase in pd.get("phases", []):
            if not phase["ok"]:
                total_wasted += phase["ms"]
            total_probe_time += phase["ms"]
    if total_probe_time > 0 and total_wasted / total_probe_time > 0.3:
        findings.append(
            f"  🔴 DESPERDÍCIO NO PROBER: {pct(total_wasted, total_probe_time)} do tempo gasto em tentativas falhas\n"
            f"     Total desperdiçado: {ms_fmt(total_wasted)}\n"
            f"     SUGESTÃO: Fazer DNS check antes do HEAD/GET. Se DNS falhar, skip all variations."
        )

    # Analyzer redundancy
    analyzer_reusable = sum(1 for r in all_results if r.get("analyze", {}).get("has_reusable_html"))
    analyzer_total = sum(1 for r in all_results if r.get("analyze"))
    if analyzer_reusable > 0:
        analyze_times = [r["pipeline"]["timings"].get("analyzer", {}).get("wall_ms", 0) for r in all_results if r.get("analyze", {}).get("has_reusable_html")]
        if analyze_times:
            findings.append(
                f"  🟢 OTIMIZAÇÃO JÁ ATIVA: {analyzer_reusable}/{analyzer_total} sites reutilizam HTML do analyzer\n"
                f"     Economia estimada: ~{ms_fmt(statistics.mean(analyze_times))} por empresa (evita GET redundante)"
            )

    # Proxy issues
    if proxy_info.get("found", 0) < proxy_info.get("attempts", 1):
        avail = proxy_info["found"] / max(proxy_info["attempts"], 1) * 100
        findings.append(
            f"  🔴 PROXY: Disponibilidade = {avail:.0f}% ({proxy_info['found']}/{proxy_info['attempts']})\n"
            f"     Pool total: {proxy_info.get('total_in_pool', 0)} proxies\n"
            f"     Únicos retornados: {proxy_info.get('unique_proxies', 0)}\n"
            f"     SUGESTÃO: Verificar quarentena excessiva ou pool insuficiente."
        )

    # Pipeline vs site speed
    for r in all_results:
        url_data = r["url_data"]
        p = r["pipeline"]["timings"]
        proxy_comp = r.get("proxy_comparison")
        if proxy_comp and proxy_comp.get("direct", {}).get("ok"):
            site_speed = proxy_comp["direct"]["wall_ms"]
            pipeline_total = p.get("total_ms", 0)
            if pipeline_total > site_speed * 5 and pipeline_total > 10000:
                hostname = urlparse(url_data["url"]).netloc[:30]
                findings.append(
                    f"  🟡 OVERHEAD: {hostname}\n"
                    f"     Site responde em {ms_fmt(site_speed)} mas pipeline leva {ms_fmt(pipeline_total)}\n"
                    f"     Overhead = {pct(pipeline_total - site_speed, pipeline_total)}"
                )

    if not findings:
        print("  ✅ Nenhum problema crítico identificado nesta amostra.")
    else:
        for f in findings:
            print(f)
            print()


# ═══════════════════════════════════════════════════════════
# 5. MAIN
# ═══════════════════════════════════════════════════════════

async def main():
    log_file = sys.argv[2] if len(sys.argv) > 2 else "logs/server_20260219.log"
    batch_id = sys.argv[1] if len(sys.argv) > 1 else None

    if not batch_id:
        for line in reversed(Path(log_file).read_text(errors="replace").splitlines()):
            try:
                entry = json.loads(line.strip())
                m = re.search(r"\[Batch (\w+)\] Iniciando:", entry.get("message", ""))
                if m:
                    batch_id = m.group(1)
                    break
            except (json.JSONDecodeError, ValueError):
                pass

    if not batch_id:
        print("ERRO: batch_id não encontrado nos logs")
        return

    print(f"{'='*75}")
    print(f"  STRESS TEST - Pipeline de Scraping")
    print(f"  Batch: {batch_id}")
    print(f"  Log: {log_file}")
    print(f"{'='*75}")

    # Extrair URLs
    print("\n📋 Extraindo URLs dos logs...")
    slow_urls, fast_urls, all_analyzed = extract_test_urls_from_logs(log_file, batch_id)
    print(f"  Top lentos: {len(slow_urls)}")
    print(f"  Top rápidos: {len(fast_urls)}")
    print(f"  Total analisados no batch: {len(all_analyzed)}")

    for i, u in enumerate(slow_urls[:10]):
        print(f"  🐢 {i+1:2d}. {ms_fmt(u['time_ms']):>8s}  {u['success']}/{u['pages']} pages  {u['url'][:55]}")
    for i, u in enumerate(fast_urls[:3]):
        print(f"  🐇 {i+1:2d}. {ms_fmt(u['time_ms']):>8s}  {u['success']}/{u['pages']} pages  {u['url'][:55]}")

    # Proxy setup
    print(f"\n🔐 TESTE DE PROXY POOL")
    print("-" * 50)
    proxy_info = await test_proxy_pool(30)
    print(f"  Pool total:          {proxy_info['total_in_pool']} proxies")
    print(f"  Disponibilidade:     {proxy_info['found']}/{proxy_info['attempts']} ({proxy_info['found']/max(proxy_info['attempts'],1)*100:.0f}%)")
    print(f"  Únicos retornados:   {proxy_info['unique_proxies']}")
    print(f"  Tempo seleção P50:   {proxy_info['p50_ms']:.1f}ms")
    print(f"  Tempo seleção avg:   {proxy_info['avg_ms']:.1f}ms")

    test_proxy = proxy_info.get("sample_proxy")
    if test_proxy:
        print(f"  Proxy para testes:   {test_proxy[:50]}...")
    else:
        print(f"  ⚠️ Nenhum proxy disponível")

    # Testar cada URL
    test_urls = slow_urls[:10] + fast_urls[:3]
    all_results = []

    for i, url_data in enumerate(test_urls):
        url = url_data["url"]
        label = "🐢 LENTO" if i < len(slow_urls[:10]) else "🐇 RÁPIDO"
        print(f"\n  [{i+1}/{len(test_urls)}] {label}: {url[:60]}...")

        probe_detail = await test_prober_phases(url)
        analyze = await test_analyzer(
            probe_detail.get("winner", url) if probe_detail.get("winner") else url
        )
        pipeline = await test_full_pipeline(url)

        proxy_comparison = None
        if test_proxy:
            target = probe_detail.get("winner", url) or url
            proxy_comparison = await test_proxy_latency_to_site(target, test_proxy)

        hostname = urlparse(url if "://" in url else f"https://{url}").netloc
        dns_result = await test_dns(hostname)

        result = {
            "url_data": url_data,
            "probe_detail": probe_detail,
            "analyze": analyze,
            "pipeline": pipeline,
            "proxy_comparison": proxy_comparison,
            "dns": dns_result,
        }
        all_results.append(result)

        print_url_report(url_data, probe_detail, analyze, pipeline, proxy_comparison, dns_result)

    # Sumário final
    print_summary(all_results)
    print_recommendations(all_results, proxy_info)


if __name__ == "__main__":
    asyncio.run(main())
