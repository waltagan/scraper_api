"""
Serviço principal de scraping — pipeline simplificado.

Pipeline: probe → scrape main → heuristic links → scrape subpages (paralelo).
Sem strategy selector, sem slow mode, sem circuit breaker.
"""

import asyncio
import time
import logging
import random
from urllib.parse import urlparse
from typing import List, Tuple, Optional
from enum import Enum

from .models import ScrapedPage, ScrapeResult
from .constants import (
    REQUEST_TIMEOUT, MAX_RETRIES, MAX_SUBPAGES,
    PER_DOMAIN_CONCURRENT, build_headers, smart_referer,
)
from .html_parser import is_cloudflare_challenge, is_soft_404, normalize_url, parse_html
from .link_selector import extract_and_prioritize_links, filter_non_html_links, prioritize_links
from .url_prober import url_prober, URLNotReachable
from .http_client import cffi_scrape, cffi_scrape_safe
from .proxy_gate import acquire_proxy_slot, record_gateway_result
from .session_pool import get_session

from app.services.scraper_manager.proxy_manager import (
    record_proxy_failure, record_proxy_success,
)

logger = logging.getLogger(__name__)


class FailureType(Enum):
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    CLOUDFLARE = "cloudflare"
    WAF = "waf"
    CAPTCHA = "captcha"
    RATE_LIMIT = "rate_limit"
    EMPTY_CONTENT = "empty_content"
    SSL_ERROR = "ssl_error"
    DNS_ERROR = "dns_error"
    UNKNOWN = "unknown"


async def scrape_all_subpages(
    url: str,
    max_subpages: int = MAX_SUBPAGES,
    ctx_label: str = "",
    request_id: str = "",
) -> ScrapeResult:
    """
    Pipeline principal: probe → scrape main → heuristic links → scrape subpages.
    Retorna ScrapeResult com pages e metadados.
    """
    overall_start = time.perf_counter()
    meta = ScrapeResult()

    # 1. PROBE URL
    try:
        best_url, probe_time = await url_prober.probe(url)
        url = best_url
    except URLNotReachable as e:
        log_msg = e.get_log_message()
        logger.error(f"{ctx_label} URL inacessível: {url} - {log_msg}")
        error_type = getattr(e, 'error_type', None)
        meta.main_page_fail_reason = f"probe_{error_type.value if error_type else 'unknown'}"
        meta.total_time_ms = (time.perf_counter() - overall_start) * 1000
        return meta
    except Exception as e:
        logger.warning(f"{ctx_label} Erro no probe, usando URL original: {e}")

    # 2. SCRAPE MAIN PAGE
    main_page = await _scrape_page_with_retry(url, ctx_label)

    if not main_page or not main_page.success:
        fail_reason = _get_fail_reason(main_page)
        logger.error(f"{ctx_label} Falha main page {url} reason={fail_reason}")
        meta.main_page_fail_reason = fail_reason
        meta.total_time_ms = (time.perf_counter() - overall_start) * 1000
        return meta

    meta.main_page_ok = True

    # 3. EXTRAIR E PRIORIZAR LINKS
    all_links = set(main_page.links)
    filtered = filter_non_html_links(all_links)
    target_subpages = prioritize_links(filtered, url)[:max_subpages]

    meta.links_in_html = len(all_links)
    meta.links_after_filter = len(filtered)
    meta.links_selected = len(target_subpages)

    # 4. SCRAPE SUBPAGES EM PARALELO
    subpages = []
    if target_subpages:
        domain_sem = asyncio.Semaphore(PER_DOMAIN_CONCURRENT)
        subpages = await _scrape_subpages_parallel(
            target_subpages, domain_sem, ctx_label
        )

    # 5. CONSOLIDAR
    all_pages = [main_page] + subpages
    meta.pages = all_pages
    meta.subpages_attempted = len(subpages)
    meta.subpages_ok = sum(1 for p in subpages if p.success)
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
        f"{meta.total_time_ms:.0f}ms links={meta.links_in_html}->{meta.links_selected} "
        f"subpages={meta.subpages_ok}/{meta.subpages_attempted}"
    )
    return meta


async def _scrape_page_with_retry(
    url: str, ctx_label: str = ""
) -> Optional[ScrapedPage]:
    """Scrape de uma página com retry. Proxy selecionado pelo gate (load balancing)."""
    last_page = None

    for attempt in range(1 + MAX_RETRIES):
        page = await _do_scrape(url, ctx_label)

        if page.success:
            record_proxy_success("gateway")
            return page

        record_proxy_failure("gateway", page.error or "unknown")
        last_page = page

        if _is_site_rejection(page.error):
            return page

        if attempt < MAX_RETRIES:
            logger.debug(f"{ctx_label} Retry {attempt+2}/{1+MAX_RETRIES} para {url[:50]}")

    return last_page


async def _do_scrape(url: str, ctx_label: str = "") -> ScrapedPage:
    """Executa scrape via cffi_scrape_safe. Proxy selecionado pelo proxy_gate."""
    try:
        text, docs, links = await cffi_scrape_safe(url)

        if not text:
            transport_err = cffi_scrape_safe.last_error or "empty_response"
            return ScrapedPage(url=url, content="", error=f"proxy_fail:{transport_err}")

        if is_cloudflare_challenge(text):
            return ScrapedPage(url=url, content="", error="Cloudflare",
                               links=list(links), document_links=list(docs), status_code=403)

        if is_soft_404(text):
            return ScrapedPage(url=url, content="", error="Soft 404",
                               links=list(links), document_links=list(docs), status_code=404)

        return ScrapedPage(url=url, content=text, links=list(links),
                           document_links=list(docs), status_code=200)

    except Exception as e:
        return ScrapedPage(url=url, content="",
                           error=f"scrape_exception:{type(e).__name__}:{str(e)[:50]}")


async def _scrape_subpages_parallel(
    urls: List[str],
    domain_sem: asyncio.Semaphore,
    ctx_label: str = "",
) -> List[ScrapedPage]:
    """Scrape subpáginas em paralelo, limitado por domain semaphore."""

    async def scrape_one(url: str) -> ScrapedPage:
        async with domain_sem:
            normalized = normalize_url(url)

            try:
                async with acquire_proxy_slot() as proxy:
                    session = await get_session(proxy)
                    t0 = time.perf_counter()
                    try:
                        text, docs, _ = await asyncio.wait_for(
                            cffi_scrape(normalized, proxy=None, session=session),
                            timeout=REQUEST_TIMEOUT,
                        )
                        lat = (time.perf_counter() - t0) * 1000
                    except Exception:
                        lat = (time.perf_counter() - t0) * 1000
                        record_gateway_result(proxy, False, lat)
                        raise

                if not text or len(text) < 100 or is_soft_404(text) or is_cloudflare_challenge(text):
                    record_gateway_result(proxy, False, lat)
                    return ScrapedPage(url=normalized, content="", error="Empty or soft 404")

                record_gateway_result(proxy, True, lat)
                record_proxy_success(proxy)
                return ScrapedPage(url=normalized, content=text,
                                   document_links=list(docs), status_code=200)

            except Exception as e:
                record_proxy_failure("gateway", str(e)[:30])
                return ScrapedPage(url=normalized, content="", error=str(e))

    tasks = [scrape_one(u) for u in urls]
    results = await asyncio.gather(*tasks)
    return list(results)


def _is_site_rejection(error: str) -> bool:
    if not error:
        return False
    err = error.lower()
    return any(sig in err for sig in (
        "403", "429", "cloudflare", "captcha", "waf", "forbidden", "blocked",
    ))


def _get_fail_reason(page: Optional[ScrapedPage]) -> str:
    if not page:
        return "scrape_null_response"
    if page.error:
        err = page.error.lower()
        if "proxy_fail" in err:
            return page.error
        if "cloudflare" in err:
            return "scrape_blocked_cloudflare"
        return f"scrape_error({page.error[:40]})"
    if page.content and len(page.content) < 100:
        return "scrape_thin_content"
    if not page.content:
        return "scrape_empty_content"
    return "scrape_unknown"


def _classify_subpage_error(error: str) -> str:
    if not error:
        return "unknown"
    err = error.lower()
    if "timeout" in err:
        return "timeout"
    if "cloudflare" in err:
        return "cloudflare"
    if "soft 404" in err or "empty" in err:
        return "empty_content"
    return "scrape_fail"


def _classify_error(error_message: str) -> FailureType:
    if not error_message:
        return FailureType.UNKNOWN
    err = error_message.lower()

    if "timeout" in err:
        return FailureType.TIMEOUT
    if "cloudflare" in err:
        return FailureType.CLOUDFLARE
    if "403" in err or "waf" in err:
        return FailureType.WAF
    if "captcha" in err:
        return FailureType.CAPTCHA
    if "rate" in err and "limit" in err:
        return FailureType.RATE_LIMIT
    if "empty" in err or "404" in err:
        return FailureType.EMPTY_CONTENT
    if "ssl" in err or "certificate" in err:
        return FailureType.SSL_ERROR
    if "dns" in err or "resolve" in err:
        return FailureType.DNS_ERROR
    if "connection" in err or "connect" in err:
        return FailureType.CONNECTION_ERROR
    return FailureType.UNKNOWN
