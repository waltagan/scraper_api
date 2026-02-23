"""
Stress test: 2000 chamadas simultâneas direto no IP 165.154.135.29:10000
vs gateway us.rotgb.711proxy.com:10000

Objetivo: verificar se o IP direto evita o overhead de alocação do gateway.
"""

import asyncio
import time
import statistics
import json
from curl_cffi.requests import AsyncSession

USER = "USER927913-zone-custom-region-BR"
PASS = "2dd94a"
TEST_URL = "http://httpbin.org/ip"
TIMEOUT = 30

TARGETS = {
    "direct_ip": f"http://{USER}:{PASS}@165.154.135.29:10000",
    "gateway_us": f"http://{USER}:{PASS}@us.rotgb.711proxy.com:10000",
}

CONCURRENCY_LEVELS = [500, 1000, 2000]


async def single_request(session: AsyncSession, url: str, proxy: str, idx: int) -> dict:
    t0 = time.perf_counter()
    try:
        resp = await asyncio.wait_for(
            session.get(url, proxy=proxy, timeout=TIMEOUT),
            timeout=TIMEOUT + 5,
        )
        lat = (time.perf_counter() - t0) * 1000
        ok = resp.status_code == 200
        return {"ok": ok, "status": resp.status_code, "lat_ms": lat, "error": None}
    except Exception as e:
        lat = (time.perf_counter() - t0) * 1000
        err_type = type(e).__name__
        err_msg = str(e)[:60]
        return {"ok": False, "status": 0, "lat_ms": lat, "error": f"{err_type}:{err_msg}"}


async def run_batch(proxy_label: str, proxy_url: str, concurrent: int) -> dict:
    print(f"\n{'='*60}")
    print(f"  {proxy_label} | {concurrent} concurrent requests")
    print(f"{'='*60}")

    session = AsyncSession(
        impersonate="chrome131",
        verify=False,
        max_clients=concurrent + 100,
    )

    t0 = time.perf_counter()
    tasks = [single_request(session, TEST_URL, proxy_url, i) for i in range(concurrent)]
    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - t0

    await session.close()

    successes = [r for r in results if r["ok"]]
    failures = [r for r in results if not r["ok"]]
    all_lats = [r["lat_ms"] for r in results]
    ok_lats = [r["lat_ms"] for r in successes]

    error_types: dict = {}
    for r in failures:
        err = r.get("error", "unknown")
        cat = err.split(":")[0] if err else "unknown"
        error_types[cat] = error_types.get(cat, 0) + 1

    def percentiles(vals):
        if not vals:
            return {}
        s = sorted(vals)
        n = len(s)
        return {
            "min": round(s[0], 1),
            "p50": round(s[n // 2], 1),
            "p75": round(s[int(n * 0.75)], 1),
            "p90": round(s[int(n * 0.9)], 1),
            "p95": round(s[min(int(n * 0.95), n - 1)], 1),
            "p99": round(s[min(int(n * 0.99), n - 1)], 1),
            "max": round(s[-1], 1),
            "avg": round(statistics.mean(vals), 1),
        }

    success_rate = len(successes) / len(results) * 100
    rps = len(results) / total_time

    stats = {
        "proxy": proxy_label,
        "concurrent": concurrent,
        "total_requests": len(results),
        "success": len(successes),
        "failed": len(failures),
        "success_rate_pct": round(success_rate, 1),
        "total_time_s": round(total_time, 1),
        "requests_per_second": round(rps, 1),
        "latency_all_ms": percentiles(all_lats),
        "latency_success_ms": percentiles(ok_lats),
        "error_breakdown": dict(sorted(error_types.items(), key=lambda x: -x[1])),
    }

    print(f"  Success: {len(successes)}/{len(results)} ({success_rate:.1f}%)")
    print(f"  Time: {total_time:.1f}s | RPS: {rps:.1f}")
    if ok_lats:
        p = percentiles(ok_lats)
        print(f"  Latency (success): p50={p['p50']}ms p90={p['p90']}ms p99={p['p99']}ms avg={p['avg']}ms")
    if error_types:
        print(f"  Errors: {error_types}")

    return stats


async def main():
    print("=" * 60)
    print("  STRESS TEST: Direct IP vs Gateway")
    print("  Target: httpbin.org/ip")
    print(f"  Concurrency levels: {CONCURRENCY_LEVELS}")
    print("=" * 60)

    # Warmup
    print("\n[Warmup] 5 requests para cada target...")
    for label, proxy in TARGETS.items():
        session = AsyncSession(impersonate="chrome131", verify=False, max_clients=10)
        for i in range(5):
            try:
                resp = await asyncio.wait_for(
                    session.get(TEST_URL, proxy=proxy, timeout=15), timeout=20
                )
                print(f"  {label} warmup {i+1}: status={resp.status_code}", flush=True)
            except Exception as e:
                print(f"  {label} warmup {i+1}: ERRO={e}", flush=True)
        await session.close()

    all_results = []

    for concurrent in CONCURRENCY_LEVELS:
        for label, proxy in TARGETS.items():
            stats = await run_batch(label, proxy, concurrent)
            all_results.append(stats)
            await asyncio.sleep(3)

    # Summary comparison
    print(f"\n\n{'='*80}")
    print("  COMPARATIVO FINAL")
    print(f"{'='*80}")
    print(f"{'Target':<15} {'Conc':>6} {'Success%':>10} {'RPS':>8} {'p50':>8} {'p90':>8} {'p99':>8} {'Avg':>8}")
    print("-" * 80)
    for r in all_results:
        lat = r.get("latency_success_ms", {})
        print(
            f"{r['proxy']:<15} {r['concurrent']:>6} "
            f"{r['success_rate_pct']:>9.1f}% "
            f"{r['requests_per_second']:>7.1f} "
            f"{lat.get('p50', 0):>7.0f} "
            f"{lat.get('p90', 0):>7.0f} "
            f"{lat.get('p99', 0):>7.0f} "
            f"{lat.get('avg', 0):>7.0f}"
        )

    with open("stress_test_direct_ip_results.json", "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nResultados salvos em stress_test_direct_ip_results.json")


if __name__ == "__main__":
    asyncio.run(main())
