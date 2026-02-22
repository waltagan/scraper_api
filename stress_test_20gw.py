#!/usr/bin/env python3
"""
Stress test — 20 Gateways combinados (somente teste combinado).

3 cenários: 100/ep (2000), 250/ep (5000), 500/ep (10000).
"""

import asyncio
import resource
import time
from dataclasses import dataclass, field
from typing import Dict, List
from urllib.parse import quote

import aiohttp

GATEWAY_HOST = "us.rotgb.711proxy.com"
GATEWAY_PORT = 10000

ENDPOINTS = {}
ENDPOINTS["EP01"] = "teste1-zone-custom-region-BR:teste1"
ENDPOINTS["EP02"] = "teste2-zone-custom-region-BR-st-SaoPaulo:teste2"
ENDPOINTS["EP03"] = "teste3-zone-custom-region-BR-st-Minasgerais:teste3"
ENDPOINTS["EP04"] = "teste4-zone-custom-region-BR-st-Saopaulo:teste4"
for i in range(5, 21):
    ENDPOINTS[f"EP{i:02d}"] = f"teste{i}-zone-custom-region-BR:teste{i}"

TEST_URL = "http://httpbin.org/get"
TIMEOUT_S = 30


def _proxy_url(creds: str) -> str:
    user, pwd = creds.split(":")
    return f"http://{quote(user, safe='')}:{quote(pwd, safe='')}@{GATEWAY_HOST}:{GATEWAY_PORT}"


def _bump_fd(target: int = 50000) -> int:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    new = min(target, hard)
    if soft < new:
        resource.setrlimit(resource.RLIMIT_NOFILE, (new, hard))
    return resource.getrlimit(resource.RLIMIT_NOFILE)[0]


def _pct(vals: List[float], p: int) -> float:
    if not vals:
        return 0
    return vals[min(int(len(vals) * p / 100), len(vals) - 1)]


@dataclass
class EPResult:
    name: str
    conc: int
    total: int = 0
    ok: int = 0
    latencies: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=dict)
    elapsed: float = 0

    def rate(self) -> float:
        return (self.ok / self.total * 100) if self.total else 0


async def _req(session: aiohttp.ClientSession, url: str, proxy: str) -> dict:
    t0 = time.perf_counter()
    try:
        async with session.get(
            url, proxy=proxy, allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
        ) as resp:
            await resp.read()
            return {"ok": resp.status < 400, "ms": (time.perf_counter() - t0) * 1000, "err": None}
    except asyncio.TimeoutError:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": "timeout"}
    except aiohttp.ClientError as e:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": type(e).__name__}
    except Exception as e:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": str(e)[:30]}


async def _test_ep(name: str, proxy: str, conc: int) -> EPResult:
    conn = aiohttp.TCPConnector(
        limit=0, limit_per_host=0, force_close=True,
        enable_cleanup_closed=True, ssl=False,
    )
    async with aiohttp.ClientSession(connector=conn, trust_env=False) as s:
        t0 = time.perf_counter()
        results = await asyncio.gather(*[_req(s, TEST_URL, proxy) for _ in range(conc)])
        elapsed = time.perf_counter() - t0

    res = EPResult(name=name, conc=conc, elapsed=elapsed)
    for r in results:
        res.total += 1
        if r["ok"]:
            res.ok += 1
            res.latencies.append(r["ms"])
        else:
            e = r["err"] or "unknown"
            res.errors[e] = res.errors.get(e, 0) + 1
    return res


async def run_combined(conc_per_ep: int):
    total = conc_per_ep * len(ENDPOINTS)
    print(f"\n{'='*90}")
    print(f"  COMBINADO: {conc_per_ep}/endpoint × {len(ENDPOINTS)} endpoints = {total} simultâneas")
    print(f"{'='*90}")

    t0 = time.perf_counter()
    tasks = [_test_ep(name, _proxy_url(creds), conc_per_ep) for name, creds in ENDPOINTS.items()]
    results = await asyncio.gather(*tasks)
    wall = time.perf_counter() - t0

    total_ok = 0
    total_n = 0
    total_errs: Dict[str, int] = {}
    all_lat: List[float] = []

    for r in sorted(results, key=lambda x: x.name):
        total_ok += r.ok
        total_n += r.total
        all_lat.extend(r.latencies)
        for e, c in r.errors.items():
            total_errs[e] = total_errs.get(e, 0) + c

    best = max(results, key=lambda x: x.rate())
    worst = min(results, key=lambda x: x.rate())

    all_lat.sort()
    p50 = _pct(all_lat, 50)
    p90 = _pct(all_lat, 90)
    p99 = _pct(all_lat, 99)

    rate = total_ok / total_n * 100 if total_n else 0
    rps = total_n / wall if wall > 0 else 0

    print(f"\n  {'Métrica':<30s} | Valor")
    print(f"  {'-'*30}-+-{'-'*40}")
    print(f"  {'Total requests':<30s} | {total_n}")
    print(f"  {'Sucesso':<30s} | {total_ok} ({rate:.1f}%)")
    print(f"  {'Falhas':<30s} | {total_n - total_ok} ({100-rate:.1f}%)")
    print(f"  {'Wall time':<30s} | {wall:.1f}s")
    print(f"  {'Throughput':<30s} | {rps:.0f} req/s")
    print(f"  {'Latência p50':<30s} | {p50:.0f}ms")
    print(f"  {'Latência p90':<30s} | {p90:.0f}ms")
    print(f"  {'Latência p99':<30s} | {p99:.0f}ms")
    print(f"  {'Melhor endpoint':<30s} | {best.name} ({best.rate():.1f}%)")
    print(f"  {'Pior endpoint':<30s} | {worst.name} ({worst.rate():.1f}%)")

    if total_errs:
        print(f"\n  Erros:")
        for e, c in sorted(total_errs.items(), key=lambda x: -x[1]):
            print(f"    {e}: {c}")

    print(f"\n  Por endpoint:")
    print(f"  {'EP':>6s} | {'OK':>5s}/{'Tot':>5s} | {'Rate':>6s} | {'p50':>7s} | {'p90':>7s}")
    print(f"  {'-'*6}-+-{'-'*11}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}")
    for r in sorted(results, key=lambda x: x.name):
        lat = sorted(r.latencies)
        ep50 = _pct(lat, 50)
        ep90 = _pct(lat, 90)
        print(f"  {r.name:>6s} | {r.ok:>5d}/{r.total:>5d} | {r.rate():5.1f}% | {ep50:6.0f}ms | {ep90:6.0f}ms")

    return rate


async def main():
    scenarios = [100, 250, 500]

    fd = _bump_fd(max(scenarios) * len(ENDPOINTS) * 3)
    print(f"  FD limit: {fd}")
    print(f"  Endpoints: {len(ENDPOINTS)}")
    print(f"  Cenários: {[c * len(ENDPOINTS) for c in scenarios]} conexões totais")

    results = {}
    for conc in scenarios:
        rate = await run_combined(conc)
        results[conc] = rate
        await asyncio.sleep(5)

    print(f"\n\n{'='*90}")
    print(f"  RESUMO FINAL — 20 Gateways")
    print(f"{'='*90}")
    print(f"\n  {'Conc/EP':>8s} | {'Total':>6s} | {'Success Rate':>12s}")
    print(f"  {'-'*8}-+-{'-'*6}-+-{'-'*12}")
    for conc, rate in results.items():
        print(f"  {conc:>8d} | {conc*len(ENDPOINTS):>6d} | {rate:11.1f}%")

    print()


if __name__ == "__main__":
    asyncio.run(main())
