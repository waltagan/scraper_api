"""
Stress Test v2 - 711Proxy Gateway
1000 URLs reais do banco de dados.
Sem download de imagens (Accept: text/html apenas).
Estatísticas completas: latência, falhas, bandwidth, distribuição.
"""

import asyncio
import time
import statistics
import json
import ssl
import sys
import math
import functools
from dataclasses import dataclass, field
from typing import List

import aiohttp

print = functools.partial(print, flush=True)

PROXY_URL = "http://USER927913-zone-custom-region-BR:2dd94a@us.rotgb.711proxy.com:10000"

with open("test_urls_1000.json") as f:
    ALL_URLS: List[str] = json.load(f)

print(f"Loaded {len(ALL_URLS)} URLs from database")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class RequestResult:
    url: str
    success: bool
    response_time_ms: float
    connect_time_ms: float = 0
    status_code: int = 0
    content_length: int = 0
    content_type: str = ""
    error_type: str = ""
    error_msg: str = ""
    is_redirect: bool = False
    final_url: str = ""


@dataclass
class TestResult:
    label: str
    concurrency: int
    total_requests: int
    timeout_s: float
    results: List[RequestResult] = field(default_factory=list)
    wall_time_ms: float = 0


async def single_request(
    url: str, timeout: float, semaphore: asyncio.Semaphore, session: aiohttp.ClientSession
) -> RequestResult:
    async with semaphore:
        start = time.perf_counter()
        connect_start = start

        try:
            async with session.get(
                url,
                proxy=PROXY_URL,
                timeout=aiohttp.ClientTimeout(total=timeout, connect=min(timeout, 10)),
                ssl=_SSL_CTX,
                headers=HEADERS,
                allow_redirects=True,
                max_redirects=5,
            ) as resp:
                connect_time = (time.perf_counter() - connect_start) * 1000
                body = await resp.read()
                elapsed = (time.perf_counter() - start) * 1000
                ct = resp.headers.get("Content-Type", "")

                return RequestResult(
                    url=url,
                    success=200 <= resp.status < 400,
                    response_time_ms=elapsed,
                    connect_time_ms=connect_time,
                    status_code=resp.status,
                    content_length=len(body),
                    content_type=ct.split(";")[0].strip() if ct else "",
                    is_redirect=str(resp.url) != url,
                    final_url=str(resp.url) if str(resp.url) != url else "",
                )

        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            return RequestResult(
                url=url, success=False, response_time_ms=elapsed,
                error_type="timeout", error_msg=f"Timeout after {timeout}s",
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            err_str = str(e).lower()

            if "timeout" in err_str or "timed out" in err_str:
                etype = "timeout"
            elif any(x in err_str for x in ("connect", "refused", "reset", "broken pipe")):
                etype = "connection_error"
            elif "ssl" in err_str or "certificate" in err_str:
                etype = "ssl_error"
            elif "dns" in err_str or "resolve" in err_str:
                etype = "dns_error"
            elif "proxy" in err_str:
                etype = "proxy_error"
            elif "too many redirect" in err_str:
                etype = "redirect_loop"
            elif "payload" in err_str or "encoding" in err_str:
                etype = "payload_error"
            else:
                etype = f"other:{type(e).__name__}"

            return RequestResult(
                url=url, success=False, response_time_ms=elapsed,
                error_type=etype, error_msg=str(e)[:120],
            )


async def run_test(label: str, concurrency: int, timeout: float, num_requests: int) -> TestResult:
    connector = aiohttp.TCPConnector(
        limit=concurrency + 50, limit_per_host=0, ssl=_SSL_CTX,
        ttl_dns_cache=300, enable_cleanup_closed=True,
    )

    urls = ALL_URLS[:num_requests]

    print(f"\n{'='*80}")
    print(f"  {label}: {num_requests} requests | concurrency={concurrency} | timeout={timeout}s")
    print(f"{'='*80}")

    wall_start = time.perf_counter()
    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [single_request(url, timeout, sem, session) for url in urls]
        results = await asyncio.gather(*tasks)

    wall_time = (time.perf_counter() - wall_start) * 1000

    return TestResult(
        label=label, concurrency=concurrency, total_requests=num_requests,
        timeout_s=timeout, results=list(results), wall_time_ms=wall_time,
    )


def percentiles(data: list) -> dict:
    if not data:
        return {}
    s = sorted(data)
    n = len(s)
    return {
        "min": round(s[0]),
        "p10": round(s[int(n * 0.10)]) if n > 9 else round(s[0]),
        "p25": round(s[int(n * 0.25)]) if n > 3 else round(s[0]),
        "p50": round(statistics.median(s)),
        "p75": round(s[int(n * 0.75)]) if n > 3 else round(s[-1]),
        "p90": round(s[int(n * 0.90)]) if n > 9 else round(s[-1]),
        "p95": round(s[int(n * 0.95)]) if n > 19 else round(s[-1]),
        "p99": round(s[int(n * 0.99)]) if n > 99 else round(s[-1]),
        "max": round(s[-1]),
        "avg": round(statistics.mean(s)),
        "stdev": round(statistics.stdev(s)) if n > 1 else 0,
    }


def histogram(data: list, bins: list) -> dict:
    """Cria histograma com bins customizados em ms."""
    hist = {}
    for i, upper in enumerate(bins):
        lower = bins[i - 1] if i > 0 else 0
        label = f"{lower/1000:.0f}-{upper/1000:.0f}s"
        hist[label] = sum(1 for v in data if lower <= v < upper)
    label = f">{bins[-1]/1000:.0f}s"
    hist[label] = sum(1 for v in data if v >= bins[-1])
    return hist


def analyze(tr: TestResult) -> dict:
    successes = [r for r in tr.results if r.success]
    failures = [r for r in tr.results if not r.success]

    all_times = [r.response_time_ms for r in tr.results]
    ok_times = [r.response_time_ms for r in successes]
    fail_times = [r.response_time_ms for r in failures]

    # Bandwidth
    total_bytes = sum(r.content_length for r in tr.results)
    ok_bytes = sum(r.content_length for r in successes)

    # Status code breakdown
    status_counts = {}
    for r in tr.results:
        if r.status_code:
            k = str(r.status_code)
            status_counts[k] = status_counts.get(k, 0) + 1

    # Error breakdown
    error_counts = {}
    for r in failures:
        error_counts[r.error_type] = error_counts.get(r.error_type, 0) + 1

    # Content-Type breakdown
    ct_counts = {}
    for r in successes:
        ct = r.content_type or "unknown"
        ct_counts[ct] = ct_counts.get(ct, 0) + 1

    # Fail speed classification
    fast_fails = [r for r in failures if r.response_time_ms < 3000]
    medium_fails = [r for r in failures if 3000 <= r.response_time_ms < 10000]
    slow_fails = [r for r in failures if 10000 <= r.response_time_ms < 25000]
    timeout_fails = [r for r in failures if r.response_time_ms >= 25000]

    # Latency histogram (ms bins)
    time_bins = [1000, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 30000]
    ok_hist = histogram(ok_times, time_bins)
    fail_hist = histogram(fail_times, time_bins)

    success_rate = len(successes) / len(tr.results) * 100 if tr.results else 0
    throughput = len(tr.results) / (tr.wall_time_ms / 1000) if tr.wall_time_ms > 0 else 0

    analysis = {
        "label": tr.label,
        "concurrency": tr.concurrency,
        "timeout_s": tr.timeout_s,
        "total_requests": tr.total_requests,
        "success_count": len(successes),
        "failure_count": len(failures),
        "success_rate_pct": round(success_rate, 1),
        "wall_time_s": round(tr.wall_time_ms / 1000, 1),
        "throughput_rps": round(throughput, 1),
        "bandwidth": {
            "total_mb": round(total_bytes / 1024 / 1024, 1),
            "success_mb": round(ok_bytes / 1024 / 1024, 1),
            "avg_page_kb": round(ok_bytes / max(len(successes), 1) / 1024, 1),
        },
        "latency_all": percentiles(all_times),
        "latency_success": percentiles(ok_times),
        "latency_failure": percentiles(fail_times),
        "latency_histogram_success": ok_hist,
        "latency_histogram_failure": fail_hist,
        "status_codes": dict(sorted(status_counts.items(), key=lambda x: -x[1])),
        "error_breakdown": dict(sorted(error_counts.items(), key=lambda x: -x[1])),
        "content_types": dict(sorted(ct_counts.items(), key=lambda x: -x[1])),
        "fail_speed": {
            "fast_lt3s": len(fast_fails),
            "medium_3_10s": len(medium_fails),
            "slow_10_25s": len(slow_fails),
            "timeout_gt25s": len(timeout_fails),
        },
    }

    _print_analysis(analysis)
    return analysis


def _print_analysis(a: dict):
    sr = a["success_rate_pct"]
    print(f"\n  ✅ Sucesso: {a['success_count']}/{a['total_requests']} ({sr}%)")
    print(f"  ⏱  Wall: {a['wall_time_s']}s | Throughput: {a['throughput_rps']} req/s")
    bw = a["bandwidth"]
    print(f"  📦 Bandwidth: {bw['total_mb']}MB total | {bw['avg_page_kb']}KB/page média")

    if a["latency_success"]:
        ls = a["latency_success"]
        print(f"\n  ⏱  LATÊNCIA SUCESSO:")
        print(f"     min={ls['min']}  p50={ls['p50']}  p75={ls['p75']}  p90={ls['p90']}  p95={ls['p95']}  p99={ls['p99']}  max={ls['max']}ms")
        print(f"     avg={ls['avg']}ms  stdev={ls['stdev']}ms")

    if a["latency_failure"]:
        lf = a["latency_failure"]
        print(f"\n  ❌ LATÊNCIA FALHA:")
        print(f"     min={lf['min']}  p50={lf['p50']}  p90={lf['p90']}  max={lf['max']}ms")

    if a["latency_histogram_success"]:
        print(f"\n  📊 HISTOGRAMA (sucesso):")
        total_ok = a["success_count"] or 1
        for bucket, count in a["latency_histogram_success"].items():
            bar = "█" * int(count / total_ok * 50)
            pct = count / total_ok * 100
            if count > 0:
                print(f"     {bucket:>10s}: {count:>4d} ({pct:>5.1f}%) {bar}")

    if a["status_codes"]:
        print(f"\n  🔢 HTTP Status Codes:")
        for code, count in list(a["status_codes"].items())[:10]:
            print(f"     {code}: {count}")

    if a["error_breakdown"]:
        print(f"\n  💥 Erros:")
        for etype, count in a["error_breakdown"].items():
            pct = count / max(a["failure_count"], 1) * 100
            print(f"     {etype}: {count} ({pct:.0f}%)")

    fs = a["fail_speed"]
    print(f"\n  🏎  Velocidade falhas: rápida(<3s)={fs['fast_lt3s']}  média(3-10s)={fs['medium_3_10s']}  lenta(10-25s)={fs['slow_10_25s']}  timeout(>25s)={fs['timeout_gt25s']}")


async def main():
    print("=" * 80)
    print("  STRESS TEST v2 - 711Proxy Gateway")
    print(f"  Proxy: {PROXY_URL.split('@')[1]}")
    print(f"  URLs: {len(ALL_URLS)} sites reais do banco de dados")
    print(f"  Accept: text/html only (sem imagens)")
    print("=" * 80)

    all_analyses = []

    # ── FASE 1: Variando concorrência com timeout fixo de 30s ──
    tests_phase1 = [
        ("C=10 (baseline)",   10,  30, 100),
        ("C=50",              50,  30, 200),
        ("C=100",            100,  30, 500),
        ("C=200",            200,  30, 700),
        ("C=500",            500,  30, 1000),
    ]

    print(f"\n{'#'*80}")
    print(f"  FASE 1: Concorrência variável | timeout=30s")
    print(f"{'#'*80}")

    for label, conc, timeout, n in tests_phase1:
        tr = await run_test(label, conc, timeout, n)
        a = analyze(tr)
        all_analyses.append(a)
        await asyncio.sleep(5)

    # ── FASE 2: Variando timeout com concorrência=200 ──
    tests_phase2 = [
        ("T=5s",   200, 5,  500),
        ("T=10s",  200, 10, 500),
        ("T=15s",  200, 15, 500),
        ("T=20s",  200, 20, 500),
        ("T=30s",  200, 30, 500),
    ]

    print(f"\n{'#'*80}")
    print(f"  FASE 2: Timeout variável | concurrency=200")
    print(f"{'#'*80}")

    for label, conc, timeout, n in tests_phase2:
        tr = await run_test(label, conc, timeout, n)
        a = analyze(tr)
        all_analyses.append(a)
        await asyncio.sleep(5)

    # ── RESUMO GERAL ──
    print(f"\n{'='*80}")
    print(f"  RESUMO FASE 1 - CONCORRÊNCIA")
    print(f"{'='*80}")
    print(f"  {'Label':>20s} | {'OK%':>6s} | {'p50':>6s} | {'p90':>7s} | {'p95':>7s} | {'RPS':>7s} | {'AvgKB':>6s} | {'TOs':>4s}")
    print(f"  {'-'*20} | {'-'*6} | {'-'*6} | {'-'*7} | {'-'*7} | {'-'*7} | {'-'*6} | {'-'*4}")

    for a in all_analyses[:5]:
        ls = a.get("latency_success", {})
        to = a["fail_speed"]["timeout_gt25s"]
        bw = a["bandwidth"]
        print(
            f"  {a['label']:>20s} | {a['success_rate_pct']:>5.1f}% | "
            f"{ls.get('p50','-'):>6} | {ls.get('p90','-'):>7} | {ls.get('p95','-'):>7} | "
            f"{a['throughput_rps']:>6.1f}/s | {bw['avg_page_kb']:>5.0f}K | {to:>4d}"
        )

    print(f"\n{'='*80}")
    print(f"  RESUMO FASE 2 - TIMEOUT (concurrency=200)")
    print(f"{'='*80}")
    print(f"  {'Timeout':>10s} | {'OK%':>6s} | {'#OK':>5s} | {'#Fail':>5s} | {'p50':>6s} | {'p90':>7s} | {'p95':>7s} | {'TOs':>4s}")
    print(f"  {'-'*10} | {'-'*6} | {'-'*5} | {'-'*5} | {'-'*6} | {'-'*7} | {'-'*7} | {'-'*4}")

    for a in all_analyses[5:]:
        ls = a.get("latency_success", {})
        to = a["fail_speed"]["timeout_gt25s"]
        print(
            f"  {a['label']:>10s} | {a['success_rate_pct']:>5.1f}% | "
            f"{a['success_count']:>5d} | {a['failure_count']:>5d} | "
            f"{ls.get('p50','-'):>6} | {ls.get('p90','-'):>7} | {ls.get('p95','-'):>7} | {to:>4d}"
        )

    # ── RECOMENDAÇÃO FINAL ──
    best_timeout_test = all_analyses[-1] if all_analyses else None
    if best_timeout_test and best_timeout_test["latency_success"]:
        ls = best_timeout_test["latency_success"]
        print(f"\n{'='*80}")
        print(f"  📐 RECOMENDAÇÃO DE TIMEOUT (baseado em {best_timeout_test['success_count']} requests bem-sucedidos)")
        print(f"{'='*80}")
        print(f"     session_timeout (cobre 90%): ~{math.ceil(ls['p90']/1000)}s")
        print(f"     session_timeout (cobre 95%): ~{math.ceil(ls['p95']/1000)}s")
        print(f"     session_timeout (cobre 99%): ~{math.ceil(ls['p99']/1000)}s")
        print(f"     Margem segura (p95 + 50%):   ~{math.ceil(ls['p95']/1000 * 1.5)}s")

    # Salvar
    output = {
        "proxy": PROXY_URL.split("@")[1],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_urls_in_db": len(ALL_URLS),
        "tests": all_analyses,
    }
    with open("proxy_stress_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n✅ Resultados completos salvos em proxy_stress_results.json")


if __name__ == "__main__":
    asyncio.run(main())
