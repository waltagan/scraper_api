"""Teste rapido concorrente: 50 requests simultaneos em cada proxy separadamente."""
import asyncio
import time
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

URLS = [
    "https://www.magazineluiza.com.br", "https://www.natura.com.br",
    "https://www.localiza.com", "https://www.totvs.com",
    "https://www.ambev.com.br", "https://www.braskem.com.br",
    "https://www.votorantim.com.br", "https://www.embraer.com.br",
    "https://www.weg.net", "https://www.gerdau.com",
    "https://www.itau.com.br", "https://www.bradesco.com.br",
    "https://www.petrobras.com.br", "https://www.vale.com",
    "https://www.suzano.com.br", "https://www.marfrig.com.br",
    "https://www.jbs.com.br", "https://www.brf-global.com",
    "https://www.csn.com.br", "https://www.usiminas.com",
    "https://www.cvc.com.br", "https://www.raia.com.br",
    "https://www.hapvida.com.br", "https://www.fleury.com.br",
    "https://www.dasa.com.br", "https://www.grupo-multi.com.br",
    "https://www.raizen.com.br", "https://www.cosan.com.br",
    "https://www.engie.com.br", "https://www.cpfl.com.br",
    "https://www.energisa.com.br", "https://www.equatorial.com.br",
    "https://www.neoenergia.com", "https://www.cemig.com.br",
    "https://www.copel.com", "https://www.taesa.com.br",
    "https://www.ccr.com.br", "https://www.ecorodovias.com.br",
    "https://www.rumo.com.br", "https://www.santos.com.br",
    "https://www.azul.com.br", "https://www.voegol.com.br",
    "https://www.movida.com.br", "https://www.unidas.com.br",
    "https://www.viavarejo.com.br", "https://www.americanas.com.br",
    "https://www.b2w.io", "https://www.casasbahia.com.br",
    "https://www.pontofrio.com.br", "https://www.shoptime.com.br",
]

TIMEOUT = 40
CONCURRENT = 50


async def fetch_one(session, url, proxy, timeout):
    t0 = time.perf_counter()
    try:
        resp = await session.get(url, proxy=proxy, timeout=timeout, allow_redirects=True, max_redirects=5)
        elapsed = (time.perf_counter() - t0) * 1000
        if resp.status_code == 200 and len(resp.content) > 100:
            return {"ok": True, "ms": elapsed}
        return {"ok": False, "ms": elapsed, "err": f"status_{resp.status_code}"}
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        err = str(e)[:60]
        return {"ok": False, "ms": elapsed, "err": err}


async def test_proxy_batch(label, proxy_url, urls, concurrent):
    from curl_cffi.requests import AsyncSession

    sem = asyncio.Semaphore(concurrent)
    session = AsyncSession(impersonate="chrome131", verify=False, max_clients=500)

    async def bounded(url):
        async with sem:
            return await fetch_one(session, url, proxy_url, TIMEOUT)

    print(f"\n{'='*60}")
    print(f"  {label} — {len(urls)} URLs, {concurrent} concorrentes, timeout {TIMEOUT}s")
    print(f"  Proxy: {proxy_url[:60]}...")
    print(f"{'='*60}")

    t_start = time.perf_counter()
    tasks = [bounded(u) for u in urls]
    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - t_start

    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    all_ms = sorted([r["ms"] for r in results])
    ok_ms = sorted([r["ms"] for r in ok]) if ok else [0]

    print(f"\n  Resultado: {len(ok)}/{len(results)} OK ({len(ok)/len(results)*100:.0f}%)")
    print(f"  Tempo total: {total_time:.1f}s")
    print(f"  Latencia (todos): p50={all_ms[len(all_ms)//2]:.0f}ms  p90={all_ms[int(len(all_ms)*0.9)]:.0f}ms  max={all_ms[-1]:.0f}ms")
    if ok_ms and ok_ms[0] > 0:
        print(f"  Latencia (OK):    p50={ok_ms[len(ok_ms)//2]:.0f}ms  p90={ok_ms[int(len(ok_ms)*0.9)]:.0f}ms  max={ok_ms[-1]:.0f}ms")

    if fail:
        err_counts = {}
        for r in fail:
            e = r["err"][:40]
            err_counts[e] = err_counts.get(e, 0) + 1
        print(f"  Erros ({len(fail)}):")
        for e, c in sorted(err_counts.items(), key=lambda x: -x[1]):
            print(f"    {e}: {c}")

    await session.close()
    return {"ok": len(ok), "fail": len(fail), "total_time": total_time}


async def main():
    from app.services.scraper_manager.proxy_manager import proxy_pool
    await proxy_pool.preload()

    p711 = proxy_pool._next_711()
    pdecodo = proxy_pool._next_decodo()

    r711 = await test_proxy_batch("711PROXY", p711, URLS, CONCURRENT)
    rdecodo = await test_proxy_batch("DECODO", pdecodo, URLS, CONCURRENT)

    print(f"\n{'='*60}")
    print(f"  COMPARATIVO")
    print(f"{'='*60}")
    print(f"  711:    {r711['ok']}/{r711['ok']+r711['fail']} OK em {r711['total_time']:.1f}s")
    print(f"  Decodo: {rdecodo['ok']}/{rdecodo['ok']+rdecodo['fail']} OK em {rdecodo['total_time']:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
