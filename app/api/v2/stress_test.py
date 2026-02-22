"""
Endpoint de stress test — roda no Railway para comparar com teste local.
GET direto em sites reais via proxy, sem pipeline (sem probe, sem subpages).
"""
import asyncio
import logging
import os
import time
import statistics
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter()

PROXY = os.getenv("PROXY_GATEWAY_URL", "")
TIMEOUT = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


class StressTestRequest(BaseModel):
    concurrent: int = 2000
    limit: int = 2000


def _percentiles(vals):
    if not vals:
        return {}
    s = sorted(vals)
    n = len(s)
    return {
        "min": round(s[0], 1),
        "p50": round(s[n // 2], 1),
        "p75": round(s[int(n * 0.75)], 1),
        "p90": round(s[int(n * 0.9)], 1),
        "p95": round(s[min(int(n * 0.95), n - 1)], 1),
        "p99": round(s[min(int(n * 0.99), n - 1)], 1),
        "max": round(s[-1], 1),
        "avg": round(statistics.mean(vals), 1),
    }


async def _fetch_urls_from_db(limit: int) -> list:
    from app.core.database import get_pool
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT website_url FROM busca_fornecedor.website_discovery
        WHERE discovery_status IN ('muito_alto','alto','medio')
        AND website_url IS NOT NULL AND website_url != ''
        ORDER BY website_url
        LIMIT $1
        """,
        limit,
    )
    urls = []
    for r in rows:
        url = r["website_url"]
        if not url.startswith("http"):
            url = f"https://{url}"
        urls.append(url)
    return urls


async def _fetch_one(session, url: str) -> dict:
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
        return {"ok": ok, "status": status, "lat_ms": lat,
                "content_bytes": content_len, "error": error}
    except Exception as e:
        lat = (time.perf_counter() - t0) * 1000
        err_msg = str(e)[:80].lower()
        cat = ("timeout" if "timeout" in err_msg or "timed out" in err_msg
               else "connection" if "connect" in err_msg or "refused" in err_msg
               else "ssl" if "ssl" in err_msg
               else "other")
        return {"ok": False, "status": 0, "lat_ms": lat,
                "content_bytes": 0, "error": f"{cat}:{type(e).__name__}"}


@router.post("/scrape/stress-test")
async def run_stress_test(req: StressTestRequest):
    """Stress test: GET direto em N sites reais, sem pipeline."""
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        raise HTTPException(500, "curl_cffi não disponível")

    logger.info(f"[stress-test] Buscando {req.limit} URLs do banco...")
    urls = await _fetch_urls_from_db(req.limit)
    if len(urls) < 10:
        raise HTTPException(400, f"Apenas {len(urls)} URLs no banco")

    urls = urls[:req.limit]
    concurrent = min(req.concurrent, len(urls))

    logger.info(f"[stress-test] Iniciando: {len(urls)} URLs, {concurrent} concurrent")

    session = AsyncSession(impersonate="chrome131", verify=False,
                           max_clients=concurrent + 100)
    sem = asyncio.Semaphore(concurrent)
    counter = {"done": 0, "ok": 0}
    total = len(urls)
    t_start = time.perf_counter()

    async def limited_fetch(url):
        async with sem:
            r = await _fetch_one(session, url)
            counter["done"] += 1
            if r["ok"]:
                counter["ok"] += 1
            done = counter["done"]
            if done % 200 == 0 or done == total:
                elapsed = time.perf_counter() - t_start
                rate = counter["ok"] / done * 100 if done else 0
                logger.info(f"[stress-test] {done}/{total} | ok={rate:.1f}% | {elapsed:.1f}s")
            return r

    tasks = [limited_fetch(u) for u in urls]
    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - t_start

    await session.close()

    successes = [r for r in results if r["ok"]]
    failures = [r for r in results if not r["ok"]]
    ok_lats = [r["lat_ms"] for r in successes]
    fail_lats = [r["lat_ms"] for r in failures]
    all_lats = [r["lat_ms"] for r in results]

    error_cats: dict = {}
    for r in failures:
        err = r.get("error") or "unknown"
        cat = err.split(":")[0] if ":" in err else err
        error_cats[cat] = error_cats.get(cat, 0) + 1

    status_codes: dict = {}
    for r in results:
        sc = str(r["status"])
        status_codes[sc] = status_codes.get(sc, 0) + 1

    rps = len(results) / total_time if total_time > 0 else 0

    return {
        "total_urls": len(urls),
        "concurrent": concurrent,
        "total_time_s": round(total_time, 1),
        "success": len(successes),
        "failed": len(failures),
        "success_rate_pct": round(len(successes) / len(results) * 100, 1),
        "requests_per_second": round(rps, 1),
        "companies_per_minute": round(rps * 60, 1),
        "latency_all_ms": _percentiles(all_lats),
        "latency_success_ms": _percentiles(ok_lats),
        "latency_fail_ms": _percentiles(fail_lats),
        "status_codes": dict(sorted(status_codes.items(), key=lambda x: -x[1])),
        "error_categories": dict(sorted(error_cats.items(), key=lambda x: -x[1])),
    }
