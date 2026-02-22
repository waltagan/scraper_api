#!/usr/bin/env python3
"""
Stress test — 4 gateways REGIONAIS (IPs físicos distintos).

Fase 1: Cada gateway SOZINHO a 800 conexões
Fase 2: Todos 4 juntos a 800 cada = 3200 simultâneas
Fase 3: Comparação com 1 gateway solo a 3200
"""

import asyncio
import resource
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from urllib.parse import quote

import aiohttp

CREDS = "teste1-zone-custom-region-BR:teste1"

GATEWAYS = {
    "US":  ("us.rotgb.711proxy.com",  10000),
    "EU":  ("eu.rotgb.711proxy.com",  10000),
    "AS":  ("as.rotgb.711proxy.com",  10000),
    "INA": ("ina.rotgb.711proxy.com", 10000),
}

TEST_URL = "http://httpbin.org/get"
TIMEOUT_S = 30
CONC_PER_GW = 800


def _proxy(host: str, port: int) -> str:
    u, p = CREDS.split(":")
    return f"http://{quote(u, safe='')}:{quote(p, safe='')}@{host}:{port}"


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
class GWResult:
    name: str
    conc: int
    total: int = 0
    ok: int = 0
    ok_lat: List[float] = field(default_factory=list)
    fail_lat: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=dict)
    wall_s: float = 0

    def rate(self) -> float:
        return (self.ok / self.total * 100) if self.total else 0

    def rps(self) -> float:
        return self.total / self.wall_s if self.wall_s > 0 else 0


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
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": str(e)[:40]}


async def _run_gw(name: str, proxy_url: str, conc: int) -> GWResult:
    conn = aiohttp.TCPConnector(
        limit=0, limit_per_host=0, force_close=True,
        enable_cleanup_closed=True, ssl=False,
    )
    async with aiohttp.ClientSession(connector=conn, trust_env=False) as s:
        t0 = time.perf_counter()
        raw = await asyncio.gather(*[_req(s, TEST_URL, proxy_url) for _ in range(conc)])
        wall = time.perf_counter() - t0

    res = GWResult(name=name, conc=conc, wall_s=wall)
    for r in raw:
        res.total += 1
        if r["ok"]:
            res.ok += 1
            res.ok_lat.append(r["ms"])
        else:
            res.fail_lat.append(r["ms"])
            e = r["err"] or "unknown"
            res.errors[e] = res.errors.get(e, 0) + 1
    return res


def _print_result(r: GWResult):
    lat = sorted(r.ok_lat)
    p50 = _pct(lat, 50)
    p90 = _pct(lat, 90)
    p99 = _pct(lat, 99)
    print(f"  {r.name:>5s} | {r.ok:>4d}/{r.total:>4d} ({r.rate():5.1f}%) | "
          f"p50={p50:6.0f}ms p90={p90:6.0f}ms p99={p99:6.0f}ms | "
          f"{r.rps():.0f} req/s | {r.wall_s:.1f}s")
    if r.errors:
        errs = ", ".join(f"{e}={c}" for e, c in sorted(r.errors.items(), key=lambda x: -x[1]))
        print(f"        erros: {errs}")


async def main():
    fd = _bump_fd(CONC_PER_GW * len(GATEWAYS) * 3)
    print(f"  FD limit: {fd}")
    print(f"  Gateways: {list(GATEWAYS.keys())}")
    print(f"  Conexões por gateway: {CONC_PER_GW}")
    print(f"  Total combinado: {CONC_PER_GW * len(GATEWAYS)}")

    # ── FASE 1: Cada gateway sozinho ───────────────────────────────────

    print(f"\n\n{'#'*80}")
    print(f"  FASE 1: Cada gateway SOZINHO — {CONC_PER_GW} conexões")
    print(f"{'#'*80}\n")

    solo_results: Dict[str, GWResult] = {}
    for name, (host, port) in GATEWAYS.items():
        proxy = _proxy(host, port)
        print(f"  Testando {name} ({host})...", flush=True)
        r = await _run_gw(name, proxy, CONC_PER_GW)
        solo_results[name] = r
        _print_result(r)
        await asyncio.sleep(3)

    # ── FASE 2: Todos 4 juntos ─────────────────────────────────────────

    total_combined = CONC_PER_GW * len(GATEWAYS)
    print(f"\n\n{'#'*80}")
    print(f"  FASE 2: TODOS 4 JUNTOS — {CONC_PER_GW}/gw × {len(GATEWAYS)} = {total_combined} simultâneas")
    print(f"{'#'*80}\n")

    tasks = []
    for name, (host, port) in GATEWAYS.items():
        proxy = _proxy(host, port)
        tasks.append(_run_gw(name, proxy, CONC_PER_GW))

    t0 = time.perf_counter()
    combined_list = await asyncio.gather(*tasks)
    combined_wall = time.perf_counter() - t0
    combined_results: Dict[str, GWResult] = {r.name: r for r in combined_list}

    for r in combined_list:
        _print_result(r)

    combo_ok = sum(r.ok for r in combined_list)
    combo_total = sum(r.total for r in combined_list)
    combo_rate = combo_ok / combo_total * 100 if combo_total else 0
    combo_all_lat = sorted(
        [ms for r in combined_list for ms in r.ok_lat]
    )
    combo_rps = combo_total / combined_wall if combined_wall > 0 else 0

    print(f"\n  TOTAL COMBINADO: {combo_ok}/{combo_total} ({combo_rate:.1f}%) | "
          f"p50={_pct(combo_all_lat, 50):.0f}ms p90={_pct(combo_all_lat, 90):.0f}ms "
          f"p99={_pct(combo_all_lat, 99):.0f}ms | {combo_rps:.0f} req/s | {combined_wall:.1f}s")

    combo_errs: Dict[str, int] = {}
    for r in combined_list:
        for e, c in r.errors.items():
            combo_errs[e] = combo_errs.get(e, 0) + c
    if combo_errs:
        errs = ", ".join(f"{e}={c}" for e, c in sorted(combo_errs.items(), key=lambda x: -x[1]))
        print(f"  Erros totais: {errs}")

    # ── FASE 3: 1 gateway solo a 3200 (baseline) ──────────────────────

    print(f"\n\n{'#'*80}")
    print(f"  FASE 3: BASELINE — 1 gateway (US) solo a {total_combined} conexões")
    print(f"{'#'*80}\n")

    await asyncio.sleep(5)
    us_host, us_port = GATEWAYS["US"]
    us_proxy = _proxy(us_host, us_port)
    print(f"  Disparando {total_combined} requests no US sozinho...", flush=True)
    baseline = await _run_gw("US_solo", us_proxy, total_combined)
    _print_result(baseline)

    # ── COMPARAÇÃO FINAL ───────────────────────────────────────────────

    print(f"\n\n{'#'*80}")
    print(f"  COMPARAÇÃO FINAL")
    print(f"{'#'*80}")

    baseline_lat = sorted(baseline.ok_lat)

    print(f"\n  {'Cenário':<30s} | {'Conex':>6s} | {'Rate':>7s} | {'p50':>8s} | {'p90':>8s} | {'p99':>8s} | {'RPS':>6s}")
    print(f"  {'-'*30}-+-{'-'*6}-+-{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}")

    for name in GATEWAYS:
        sr = solo_results[name]
        lat = sorted(sr.ok_lat)
        print(f"  {name+' solo @800':<30s} | {sr.conc:>6d} | {sr.rate():6.1f}% | "
              f"{_pct(lat,50):7.0f}ms | {_pct(lat,90):7.0f}ms | {_pct(lat,99):7.0f}ms | {sr.rps():5.0f}/s")

    print(f"  {'':<30s} | {'':<6s} | {'':<7s} | {'':<8s} | {'':<8s} | {'':<8s} | {'':<6s}")

    print(f"  {'4 GW combinados @800/gw':<30s} | {total_combined:>6d} | {combo_rate:6.1f}% | "
          f"{_pct(combo_all_lat,50):7.0f}ms | {_pct(combo_all_lat,90):7.0f}ms | {_pct(combo_all_lat,99):7.0f}ms | {combo_rps:5.0f}/s")

    print(f"  {'1 GW (US) solo @3200':<30s} | {baseline.conc:>6d} | {baseline.rate():6.1f}% | "
          f"{_pct(baseline_lat,50):7.0f}ms | {_pct(baseline_lat,90):7.0f}ms | {_pct(baseline_lat,99):7.0f}ms | {baseline.rps():5.0f}/s")

    delta = combo_rate - baseline.rate()
    print(f"\n  Delta (4 GW vs 1 GW): {delta:+.1f}%")
    if delta > 5:
        print(f"  VEREDICTO: 4 gateways regionais é SIGNIFICATIVAMENTE melhor!")
    elif delta > 1:
        print(f"  VEREDICTO: 4 gateways regionais é melhor.")
    elif delta > -1:
        print(f"  VEREDICTO: Praticamente igual — gateways compartilham gargalo.")
    else:
        print(f"  VEREDICTO: 1 gateway melhor — overhead de gateways distantes.")

    solo_avg_rate = sum(r.rate() for r in solo_results.values()) / len(solo_results)
    print(f"\n  Média solo individual (800/gw): {solo_avg_rate:.1f}%")
    print(f"  Combinado (3200 total):          {combo_rate:.1f}%")
    print(f"  Degradação combinado vs solo:     {combo_rate - solo_avg_rate:+.1f}%")

    print(f"\n\n{'='*80}")
    print(f"  STRESS TEST 4 REGIÕES CONCLUÍDO")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
