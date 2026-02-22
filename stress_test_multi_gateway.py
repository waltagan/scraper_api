#!/usr/bin/env python3
"""
Stress test — Multi-Gateway 711Proxy.

Testa se múltiplos endpoints (usernames diferentes) têm comportamento
independente no gateway, ou se compartilham o mesmo gargalo.

Fases:
  1) Cada endpoint sozinho com C conexões simultâneas
  2) Todos endpoints juntos, cada um com C conexões (N*C total)
  3) Compara resultados para detectar interferência
"""

import asyncio
import os
import resource
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from urllib.parse import quote

import aiohttp

GATEWAY_HOST = "us.rotgb.711proxy.com"
GATEWAY_PORT = 10000

ENDPOINTS = {
    "EP1_BR": "teste1-zone-custom-region-BR:teste1",
    "EP2_SP": "teste2-zone-custom-region-BR-st-SaoPaulo:teste2",
    "EP3_MG": "teste3-zone-custom-region-BR-st-Minasgerais:teste3",
    "EP4_SP2": "teste4-zone-custom-region-BR-st-Saopaulo:teste4",
}

TEST_URL = "http://httpbin.org/get"
TIMEOUT_S = 30


def _build_proxy_url(credentials: str) -> str:
    user, pwd = credentials.split(":")
    return f"http://{quote(user, safe='')}:{quote(pwd, safe='')}@{GATEWAY_HOST}:{GATEWAY_PORT}"


def _bump_fd_limit(target: int = 30000) -> int:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    new_soft = min(target, hard)
    if soft < new_soft:
        resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
    return resource.getrlimit(resource.RLIMIT_NOFILE)[0]


def _percentile(sorted_vals: List[float], p: int) -> float:
    if not sorted_vals:
        return 0
    idx = min(int(len(sorted_vals) * p / 100), len(sorted_vals) - 1)
    return sorted_vals[idx]


@dataclass
class EndpointResult:
    name: str
    concurrency: int
    total: int = 0
    ok: int = 0
    fail: int = 0
    latencies_ms: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0
    rps: float = 0

    def success_rate(self) -> float:
        return (self.ok / self.total * 100) if self.total else 0

    def summary_line(self) -> str:
        lat = sorted(self.latencies_ms)
        p50 = _percentile(lat, 50)
        p90 = _percentile(lat, 90)
        p99 = _percentile(lat, 99)
        return (
            f"  {self.name:>10s} | C={self.concurrency:>4d} | "
            f"{self.ok}/{self.total} ok ({self.success_rate():5.1f}%) | "
            f"p50={p50:7.0f}ms p90={p90:7.0f}ms p99={p99:7.0f}ms | "
            f"{self.rps:.1f} req/s | {self.elapsed_s:.1f}s"
        )


async def _single_request(
    session: aiohttp.ClientSession, url: str, proxy: str
) -> dict:
    start = time.perf_counter()
    try:
        async with session.get(
            url,
            allow_redirects=True,
            proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
        ) as resp:
            await resp.read()
            ms = (time.perf_counter() - start) * 1000
            return {"ok": resp.status < 400, "ms": ms, "error": None}
    except asyncio.TimeoutError:
        return {"ok": False, "ms": (time.perf_counter() - start) * 1000, "error": "timeout"}
    except aiohttp.ClientError as e:
        return {"ok": False, "ms": (time.perf_counter() - start) * 1000, "error": type(e).__name__}
    except Exception as e:
        return {"ok": False, "ms": (time.perf_counter() - start) * 1000, "error": str(e)[:40]}


async def run_endpoint_test(
    name: str, proxy_url: str, concurrency: int
) -> EndpointResult:
    connector = aiohttp.TCPConnector(
        limit=0, limit_per_host=0, force_close=True,
        enable_cleanup_closed=True, ssl=False,
    )
    async with aiohttp.ClientSession(connector=connector, trust_env=False) as session:
        start = time.perf_counter()
        tasks = [_single_request(session, TEST_URL, proxy_url) for _ in range(concurrency)]
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

    res = EndpointResult(name=name, concurrency=concurrency, elapsed_s=elapsed)
    for r in results:
        res.total += 1
        if r["ok"]:
            res.ok += 1
            res.latencies_ms.append(r["ms"])
        else:
            res.fail += 1
            err = r["error"] or "unknown"
            res.errors[err] = res.errors.get(err, 0) + 1
    res.rps = res.total / elapsed if elapsed > 0 else 0
    return res


async def phase_individual(concurrency: int) -> Dict[str, EndpointResult]:
    """Testa cada endpoint SOZINHO, sequencialmente."""
    print(f"\n{'='*80}")
    print(f"  FASE 1: Cada endpoint SOZINHO — {concurrency} conexões simultâneas")
    print(f"{'='*80}")

    results = {}
    for name, creds in ENDPOINTS.items():
        proxy_url = _build_proxy_url(creds)
        print(f"\n  Testando {name}...", flush=True)
        res = await run_endpoint_test(name, proxy_url, concurrency)
        results[name] = res
        print(res.summary_line())
        if res.errors:
            for err, cnt in sorted(res.errors.items(), key=lambda x: -x[1]):
                print(f"    erro: {err} = {cnt}")
        await asyncio.sleep(2)
    return results


async def phase_combined(concurrency_per_ep: int) -> Dict[str, EndpointResult]:
    """Testa TODOS endpoints ao mesmo tempo, cada um com C conexões."""
    total = concurrency_per_ep * len(ENDPOINTS)
    print(f"\n{'='*80}")
    print(f"  FASE 2: TODOS juntos — {concurrency_per_ep}/endpoint × {len(ENDPOINTS)} = {total} total")
    print(f"{'='*80}")

    tasks = []
    for name, creds in ENDPOINTS.items():
        proxy_url = _build_proxy_url(creds)
        tasks.append(run_endpoint_test(name, proxy_url, concurrency_per_ep))

    results_list = await asyncio.gather(*tasks)
    results = {}
    for res in results_list:
        results[res.name] = res
        print(res.summary_line())
        if res.errors:
            for err, cnt in sorted(res.errors.items(), key=lambda x: -x[1]):
                print(f"    erro: {err} = {cnt}")
    return results


def compare_results(
    individual: Dict[str, EndpointResult],
    combined: Dict[str, EndpointResult],
):
    print(f"\n{'='*80}")
    print(f"  COMPARAÇÃO: Individual vs Combinado")
    print(f"{'='*80}")
    print(f"\n  {'Endpoint':>10s} | {'Solo %':>8s} | {'Combo %':>8s} | {'Delta':>8s} | Veredicto")
    print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*20}")

    degradations = []
    for name in ENDPOINTS:
        solo = individual[name].success_rate()
        combo = combined[name].success_rate()
        delta = combo - solo
        if delta < -10:
            verdict = "DEGRADOU"
        elif delta < -3:
            verdict = "Leve queda"
        else:
            verdict = "OK"
        degradations.append(delta)
        print(f"  {name:>10s} | {solo:7.1f}% | {combo:7.1f}% | {delta:+7.1f}% | {verdict}")

    avg_delta = sum(degradations) / len(degradations)
    solo_total_ok = sum(r.ok for r in individual.values())
    solo_total = sum(r.total for r in individual.values())
    combo_total_ok = sum(r.ok for r in combined.values())
    combo_total = sum(r.total for r in combined.values())

    print(f"\n  Totais: Solo {solo_total_ok}/{solo_total} ({solo_total_ok/solo_total*100:.1f}%) "
          f"vs Combo {combo_total_ok}/{combo_total} ({combo_total_ok/combo_total*100:.1f}%)")
    print(f"  Delta médio: {avg_delta:+.1f}%")

    if avg_delta > -3:
        print(f"\n  CONCLUSÃO: Endpoints são INDEPENDENTES! Podemos distribuir carga.")
    elif avg_delta > -10:
        print(f"\n  CONCLUSÃO: Interferência LEVE. Distribuir carga ainda ajuda.")
    else:
        print(f"\n  CONCLUSÃO: Endpoints COMPARTILHAM gargalo. Distribuir não ajuda muito.")


async def main():
    levels = [200, 500, 800]

    fd = _bump_fd_limit(max(levels) * len(ENDPOINTS) * 3)
    print(f"  FD limit: {fd}")
    print(f"  Endpoints: {list(ENDPOINTS.keys())}")
    print(f"  Níveis de concorrência: {levels}")

    for conc in levels:
        print(f"\n\n{'#'*80}")
        print(f"  RODADA: {conc} conexões por endpoint")
        print(f"{'#'*80}")

        individual = await phase_individual(conc)
        await asyncio.sleep(5)
        combined = await phase_combined(conc)
        compare_results(individual, combined)
        await asyncio.sleep(5)

    print(f"\n\n{'='*80}")
    print(f"  STRESS TEST MULTI-GATEWAY CONCLUÍDO")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
