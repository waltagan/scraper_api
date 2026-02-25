"""
Servico principal de scraping — pipeline direto.

Pipeline: GET unico (probe+main) → heuristic links → scrape subpages (throttled).
Subpages usam stagger delay + semaforo por dominio + circuit breaker.
"""

import asyncio
import random
import time
import logging
from typing import List, Optional, Tuple

from .models import ScrapedPage, ScrapeResult
from .constants import (
    REQUEST_TIMEOUT, SUBPAGE_TIMEOUT, MAX_SUBPAGES, MIN_CONTENT_LENGTH,
    PER_DOMAIN_CONCURRENT, CIRCUIT_BREAKER_THRESHOLD,
    RETRY_TIMEOUT, MAX_RETRIES, PROBE_ONLY_MODE,
    smart_referer,
)
from .html_parser import is_cloudflare_challenge, is_soft_404, normalize_url, parse_html, extract_links
from .link_selector import filter_non_html_links, prioritize_links
from .url_prober import fast_probe_and_scrape, URLNotReachable
from .http_client import cffi_scrape_safe

logger = logging.getLogger(__name__)

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

_MAIN_PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.google.com/",
}
_MAIN_PAGE_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
]


async def scrape_all_subpages(
    url: str,
    max_subpages: int = MAX_SUBPAGES,
    ctx_label: str = "",
    request_id: str = "",
    proxy: str = "",
    proxy_provider: str = "",
    probe_only: Optional[bool] = None,
) -> ScrapeResult:
    """
    Pipeline: GET unico (probe+main) -> select links -> scrape subpages.
    """
    overall_start = time.perf_counter()
    meta = ScrapeResult()

    # 1. GET UNICO (probe + main page fundidos)
    t0 = time.perf_counter()
    try:
        best_url, text, docs, links, probe_time = await fast_probe_and_scrape(
            url,
            proxy=proxy or None,
            proxy_provider=proxy_provider or None,
            timeout=REQUEST_TIMEOUT,
            retry_timeout=RETRY_TIMEOUT,
            max_retries=MAX_RETRIES,
        )
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
    meta.all_links = sorted(all_links)
    meta.target_links = list(target_subpages)

    effective_probe_only = PROBE_ONLY_MODE if probe_only is None else bool(probe_only)
    if effective_probe_only:
        meta.pages = [main_page]
        meta.subpages_attempted = 0
        meta.subpages_ok = 0
        meta.subpages_skipped = 0
        meta.subpages_time_ms = 0.0
        meta.total_time_ms = (time.perf_counter() - overall_start) * 1000
        logger.info(
            f"{ctx_label} {url[:50]} | probe_only=on | main_ok=1/1 "
            f"links={meta.links_in_html}->{meta.links_selected} "
            f"probe+main={meta.main_scrape_time_ms:.0f}ms total={meta.total_time_ms:.0f}ms"
        )
        return meta

    # 3. SCRAPE SUBPAGES (stagger + domain_sem + circuit breaker)
    base_referer = smart_referer(url)
    t_sub = time.perf_counter()
    subpages: List[ScrapedPage] = []
    skipped = 0
    if target_subpages:
        subpages, skipped = await _scrape_subpages(
            target_subpages, base_referer, ctx_label,
            proxy=proxy, proxy_provider=proxy_provider,
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
    proxy: str = "",
    proxy_provider: str = "",
) -> tuple:
    """
    Scrape subpaginas com stagger + semaforo por dominio + circuit breaker.
    Retorna (list[ScrapedPage], skipped_count).
    """
    domain_sem = asyncio.Semaphore(PER_DOMAIN_CONCURRENT)
    fail_streak = 0
    abort = False

    def _is_retryable_transport_error(err: str) -> bool:
        e = (err or "").lower()
        return any(k in e for k in [
            "timeout", "timed out", "connection", "refused", "reset",
            "http_429", "http_502", "http_503", "http_504", "server error",
        ])

    async def scrape_one(url: str) -> ScrapedPage:
        normalized = normalize_url(url)
        try:
            text, docs, _ = await cffi_scrape_safe(
                normalized, proxy=proxy or None,
                timeout=SUBPAGE_TIMEOUT, referer=referer,
                provider=proxy_provider or None,
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

            if not text and transport_err and MAX_RETRIES > 0 and _is_retryable_transport_error(transport_err):
                text, docs, _ = await cffi_scrape_safe(
                    normalized, proxy=proxy or None,
                    timeout=RETRY_TIMEOUT, referer=referer,
                    provider=proxy_provider or None,
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

        async with domain_sem:
            if abort:
                return None
            if idx > 0:
                delay = random.uniform(0.4, 0.65)
                await asyncio.sleep(delay)
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


async def scrape_single_subpage_simple(
    url: str,
    referer: str = "",
    proxy: str = "",
    proxy_provider: str = "",
) -> ScrapedPage:
    """
    Scrape simples de subpágina (sem retry/circuit breaker/stagger).
    A concorrência global é controlada externamente pelo batch processor.
    """
    normalized = normalize_url(url)
    text, docs, _ = await cffi_scrape_safe(
        normalized,
        proxy=proxy or None,
        timeout=SUBPAGE_TIMEOUT,
        referer=referer,
        provider=proxy_provider or None,
    )
    timing = dict(
        response_time_ms=cffi_scrape_safe.elapsed_ms,
        sem_wait_ms=cffi_scrape_safe.sem_wait_ms,
        http_time_ms=cffi_scrape_safe.http_time_ms,
    )
    transport_err = cffi_scrape_safe.last_error

    if not text and transport_err:
        return ScrapedPage(url=normalized, content="", error=f"transport:{transport_err}", **timing)
    if not text:
        return ScrapedPage(url=normalized, content="", error="empty_response", **timing)
    if is_cloudflare_challenge(text):
        return ScrapedPage(url=normalized, content="", error="blocked:cloudflare", **timing)
    if is_soft_404(text):
        return ScrapedPage(url=normalized, content="", error="content:soft_404", **timing)
    if len(text) < MIN_CONTENT_LENGTH:
        return ScrapedPage(url=normalized, content="", error=f"content:thin_{len(text)}chars", **timing)
    return ScrapedPage(
        url=normalized,
        content=text,
        document_links=list(docs),
        status_code=200,
        **timing,
    )


async def scrape_main_page_raw(
    url: str,
    timeout: int = REQUEST_TIMEOUT,
    proxy: str = "",
) -> Tuple[str, int, str, str]:
    """
    Faz um GET único da main page (estilo stress test) e retorna:
    (final_url, status_code, raw_html, error).
    """
    if not HAS_CURL_CFFI:
        return url, 0, "", "curl_cffi_not_available"

    session = AsyncSession(impersonate="chrome131", verify=False, max_clients=200)
    try:
        return await scrape_main_page_raw_with_session(
            session=session,
            url=url,
            timeout=timeout,
            proxy=proxy,
        )
    finally:
        await session.close()


async def scrape_main_page_raw_with_session(
    session: "AsyncSession",
    url: str,
    timeout: int = REQUEST_TIMEOUT,
    proxy: str = "",
) -> Tuple[str, int, str, str]:
    """
    Igual ao stress test: usa sessão HTTP reutilizada para múltiplas URLs.
    PROIBIDO alterar este padrão para criar sessão por requisição.
    """
    target_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
    error = ""
    try:
        headers = dict(_MAIN_PAGE_HEADERS)
        headers["User-Agent"] = random.choice(_MAIN_PAGE_USER_AGENTS)
        resp = await session.get(
            target_url,
            headers=headers,
            proxy=(proxy or None),
            timeout=timeout,
            allow_redirects=True,
            max_redirects=5,
        )
        status_code = int(getattr(resp, "status_code", 0) or 0)
        final_url = str(getattr(resp, "url", target_url))
        raw_html = (resp.content or b"").decode("utf-8", errors="ignore")

        # Igual ao stress test: sucesso somente com HTTP 200.
        if status_code != 200:
            error = f"http_{status_code}"

        return final_url, status_code, raw_html, error
    except Exception as exc:
        return target_url, 0, "", f"{type(exc).__name__}: {str(exc)[:200]}"


def extract_subpage_links_from_raw(raw_content: str, base_url: str) -> List[str]:
    """
    Extrai e prioriza links de subpágina a partir do HTML bruto salvo.
    """
    _docs, internal_links = extract_links(raw_content or "", base_url)
    filtered = filter_non_html_links(internal_links)
    prioritized = prioritize_links(filtered, base_url)
    return prioritized


def extract_mainpage_text_from_raw(raw_content: str, base_url: str) -> str:
    """
    Extrai texto limpo da main page a partir do HTML bruto salvo.
    """
    text, _docs, _links = parse_html(raw_content or "", base_url)
    return text or ""
