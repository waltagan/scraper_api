"""Stress test EU gateway — Sites BR Reais (somente texto)."""
import asyncio, aiohttp, time

PROXY_EU = "http://USER927913-zone-custom-region-BR:2dd94a@eu.rotgb.711proxy.com:10000"

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


def log(msg):
    print(msg, flush=True)


async def fetch(session, url):
    t0 = time.perf_counter()
    try:
        async with session.get(url, proxy=PROXY_EU, headers=HEADERS,
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


async def run_test(conc):
    urls = (SITES * ((conc // len(SITES)) + 1))[:conc]
    sem = asyncio.Semaphore(conc)
    conn = aiohttp.TCPConnector(limit=conc, limit_per_host=50, force_close=True)
    errors = {}
    success = 0
    lats = []

    async def bf(url):
        async with sem:
            return await fetch(session, url)

    t0 = time.perf_counter()
    async with aiohttp.ClientSession(connector=conn) as session:
        results = await asyncio.gather(*[bf(u) for u in urls], return_exceptions=True)
    dur = time.perf_counter() - t0

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

    lats.sort()
    n = len(urls)
    ok_pct = success / n * 100
    log(f"EU | conc={conc:>4} | {success}/{n} ({ok_pct:.1f}%) | {dur:.1f}s | RPS={n/dur:.1f}")
    if lats:
        log(f"  p50={lats[len(lats)//2]:.0f}ms  p90={lats[int(len(lats)*0.9)]:.0f}ms  "
            f"p99={lats[int(len(lats)*0.99)]:.0f}ms  max={lats[-1]:.0f}ms")
    if errors:
        top = sorted(errors.items(), key=lambda x: -x[1])
        parts = ", ".join(f"{k}:{v}" for k, v in top)
        log(f"  Erros: {parts}")


async def main():
    log("=" * 70)
    log("STRESS TEST EU GATEWAY — Sites BR Reais (somente texto)")
    log("=" * 70)

    log("\nValidação (1 request)...")
    await run_test(1)
    log("")

    for c in [50, 200, 500, 800]:
        await run_test(c)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
