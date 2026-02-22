"""
Stress test isolado por gateway — testa US, AS e INA contra sites BR reais.
Objetivo: identificar qual gateway causa erros proxy:connection.
Somente texto (Accept: text/html), sem imagens.
"""

import asyncio
import aiohttp
import time
import statistics
import json
import sys
from dataclasses import dataclass, field
from typing import List, Dict


def log(msg: str):
    print(msg, flush=True)

PROXY_BASE = "http://USER927913-zone-custom-region-BR:2dd94a@{region}.rotgb.711proxy.com:10000"

GATEWAYS = {
    "US": PROXY_BASE.format(region="us"),
    "AS": PROXY_BASE.format(region="as"),
    "INA": PROXY_BASE.format(region="ina"),
}

BRAZILIAN_SITES = [
    "https://www.magazineluiza.com.br",
    "https://www.americanas.com.br",
    "https://www.casasbahia.com.br",
    "https://www.submarino.com.br",
    "https://www.mercadolivre.com.br",
    "https://www.extra.com.br",
    "https://www.pontofrio.com.br",
    "https://www.shoptime.com.br",
    "https://www.kabum.com.br",
    "https://www.amazon.com.br",
    "https://www.dafiti.com.br",
    "https://www.netshoes.com.br",
    "https://www.centauro.com.br",
    "https://www.riachuelo.com.br",
    "https://www.renner.com.br",
    "https://www.cea.com.br",
    "https://www.havan.com.br",
    "https://www.leroymerlin.com.br",
    "https://www.madeiramadeira.com.br",
    "https://www.colombo.com.br",
    "https://www.pernambucanas.com.br",
    "https://www.marisa.com.br",
    "https://www.zattini.com.br",
    "https://www.girafa.com.br",
    "https://www.fastshop.com.br",
    "https://www.saraiva.com.br",
    "https://www.natura.com.br",
    "https://www.boticario.com.br",
    "https://www.avon.com.br",
    "https://www.samsung.com.br",
    "https://www.dell.com.br",
    "https://www.lenovo.com.br",
    "https://www.hp.com.br",
    "https://www.positivo.com.br",
    "https://www.multilaser.com.br",
    "https://www.intelbras.com",
    "https://www.weg.net",
    "https://www.totvs.com",
    "https://www.locaweb.com.br",
    "https://www.uol.com.br",
    "https://www.globo.com",
    "https://www.folha.uol.com.br",
    "https://www.estadao.com.br",
    "https://www.infomoney.com.br",
    "https://www.valor.com.br",
    "https://www.band.uol.com.br",
    "https://www.terra.com.br",
    "https://www.ig.com.br",
    "https://www.r7.com",
    "https://www.cnnbrasil.com.br",
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Connection": "keep-alive",
}

TIMEOUT = aiohttp.ClientTimeout(total=15, connect=10)
CONCURRENCY_LEVELS = [50, 200, 500, 800]


@dataclass
class TestResult:
    gateway: str
    concurrency: int
    total: int = 0
    success: int = 0
    errors: Dict[str, int] = field(default_factory=dict)
    latencies: List[float] = field(default_factory=list)
    duration_s: float = 0
    content_sizes: List[int] = field(default_factory=list)


async def fetch_one(session: aiohttp.ClientSession, url: str, proxy: str) -> tuple:
    """Faz request e retorna (success, latency_ms, error_type, content_len)."""
    t0 = time.perf_counter()
    try:
        async with session.get(url, proxy=proxy, headers=HEADERS, timeout=TIMEOUT,
                               ssl=False, allow_redirects=True) as resp:
            body = await resp.read()
            lat = (time.perf_counter() - t0) * 1000
            if resp.status < 400:
                return True, lat, None, len(body)
            return False, lat, f"http_{resp.status}", 0
    except asyncio.TimeoutError:
        lat = (time.perf_counter() - t0) * 1000
        return False, lat, "timeout", 0
    except aiohttp.ClientOSError as e:
        lat = (time.perf_counter() - t0) * 1000
        return False, lat, f"os_error:{e.errno}", 0
    except aiohttp.ClientConnectorError:
        lat = (time.perf_counter() - t0) * 1000
        return False, lat, "connector_error", 0
    except Exception as e:
        lat = (time.perf_counter() - t0) * 1000
        return False, lat, type(e).__name__, 0


async def run_test(gw_name: str, proxy_url: str, concurrency: int) -> TestResult:
    """Testa um gateway com N requests concorrentes contra sites BR reais."""
    result = TestResult(gateway=gw_name, concurrency=concurrency)

    urls = []
    while len(urls) < concurrency:
        urls.extend(BRAZILIAN_SITES)
    urls = urls[:concurrency]
    result.total = len(urls)

    sem = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=50, force_close=True)

    async def bounded_fetch(url):
        async with sem:
            return await fetch_one(session, url, proxy_url)

    t_start = time.perf_counter()
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [bounded_fetch(u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    result.duration_s = time.perf_counter() - t_start

    for r in results:
        if isinstance(r, Exception):
            err = type(r).__name__
            result.errors[err] = result.errors.get(err, 0) + 1
            continue
        ok, lat, err_type, content_len = r
        result.latencies.append(lat)
        if ok:
            result.success += 1
            result.content_sizes.append(content_len)
        else:
            result.errors[err_type] = result.errors.get(err_type, 0) + 1

    return result


def print_result(r: TestResult):
    ok_pct = r.success / r.total * 100 if r.total > 0 else 0
    fail = r.total - r.success
    lats = sorted(r.latencies) if r.latencies else [0]

    log(f"\n{'='*70}")
    log(f"  {r.gateway} | concorrência={r.concurrency} | {r.total} requests")
    log(f"{'='*70}")
    log(f"  Sucesso: {r.success}/{r.total} ({ok_pct:.1f}%)")
    log(f"  Falhas:  {fail}")
    log(f"  Tempo:   {r.duration_s:.1f}s")
    log(f"  RPS:     {r.total / r.duration_s:.1f}")

    if lats:
        log(f"  Latência (ms):")
        log(f"    p50={lats[len(lats)//2]:.0f}  p90={lats[int(len(lats)*0.9)]:.0f}  "
            f"p99={lats[int(len(lats)*0.99)]:.0f}  max={lats[-1]:.0f}")

    if r.content_sizes:
        avg_size = sum(r.content_sizes) / len(r.content_sizes) / 1024
        log(f"  Tamanho médio: {avg_size:.1f} KB")

    if r.errors:
        log(f"  Erros:")
        for err, count in sorted(r.errors.items(), key=lambda x: -x[1]):
            log(f"    {err}: {count}")


async def main():
    log("=" * 70)
    log("STRESS TEST ISOLADO POR GATEWAY — Sites BR Reais (somente texto)")
    log("=" * 70)

    all_results = []

    # Fase 1: Teste unitário — 1 request por gateway para validar
    log("\n--- FASE 1: Validação (1 request por gateway) ---")
    for gw_name, proxy_url in GATEWAYS.items():
        r = await run_test(gw_name, proxy_url, 1)
        status = "OK" if r.success > 0 else "FALHOU"
        lat = r.latencies[0] if r.latencies else 0
        log(f"  {gw_name}: {status} (latência={lat:.0f}ms)")

    # Fase 2: Teste isolado por gateway em cada nível de concorrência
    log("\n--- FASE 2: Teste isolado por gateway ---")
    for conc in CONCURRENCY_LEVELS:
        log(f"\n{'#'*70}")
        log(f"  CONCORRÊNCIA: {conc}")
        log(f"{'#'*70}")

        for gw_name, proxy_url in GATEWAYS.items():
            log(f"\n  Testando {gw_name} @ {conc} conexões...")
            r = await run_test(gw_name, proxy_url, conc)
            print_result(r)
            all_results.append({
                "gateway": r.gateway,
                "concurrency": r.concurrency,
                "total": r.total,
                "success": r.success,
                "success_pct": round(r.success / r.total * 100, 1),
                "duration_s": round(r.duration_s, 1),
                "rps": round(r.total / r.duration_s, 1),
                "p50_ms": round(sorted(r.latencies)[len(r.latencies)//2]) if r.latencies else 0,
                "p90_ms": round(sorted(r.latencies)[int(len(r.latencies)*0.9)]) if r.latencies else 0,
                "p99_ms": round(sorted(r.latencies)[int(len(r.latencies)*0.99)]) if r.latencies else 0,
                "errors": r.errors,
            })
            await asyncio.sleep(2)

    # Resumo comparativo
    log("\n\n" + "=" * 90)
    log("RESUMO COMPARATIVO")
    log("=" * 90)
    log(f"{'Gateway':<8} {'Conc':<6} {'Success%':<10} {'RPS':<8} {'p50ms':<8} {'p90ms':<8} {'p99ms':<8} {'Erros Top'}")
    log("-" * 90)
    for r in all_results:
        top_err = ""
        if r["errors"]:
            top = sorted(r["errors"].items(), key=lambda x: -x[1])[:2]
            top_err = ", ".join(f"{k}:{v}" for k, v in top)
        log(f"{r['gateway']:<8} {r['concurrency']:<6} {r['success_pct']:<10} {r['rps']:<8} "
            f"{r['p50_ms']:<8} {r['p90_ms']:<8} {r['p99_ms']:<8} {top_err}")

    with open("stress_test_gw_isolado_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    log("\nResultados salvos em stress_test_gw_isolado_results.json")


if __name__ == "__main__":
    asyncio.run(main())
