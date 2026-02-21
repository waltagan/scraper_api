#!/usr/bin/env python3
"""
Stress test do gateway 711Proxy — conexões REALMENTE simultâneas.

Usa aiohttp com TCPConnector(limit=0) para abrir milhares de conexões TCP
ao mesmo tempo. HEAD para httpbin.org (~0 bandwidth).
"""

import asyncio
import os
import resource
import sys
import time
from dataclasses import dataclass, field
from typing import List
from urllib.parse import urlparse

import aiohttp

RAW_PROXY = os.getenv(
    "PROXY_GATEWAY_URL",
    "http://USER927913-zone-custom-region-BR:2dd94a@us.rotgb.711proxy.com:10000",
)

TEST_URL = "http://httpbin.org/get"
TIMEOUT_S = 30

BATCH_SIZE = 500


def _bump_fd_limit(target: int = 20000) -> int:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    new_soft = min(target, hard)
    if soft < new_soft:
        resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
    return resource.getrlimit(resource.RLIMIT_NOFILE)[0]


@dataclass
class TestResult:
    concurrency: int
    total: int
    ok: int
    failed: int
    success_rate: float
    throughput_per_sec: float
    elapsed_s: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    error_breakdown: dict = field(default_factory=dict)


def _percentile(sorted_data: List[float], p: float) -> float:
    if not sorted_data:
        return 0
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


async def _single_request(
    session: aiohttp.ClientSession, url: str, proxy: str
) -> dict:
    start = time.perf_counter()
    try:
        async with session.head(
            url,
            allow_redirects=True,
            proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
        ) as resp:
            ms = (time.perf_counter() - start) * 1000
            return {"ok": resp.status < 400, "ms": ms, "status": resp.status}
    except asyncio.TimeoutError:
        return {"ok": False, "ms": (time.perf_counter() - start) * 1000, "error": "timeout"}
    except aiohttp.ClientConnectionError as e:
        ms = (time.perf_counter() - start) * 1000
        err = str(e).lower()
        if "refused" in err or "reset" in err:
            return {"ok": False, "ms": ms, "error": "connection_refused"}
        return {"ok": False, "ms": ms, "error": "connection"}
    except Exception as e:
        ms = (time.perf_counter() - start) * 1000
        return {"ok": False, "ms": ms, "error": f"other({type(e).__name__})"}


async def run_test(concurrency: int, proxy_url: str) -> TestResult:
    """Dispara `concurrency` requests HEAD simultaneamente via gateway."""

    connector = aiohttp.TCPConnector(
        limit=0,
        limit_per_host=0,
        force_close=True,
        enable_cleanup_closed=True,
        ssl=False,
    )

    async with aiohttp.ClientSession(
        connector=connector,
        trust_env=False,
    ) as session:
        print(f"\n  C={concurrency:>5d} | disparando {concurrency} HEAD simultâneos... ", end="", flush=True)
        start = time.perf_counter()

        tasks = [_single_request(session, TEST_URL, proxy_url) for _ in range(concurrency)]
        results = await asyncio.gather(*tasks)

        elapsed = time.perf_counter() - start

    ok_times = sorted([r["ms"] for r in results if r["ok"]])
    failed = [r for r in results if not r["ok"]]
    error_breakdown: dict = {}
    for r in failed:
        cat = r.get("error", "unknown")
        error_breakdown[cat] = error_breakdown.get(cat, 0) + 1

    ok_count = len(ok_times)
    fail_count = len(failed)
    rate = ok_count / len(results) * 100 if results else 0
    tps = len(results) / elapsed if elapsed > 0 else 0

    res = TestResult(
        concurrency=concurrency,
        total=len(results),
        ok=ok_count,
        failed=fail_count,
        success_rate=round(rate, 1),
        throughput_per_sec=round(tps, 1),
        elapsed_s=round(elapsed, 1),
        p50_ms=round(_percentile(ok_times, 50), 0),
        p90_ms=round(_percentile(ok_times, 90), 0),
        p95_ms=round(_percentile(ok_times, 95), 0),
        p99_ms=round(_percentile(ok_times, 99), 0),
        max_ms=round(max(ok_times) if ok_times else 0, 0),
        error_breakdown=error_breakdown,
    )

    print(
        f"✅ {rate:.0f}% ok | {tps:.0f} req/s | "
        f"p50={res.p50_ms:.0f}ms p90={res.p90_ms:.0f}ms p99={res.p99_ms:.0f}ms | "
        f"erros: {error_breakdown or 'nenhum'}"
    )
    return res


async def main():
    levels = [100, 500, 1000, 2000, 5000, 10000]

    if len(sys.argv) > 1:
        levels = [int(x) for x in sys.argv[1].split(",")]

    fd_limit = _bump_fd_limit(max(levels) * 3)

    parsed = urlparse(RAW_PROXY)
    proxy_display = f"{parsed.hostname}:{parsed.port}"

    print("=" * 80)
    print("  STRESS TEST — Gateway 711Proxy (conexões reais)")
    print(f"  Target:    {TEST_URL} (HEAD, ~0 banda)")
    print(f"  Proxy:     {proxy_display}")
    print(f"  Timeout:   {TIMEOUT_S}s")
    print(f"  FD limit:  {fd_limit}")
    print(f"  Batch:     {BATCH_SIZE} (disparos por lote)")
    print(f"  Levels:    {levels}")
    print("=" * 80)

    all_results: List[TestResult] = []

    for conc in levels:
        result = await run_test(conc, RAW_PROXY)
        all_results.append(result)
        await asyncio.sleep(3)

    print(f"\n{'=' * 80}")
    print("  RESUMO FINAL")
    print(f"{'=' * 80}")
    hdr = f"  {'Conc':>6s} | {'OK':>5s} | {'Fail':>5s} | {'OK%':>6s} | {'req/s':>7s} | {'p50':>7s} | {'p90':>7s} | {'p99':>7s} | {'max':>7s} | Erros"
    print(hdr)
    print(f"  {'-' * len(hdr)}")

    for r in all_results:
        errs = ", ".join(f"{k}={v}" for k, v in r.error_breakdown.items()) if r.error_breakdown else "-"
        print(
            f"  {r.concurrency:>6d} | {r.ok:>5d} | {r.failed:>5d} | {r.success_rate:>5.1f}% | "
            f"{r.throughput_per_sec:>6.0f}/s | {r.p50_ms:>6.0f}ms | {r.p90_ms:>6.0f}ms | "
            f"{r.p99_ms:>6.0f}ms | {r.max_ms:>6.0f}ms | {errs}"
        )

    degradation_point = None
    baseline = all_results[0].success_rate if all_results else 100
    for r in all_results[1:]:
        if r.success_rate < baseline - 10:
            degradation_point = r.concurrency
            break

    print(f"\n  Baseline (C={all_results[0].concurrency}): {baseline}% sucesso")
    if degradation_point:
        print(f"  ⚠️  Degradação significativa (>10pp) em C={degradation_point}")
    else:
        print(f"  ✅ Sem degradação significativa até C={all_results[-1].concurrency}")


if __name__ == "__main__":
    asyncio.run(main())
