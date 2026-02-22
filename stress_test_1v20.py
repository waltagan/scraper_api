#!/usr/bin/env python3
"""
Stress test DEFINITIVO — 1 endpoint vs 20 endpoints.

Fase 0: Validar todos os 20 endpoints (1 chamada cada)
Fase 1: 1 endpoint solo a 3000, 5000, 7000, 10000
Fase 2: 20 endpoints combinados nos mesmos totais (150, 250, 350, 500 por EP)
Fase 3: Comparação lado a lado
"""

import asyncio
import resource
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from urllib.parse import quote

import aiohttp

GATEWAY_HOST = "us.rotgb.711proxy.com"
GATEWAY_PORT = 10000

SOLO_CREDS = "teste1-zone-custom-region-BR:teste1"

ALL_ENDPOINTS: Dict[str, str] = {}
ALL_ENDPOINTS["EP01"] = "teste1-zone-custom-region-BR:teste1"
ALL_ENDPOINTS["EP02"] = "teste2-zone-custom-region-BR-st-SaoPaulo:teste2"
ALL_ENDPOINTS["EP03"] = "teste3-zone-custom-region-BR-st-Minasgerais:teste3"
ALL_ENDPOINTS["EP04"] = "teste4-zone-custom-region-BR-st-Saopaulo:teste4"
for i in range(5, 21):
    ALL_ENDPOINTS[f"EP{i:02d}"] = f"teste{i}-zone-custom-region-BR:teste{i}"

TEST_URL = "http://httpbin.org/get"
TIMEOUT_S = 30


def _proxy(creds: str) -> str:
    u, p = creds.split(":")
    return f"http://{quote(u, safe='')}:{quote(p, safe='')}@{GATEWAY_HOST}:{GATEWAY_PORT}"


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
class Result:
    label: str
    total_conc: int
    total: int = 0
    ok: int = 0
    latencies: List[float] = field(default_factory=list)
    fail_latencies: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=dict)
    wall_s: float = 0
    ep_results: Dict[str, dict] = field(default_factory=dict)

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
            ms = (time.perf_counter() - t0) * 1000
            return {"ok": resp.status < 400, "ms": ms, "err": None}
    except asyncio.TimeoutError:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": "timeout"}
    except aiohttp.ClientError as e:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": type(e).__name__}
    except Exception as e:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000, "err": str(e)[:40]}


def _print_latency_table(label: str, ok_lat: List[float], fail_lat: List[float]):
    ok_lat.sort()
    fail_lat.sort()
    all_lat = sorted(ok_lat + fail_lat)
    pcts = [10, 25, 50, 75, 90, 95, 99]

    print(f"\n  Latências {label}:")
    print(f"  {'Percentil':>10s} | {'Sucesso':>10s} | {'Falha':>10s} | {'Todas':>10s}")
    print(f"  {'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}")
    for p in pcts:
        ok_v = _pct(ok_lat, p) if ok_lat else 0
        fail_v = _pct(fail_lat, p) if fail_lat else 0
        all_v = _pct(all_lat, p) if all_lat else 0
        print(f"  {'p'+str(p):>10s} | {ok_v:9.0f}ms | {fail_v:9.0f}ms | {all_v:9.0f}ms")

    if ok_lat:
        print(f"  {'avg':>10s} | {sum(ok_lat)/len(ok_lat):9.0f}ms | ", end="")
    else:
        print(f"  {'avg':>10s} | {'—':>10s} | ", end="")
    if fail_lat:
        print(f"{sum(fail_lat)/len(fail_lat):9.0f}ms | ", end="")
    else:
        print(f"{'—':>10s} | ", end="")
    if all_lat:
        print(f"{sum(all_lat)/len(all_lat):9.0f}ms")
    else:
        print(f"{'—':>10s}")

    if ok_lat:
        print(f"  {'min':>10s} | {ok_lat[0]:9.0f}ms | ", end="")
    else:
        print(f"  {'min':>10s} | {'—':>10s} | ", end="")
    if fail_lat:
        print(f"{fail_lat[0]:9.0f}ms | {all_lat[0]:9.0f}ms")
    else:
        print(f"{'—':>10s} | {all_lat[0] if all_lat else 0:9.0f}ms")

    if ok_lat:
        print(f"  {'max':>10s} | {ok_lat[-1]:9.0f}ms | ", end="")
    else:
        print(f"  {'max':>10s} | {'—':>10s} | ", end="")
    if fail_lat:
        print(f"{fail_lat[-1]:9.0f}ms | {all_lat[-1]:9.0f}ms")
    else:
        print(f"{'—':>10s} | {all_lat[-1] if all_lat else 0:9.0f}ms")


async def _run_batch(proxy_url: str, conc: int, label: str = "") -> Tuple[List[dict], float]:
    conn = aiohttp.TCPConnector(
        limit=0, limit_per_host=0, force_close=True,
        enable_cleanup_closed=True, ssl=False,
    )
    async with aiohttp.ClientSession(connector=conn, trust_env=False) as s:
        t0 = time.perf_counter()
        results = await asyncio.gather(*[_req(s, TEST_URL, proxy_url) for _ in range(conc)])
        wall = time.perf_counter() - t0
    return results, wall


# ── FASE 0: Validação ──────────────────────────────────────────────────────

async def phase0_validate():
    print(f"\n{'='*90}")
    print(f"  FASE 0: Validar todos os 20 endpoints (1 chamada cada)")
    print(f"{'='*90}\n")

    conn = aiohttp.TCPConnector(limit=0, ssl=False)
    ok_count = 0
    async with aiohttp.ClientSession(connector=conn, trust_env=False) as s:
        for name, creds in ALL_ENDPOINTS.items():
            proxy = _proxy(creds)
            t0 = time.perf_counter()
            try:
                async with s.get(
                    TEST_URL, proxy=proxy, allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    await resp.read()
                    ms = (time.perf_counter() - t0) * 1000
                    status = "OK" if resp.status < 400 else f"HTTP {resp.status}"
                    if resp.status < 400:
                        ok_count += 1
                    print(f"  {name}: {status} — {ms:.0f}ms", flush=True)
            except Exception as e:
                ms = (time.perf_counter() - t0) * 1000
                print(f"  {name}: FALHOU — {type(e).__name__} — {ms:.0f}ms", flush=True)

    print(f"\n  Resultado: {ok_count}/{len(ALL_ENDPOINTS)} endpoints funcionando")
    if ok_count < len(ALL_ENDPOINTS):
        print(f"  ATENÇÃO: {len(ALL_ENDPOINTS) - ok_count} endpoints falharam!")
    return ok_count


# ── FASE 1: 1 endpoint solo ────────────────────────────────────────────────

async def phase1_solo(levels: List[int]) -> Dict[int, Result]:
    print(f"\n\n{'#'*90}")
    print(f"  FASE 1: 1 ENDPOINT SOLO (EP01) — {levels} conexões simultâneas")
    print(f"{'#'*90}")

    solo_proxy = _proxy(SOLO_CREDS)
    results = {}

    for conc in levels:
        print(f"\n{'='*90}")
        print(f"  SOLO: {conc} conexões simultâneas via EP01")
        print(f"{'='*90}")
        print(f"  Disparando {conc} requests...", flush=True)

        raw, wall = await _run_batch(solo_proxy, conc)
        res = Result(label=f"Solo {conc}", total_conc=conc, wall_s=wall)

        for r in raw:
            res.total += 1
            if r["ok"]:
                res.ok += 1
                res.latencies.append(r["ms"])
            else:
                res.fail_latencies.append(r["ms"])
                e = r["err"] or "unknown"
                res.errors[e] = res.errors.get(e, 0) + 1

        print(f"\n  Total: {res.ok}/{res.total} ({res.rate():.1f}%) em {wall:.1f}s — {res.rps():.0f} req/s")

        if res.errors:
            print(f"  Erros:", end="")
            for e, c in sorted(res.errors.items(), key=lambda x: -x[1]):
                print(f"  {e}={c}", end="")
            print()

        _print_latency_table("(solo)", res.latencies, res.fail_latencies)
        results[conc] = res

        print(f"\n  Aguardando 5s para o gateway se recuperar...", flush=True)
        await asyncio.sleep(5)

    return results


# ── FASE 2: 20 endpoints combinados ────────────────────────────────────────

async def phase2_multi(levels: List[int]) -> Dict[int, Result]:
    print(f"\n\n{'#'*90}")
    print(f"  FASE 2: 20 ENDPOINTS COMBINADOS — {levels} conexões totais")
    print(f"{'#'*90}")

    results = {}
    for total_conc in levels:
        per_ep = total_conc // len(ALL_ENDPOINTS)
        actual_total = per_ep * len(ALL_ENDPOINTS)

        print(f"\n{'='*90}")
        print(f"  MULTI: {per_ep}/endpoint × {len(ALL_ENDPOINTS)} = {actual_total} simultâneas")
        print(f"{'='*90}")
        print(f"  Disparando...", flush=True)

        tasks = []
        ep_names = []
        for name, creds in ALL_ENDPOINTS.items():
            proxy = _proxy(creds)
            tasks.append(_run_batch(proxy, per_ep, name))
            ep_names.append(name)

        t0 = time.perf_counter()
        batch_results = await asyncio.gather(*tasks)
        total_wall = time.perf_counter() - t0

        res = Result(label=f"Multi {actual_total}", total_conc=actual_total, wall_s=total_wall)

        for idx, (raw, ep_wall) in enumerate(batch_results):
            ep_name = ep_names[idx]
            ep_ok = sum(1 for r in raw if r["ok"])
            ep_total = len(raw)
            ep_ok_lat = sorted([r["ms"] for r in raw if r["ok"]])
            ep_fail_lat = sorted([r["ms"] for r in raw if not r["ok"]])

            res.ep_results[ep_name] = {
                "ok": ep_ok, "total": ep_total,
                "rate": ep_ok / ep_total * 100 if ep_total else 0,
                "p50_ok": _pct(ep_ok_lat, 50), "p90_ok": _pct(ep_ok_lat, 90),
            }

            for r in raw:
                res.total += 1
                if r["ok"]:
                    res.ok += 1
                    res.latencies.append(r["ms"])
                else:
                    res.fail_latencies.append(r["ms"])
                    e = r["err"] or "unknown"
                    res.errors[e] = res.errors.get(e, 0) + 1

        print(f"\n  Total: {res.ok}/{res.total} ({res.rate():.1f}%) em {total_wall:.1f}s — {res.rps():.0f} req/s")

        if res.errors:
            print(f"  Erros:", end="")
            for e, c in sorted(res.errors.items(), key=lambda x: -x[1]):
                print(f"  {e}={c}", end="")
            print()

        _print_latency_table("(multi)", res.latencies, res.fail_latencies)

        print(f"\n  Por endpoint (top 5 melhores / 5 piores):")
        sorted_eps = sorted(res.ep_results.items(), key=lambda x: -x[1]["rate"])
        show = sorted_eps[:5] + [("...", {})] + sorted_eps[-5:]
        for name, d in show:
            if name == "...":
                print(f"  {'...':>6s}")
                continue
            print(f"  {name:>6s}: {d['ok']:>4d}/{d['total']:>4d} ({d['rate']:5.1f}%) "
                  f"p50={d['p50_ok']:6.0f}ms p90={d['p90_ok']:6.0f}ms")

        results[total_conc] = res
        print(f"\n  Aguardando 5s...", flush=True)
        await asyncio.sleep(5)

    return results


# ── FASE 3: Comparação ─────────────────────────────────────────────────────

def phase3_compare(solo: Dict[int, Result], multi: Dict[int, Result], levels: List[int]):
    print(f"\n\n{'#'*90}")
    print(f"  FASE 3: COMPARAÇÃO FINAL — 1 EP vs 20 EPs")
    print(f"{'#'*90}")

    print(f"\n  {'Conc Total':>10s} | {'1 EP Rate':>10s} | {'20 EP Rate':>10s} | "
          f"{'Delta':>8s} | {'1 EP p50':>10s} | {'20 EP p50':>10s} | "
          f"{'1 EP p90':>10s} | {'20 EP p90':>10s} | "
          f"{'1 EP rps':>8s} | {'20 EP rps':>8s}")
    print(f"  {'-'*10}-+-{'-'*10}-+-{'-'*10}-+-"
          f"{'-'*8}-+-{'-'*10}-+-{'-'*10}-+-"
          f"{'-'*10}-+-{'-'*10}-+-"
          f"{'-'*8}-+-{'-'*8}")

    for conc in levels:
        s = solo.get(conc)
        m = multi.get(conc)
        if not s or not m:
            continue

        s_lat = sorted(s.latencies)
        m_lat = sorted(m.latencies)
        s_p50 = _pct(s_lat, 50)
        m_p50 = _pct(m_lat, 50)
        s_p90 = _pct(s_lat, 90)
        m_p90 = _pct(m_lat, 90)
        delta = m.rate() - s.rate()

        print(f"  {conc:>10d} | {s.rate():9.1f}% | {m.rate():9.1f}% | "
              f"{delta:+7.1f}% | {s_p50:9.0f}ms | {m_p50:9.0f}ms | "
              f"{s_p90:9.0f}ms | {m_p90:9.0f}ms | "
              f"{s.rps():7.0f}/s | {m.rps():7.0f}/s")

    print(f"\n  Tabela de erros:")
    print(f"  {'Conc Total':>10s} | {'1 EP erros':>30s} | {'20 EP erros':>30s}")
    print(f"  {'-'*10}-+-{'-'*30}-+-{'-'*30}")
    for conc in levels:
        s = solo.get(conc)
        m = multi.get(conc)
        if not s or not m:
            continue
        s_errs = ", ".join(f"{e}={c}" for e, c in sorted(s.errors.items(), key=lambda x: -x[1])[:3])
        m_errs = ", ".join(f"{e}={c}" for e, c in sorted(m.errors.items(), key=lambda x: -x[1])[:3])
        print(f"  {conc:>10d} | {s_errs:>30s} | {m_errs:>30s}")

    best_solo = max(solo.values(), key=lambda r: r.rate())
    best_multi = max(multi.values(), key=lambda r: r.rate())

    print(f"\n  ── CONCLUSÃO ──")
    for conc in levels:
        s = solo.get(conc)
        m = multi.get(conc)
        if not s or not m:
            continue
        delta = m.rate() - s.rate()
        if delta > 5:
            verdict = "20 EPs MUITO MELHOR"
        elif delta > 1:
            verdict = "20 EPs melhor"
        elif delta > -1:
            verdict = "~IGUAL"
        elif delta > -5:
            verdict = "1 EP melhor"
        else:
            verdict = "1 EP MUITO MELHOR"
        print(f"  {conc:>6d} conex: {verdict} (delta {delta:+.1f}%)")


async def main():
    levels = [3000, 5000, 7000, 10000]

    fd = _bump_fd(max(levels) * 3)
    print(f"  FD limit: {fd}")
    print(f"  Endpoints: {len(ALL_ENDPOINTS)}")
    print(f"  Host: {GATEWAY_HOST}:{GATEWAY_PORT}")
    print(f"  Timeout: {TIMEOUT_S}s")
    print(f"  Target URL: {TEST_URL}")
    print(f"  Cenários: {levels}")

    ok = await phase0_validate()
    if ok < 15:
        print(f"\n  ABORTANDO: muitos endpoints falharam ({ok}/{len(ALL_ENDPOINTS)})")
        sys.exit(1)

    await asyncio.sleep(3)
    solo = await phase1_solo(levels)
    await asyncio.sleep(10)
    multi = await phase2_multi(levels)
    phase3_compare(solo, multi, levels)

    print(f"\n\n{'='*90}")
    print(f"  STRESS TEST 1 vs 20 CONCLUÍDO")
    print(f"{'='*90}\n")


if __name__ == "__main__":
    asyncio.run(main())
