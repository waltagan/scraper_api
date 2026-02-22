"""
Stress test combinado — GLOBAL + US + AS + HK simultâneos.
Simula o comportamento real do scraper com load balancing.
800 conexões por gateway = 3200 total simultâneas.
"""
import asyncio, aiohttp, time, random

GATEWAYS = {
    "GLOBAL": "http://USER927913-zone-custom-region-BR:2dd94a@global.rotgb.711proxy.com:10000",
    "US": "http://USER927913-zone-custom-region-BR:2dd94a@us.rotgb.711proxy.com:10000",
    "AS": "http://USER927913-zone-custom-region-BR:2dd94a@as.rotgb.711proxy.com:10000",
    "HK": "http://USER927913-zone-custom-region-BR:2dd94a@hk.rotgb.711proxy.com:10000",
}

SITES = [
    "https://www.magazineluiza.com.br", "https://www.americanas.com.br",
    "https://www.casasbahia.com.br", "https://www.submarino.com.br",
    "https://www.mercadolivre.com.br", "https://www.extra.com.br",
    "https://www.kabum.com.br", "https://www.amazon.com.br",
    "https://www.dafiti.com.br", "https://www.netshoes.com.br",
    "https://www.centauro.com.br", "https://www.riachuelo.com.br",
    "https://www.renner.com.br", "https://www.cea.com.br",
    "https://www.havan.com.br", "https://www.leroymerlin.com.br",
    "https://www.madeiramadeira.com.br", "https://www.colombo.com.br",
    "https://www.pernambucanas.com.br", "https://www.marisa.com.br",
    "https://www.zattini.com.br", "https://www.girafa.com.br",
    "https://www.fastshop.com.br", "https://www.saraiva.com.br",
    "https://www.natura.com.br", "https://www.boticario.com.br",
    "https://www.avon.com.br", "https://www.samsung.com.br",
    "https://www.dell.com.br", "https://www.lenovo.com.br",
    "https://www.hp.com.br", "https://www.positivo.com.br",
    "https://www.multilaser.com.br", "https://www.intelbras.com",
    "https://www.weg.net", "https://www.totvs.com",
    "https://www.locaweb.com.br", "https://www.uol.com.br",
    "https://www.globo.com", "https://www.folha.uol.com.br",
    "https://www.estadao.com.br", "https://www.infomoney.com.br",
    "https://www.valor.com.br", "https://www.band.uol.com.br",
    "https://www.terra.com.br", "https://www.ig.com.br",
    "https://www.r7.com", "https://www.cnnbrasil.com.br",
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Connection": "keep-alive",
}
TIMEOUT = aiohttp.ClientTimeout(total=15, connect=10)
PER_GW = 800


def log(msg):
    print(msg, flush=True)


async def fetch(session, url, proxy):
    t0 = time.perf_counter()
    try:
        async with session.get(url, proxy=proxy, headers=HEADERS,
                               timeout=TIMEOUT, ssl=False, allow_redirects=True) as resp:
            await resp.read()
            lat = (time.perf_counter() - t0) * 1000
            if resp.status < 400:
                return True, lat, None
            return False, lat, f"http_{resp.status}"
    except asyncio.TimeoutError:
        return False, (time.perf_counter() - t0) * 1000, "timeout"
    except aiohttp.ClientOSError as e:
        return False, (time.perf_counter() - t0) * 1000, f"os_error:{e.errno}"
    except aiohttp.ClientConnectorError:
        return False, (time.perf_counter() - t0) * 1000, "connector_error"
    except Exception as e:
        return False, (time.perf_counter() - t0) * 1000, type(e).__name__


async def run_gw(gw_name, proxy_url, n, session):
    """Roda N requests em paralelo contra 1 gateway."""
    urls = (SITES * ((n // len(SITES)) + 1))[:n]
    random.shuffle(urls)
    sem = asyncio.Semaphore(n)
    errors = {}
    success = 0
    lats = []

    async def bf(url):
        async with sem:
            return await fetch(session, url, proxy_url)

    results = await asyncio.gather(*[bf(u) for u in urls], return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            e = type(r).__name__
            errors[e] = errors.get(e, 0) + 1
            continue
        ok, lat, err = r
        lats.append(lat)
        if ok:
            success += 1
        elif err:
            errors[err] = errors.get(err, 0) + 1

    return gw_name, n, success, lats, errors


async def main():
    total = PER_GW * len(GATEWAYS)
    log("=" * 80)
    log(f"TESTE COMBINADO — {len(GATEWAYS)} GWs x {PER_GW} = {total} requests simultâneas")
    log(f"Gateways: {', '.join(GATEWAYS.keys())}")
    log("=" * 80)

    conn = aiohttp.TCPConnector(limit=total, limit_per_host=200, force_close=True)

    t_start = time.perf_counter()
    async with aiohttp.ClientSession(connector=conn) as session:
        tasks = [
            run_gw(name, proxy, PER_GW, session)
            for name, proxy in GATEWAYS.items()
        ]
        results = await asyncio.gather(*tasks)
    t_total = time.perf_counter() - t_start

    log(f"\nTempo total: {t_total:.1f}s")
    log("")

    grand_success = 0
    grand_total = 0
    grand_lats = []
    grand_errors = {}

    log(f"{'Gateway':<10} {'Total':<6} {'OK':<6} {'Fail':<6} {'Success%':<10} "
        f"{'p50ms':<8} {'p90ms':<8} {'p99ms':<8} {'Erros Top'}")
    log("-" * 100)

    for gw_name, n, success, lats, errors in results:
        lats.sort()
        fail = n - success
        pct = success / n * 100
        p50 = lats[len(lats) // 2] if lats else 0
        p90 = lats[int(len(lats) * 0.9)] if lats else 0
        p99 = lats[int(len(lats) * 0.99)] if lats else 0

        top_errs = ""
        if errors:
            top = sorted(errors.items(), key=lambda x: -x[1])[:3]
            top_errs = ", ".join(f"{k}:{v}" for k, v in top)

        log(f"{gw_name:<10} {n:<6} {success:<6} {fail:<6} {pct:<10.1f} "
            f"{p50:<8.0f} {p90:<8.0f} {p99:<8.0f} {top_errs}")

        grand_success += success
        grand_total += n
        grand_lats.extend(lats)
        for k, v in errors.items():
            grand_errors[k] = grand_errors.get(k, 0) + v

    grand_lats.sort()
    grand_pct = grand_success / grand_total * 100
    gp50 = grand_lats[len(grand_lats) // 2] if grand_lats else 0
    gp90 = grand_lats[int(len(grand_lats) * 0.9)] if grand_lats else 0
    gp99 = grand_lats[int(len(grand_lats) * 0.99)] if grand_lats else 0

    log("-" * 100)
    top_errs_all = ""
    if grand_errors:
        top = sorted(grand_errors.items(), key=lambda x: -x[1])[:4]
        top_errs_all = ", ".join(f"{k}:{v}" for k, v in top)
    log(f"{'TOTAL':<10} {grand_total:<6} {grand_success:<6} {grand_total - grand_success:<6} "
        f"{grand_pct:<10.1f} {gp50:<8.0f} {gp90:<8.0f} {gp99:<8.0f} {top_errs_all}")

    waf = grand_errors.get("http_403", 0)
    effective = grand_total - waf
    effective_pct = grand_success / effective * 100 if effective > 0 else 0
    log(f"\n  Sucesso excluindo WAF (http_403={waf}): {grand_success}/{effective} = {effective_pct:.1f}%")
    log(f"  RPS total: {grand_total / t_total:.1f}")
    log(f"  Throughput: {grand_success / t_total:.1f} requests OK/s = {grand_success / t_total * 60:.0f}/min")


if __name__ == "__main__":
    asyncio.run(main())
