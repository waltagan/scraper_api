"""
Stress Test v3 - Pipeline completo de subpáginas via 711Proxy.

Simula o cenário real do scraper:
1. Faz GET na main page de N sites
2. Extrai links internos do HTML
3. Faz GET em até K subpáginas de cada site
4. Mede tudo: latência por stage, retries, banda, taxa de sucesso, distribuição

Parâmetros estudados:
- Timeout ideal por request
- Delay ideal entre requests ao mesmo domínio (intra-domain)
- Delay ideal entre batches de subpáginas
- Quantas subpáginas paralelas por domínio
- Impacto de retries (0, 1, 2)
- Throughput de empresas/minuto
"""

import asyncio
import time
import statistics
import json
import ssl
import re
import math
import functools
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional
from urllib.parse import urlparse, urljoin
from html.parser import HTMLParser

import aiohttp

print = functools.partial(print, flush=True)

PROXY_URL = "http://USER927913-zone-custom-region-BR:2dd94a@us.rotgb.711proxy.com:10000"

with open("test_urls_1000.json") as f:
    ALL_URLS: List[str] = json.load(f)

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

SKIP_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp',
    '.css', '.js', '.json', '.xml', '.pdf', '.doc', '.docx', '.xls',
    '.xlsx', '.zip', '.rar', '.mp4', '.mp3', '.avi', '.woff', '.woff2',
    '.ttf', '.eot', '.otf',
}

SKIP_PATHS = {'/wp-content/uploads/', '/assets/', '/images/', '/img/', '/static/', '/media/'}


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc.lower()
        self.links: Set[str] = set()

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        for name, value in attrs:
            if name == 'href' and value:
                url = urljoin(self.base_url, value.strip())
                parsed = urlparse(url)
                if parsed.netloc.lower() == self.base_domain and parsed.scheme in ('http', 'https'):
                    path = parsed.path.lower()
                    if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
                        continue
                    if any(skip in path for skip in SKIP_PATHS):
                        continue
                    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    if clean != self.base_url.rstrip('/') and clean != self.base_url:
                        self.links.add(clean)


def extract_internal_links(html: str, base_url: str) -> List[str]:
    try:
        parser = LinkExtractor(base_url)
        parser.feed(html)
        return list(parser.links)[:50]
    except Exception:
        return []


@dataclass
class PageResult:
    url: str
    success: bool
    response_time_ms: float
    status_code: int = 0
    content_length: int = 0
    error_type: str = ""
    attempt: int = 1
    is_main: bool = False


@dataclass
class SiteResult:
    url: str
    main_page: Optional[PageResult] = None
    subpages: List[PageResult] = field(default_factory=list)
    links_found: int = 0
    links_attempted: int = 0
    total_time_ms: float = 0
    success: bool = False


async def fetch_page(
    url: str, timeout: float, session: aiohttp.ClientSession,
    max_retries: int = 0, retry_delay: float = 0,
) -> PageResult:
    for attempt in range(1 + max_retries):
        start = time.perf_counter()
        try:
            async with session.get(
                url, proxy=PROXY_URL,
                timeout=aiohttp.ClientTimeout(total=timeout, connect=min(timeout, 8)),
                ssl=_SSL_CTX, headers=HEADERS,
                allow_redirects=True, max_redirects=5,
            ) as resp:
                body = await resp.read()
                elapsed = (time.perf_counter() - start) * 1000

                if 200 <= resp.status < 400:
                    return PageResult(
                        url=url, success=True, response_time_ms=elapsed,
                        status_code=resp.status, content_length=len(body),
                        attempt=attempt + 1,
                    )

                error_type = f"http_{resp.status}"

        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            error_type = "timeout"
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            err = str(e).lower()
            if any(x in err for x in ("connect", "refused", "reset", "pipe")):
                error_type = "connection_error"
            elif "ssl" in err:
                error_type = "ssl_error"
            elif "payload" in err or "encoding" in err:
                error_type = "payload_error"
            else:
                error_type = f"other:{type(e).__name__}"

        if attempt < max_retries and retry_delay > 0:
            await asyncio.sleep(retry_delay)

    return PageResult(
        url=url, success=False, response_time_ms=elapsed,
        status_code=0, error_type=error_type, attempt=attempt + 1,
    )


async def scrape_site(
    url: str,
    session: aiohttp.ClientSession,
    timeout: float,
    max_subpages: int,
    per_domain_concurrency: int,
    intra_delay: float,
    inter_batch_delay: float,
    batch_size: int,
    max_retries: int,
    retry_delay: float,
) -> SiteResult:
    """Simula o pipeline completo de 1 empresa."""
    site_start = time.perf_counter()
    result = SiteResult(url=url)

    # 1. Main page
    main = await fetch_page(url, timeout, session, max_retries=max_retries, retry_delay=retry_delay)
    main.is_main = True
    result.main_page = main

    if not main.success:
        result.total_time_ms = (time.perf_counter() - site_start) * 1000
        return result

    # 2. Extrair links (precisa do HTML)
    try:
        async with session.get(
            url, proxy=PROXY_URL,
            timeout=aiohttp.ClientTimeout(total=timeout, connect=8),
            ssl=_SSL_CTX, headers=HEADERS,
            allow_redirects=True, max_redirects=5,
        ) as resp:
            html = await resp.text()
            links = extract_internal_links(html, url)
    except Exception:
        links = []

    result.links_found = len(links)
    target_links = links[:max_subpages]
    result.links_attempted = len(target_links)

    if not target_links:
        result.success = True
        result.total_time_ms = (time.perf_counter() - site_start) * 1000
        return result

    # 3. Scrape subpáginas em batches com concorrência limitada por domínio
    domain_sem = asyncio.Semaphore(per_domain_concurrency)
    subpage_results = []

    batches = [target_links[i:i + batch_size] for i in range(0, len(target_links), batch_size)]

    for b_idx, batch in enumerate(batches):
        async def fetch_sub(i: int, sub_url: str):
            if intra_delay > 0 and i > 0:
                await asyncio.sleep(intra_delay * i)
            async with domain_sem:
                return await fetch_page(sub_url, timeout, session, max_retries=max_retries, retry_delay=retry_delay)

        tasks = [fetch_sub(i, sub_url) for i, sub_url in enumerate(batch)]
        batch_results = await asyncio.gather(*tasks)
        subpage_results.extend(batch_results)

        if b_idx < len(batches) - 1 and inter_batch_delay > 0:
            await asyncio.sleep(inter_batch_delay)

    result.subpages = subpage_results
    result.success = True
    result.total_time_ms = (time.perf_counter() - site_start) * 1000
    return result


def percentiles(data: list) -> dict:
    if not data:
        return {}
    s = sorted(data)
    n = len(s)
    return {
        "min": round(s[0]),
        "p10": round(s[max(0, int(n * 0.10))]),
        "p25": round(s[max(0, int(n * 0.25))]),
        "p50": round(statistics.median(s)),
        "p75": round(s[min(n - 1, int(n * 0.75))]),
        "p90": round(s[min(n - 1, int(n * 0.90))]),
        "p95": round(s[min(n - 1, int(n * 0.95))]),
        "p99": round(s[min(n - 1, int(n * 0.99))]),
        "max": round(s[-1]),
        "avg": round(statistics.mean(s)),
        "stdev": round(statistics.stdev(s)) if n > 1 else 0,
    }


def histogram(data: list, bins: list) -> dict:
    hist = {}
    for i, upper in enumerate(bins):
        lower = bins[i - 1] if i > 0 else 0
        label = f"{lower/1000:.0f}-{upper/1000:.0f}s"
        hist[label] = sum(1 for v in data if lower <= v < upper)
    label = f">{bins[-1]/1000:.0f}s"
    hist[label] = sum(1 for v in data if v >= bins[-1])
    return hist


async def run_pipeline_test(
    label: str,
    num_sites: int,
    site_concurrency: int,
    timeout: float,
    max_subpages: int,
    per_domain_concurrency: int,
    intra_delay: float,
    inter_batch_delay: float,
    batch_size: int,
    max_retries: int,
    retry_delay: float,
) -> dict:
    """Roda teste completo do pipeline em N sites."""
    urls = ALL_URLS[:num_sites]

    print(f"\n{'='*90}")
    print(f"  {label}")
    print(f"  sites={num_sites} | site_conc={site_concurrency} | timeout={timeout}s | "
          f"subpages={max_subpages} | domain_conc={per_domain_concurrency}")
    print(f"  intra_delay={intra_delay}s | batch_delay={inter_batch_delay}s | "
          f"batch_size={batch_size} | retries={max_retries} | retry_delay={retry_delay}s")
    print(f"{'='*90}")

    connector = aiohttp.TCPConnector(
        limit=site_concurrency * per_domain_concurrency + 50,
        limit_per_host=0, ssl=_SSL_CTX,
        ttl_dns_cache=300, enable_cleanup_closed=True,
    )
    site_sem = asyncio.Semaphore(site_concurrency)

    async def process_site(url: str, session: aiohttp.ClientSession) -> SiteResult:
        async with site_sem:
            return await scrape_site(
                url, session, timeout, max_subpages, per_domain_concurrency,
                intra_delay, inter_batch_delay, batch_size, max_retries, retry_delay,
            )

    wall_start = time.perf_counter()
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [process_site(url, session) for url in urls]
        site_results = await asyncio.gather(*tasks)
    wall_time = (time.perf_counter() - wall_start) * 1000

    # ── Análise ──
    main_ok = [sr for sr in site_results if sr.main_page and sr.main_page.success]
    main_fail = [sr for sr in site_results if sr.main_page and not sr.main_page.success]

    all_main_times = [sr.main_page.response_time_ms for sr in site_results if sr.main_page]
    ok_main_times = [sr.main_page.response_time_ms for sr in main_ok]

    all_sub_results = []
    for sr in site_results:
        all_sub_results.extend(sr.subpages)

    sub_ok = [r for r in all_sub_results if r.success]
    sub_fail = [r for r in all_sub_results if not r.success]
    ok_sub_times = [r.response_time_ms for r in sub_ok]
    fail_sub_times = [r.response_time_ms for r in sub_fail]

    site_times = [sr.total_time_ms for sr in site_results]
    ok_site_times = [sr.total_time_ms for sr in site_results if sr.success]

    total_bytes_main = sum(sr.main_page.content_length for sr in main_ok)
    total_bytes_sub = sum(r.content_length for r in sub_ok)
    total_links = sum(sr.links_found for sr in site_results)
    total_attempted = sum(sr.links_attempted for sr in site_results)

    # Retries usados
    retry_counts = [r.attempt for r in all_sub_results]
    retries_used = sum(r.attempt - 1 for r in all_sub_results)

    # Subpage errors
    sub_errors = {}
    for r in sub_fail:
        sub_errors[r.error_type] = sub_errors.get(r.error_type, 0) + 1

    main_errors = {}
    for sr in main_fail:
        main_errors[sr.main_page.error_type] = main_errors.get(sr.main_page.error_type, 0) + 1

    # Status codes
    main_statuses = {}
    for sr in site_results:
        if sr.main_page and sr.main_page.status_code:
            k = str(sr.main_page.status_code)
            main_statuses[k] = main_statuses.get(k, 0) + 1

    sub_statuses = {}
    for r in all_sub_results:
        if r.status_code:
            k = str(r.status_code)
            sub_statuses[k] = sub_statuses.get(k, 0) + 1

    throughput_sites = num_sites / (wall_time / 1000 / 60)
    throughput_pages = (len(main_ok) + len(sub_ok)) / (wall_time / 1000)

    time_bins = [1000, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 30000]
    site_time_bins = [5000, 10000, 15000, 20000, 30000, 45000, 60000, 90000]

    analysis = {
        "label": label,
        "config": {
            "num_sites": num_sites,
            "site_concurrency": site_concurrency,
            "timeout_s": timeout,
            "max_subpages": max_subpages,
            "per_domain_concurrency": per_domain_concurrency,
            "intra_delay_s": intra_delay,
            "inter_batch_delay_s": inter_batch_delay,
            "batch_size": batch_size,
            "max_retries": max_retries,
            "retry_delay_s": retry_delay,
        },
        "wall_time_s": round(wall_time / 1000, 1),
        "throughput_sites_per_min": round(throughput_sites, 1),
        "throughput_pages_per_sec": round(throughput_pages, 1),
        "main_page": {
            "total": num_sites,
            "success": len(main_ok),
            "failure": len(main_fail),
            "success_rate": round(len(main_ok) / max(num_sites, 1) * 100, 1),
            "latency": percentiles(ok_main_times),
            "errors": dict(sorted(main_errors.items(), key=lambda x: -x[1])),
            "status_codes": dict(sorted(main_statuses.items(), key=lambda x: -x[1])),
            "avg_size_kb": round(total_bytes_main / max(len(main_ok), 1) / 1024, 1),
        },
        "subpages": {
            "total_links_found": total_links,
            "total_attempted": total_attempted,
            "avg_links_per_site": round(total_links / max(len(main_ok), 1), 1),
            "avg_attempted_per_site": round(total_attempted / max(len(main_ok), 1), 1),
            "total_requests": len(all_sub_results),
            "success": len(sub_ok),
            "failure": len(sub_fail),
            "success_rate": round(len(sub_ok) / max(len(all_sub_results), 1) * 100, 1),
            "latency_success": percentiles(ok_sub_times),
            "latency_failure": percentiles(fail_sub_times),
            "histogram_success": histogram(ok_sub_times, time_bins),
            "errors": dict(sorted(sub_errors.items(), key=lambda x: -x[1])),
            "status_codes": dict(sorted(sub_statuses.items(), key=lambda x: -x[1])),
            "avg_size_kb": round(total_bytes_sub / max(len(sub_ok), 1) / 1024, 1),
            "retries_total": retries_used,
            "avg_retries_per_page": round(retries_used / max(len(all_sub_results), 1), 2),
        },
        "per_site": {
            "latency_all": percentiles(site_times),
            "latency_success": percentiles(ok_site_times),
            "histogram": histogram(ok_site_times, site_time_bins),
        },
        "bandwidth": {
            "total_mb": round((total_bytes_main + total_bytes_sub) / 1024 / 1024, 1),
            "main_mb": round(total_bytes_main / 1024 / 1024, 1),
            "sub_mb": round(total_bytes_sub / 1024 / 1024, 1),
        },
    }

    _print_analysis(analysis)
    return analysis


def _print_analysis(a: dict):
    mp = a["main_page"]
    sp = a["subpages"]
    ps = a["per_site"]
    bw = a["bandwidth"]

    print(f"\n  📊 RESULTADOS")
    print(f"  Wall: {a['wall_time_s']}s | Sites/min: {a['throughput_sites_per_min']} | Pages/s: {a['throughput_pages_per_sec']}")
    print(f"  Bandwidth: {bw['total_mb']}MB (main={bw['main_mb']}MB, sub={bw['sub_mb']}MB)")

    print(f"\n  📄 MAIN PAGE: {mp['success']}/{mp['total']} ({mp['success_rate']}%)")
    if mp["latency"]:
        l = mp["latency"]
        print(f"     Latência: p50={l['p50']}  p90={l['p90']}  p95={l['p95']}  max={l['max']}ms  avg={l['avg']}ms")
    if mp["errors"]:
        print(f"     Erros: {mp['errors']}")

    print(f"\n  📑 SUBPAGES: {sp['success']}/{sp['total_requests']} ({sp['success_rate']}%)")
    print(f"     Links/site: {sp['avg_links_per_site']} encontrados, {sp['avg_attempted_per_site']} tentados")
    if sp["latency_success"]:
        l = sp["latency_success"]
        print(f"     Latência OK:   p50={l['p50']}  p90={l['p90']}  p95={l['p95']}  max={l['max']}ms")
    if sp["latency_failure"]:
        l = sp["latency_failure"]
        print(f"     Latência FAIL: p50={l['p50']}  p90={l['p90']}  max={l['max']}ms")
    print(f"     Retries: {sp['retries_total']} total ({sp['avg_retries_per_page']} avg/page)")
    if sp["errors"]:
        print(f"     Erros: {sp['errors']}")

    if sp["histogram_success"]:
        print(f"\n  📊 HISTOGRAMA SUBPAGES (sucesso):")
        total_ok = max(sp["success"], 1)
        for bucket, count in sp["histogram_success"].items():
            if count > 0:
                bar = "█" * int(count / total_ok * 40)
                print(f"     {bucket:>10s}: {count:>4d} ({count/total_ok*100:>5.1f}%) {bar}")

    print(f"\n  🏢 PER SITE (tempo total por empresa):")
    if ps["latency_success"]:
        l = ps["latency_success"]
        print(f"     p50={l['p50']/1000:.1f}s  p90={l['p90']/1000:.1f}s  p95={l['p95']/1000:.1f}s  max={l['max']/1000:.1f}s  avg={l['avg']/1000:.1f}s")
    if ps["histogram"]:
        print(f"     Histograma (empresa completa):")
        total_s = max(len([1 for sr in ps.get("_raw", []) if True]), sum(ps["histogram"].values()), 1)
        for bucket, count in ps["histogram"].items():
            if count > 0:
                bar = "█" * int(count / total_s * 40)
                print(f"       {bucket:>10s}: {count:>4d} ({count/total_s*100:>5.1f}%) {bar}")


async def main():
    print("=" * 90)
    print("  STRESS TEST v3 - Pipeline de Subpáginas via 711Proxy")
    print(f"  Proxy: {PROXY_URL.split('@')[1]}")
    print(f"  URLs: {len(ALL_URLS)} sites reais")
    print("=" * 90)

    all_analyses = []

    # ── TESTE 1: Timeout ideal para subpáginas ──
    print(f"\n{'#'*90}")
    print(f"  FASE 1: Timeout ideal para subpáginas (200 sites, 5 subpages, domain_conc=5)")
    print(f"{'#'*90}")

    for timeout in [5, 8, 10, 12, 15, 20]:
        a = await run_pipeline_test(
            label=f"Timeout={timeout}s",
            num_sites=200, site_concurrency=100, timeout=timeout,
            max_subpages=5, per_domain_concurrency=5,
            intra_delay=0, inter_batch_delay=0, batch_size=10,
            max_retries=1, retry_delay=0,
        )
        all_analyses.append(a)
        await asyncio.sleep(3)

    # ── TESTE 2: Concorrência por domínio ──
    print(f"\n{'#'*90}")
    print(f"  FASE 2: Concorrência por domínio (200 sites, 5 subpages, timeout=12s)")
    print(f"{'#'*90}")

    for dc in [1, 2, 3, 5, 10]:
        a = await run_pipeline_test(
            label=f"DomainConc={dc}",
            num_sites=200, site_concurrency=100, timeout=12,
            max_subpages=5, per_domain_concurrency=dc,
            intra_delay=0, inter_batch_delay=0, batch_size=10,
            max_retries=1, retry_delay=0,
        )
        all_analyses.append(a)
        await asyncio.sleep(3)

    # ── TESTE 3: Impacto de delays intra-domínio ──
    print(f"\n{'#'*90}")
    print(f"  FASE 3: Delay entre requests ao mesmo domínio (200 sites)")
    print(f"{'#'*90}")

    for delay in [0, 0.1, 0.3, 0.5, 1.0]:
        a = await run_pipeline_test(
            label=f"IntraDelay={delay}s",
            num_sites=200, site_concurrency=100, timeout=12,
            max_subpages=5, per_domain_concurrency=5,
            intra_delay=delay, inter_batch_delay=0, batch_size=10,
            max_retries=1, retry_delay=0,
        )
        all_analyses.append(a)
        await asyncio.sleep(3)

    # ── TESTE 4: Impacto de retries ──
    print(f"\n{'#'*90}")
    print(f"  FASE 4: Retries (200 sites, timeout=12s)")
    print(f"{'#'*90}")

    for retries, rdelay in [(0, 0), (1, 0), (1, 0.5), (2, 0), (2, 1.0)]:
        a = await run_pipeline_test(
            label=f"Retries={retries},delay={rdelay}s",
            num_sites=200, site_concurrency=100, timeout=12,
            max_subpages=5, per_domain_concurrency=5,
            intra_delay=0, inter_batch_delay=0, batch_size=10,
            max_retries=retries, retry_delay=rdelay,
        )
        all_analyses.append(a)
        await asyncio.sleep(3)

    # ── TESTE 5: Número de subpáginas ──
    print(f"\n{'#'*90}")
    print(f"  FASE 5: Quantidade de subpáginas (200 sites, timeout=12s)")
    print(f"{'#'*90}")

    for nsub in [2, 5, 10, 15]:
        a = await run_pipeline_test(
            label=f"MaxSubpages={nsub}",
            num_sites=200, site_concurrency=100, timeout=12,
            max_subpages=nsub, per_domain_concurrency=5,
            intra_delay=0, inter_batch_delay=0, batch_size=10,
            max_retries=1, retry_delay=0,
        )
        all_analyses.append(a)
        await asyncio.sleep(3)

    # ── TESTE 6: Escala — throughput com config otimizada ──
    print(f"\n{'#'*90}")
    print(f"  FASE 6: Escala com config otimizada (timeout=12s, dc=5, retries=1, delay=0)")
    print(f"{'#'*90}")

    for nsites, sconc in [(100, 50), (200, 100), (500, 200), (1000, 500)]:
        a = await run_pipeline_test(
            label=f"Scale={nsites}sites,conc={sconc}",
            num_sites=nsites, site_concurrency=sconc, timeout=12,
            max_subpages=5, per_domain_concurrency=5,
            intra_delay=0, inter_batch_delay=0, batch_size=10,
            max_retries=1, retry_delay=0,
        )
        all_analyses.append(a)
        await asyncio.sleep(5)

    # ── RESUMOS ──
    _print_summaries(all_analyses)

    output = {
        "proxy": PROXY_URL.split("@")[1],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tests": all_analyses,
    }
    with open("subpage_stress_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n✅ Resultados salvos em subpage_stress_results.json")


def _print_summaries(analyses: List[dict]):
    phases = {
        "FASE 1 - TIMEOUT": analyses[:6],
        "FASE 2 - DOMAIN CONCURRENCY": analyses[6:11],
        "FASE 3 - INTRA DELAY": analyses[11:16],
        "FASE 4 - RETRIES": analyses[16:21],
        "FASE 5 - NUM SUBPAGES": analyses[21:25],
        "FASE 6 - ESCALA": analyses[25:29],
    }

    for phase_name, phase_data in phases.items():
        if not phase_data:
            continue

        print(f"\n{'='*90}")
        print(f"  RESUMO {phase_name}")
        print(f"{'='*90}")
        print(f"  {'Label':>30s} | {'Main%':>6s} | {'Sub%':>6s} | {'SubP50':>7s} | {'SubP90':>7s} | "
              f"{'Site p50':>8s} | {'Site p90':>8s} | {'Sites/min':>9s}")
        print(f"  {'-'*30} | {'-'*6} | {'-'*6} | {'-'*7} | {'-'*7} | {'-'*8} | {'-'*8} | {'-'*9}")

        for a in phase_data:
            mp = a["main_page"]
            sp = a["subpages"]
            ps = a["per_site"]
            sl = sp.get("latency_success", {})
            pl = ps.get("latency_success", {})
            print(
                f"  {a['label']:>30s} | {mp['success_rate']:>5.1f}% | {sp['success_rate']:>5.1f}% | "
                f"{sl.get('p50','-'):>7} | {sl.get('p90','-'):>7} | "
                f"{str(round(pl.get('p50',0)/1000,1))+'s':>8s} | "
                f"{str(round(pl.get('p90',0)/1000,1))+'s':>8s} | "
                f"{a['throughput_sites_per_min']:>8.0f}/m"
            )


if __name__ == "__main__":
    asyncio.run(main())
