#!/usr/bin/env python3
"""
Stress Test COMPLETO — Plano Unlimited By Port (711Proxy).

Testes:
  T1: Latência unitária (1 req cada porta, 3x)
  T2: Sticky IP validation (mesmo IP por porta?)
  T3: Concorrência escalonada: 1 porta solo (100→5000)
  T4: 5 portas combinadas (800→20000)
  T5: Bandwidth real por porta (download de payload grande)
  T6: Independência entre portas (1 porta saturada vs outras)
"""

import asyncio
import resource
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from urllib.parse import quote

import aiohttp

PROXY_HOST = "128.14.145.62"
PROXY_USER = "USER927913-region-BR-sessTime-3-sessAuto-1"
PROXY_PASS = "2dd94a"
PORTS = [25001, 25002, 25003, 25004, 25005]

TEST_URL = "http://httpbin.org/get"
BANDWIDTH_URL = "http://httpbin.org/bytes/102400"  # 100 KB payload
TIMEOUT_S = 30


def _proxy(port: int) -> str:
    return f"http://{quote(PROXY_USER, safe='')}:{quote(PROXY_PASS, safe='')}@{PROXY_HOST}:{port}"


def _bump_fd(target: int = 60000) -> int:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    new = min(target, hard)
    if soft < new:
        resource.setrlimit(resource.RLIMIT_NOFILE, (new, hard))
    return resource.getrlimit(resource.RLIMIT_NOFILE)[0]


def _pct(vals: List[float], p: int) -> float:
    if not vals:
        return 0
    return vals[min(int(len(vals) * p / 100), len(vals) - 1)]


def _print_lat_table(ok_lat: List[float], fail_lat: List[float]):
    ok_lat.sort()
    fail_lat.sort()
    all_lat = sorted(ok_lat + fail_lat)
    pcts = [10, 25, 50, 75, 90, 95, 99]
    print(f"    {'Pct':>6s} | {'Sucesso':>10s} | {'Falha':>10s} | {'Todas':>10s}")
    print(f"    {'-'*6}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}")
    for p in pcts:
        ok_v = _pct(ok_lat, p) if ok_lat else 0
        fail_v = _pct(fail_lat, p) if fail_lat else 0
        all_v = _pct(all_lat, p) if all_lat else 0
        print(f"    {'p'+str(p):>6s} | {ok_v:9.0f}ms | {fail_v:9.0f}ms | {all_v:9.0f}ms")
    if ok_lat:
        print(f"    {'avg':>6s} | {sum(ok_lat)/len(ok_lat):9.0f}ms | ", end="")
    else:
        print(f"    {'avg':>6s} | {'—':>10s} | ", end="")
    if fail_lat:
        print(f"{sum(fail_lat)/len(fail_lat):9.0f}ms | {sum(all_lat)/len(all_lat):9.0f}ms")
    else:
        print(f"{'—':>10s} | {sum(all_lat)/len(all_lat) if all_lat else 0:9.0f}ms")


@dataclass
class Result:
    label: str
    conc: int
    total: int = 0
    ok: int = 0
    ok_lat: List[float] = field(default_factory=list)
    fail_lat: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=dict)
    wall_s: float = 0
    bytes_downloaded: int = 0

    def rate(self) -> float:
        return (self.ok / self.total * 100) if self.total else 0

    def rps(self) -> float:
        return self.total / self.wall_s if self.wall_s > 0 else 0


async def _req(session: aiohttp.ClientSession, url: str, proxy: str, read_body: bool = True) -> dict:
    t0 = time.perf_counter()
    try:
        async with session.get(
            url, proxy=proxy, allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
        ) as resp:
            body = await resp.read() if read_body else b""
            ms = (time.perf_counter() - t0) * 1000
            return {"ok": resp.status < 400, "ms": ms, "err": None,
                    "bytes": len(body), "status": resp.status}
    except asyncio.TimeoutError:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": "timeout", "bytes": 0}
    except aiohttp.ClientError as e:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": type(e).__name__, "bytes": 0}
    except Exception as e:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": str(e)[:40], "bytes": 0}


async def _run_conc(proxy_url: str, conc: int, url: str = TEST_URL) -> Result:
    conn = aiohttp.TCPConnector(
        limit=0, limit_per_host=0, force_close=True,
        enable_cleanup_closed=True, ssl=False,
    )
    async with aiohttp.ClientSession(connector=conn, trust_env=False) as s:
        t0 = time.perf_counter()
        raw = await asyncio.gather(*[_req(s, url, proxy_url) for _ in range(conc)])
        wall = time.perf_counter() - t0

    res = Result(label="", conc=conc, wall_s=wall)
    for r in raw:
        res.total += 1
        res.bytes_downloaded += r.get("bytes", 0)
        if r["ok"]:
            res.ok += 1
            res.ok_lat.append(r["ms"])
        else:
            res.fail_lat.append(r["ms"])
            e = r["err"] or "unknown"
            res.errors[e] = res.errors.get(e, 0) + 1
    return res


def _print_result(r: Result, show_lat: bool = False):
    lat = sorted(r.ok_lat)
    p50 = _pct(lat, 50)
    p90 = _pct(lat, 90)
    p99 = _pct(lat, 99)
    mbps = (r.bytes_downloaded * 8 / r.wall_s / 1_000_000) if r.wall_s > 0 else 0
    print(f"    C={r.conc:>5d} | {r.ok:>5d}/{r.total:>5d} ({r.rate():5.1f}%) | "
          f"p50={p50:7.0f}ms p90={p90:7.0f}ms p99={p99:7.0f}ms | "
          f"{r.rps():.0f} req/s | {r.wall_s:.1f}s"
          + (f" | {mbps:.1f} Mbps" if r.bytes_downloaded > 0 else ""))
    if r.errors:
        errs = ", ".join(f"{e}={c}" for e, c in sorted(r.errors.items(), key=lambda x: -x[1]))
        print(f"      erros: {errs}")
    if show_lat and (r.ok_lat or r.fail_lat):
        _print_lat_table(r.ok_lat, r.fail_lat)


# ═══════════════════════════════════════════════════════════════════════════
# T1: Latência unitária
# ═══════════════════════════════════════════════════════════════════════════

async def test_latency():
    print(f"\n\n{'#'*80}")
    print(f"  T1: LATÊNCIA UNITÁRIA — 1 request por porta, 3 rodadas")
    print(f"{'#'*80}\n")

    conn = aiohttp.TCPConnector(limit=0, ssl=False)
    async with aiohttp.ClientSession(connector=conn, trust_env=False) as s:
        for round_n in range(1, 4):
            print(f"  Rodada {round_n}:")
            for port in PORTS:
                proxy = _proxy(port)
                r = await _req(s, TEST_URL, proxy)
                status = f"{r['ms']:.0f}ms" if r["ok"] else f"FALHOU: {r['err']}"
                print(f"    Porta {port}: {status}", flush=True)
            if round_n < 3:
                await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════════════════════
# T2: Sticky IP validation
# ═══════════════════════════════════════════════════════════════════════════

async def test_sticky_ip():
    print(f"\n\n{'#'*80}")
    print(f"  T2: STICKY IP — Verificar se mesma porta = mesmo IP")
    print(f"{'#'*80}\n")

    conn = aiohttp.TCPConnector(limit=0, ssl=False)
    ip_url = "http://httpbin.org/ip"
    async with aiohttp.ClientSession(connector=conn, trust_env=False) as s:
        for port in PORTS:
            proxy = _proxy(port)
            ips = []
            for i in range(5):
                try:
                    async with s.get(ip_url, proxy=proxy,
                                     timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        data = await resp.json()
                        ips.append(data.get("origin", "?"))
                except Exception as e:
                    ips.append(f"ERR:{type(e).__name__}")
            unique = set(ips)
            sticky = "STICKY" if len(unique) == 1 else f"ROTOU ({len(unique)} IPs)"
            print(f"    Porta {port}: {ips[0]} — {sticky}")
            if len(unique) > 1:
                print(f"      IPs vistos: {unique}")


# ═══════════════════════════════════════════════════════════════════════════
# T3: Concorrência escalonada — 1 porta solo
# ═══════════════════════════════════════════════════════════════════════════

async def test_single_port_scaling():
    print(f"\n\n{'#'*80}")
    print(f"  T3: CONCORRÊNCIA — 1 PORTA SOLO (porta {PORTS[0]})")
    print(f"{'#'*80}\n")

    proxy = _proxy(PORTS[0])
    levels = [100, 500, 800, 1000, 2000, 3000, 5000]

    results = []
    for conc in levels:
        print(f"  Disparando {conc} conexões na porta {PORTS[0]}...", flush=True)
        r = await _run_conc(proxy, conc)
        r.label = f"Solo P1 @{conc}"
        results.append(r)
        _print_result(r, show_lat=(conc in [800, 3000, 5000]))
        await asyncio.sleep(3)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# T4: 5 portas combinadas
# ═══════════════════════════════════════════════════════════════════════════

async def test_combined_ports():
    print(f"\n\n{'#'*80}")
    print(f"  T4: 5 PORTAS COMBINADAS — Concorrência distribuída")
    print(f"{'#'*80}\n")

    levels = [800, 2000, 5000, 10000, 20000]
    all_results = []

    for total_conc in levels:
        per_port = total_conc // len(PORTS)
        actual = per_port * len(PORTS)
        print(f"\n  === {per_port}/porta × {len(PORTS)} = {actual} simultâneas ===\n", flush=True)

        tasks = [_run_conc(_proxy(p), per_port) for p in PORTS]
        t0 = time.perf_counter()
        port_results = await asyncio.gather(*tasks)
        combo_wall = time.perf_counter() - t0

        combo_ok = 0
        combo_total = 0
        combo_ok_lat = []
        combo_fail_lat = []
        combo_errs: Dict[str, int] = {}
        combo_bytes = 0

        for i, r in enumerate(port_results):
            combo_ok += r.ok
            combo_total += r.total
            combo_ok_lat.extend(r.ok_lat)
            combo_fail_lat.extend(r.fail_lat)
            combo_bytes += r.bytes_downloaded
            for e, c in r.errors.items():
                combo_errs[e] = combo_errs.get(e, 0) + c

            lat = sorted(r.ok_lat)
            print(f"    P{PORTS[i]}: {r.ok:>5d}/{r.total:>5d} ({r.rate():5.1f}%) "
                  f"p50={_pct(lat,50):6.0f}ms p90={_pct(lat,90):6.0f}ms")

        combo_rate = combo_ok / combo_total * 100 if combo_total else 0
        combo_all_lat = sorted(combo_ok_lat)
        combo_rps = combo_total / combo_wall if combo_wall > 0 else 0

        print(f"\n    TOTAL: {combo_ok}/{combo_total} ({combo_rate:.1f}%) | "
              f"p50={_pct(combo_all_lat,50):.0f}ms p90={_pct(combo_all_lat,90):.0f}ms "
              f"p99={_pct(combo_all_lat,99):.0f}ms | {combo_rps:.0f} req/s | {combo_wall:.1f}s")
        if combo_errs:
            errs = ", ".join(f"{e}={c}" for e, c in sorted(combo_errs.items(), key=lambda x: -x[1]))
            print(f"    Erros: {errs}")

        if total_conc in [5000, 10000, 20000]:
            _print_lat_table(combo_ok_lat, combo_fail_lat)

        all_results.append({
            "conc": actual, "rate": combo_rate,
            "p50": _pct(combo_all_lat, 50), "p90": _pct(combo_all_lat, 90),
            "p99": _pct(combo_all_lat, 99), "rps": combo_rps,
            "wall": combo_wall, "errors": combo_errs,
        })

        await asyncio.sleep(5)

    return all_results


# ═══════════════════════════════════════════════════════════════════════════
# T5: Bandwidth real
# ═══════════════════════════════════════════════════════════════════════════

async def test_bandwidth():
    print(f"\n\n{'#'*80}")
    print(f"  T5: BANDWIDTH REAL — Download de 100KB payloads")
    print(f"{'#'*80}\n")

    for port in PORTS:
        proxy = _proxy(port)
        conc_levels = [10, 50, 100]

        for conc in conc_levels:
            r = await _run_conc(proxy, conc, url=BANDWIDTH_URL)
            mbps = (r.bytes_downloaded * 8 / r.wall_s / 1_000_000) if r.wall_s > 0 else 0
            mb_total = r.bytes_downloaded / 1_000_000
            lat = sorted(r.ok_lat)
            print(f"    Porta {port} @{conc:>3d} conc: {r.ok}/{r.total} ok | "
                  f"{mb_total:.1f} MB em {r.wall_s:.1f}s = {mbps:.1f} Mbps | "
                  f"p50={_pct(lat,50):.0f}ms")
            if r.errors:
                errs = ", ".join(f"{e}={c}" for e, c in sorted(r.errors.items(), key=lambda x: -x[1]))
                print(f"      erros: {errs}")

        await asyncio.sleep(2)

    print(f"\n  Teste combinado: 5 portas × 100 downloads de 100KB simultâneos")
    tasks = [_run_conc(_proxy(p), 100, url=BANDWIDTH_URL) for p in PORTS]
    t0 = time.perf_counter()
    results = await asyncio.gather(*tasks)
    wall = time.perf_counter() - t0
    total_bytes = sum(r.bytes_downloaded for r in results)
    total_mbps = (total_bytes * 8 / wall / 1_000_000) if wall > 0 else 0
    total_ok = sum(r.ok for r in results)
    total_n = sum(r.total for r in results)

    for i, r in enumerate(results):
        mbps = (r.bytes_downloaded * 8 / r.wall_s / 1_000_000) if r.wall_s > 0 else 0
        print(f"    P{PORTS[i]}: {r.ok}/{r.total} ok, {mbps:.1f} Mbps")

    print(f"    TOTAL: {total_ok}/{total_n} ok, {total_bytes/1_000_000:.1f} MB, "
          f"{total_mbps:.1f} Mbps combinado em {wall:.1f}s")


# ═══════════════════════════════════════════════════════════════════════════
# T6: Independência entre portas
# ═══════════════════════════════════════════════════════════════════════════

async def test_port_independence():
    print(f"\n\n{'#'*80}")
    print(f"  T6: INDEPENDÊNCIA — Porta 1 saturada (3000) + outras 4 leves (100)")
    print(f"{'#'*80}\n")

    tasks = [_run_conc(_proxy(PORTS[0]), 3000)]
    for p in PORTS[1:]:
        tasks.append(_run_conc(_proxy(p), 100))

    results = await asyncio.gather(*tasks)

    for i, r in enumerate(results):
        conc = 3000 if i == 0 else 100
        lat = sorted(r.ok_lat)
        tag = "SATURADA" if i == 0 else "LEVE"
        print(f"    P{PORTS[i]} ({tag} @{conc}): {r.ok}/{r.total} ({r.rate():.1f}%) "
              f"p50={_pct(lat,50):.0f}ms p90={_pct(lat,90):.0f}ms")
        if r.errors:
            errs = ", ".join(f"{e}={c}" for e, c in sorted(r.errors.items(), key=lambda x: -x[1]))
            print(f"      erros: {errs}")

    saturated_rate = results[0].rate()
    light_rates = [r.rate() for r in results[1:]]
    avg_light = sum(light_rates) / len(light_rates)

    if avg_light > saturated_rate + 5:
        print(f"\n    VEREDICTO: Portas são INDEPENDENTES (saturada={saturated_rate:.1f}%, leves={avg_light:.1f}%)")
    else:
        print(f"\n    VEREDICTO: Portas COMPARTILHAM recurso (saturada={saturated_rate:.1f}%, leves={avg_light:.1f}%)")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

async def main():
    fd = _bump_fd(60000)
    print(f"{'='*80}")
    print(f"  STRESS TEST COMPLETO — Plano Unlimited By Port")
    print(f"{'='*80}")
    print(f"  Proxy: {PROXY_HOST}")
    print(f"  Portas: {PORTS}")
    print(f"  Auth: {PROXY_USER}")
    print(f"  FD limit: {fd}")
    print(f"  Timeout: {TIMEOUT_S}s")

    await test_latency()
    await test_sticky_ip()
    await asyncio.sleep(3)

    solo_results = await test_single_port_scaling()
    await asyncio.sleep(5)

    combined_results = await test_combined_ports()
    await asyncio.sleep(5)

    await test_bandwidth()
    await asyncio.sleep(5)

    await test_port_independence()

    # RESUMO FINAL
    print(f"\n\n{'#'*80}")
    print(f"  RESUMO FINAL")
    print(f"{'#'*80}")

    print(f"\n  1 porta solo:")
    print(f"  {'Conc':>8s} | {'Rate':>7s} | {'p50':>8s} | {'p90':>8s} | {'RPS':>6s}")
    print(f"  {'-'*8}-+-{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}")
    for r in solo_results:
        lat = sorted(r.ok_lat)
        print(f"  {r.conc:>8d} | {r.rate():6.1f}% | {_pct(lat,50):7.0f}ms | {_pct(lat,90):7.0f}ms | {r.rps():5.0f}/s")

    print(f"\n  5 portas combinadas:")
    print(f"  {'Conc':>8s} | {'Rate':>7s} | {'p50':>8s} | {'p90':>8s} | {'p99':>8s} | {'RPS':>6s}")
    print(f"  {'-'*8}-+-{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}")
    for cr in combined_results:
        print(f"  {cr['conc']:>8d} | {cr['rate']:6.1f}% | {cr['p50']:7.0f}ms | {cr['p90']:7.0f}ms | "
              f"{cr['p99']:7.0f}ms | {cr['rps']:5.0f}/s")

    print(f"\n\n{'='*80}")
    print(f"  STRESS TEST BY PORT CONCLUÍDO")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
