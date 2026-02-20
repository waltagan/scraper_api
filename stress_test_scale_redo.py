"""
Redo dos testes de escala (Fase 6) que degradaram por falta de banda no proxy.
Refaz apenas: 500 sites (conc=200) e 1000 sites (conc=500).
"""

import asyncio
import time
import statistics
import json
import ssl
import functools
from dataclasses import dataclass, field
from typing import List, Optional, Set
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


@dataclass
class SiteResult:
    url: str
    main_page: Optional[PageResult] = None
    subpages: List[PageResult] = field(default_factory=list)
    links_found: int = 0
    links_attempted: int = 0
    total_time_ms: float = 0
    success: bool = False


async def fetch_page(url, timeout, session, max_retries=0, retry_delay=0):
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
                    return PageResult(url=url, success=True, response_time_ms=elapsed,
                                      status_code=resp.status, content_length=len(body), attempt=attempt+1)
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
            elif "proxy" in err or "407" in err:
                error_type = "proxy_error"
            else:
                error_type = f"other:{type(e).__name__}"
        if attempt < max_retries and retry_delay > 0:
            await asyncio.sleep(retry_delay)
    return PageResult(url=url, success=False, response_time_ms=elapsed, error_type=error_type, attempt=attempt+1)


async def scrape_site(url, session, timeout, max_subpages, per_domain_conc):
    site_start = time.perf_counter()
    result = SiteResult(url=url)

    main = await fetch_page(url, timeout, session, max_retries=1)
    result.main_page = main
    if not main.success:
        result.total_time_ms = (time.perf_counter() - site_start) * 1000
        return result

    try:
        async with session.get(url, proxy=PROXY_URL,
                               timeout=aiohttp.ClientTimeout(total=timeout, connect=8),
                               ssl=_SSL_CTX, headers=HEADERS,
                               allow_redirects=True, max_redirects=5) as resp:
            html = await resp.text()
            links = extract_internal_links(html, url)
    except Exception:
        links = []

    result.links_found = len(links)
    target = links[:max_subpages]
    result.links_attempted = len(target)

    if not target:
        result.success = True
        result.total_time_ms = (time.perf_counter() - site_start) * 1000
        return result

    dom_sem = asyncio.Semaphore(per_domain_conc)
    async def fetch_sub(sub_url):
        async with dom_sem:
            return await fetch_page(sub_url, timeout, session, max_retries=1)

    tasks = [fetch_sub(u) for u in target]
    result.subpages = list(await asyncio.gather(*tasks))
    result.success = True
    result.total_time_ms = (time.perf_counter() - site_start) * 1000
    return result


def percentiles(data):
    if not data:
        return {}
    s = sorted(data)
    n = len(s)
    return {
        "min": round(s[0]), "p25": round(s[max(0,int(n*0.25))]),
        "p50": round(statistics.median(s)), "p75": round(s[min(n-1,int(n*0.75))]),
        "p90": round(s[min(n-1,int(n*0.90))]), "p95": round(s[min(n-1,int(n*0.95))]),
        "p99": round(s[min(n-1,int(n*0.99))]), "max": round(s[-1]),
        "avg": round(statistics.mean(s)), "stdev": round(statistics.stdev(s)) if n > 1 else 0,
    }


def histogram(data, bins):
    hist = {}
    for i, upper in enumerate(bins):
        lower = bins[i-1] if i > 0 else 0
        hist[f"{lower/1000:.0f}-{upper/1000:.0f}s"] = sum(1 for v in data if lower <= v < upper)
    hist[f">{bins[-1]/1000:.0f}s"] = sum(1 for v in data if v >= bins[-1])
    return hist


async def run_test(label, num_sites, site_conc, timeout=12, max_sub=5, dc=5):
    urls = ALL_URLS[:num_sites]
    connector = aiohttp.TCPConnector(limit=site_conc * dc + 100, limit_per_host=0,
                                      ssl=_SSL_CTX, ttl_dns_cache=300, enable_cleanup_closed=True)
    site_sem = asyncio.Semaphore(site_conc)

    async def process(url, session):
        async with site_sem:
            return await scrape_site(url, session, timeout, max_sub, dc)

    print(f"\n{'='*90}")
    print(f"  {label}: {num_sites} sites | site_conc={site_conc} | timeout={timeout}s | sub={max_sub} | dc={dc}")
    print(f"{'='*90}")

    wall_start = time.perf_counter()
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [process(url, session) for url in urls]
        results = await asyncio.gather(*tasks)
    wall_ms = (time.perf_counter() - wall_start) * 1000

    # Análise
    main_ok = [r for r in results if r.main_page and r.main_page.success]
    main_fail = [r for r in results if r.main_page and not r.main_page.success]
    all_sub = [s for r in results for s in r.subpages]
    sub_ok = [s for s in all_sub if s.success]
    sub_fail = [s for s in all_sub if not s.success]

    ok_main_t = [r.main_page.response_time_ms for r in main_ok]
    ok_sub_t = [s.response_time_ms for s in sub_ok]
    fail_sub_t = [s.response_time_ms for s in sub_fail]
    site_t = [r.total_time_ms for r in results if r.success]

    total_bytes = sum(r.main_page.content_length for r in main_ok) + sum(s.content_length for s in sub_ok)
    total_links = sum(r.links_found for r in results)
    total_attempted = sum(r.links_attempted for r in results)

    main_errs = {}
    for r in main_fail:
        main_errs[r.main_page.error_type] = main_errs.get(r.main_page.error_type, 0) + 1
    sub_errs = {}
    for s in sub_fail:
        sub_errs[s.error_type] = sub_errs.get(s.error_type, 0) + 1

    tpm = len(results) / (wall_ms / 1000 / 60)
    pps = (len(main_ok) + len(sub_ok)) / (wall_ms / 1000) if wall_ms > 0 else 0

    site_bins = [5000, 10000, 15000, 20000, 30000, 45000, 60000, 90000]
    sub_bins = [1000, 2000, 3000, 5000, 8000, 10000, 15000]

    a = {
        "label": label, "num_sites": num_sites, "site_conc": site_conc,
        "wall_s": round(wall_ms/1000, 1), "sites_per_min": round(tpm, 1), "pages_per_sec": round(pps, 1),
        "main_total": num_sites, "main_ok": len(main_ok), "main_fail": len(main_fail),
        "main_rate": round(len(main_ok)/max(num_sites,1)*100, 1),
        "main_latency": percentiles(ok_main_t), "main_errors": main_errs,
        "sub_total": len(all_sub), "sub_ok": len(sub_ok), "sub_fail": len(sub_fail),
        "sub_rate": round(len(sub_ok)/max(len(all_sub),1)*100, 1),
        "sub_latency": percentiles(ok_sub_t), "sub_fail_latency": percentiles(fail_sub_t),
        "sub_hist": histogram(ok_sub_t, sub_bins), "sub_errors": sub_errs,
        "links_avg": round(total_links/max(len(main_ok),1), 1),
        "attempted_avg": round(total_attempted/max(len(main_ok),1), 1),
        "site_latency": percentiles(site_t), "site_hist": histogram(site_t, site_bins),
        "bandwidth_mb": round(total_bytes/1024/1024, 1),
    }

    # Print
    print(f"\n  Wall: {a['wall_s']}s | Sites/min: {a['sites_per_min']} | Pages/s: {a['pages_per_sec']}")
    print(f"  Bandwidth: {a['bandwidth_mb']}MB")
    print(f"\n  MAIN: {a['main_ok']}/{a['main_total']} ({a['main_rate']}%)")
    if a['main_latency']:
        l = a['main_latency']
        print(f"    Latência: p50={l['p50']}  p90={l['p90']}  p95={l['p95']}  max={l['max']}ms")
    if a['main_errors']:
        print(f"    Erros: {a['main_errors']}")

    print(f"\n  SUBPAGES: {a['sub_ok']}/{a['sub_total']} ({a['sub_rate']}%)")
    print(f"    Links/site: {a['links_avg']} encontrados, {a['attempted_avg']} tentados")
    if a['sub_latency']:
        l = a['sub_latency']
        print(f"    Latência OK:   p50={l['p50']}  p90={l['p90']}  p95={l['p95']}  max={l['max']}ms")
    if a['sub_fail_latency']:
        l = a['sub_fail_latency']
        print(f"    Latência FAIL: p50={l['p50']}  p90={l['p90']}  max={l['max']}ms")
    if a['sub_errors']:
        print(f"    Erros: {a['sub_errors']}")

    if a['sub_hist']:
        print(f"\n  HISTOGRAMA SUBPAGES:")
        tot = max(a['sub_ok'], 1)
        for b, c in a['sub_hist'].items():
            if c > 0:
                bar = "█" * int(c / tot * 40)
                print(f"    {b:>10s}: {c:>4d} ({c/tot*100:>5.1f}%) {bar}")

    print(f"\n  PER SITE (empresa completa):")
    if a['site_latency']:
        l = a['site_latency']
        print(f"    p50={l['p50']/1000:.1f}s  p90={l['p90']/1000:.1f}s  p95={l['p95']/1000:.1f}s  max={l['max']/1000:.1f}s  avg={l['avg']/1000:.1f}s")
    if a['site_hist']:
        tot = max(sum(a['site_hist'].values()), 1)
        for b, c in a['site_hist'].items():
            if c > 0:
                bar = "█" * int(c / tot * 40)
                print(f"    {b:>10s}: {c:>4d} ({c/tot*100:>5.1f}%) {bar}")

    return a


async def main():
    print("=" * 90)
    print("  REDO - Testes de Escala (Fase 6) - 711Proxy Gateway")
    print(f"  Proxy: {PROXY_URL.split('@')[1]}")
    print(f"  Config: timeout=12s, retries=1, delay=0, subpages=5, dc=5")
    print("=" * 90)

    all_results = []

    configs = [
        ("Scale=100,C=50",   100, 50),
        ("Scale=200,C=100",  200, 100),
        ("Scale=300,C=150",  300, 150),
        ("Scale=500,C=200",  500, 200),
        ("Scale=500,C=300",  500, 300),
        ("Scale=1000,C=200", 1000, 200),
        ("Scale=1000,C=500", 1000, 500),
    ]

    for label, nsites, conc in configs:
        a = await run_test(label, nsites, conc)
        all_results.append(a)
        await asyncio.sleep(5)

    # Resumo
    print(f"\n{'='*90}")
    print(f"  RESUMO ESCALA")
    print(f"{'='*90}")
    print(f"  {'Label':>25s} | {'Main%':>6s} | {'Sub%':>6s} | {'SubP50':>7s} | {'SubP90':>7s} | "
          f"{'Site p50':>8s} | {'Site p90':>8s} | {'Sites/min':>9s}")
    print(f"  {'-'*25} | {'-'*6} | {'-'*6} | {'-'*7} | {'-'*7} | {'-'*8} | {'-'*8} | {'-'*9}")

    for a in all_results:
        sl = a.get('sub_latency', {})
        pl = a.get('site_latency', {})
        print(
            f"  {a['label']:>25s} | {a['main_rate']:>5.1f}% | {a['sub_rate']:>5.1f}% | "
            f"{sl.get('p50','-'):>7} | {sl.get('p90','-'):>7} | "
            f"{str(round(pl.get('p50',0)/1000,1))+'s':>8s} | "
            f"{str(round(pl.get('p90',0)/1000,1))+'s':>8s} | "
            f"{a['sites_per_min']:>8.0f}/m"
        )

    with open("scale_redo_results.json", "w") as f:
        json.dump({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "tests": all_results}, f, indent=2, default=str)
    print(f"\n✅ Resultados salvos em scale_redo_results.json")


if __name__ == "__main__":
    asyncio.run(main())
