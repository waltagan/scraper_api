"""
Stress test: 2000 sites reais simultâneos via proxy IP direto.
Só GET + download de texto (sem parsing, sem subpages).
Objetivo: isolar se o gargalo é proxy/rede ou nosso código.
"""

import asyncio
import time
import statistics
import json
from curl_cffi.requests import AsyncSession

PROXY = "http://USER927913-zone-custom-region-BR:2dd94a@165.154.135.29:10000"
TIMEOUT = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def load_urls(path: str, limit: int = 2000) -> list:
    with open(path) as f:
        urls = [line.strip() for line in f if line.strip()]
    return urls[:limit]


def ensure_scheme(url: str) -> str:
    if not url.startswith("http"):
        return f"https://{url}"
    return url


async def fetch_one(session: AsyncSession, url: str, idx: int) -> dict:
    url = ensure_scheme(url)
    t0 = time.perf_counter()
    try:
        resp = await asyncio.wait_for(
            session.get(url, headers=HEADERS, proxy=PROXY, timeout=TIMEOUT,
                        allow_redirects=True, max_redirects=5),
            timeout=TIMEOUT + 5,
        )
        lat = (time.perf_counter() - t0) * 1000
        content_len = len(resp.content) if resp.content else 0
        status = resp.status_code
        ok = 200 <= status < 400 and content_len > 100
        error = None
        if not ok:
            if content_len <= 100:
                error = f"empty_content:status_{status}:len_{content_len}"
            else:
                error = f"http_error:status_{status}"
        return {
            "ok": ok, "status": status, "lat_ms": lat,
            "content_bytes": content_len, "error": error,
            "url": url[:60],
        }
    except Exception as e:
        lat = (time.perf_counter() - t0) * 1000
        err_name = type(e).__name__
        err_msg = str(e)[:80]
        err_cat = "timeout" if "timeout" in err_msg.lower() or "timed out" in err_msg.lower() \
            else "connection" if "connect" in err_msg.lower() or "refused" in err_msg.lower() \
            else "ssl" if "ssl" in err_msg.lower() \
            else "dns" if "resolve" in err_msg.lower() or "dns" in err_msg.lower() \
            else "other"
        return {
            "ok": False, "status": 0, "lat_ms": lat,
            "content_bytes": 0, "error": f"{err_cat}:{err_name}:{err_msg}",
            "url": url[:60],
        }


def percentiles(vals):
    if not vals:
        return {}
    s = sorted(vals)
    n = len(s)
    return {
        "min": round(s[0], 1),
        "p25": round(s[n // 4], 1),
        "p50": round(s[n // 2], 1),
        "p75": round(s[int(n * 0.75)], 1),
        "p90": round(s[int(n * 0.9)], 1),
        "p95": round(s[min(int(n * 0.95), n - 1)], 1),
        "p99": round(s[min(int(n * 0.99), n - 1)], 1),
        "max": round(s[-1], 1),
        "avg": round(statistics.mean(vals), 1),
    }


async def run_test(urls: list, concurrent: int, label: str) -> dict:
    print(f"\n{'='*70}")
    print(f"  {label}: {len(urls)} sites | {concurrent} concurrent")
    print(f"{'='*70}", flush=True)

    session = AsyncSession(
        impersonate="chrome131",
        verify=False,
        max_clients=concurrent + 100,
    )

    sem = asyncio.Semaphore(concurrent)
    counter = {"done": 0, "ok": 0, "fail": 0}
    total = len(urls)
    t_start = time.perf_counter()

    async def limited_fetch(url, idx):
        async with sem:
            result = await fetch_one(session, url, idx)
            counter["done"] += 1
            if result["ok"]:
                counter["ok"] += 1
            else:
                counter["fail"] += 1
            done = counter["done"]
            if done % 100 == 0 or done == total:
                elapsed = time.perf_counter() - t_start
                rps = done / elapsed if elapsed > 0 else 0
                pct = done / total * 100
                ok_rate = counter["ok"] / done * 100 if done > 0 else 0
                print(
                    f"  [{done:>4}/{total}] {pct:5.1f}%  |  "
                    f"ok={counter['ok']}  fail={counter['fail']}  "
                    f"success={ok_rate:.1f}%  |  "
                    f"{elapsed:.1f}s  rps={rps:.1f}  "
                    f"lat={result['lat_ms']:.0f}ms",
                    flush=True,
                )
            return result

    t0 = time.perf_counter()
    tasks = [limited_fetch(url, i) for i, url in enumerate(urls)]
    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - t0

    await session.close()

    successes = [r for r in results if r["ok"]]
    failures = [r for r in results if not r["ok"]]
    all_lats = [r["lat_ms"] for r in results]
    ok_lats = [r["lat_ms"] for r in successes]
    fail_lats = [r["lat_ms"] for r in failures]
    content_sizes = [r["content_bytes"] for r in successes]

    error_cats: dict = {}
    error_details: dict = {}
    for r in failures:
        err = r.get("error") or "unknown"
        cat = err.split(":")[0] if ":" in err else err
        error_cats[cat] = error_cats.get(cat, 0) + 1
        error_details[err[:60]] = error_details.get(err[:60], 0) + 1

    status_codes: dict = {}
    for r in results:
        sc = str(r["status"])
        status_codes[sc] = status_codes.get(sc, 0) + 1

    success_rate = len(successes) / len(results) * 100
    rps = len(results) / total_time

    stats = {
        "label": label,
        "total_urls": len(urls),
        "concurrent": concurrent,
        "total_time_s": round(total_time, 1),
        "success": len(successes),
        "failed": len(failures),
        "success_rate_pct": round(success_rate, 1),
        "requests_per_second": round(rps, 1),
        "companies_per_minute": round(rps * 60, 1),
        "latency_all_ms": percentiles(all_lats),
        "latency_success_ms": percentiles(ok_lats),
        "latency_fail_ms": percentiles(fail_lats),
        "content_bytes": percentiles(content_sizes) if content_sizes else {},
        "status_codes": dict(sorted(status_codes.items(), key=lambda x: -x[1])),
        "error_categories": dict(sorted(error_cats.items(), key=lambda x: -x[1])),
        "error_top10": dict(sorted(error_details.items(), key=lambda x: -x[1])[:10]),
    }

    print(f"  Total time: {total_time:.1f}s")
    print(f"  Success: {len(successes)}/{len(results)} ({success_rate:.1f}%)")
    print(f"  RPS: {rps:.1f} | Companies/min: {rps*60:.1f}")
    if ok_lats:
        p = percentiles(ok_lats)
        print(f"  Latency (ok):   p50={p['p50']:.0f}ms p90={p['p90']:.0f}ms p99={p['p99']:.0f}ms avg={p['avg']:.0f}ms")
    if fail_lats:
        p = percentiles(fail_lats)
        print(f"  Latency (fail): p50={p['p50']:.0f}ms p90={p['p90']:.0f}ms p99={p['p99']:.0f}ms avg={p['avg']:.0f}ms")
    if content_sizes:
        p = percentiles(content_sizes)
        print(f"  Content (ok):   p50={p['p50']:.0f}B p90={p['p90']:.0f}B avg={p['avg']:.0f}B")
    print(f"  Status codes: {status_codes}")
    print(f"  Error cats: {error_cats}")

    return stats


async def main():
    urls = load_urls("test_urls_10000.txt", 10000)
    print(f"Carregadas {len(urls)} URLs reais do banco")

    all_results = []

    r = await run_test(urls[:2000], 2000, "2000_concurrent")
    all_results.append(r)

    # Summary
    print(f"\n\n{'='*100}")
    print("  COMPARATIVO FINAL — 10.000 Sites Reais")
    print(f"{'='*100}")
    print(f"{'Conc':>6} {'Success%':>10} {'RPS':>8} {'Emp/min':>10} {'p50ok':>8} {'p90ok':>8} {'p50fail':>8} {'Errors':>8} {'Time':>8}")
    print("-" * 100)
    for r in all_results:
        lok = r.get("latency_success_ms", {})
        lfail = r.get("latency_fail_ms", {})
        print(
            f"{r['concurrent']:>6} "
            f"{r['success_rate_pct']:>9.1f}% "
            f"{r['requests_per_second']:>7.1f} "
            f"{r['companies_per_minute']:>9.1f} "
            f"{lok.get('p50', 0):>7.0f} "
            f"{lok.get('p90', 0):>7.0f} "
            f"{lfail.get('p50', 0):>7.0f} "
            f"{sum(r['error_categories'].values()):>7}"
            f"{r['total_time_s']:>7.0f}s")

    with open("stress_test_10k_results.json", "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nResultados salvos em stress_test_10k_results.json")


if __name__ == "__main__":
    asyncio.run(main())
