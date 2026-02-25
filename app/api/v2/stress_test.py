"""
Endpoint de stress test — roda no Railway para comparar com teste local.
GET direto em sites reais via proxy, sem pipeline (sem probe, sem subpages).
"""
import asyncio
import logging
import os
import random
import time
import statistics
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)
router = APIRouter()

PROXY = os.getenv("PROXY_GATEWAY_URL", "")
TIMEOUT = 12
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

_AB_SAMPLES: Dict[str, List[str]] = {}
_AB_SAMPLE_META: Dict[str, Dict[str, Any]] = {}


class StressTestRequest(BaseModel):
    concurrent: int = 2000
    limit: int = 2000


class ABPrepareRequest(BaseModel):
    limit: int = Field(3200, ge=100, le=10000)
    seed: int = Field(42, ge=0, le=999999999)


class ABRunRequest(BaseModel):
    sample_id: str
    concurrent: int = Field(3200, ge=1, le=20000)
    timeout_seconds: int = Field(40, ge=5, le=120)


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
        SELECT website_url FROM busca_fornecedor.website_discovery
        WHERE discovery_status IN ('muito_alto','alto','medio')
        AND website_url IS NOT NULL AND website_url != ''
        LIMIT $1
        """,
        limit,
        timeout=60,
    )
    seen = set()
    urls = []
    for r in rows:
        url = r["website_url"]
        if url in seen:
            continue
        seen.add(url)
        if not url.startswith("http"):
            url = f"https://{url}"
        urls.append(url)
    return urls


async def _prepare_ab_sample(limit: int, seed: int) -> Dict[str, Any]:
    urls = await _fetch_urls_from_db(limit)
    if len(urls) < 10:
        raise HTTPException(400, f"Apenas {len(urls)} URLs no banco")

    rng = random.Random(seed)
    rng.shuffle(urls)
    sample = urls[:limit]
    sample_id = f"ab_{int(time.time())}_{seed}_{len(sample)}"
    _AB_SAMPLES[sample_id] = sample
    _AB_SAMPLE_META[sample_id] = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": seed,
        "count": len(sample),
    }
    return {"sample_id": sample_id, "count": len(sample), "seed": seed}


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


def _classify_probe_exception(err: Exception) -> str:
    msg = str(err).lower()
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "connect" in msg or "refused" in msg:
        return "connection"
    if "ssl" in msg:
        return "ssl"
    if "dns" in msg or "resolve" in msg:
        return "dns"
    return "other"


def _build_test_summary(results: List[Dict[str, Any]], total_time: float, test_type: str) -> Dict[str, Any]:
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
        sc = str(r.get("status", 0))
        status_codes[sc] = status_codes.get(sc, 0) + 1

    rps = len(results) / total_time if total_time > 0 else 0
    return {
        "test_type": test_type,
        "total_urls": len(results),
        "total_time_s": round(total_time, 1),
        "success": len(successes),
        "failed": len(failures),
        "success_rate_pct": round(len(successes) / len(results) * 100, 1) if results else 0,
        "requests_per_second": round(rps, 1),
        "companies_per_minute": round(rps * 60, 1),
        "latency_all_ms": _percentiles(all_lats),
        "latency_success_ms": _percentiles(ok_lats),
        "latency_fail_ms": _percentiles(fail_lats),
        "status_codes": dict(sorted(status_codes.items(), key=lambda x: -x[1])),
        "error_categories": dict(sorted(error_cats.items(), key=lambda x: -x[1])),
    }


async def _run_stress_direct(urls: List[str], concurrent: int, timeout_seconds: int) -> Dict[str, Any]:
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        raise HTTPException(500, "curl_cffi não disponível")

    concurrent = min(concurrent, len(urls))
    session = AsyncSession(impersonate="chrome131", verify=False, max_clients=concurrent + 100)
    sem = asyncio.Semaphore(concurrent)
    counter = {"done": 0, "ok": 0}
    total = len(urls)
    t_start = time.perf_counter()

    async def run_one(url: str):
        async with sem:
            t0 = time.perf_counter()
            try:
                resp = await asyncio.wait_for(
                    session.get(url, headers=HEADERS, proxy=PROXY, timeout=timeout_seconds,
                                allow_redirects=True, max_redirects=5),
                    timeout=timeout_seconds + 5,
                )
                lat = (time.perf_counter() - t0) * 1000
                content_len = len(resp.content) if resp.content else 0
                status = resp.status_code
                ok = 200 <= status < 400 and content_len > 100
                error = None if ok else f"http_or_empty:status_{status}:len_{content_len}"
                result = {"ok": ok, "status": status, "lat_ms": lat, "error": error}
            except Exception as e:
                lat = (time.perf_counter() - t0) * 1000
                result = {"ok": False, "status": 0, "lat_ms": lat, "error": f"{_classify_probe_exception(e)}:{type(e).__name__}"}
            counter["done"] += 1
            if result["ok"]:
                counter["ok"] += 1
            done = counter["done"]
            if done % 400 == 0 or done == total:
                elapsed = time.perf_counter() - t_start
                rate = counter["ok"] / done * 100 if done else 0
                logger.info(f"[ab-stress] {done}/{total} | ok={rate:.1f}% | {elapsed:.1f}s")
            return result

    results = await asyncio.gather(*[run_one(u) for u in urls])
    total_time = time.perf_counter() - t_start
    await session.close()
    summary = _build_test_summary(results, total_time, "stress_direct")
    summary["concurrent"] = concurrent
    summary["timeout_seconds"] = timeout_seconds
    return summary


async def _run_probe_only(urls: List[str], concurrent: int, timeout_seconds: int) -> Dict[str, Any]:
    from app.services.scraper.url_prober import fast_probe_and_scrape, URLNotReachable

    concurrent = min(concurrent, len(urls))
    sem = asyncio.Semaphore(concurrent)
    counter = {"done": 0, "ok": 0}
    total = len(urls)
    t_start = time.perf_counter()
    empty_content_sample: List[Dict[str, Any]] = []

    async def run_one(url: str):
        async with sem:
            t0 = time.perf_counter()
            try:
                _best_url, text, _docs, _links, _probe_time = await fast_probe_and_scrape(
                    url,
                    timeout=timeout_seconds,
                    proxy=PROXY or None,
                    proxy_provider=None,
                    retry_timeout=None,
                    max_retries=0,
                )
                probe_meta = dict(getattr(fast_probe_and_scrape, "last_meta", {}) or {})
                lat = (time.perf_counter() - t0) * 1000
                ok = bool(text) and len(text) > 100
                err = None if ok else "empty_content"
                status_code = int(probe_meta.get("status_code") or 0)
                parsed_len = int(probe_meta.get("parsed_text_len") or len(text or ""))
                raw_len = int(probe_meta.get("raw_content_len") or 0)
                final_url = probe_meta.get("final_url") or url
                if not ok and err == "empty_content" and len(empty_content_sample) < 30:
                    empty_content_sample.append(
                        {
                            "url": url,
                            "final_url": final_url,
                            "status_code": status_code,
                            "raw_content_len": raw_len,
                            "parsed_text_len": parsed_len,
                            "lat_ms": round(lat, 1),
                        }
                    )
                result = {
                    "ok": ok,
                    "status": status_code or (200 if ok else 0),
                    "lat_ms": lat,
                    "error": err,
                    "url": url,
                }
            except URLNotReachable as e:
                lat = (time.perf_counter() - t0) * 1000
                result = {
                    "ok": False,
                    "status": 0,
                    "lat_ms": lat,
                    "error": f"probe_{e.error_type.value if e.error_type else 'unknown'}",
                    "url": url,
                }
            except Exception as e:
                lat = (time.perf_counter() - t0) * 1000
                result = {
                    "ok": False,
                    "status": 0,
                    "lat_ms": lat,
                    "error": f"{_classify_probe_exception(e)}:{type(e).__name__}",
                    "url": url,
                }

            counter["done"] += 1
            if result["ok"]:
                counter["ok"] += 1
            done = counter["done"]
            if done % 400 == 0 or done == total:
                elapsed = time.perf_counter() - t_start
                rate = counter["ok"] / done * 100 if done else 0
                logger.info(f"[ab-probe] {done}/{total} | ok={rate:.1f}% | {elapsed:.1f}s")
            return result

    results = await asyncio.gather(*[run_one(u) for u in urls])
    total_time = time.perf_counter() - t_start
    summary = _build_test_summary(results, total_time, "probe_only")
    summary["content_rejections"] = {
        "threshold": 100,
        "empty_content_total": sum(1 for r in results if r.get("error") == "empty_content"),
        "empty_content_sample": empty_content_sample,
    }
    summary["concurrent"] = concurrent
    summary["timeout_seconds"] = timeout_seconds
    return summary


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


@router.post("/scrape/ab-test/prepare")
async def prepare_ab_sample(req: ABPrepareRequest):
    sample = await _prepare_ab_sample(req.limit, req.seed)
    return {"success": True, **sample}


@router.post("/scrape/ab-test/run-stress")
async def run_ab_stress(req: ABRunRequest):
    urls = _AB_SAMPLES.get(req.sample_id)
    if not urls:
        raise HTTPException(404, "sample_id não encontrado. Rode /scrape/ab-test/prepare primeiro.")
    result = await _run_stress_direct(urls, req.concurrent, req.timeout_seconds)
    return {"sample_id": req.sample_id, "sample_meta": _AB_SAMPLE_META.get(req.sample_id, {}), **result}


@router.post("/scrape/ab-test/run-probe-only")
async def run_ab_probe_only(req: ABRunRequest):
    urls = _AB_SAMPLES.get(req.sample_id)
    if not urls:
        raise HTTPException(404, "sample_id não encontrado. Rode /scrape/ab-test/prepare primeiro.")
    result = await _run_probe_only(urls, req.concurrent, req.timeout_seconds)
    return {"sample_id": req.sample_id, "sample_meta": _AB_SAMPLE_META.get(req.sample_id, {}), **result}


@router.post("/scrape/ab-test/run-both")
async def run_ab_both(req: ABRunRequest):
    urls = _AB_SAMPLES.get(req.sample_id)
    if not urls:
        raise HTTPException(404, "sample_id não encontrado. Rode /scrape/ab-test/prepare primeiro.")
    stress = await _run_stress_direct(urls, req.concurrent, req.timeout_seconds)
    probe = await _run_probe_only(urls, req.concurrent, req.timeout_seconds)
    return {
        "sample_id": req.sample_id,
        "sample_meta": _AB_SAMPLE_META.get(req.sample_id, {}),
        "settings": {"concurrent": req.concurrent, "timeout_seconds": req.timeout_seconds},
        "stress_direct": stress,
        "probe_only": probe,
    }
