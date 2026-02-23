"""
Servico principal de scraping — pipeline direto.

Pipeline: GET unico (probe+main) → heuristic links → scrape subpages (throttled).
Subpages usam stagger delay + semaforo por dominio + circuit breaker.
"""

import asyncio
import time
import logging
from typing import List, Optional

from .models import ScrapedPage, ScrapeResult
from .constants import (
    REQUEST_TIMEOUT, SUBPAGE_TIMEOUT, MAX_SUBPAGES, MIN_CONTENT_LENGTH,
    PER_DOMAIN_CONCURRENT, STAGGER_DELAY, CIRCUIT_BREAKER_THRESHOLD,
    smart_referer,
)
from .html_parser import is_cloudflare_challenge, is_soft_404, normalize_url
from .link_selector import filter_non_html_links, prioritize_links
from .url_prober import fast_probe_and_scrape, URLNotReachable
from .http_client import cffi_scrape_safe

logger = logging.getLogger(__name__)


async def scrape_all_subpages(
    url: str,
    max_subpages: int = MAX_SUBPAGES,
    ctx_label: str = "",
    request_id: str = "",
) -> ScrapeResult:
    """
    Pipeline: GET unico (probe+main) -> select links -> scrape subpages.
    """
    overall_start = time.perf_counter()
    meta = ScrapeResult()

    # 1. GET UNICO (probe + main page fundidos)
    t0 = time.perf_counter()
    try:
        best_url, text, docs, links, probe_time = await fast_probe_and_scrape(url)
        url = best_url
        meta.probe_ok = True
        meta.probe_time_ms = probe_time
    except URLNotReachable as e:
        meta.probe_time_ms = (time.perf_counter() - t0) * 1000
        logger.error(f"{ctx_label} URL inacessivel: {url} - {e.get_log_message()}")
        meta.main_page_fail_reason = f"probe_{e.error_type.value if e.error_type else 'unknown'}"
        meta.total_time_ms = (time.perf_counter() - overall_start) * 1000
        return meta
    except Exception as e:
        meta.probe_time_ms = (time.perf_counter() - t0) * 1000
        logger.error(f"{ctx_label} Erro inesperado no probe+scrape: {e}")
        meta.main_page_fail_reason = f"probe_unknown"
        meta.total_time_ms = (time.perf_counter() - overall_start) * 1000
        return meta

    meta.main_scrape_time_ms = meta.probe_time_ms

    # Validar conteudo da main page
    main_page = _validate_main_page(url, text, links, docs)

    if not main_page or not main_page.success:
        fail_reason = _get_fail_reason(main_page)
        logger.error(f"{ctx_label} Falha main page {url} reason={fail_reason}")
        meta.main_page_fail_reason = fail_reason
        meta.total_time_ms = (time.perf_counter() - overall_start) * 1000
        return meta

    meta.main_page_ok = True

    # 2. SELECIONAR TOP LINKS
    all_links = set(main_page.links)
    filtered = filter_non_html_links(all_links)
    target_subpages = prioritize_links(filtered, url)[:max_subpages]

    meta.links_in_html = len(all_links)
    meta.links_after_filter = len(filtered)
    meta.links_selected = len(target_subpages)

    # 3. SCRAPE SUBPAGES (stagger + domain_sem + circuit breaker)
    base_referer = smart_referer(url)
    t_sub = time.perf_counter()
    subpages: List[ScrapedPage] = []
    skipped = 0
    if target_subpages:
        subpages, skipped = await _scrape_subpages(
            target_subpages, base_referer, ctx_label,
        )
    meta.subpages_time_ms = (time.perf_counter() - t_sub) * 1000

    # 4. CONSOLIDAR
    all_pages = [main_page] + subpages
    meta.pages = all_pages
    meta.subpages_attempted = len(subpages)
    meta.subpages_ok = sum(1 for p in subpages if p.success)
    meta.subpages_skipped = skipped
    meta.total_time_ms = (time.perf_counter() - overall_start) * 1000

    error_breakdown: dict = {}
    for p in subpages:
        if not p.success and p.error:
            cat = _classify_subpage_error(p.error)
            error_breakdown[cat] = error_breakdown.get(cat, 0) + 1
    meta.subpage_errors = error_breakdown

    ok = sum(1 for p in all_pages if p.success)
    logger.info(
        f"{ctx_label} {url[:50]} | {ok}/{len(all_pages)} ok | "
        f"probe+main={meta.main_scrape_time_ms:.0f}ms "
        f"sub={meta.subpages_time_ms:.0f}ms total={meta.total_time_ms:.0f}ms "
        f"links={meta.links_in_html}->{meta.links_selected} "
        f"subpages={meta.subpages_ok}/{meta.subpages_attempted} skip={skipped}"
    )
    return meta


def _validate_main_page(
    url: str, text: str, links: set, docs: set
) -> Optional[ScrapedPage]:
    """Valida o conteudo retornado pelo probe+scrape."""
    if not text:
        return ScrapedPage(url=url, content="", error="empty_response")

    if is_cloudflare_challenge(text):
        return ScrapedPage(
            url=url, content="", error="Cloudflare",
            links=list(links), document_links=list(docs), status_code=403,
        )

    if is_soft_404(text):
        return ScrapedPage(
            url=url, content="", error="Soft 404",
            links=list(links), document_links=list(docs), status_code=404,
        )

    if len(text) < MIN_CONTENT_LENGTH:
        return ScrapedPage(url=url, content="", error="thin_content")

    return ScrapedPage(
        url=url, content=text, links=list(links),
        document_links=list(docs), status_code=200,
    )


async def _scrape_subpages(
    urls: List[str],
    referer: str = "",
    ctx_label: str = "",
) -> tuple:
    """
    Scrape subpaginas com stagger + semaforo por dominio + circuit breaker.
    Retorna (list[ScrapedPage], skipped_count).
    """
    domain_sem = asyncio.Semaphore(PER_DOMAIN_CONCURRENT)
    fail_streak = 0
    abort = False

    async def scrape_one(url: str) -> ScrapedPage:
        normalized = normalize_url(url)
        try:
            text, docs, _ = await cffi_scrape_safe(
                normalized, timeout=SUBPAGE_TIMEOUT, referer=referer,
            )
            transport_err = cffi_scrape_safe.last_error
            elapsed = cffi_scrape_safe.elapsed_ms
            sem_w = cffi_scrape_safe.sem_wait_ms
            http_t = cffi_scrape_safe.http_time_ms

            timing = dict(
                response_time_ms=elapsed,
                sem_wait_ms=sem_w,
                http_time_ms=http_t,
            )

            if not text and transport_err:
                return ScrapedPage(
                    url=normalized, content="",
                    error=f"transport:{transport_err}", **timing,
                )

            if not text:
                return ScrapedPage(
                    url=normalized, content="", error="empty_response",
                    **timing,
                )

            if is_cloudflare_challenge(text):
                return ScrapedPage(
                    url=normalized, content="", error="blocked:cloudflare",
                    **timing,
                )

            if is_soft_404(text):
                return ScrapedPage(
                    url=normalized, content="", error="content:soft_404",
                    **timing,
                )

            if len(text) < MIN_CONTENT_LENGTH:
                return ScrapedPage(
                    url=normalized, content="",
                    error=f"content:thin_{len(text)}chars", **timing,
                )

            return ScrapedPage(
                url=normalized, content=text,
                document_links=list(docs), status_code=200, **timing,
            )
        except Exception as e:
            return ScrapedPage(
                url=normalized, content="",
                error=f"exception:{type(e).__name__}:{str(e)[:60]}",
            )

    async def guarded_scrape(url: str, idx: int) -> Optional[ScrapedPage]:
        nonlocal fail_streak, abort

        if abort:
            return None

        await asyncio.sleep(idx * STAGGER_DELAY)

        if abort:
            return None

        async with domain_sem:
            if abort:
                return None
            result = await scrape_one(url)
            if not result.success:
                fail_streak += 1
                if fail_streak >= CIRCUIT_BREAKER_THRESHOLD:
                    abort = True
            else:
                fail_streak = 0
            return result

    tasks = [guarded_scrape(u, i) for i, u in enumerate(urls)]
    raw = await asyncio.gather(*tasks)

    pages = [r for r in raw if r is not None]
    skipped = sum(1 for r in raw if r is None)
    return pages, skipped


def _get_fail_reason(page: Optional[ScrapedPage]) -> str:
    if not page:
        return "scrape_null_response"
    if page.error:
        err = page.error.lower()
        if "cloudflare" in err:
            return "scrape_blocked_cloudflare"
        if "soft 404" in err:
            return "scrape_soft_404"
        if "thin_content" in err:
            return "scrape_thin_content"
        if "empty_response" in err:
            return "scrape_empty_content"
        return f"proxy_fail:{page.error[:40]}"
    if not page.content:
        return "scrape_empty_content"
    return "scrape_unknown"


def _classify_subpage_error(error: str) -> str:
    if not error:
        return "unknown"
    err = error.lower()

    if "skipped" in err or "circuit_breaker" in err:
        return "sub:skipped"

    if err.startswith("transport:"):
        detail = err[len("transport:"):]
        if "timeout" in detail:
            return "sub:timeout"
        if "http_403" in detail:
            return "sub:http_403"
        if "http_4" in detail:
            return "sub:http_4xx"
        if "http_5" in detail:
            return "sub:http_5xx"
        if "connection" in detail:
            return "sub:connection"
        if "ssl" in detail:
            return "sub:ssl"
        return "sub:transport_other"

    if "blocked:cloudflare" in err:
        return "sub:cloudflare"
    if "content:soft_404" in err:
        return "sub:soft_404"
    if "content:thin" in err:
        return "sub:thin_content"
    if "empty_response" in err:
        return "sub:empty_response"
    if err.startswith("exception:"):
        return "sub:exception"

    return "sub:other"
