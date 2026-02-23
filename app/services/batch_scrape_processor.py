"""
Batch Scrape Processor — pipeline com chunking.

Processa empresas em chunks de CHUNK_SIZE para limitar memória e
permitir renovação de sessões sticky entre lotes.
Semáforos por provider: 711Proxy (800) + Decodo (1500).
"""

import asyncio
import bisect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from app.services.scraper.scraper_service import scrape_all_subpages
from app.services.scraper.models import ScrapeResult
from app.core.chunking import process_content
from app.services.database_service import get_db_service
from app.services.scraper.constants import FLUSH_SIZE, MAX_SUBPAGES, CHUNK_SIZE
from app.services.scraper_manager.proxy_manager import proxy_pool

logger = logging.getLogger(__name__)

TRANSIENT_KEYWORDS = frozenset([
    "timeout", "429", "rate limit", "connection reset",
    "connection refused", "connection error", "temporarily",
    "server error", "502", "503", "504",
])

ERROR_CATEGORIES = {
    "dns": ["dns", "resolve", "name resolution"],
    "timeout": ["timeout", "timed out"],
    "connection": ["connection reset", "connection refused", "connection error", "connect"],
    "ssl": ["ssl", "certificate"],
    "cloudflare": ["cloudflare", "challenge"],
    "captcha": ["captcha"],
    "rate_limit": ["429", "rate limit", "too many"],
    "empty_content": ["nenhum conteudo", "empty", "soft 404", "insuficiente"],
    "server_error": ["502", "503", "504", "server error"],
    "blocked": ["403", "forbidden", "blocked"],
}


def _is_transient(error_msg: str) -> bool:
    lower = error_msg.lower()
    return any(kw in lower for kw in TRANSIENT_KEYWORDS)


def _classify_error(error_msg: str) -> str:
    if not error_msg:
        return "unknown"
    lower = error_msg.lower()
    for category, keywords in ERROR_CATEGORIES.items():
        if any(kw in lower for kw in keywords):
            return category
    return "other"


def _bucket_fail_reason(reason: str) -> str:
    if not reason:
        return "unknown"
    r = reason.lower()

    if r.startswith("probe_"):
        if "dns" in r:
            return "probe:dns"
        if "connection_timeout" in r or ("timeout" in r and "concurrency" not in r):
            return "probe:timeout"
        if "refused" in r or "reset" in r:
            return "probe:refused"
        if "ssl" in r:
            return "probe:ssl"
        if "blocked" in r or "403" in r:
            return "probe:blocked"
        if "server_error" in r or "500" in r:
            return "probe:server_error"
        if "redirect" in r:
            return "probe:redirect_loop"
        return "probe:other"

    if "proxy_fail" in r:
        if "proxy_timeout" in r or "timed out" in r:
            return "proxy:timeout"
        if "proxy_connection" in r or "refused" in r:
            return "proxy:connection"
        if "http_403" in r:
            return "proxy:http_403"
        if "http_5" in r:
            return "proxy:http_5xx"
        if "ssl" in r:
            return "proxy:ssl"
        if "empty_response" in r:
            return "proxy:empty_response"
        return "proxy:other"

    if "blocked" in r:
        if "cloudflare" in r:
            return "scrape:blocked_cloudflare"
        return "scrape:blocked_waf"

    if "soft 404" in r or "soft_404" in r:
        return "scrape:soft_404"
    if "cloudflare" in r:
        return "scrape:cloudflare"
    if "timeout" in r:
        return "scrape:timeout"
    if "thin_content" in r:
        return "scrape:thin_content"
    if "empty_content" in r:
        return "scrape:empty_content"
    if "scrape_error" in r:
        return "scrape:error"
    if "scrape_null" in r:
        return "scrape:null_response"

    return f"other:{reason[:30]}"


def _build_failure_diagnosis(fail_reasons: Dict[str, int], total_processed: int) -> dict:
    categories: Dict[str, Dict[str, int]] = {
        "site_offline": {}, "proxy_infra": {}, "blocked": {},
        "content_issue": {}, "other": {},
    }
    mapping = {
        "probe:dns": "site_offline", "probe:refused": "site_offline",
        "probe:server_error": "site_offline", "probe:redirect_loop": "site_offline",
        "probe:timeout": "proxy_infra", "probe:ssl": "site_offline",
        "probe:other": "proxy_infra", "probe:blocked": "blocked",
        "proxy:timeout": "proxy_infra", "proxy:connection": "proxy_infra",
        "proxy:ssl": "proxy_infra", "proxy:empty_response": "proxy_infra",
        "proxy:other": "proxy_infra", "proxy:http_403": "blocked",
        "proxy:http_5xx": "site_offline",
        "scrape:blocked_waf": "blocked", "scrape:blocked_cloudflare": "blocked",
        "scrape:cloudflare": "blocked", "scrape:soft_404": "content_issue",
        "scrape:thin_content": "content_issue", "scrape:empty_content": "content_issue",
        "scrape:error": "other", "scrape:null_response": "other",
        "scrape:timeout": "proxy_infra",
    }
    for reason, count in fail_reasons.items():
        cat = mapping.get(reason, "other")
        categories[cat][reason] = count

    total_failures = sum(fail_reasons.values())
    summary = {}
    for cat, reasons in categories.items():
        cat_total = sum(reasons.values())
        if cat_total > 0:
            summary[cat] = {
                "count": cat_total,
                "pct_of_failures": round(cat_total / total_failures * 100, 1) if total_failures else 0,
                "pct_of_total": round(cat_total / total_processed * 100, 1) if total_processed else 0,
                "breakdown": dict(sorted(reasons.items(), key=lambda x: -x[1])),
            }
    return {
        "total_failures": total_failures,
        "total_processed": total_processed,
        "failure_rate_pct": round(total_failures / total_processed * 100, 1) if total_processed else 0,
        "categories": summary,
    }


def _percentiles(sorted_values: List[float], pcts: List[int]) -> Dict[str, float]:
    n = len(sorted_values)
    if n == 0:
        return {f"p{p}": 0 for p in pcts}
    return {f"p{p}": round(sorted_values[min(int(n * p / 100), n - 1)], 1) for p in pcts}


def _http_time_histogram(ok_sorted: List[float], fail_sorted: List[float]) -> dict:
    """Distribui requests OK e FAIL por faixas de http_time (ms)."""
    boundaries_ms = [3000, 6000, 9000, 12000, 15000, 18000, 21000]
    labels = ["0-3s", "3-6s", "6-9s", "9-12s", "12-15s", "15-18s", "18-21s", "21s+"]
    result = {}
    for i, label in enumerate(labels):
        lo = boundaries_ms[i - 1] if i > 0 else 0
        hi = boundaries_ms[i] if i < len(boundaries_ms) else float('inf')
        ok_lo = bisect.bisect_left(ok_sorted, lo)
        ok_hi = bisect.bisect_left(ok_sorted, hi) if hi != float('inf') else len(ok_sorted)
        fail_lo = bisect.bisect_left(fail_sorted, lo)
        fail_hi = bisect.bisect_left(fail_sorted, hi) if hi != float('inf') else len(fail_sorted)
        ok_n = ok_hi - ok_lo
        fail_n = fail_hi - fail_lo
        if ok_n > 0 or fail_n > 0:
            result[label] = {"ok": ok_n, "fail": fail_n}
    return result


def _build_error_summary(scrape_result: ScrapeResult, fallback_error: str = "") -> str:
    pages = scrape_result.pages or []
    successful = [p for p in pages if p.success]
    fail_reason = scrape_result.main_page_fail_reason
    bucket = _bucket_fail_reason(fail_reason) if fail_reason else None
    summary = {
        "error_category": bucket or _classify_error(fallback_error),
        "main_page": {"ok": scrape_result.main_page_ok, "fail_reason": bucket},
        "subpages": {
            "attempted": scrape_result.subpages_attempted,
            "ok": scrape_result.subpages_ok,
            "errors": scrape_result.subpage_errors or {},
        },
        "pages_total": len(pages), "pages_ok": len(successful),
        "processing_time_ms": round(scrape_result.total_time_ms, 1),
    }
    if not scrape_result.main_page_ok:
        summary["resumo"] = f"Main page falhou: {bucket or fail_reason or 'desconhecido'}"
    elif len(successful) == 0:
        summary["resumo"] = "Main page ok mas conteudo insuficiente"
    else:
        summary["resumo"] = fallback_error or "Erro desconhecido"
    return json.dumps(summary, ensure_ascii=False)


@dataclass
class CompanyResult:
    cnpj_basico: str
    discovery_id: Optional[int]
    website_url: str
    chunks: List[Any] = field(default_factory=list)
    error: Optional[str] = None
    success: bool = False
    processing_time_ms: float = 0
    pages_scraped: int = 0
    total_pages_attempted: int = 0
    retries_used: int = 0
    page_website: Optional[str] = None
    page_scraped: Optional[str] = None


class BatchScrapeProcessor:
    """Processador batch com chunking — processa CHUNK_SIZE empresas por vez."""

    def __init__(
        self,
        worker_count: int = 2300,
        flush_size: int = FLUSH_SIZE,
        status_filter: Optional[List[str]] = None,
        limit: Optional[int] = None,
        instances: int = 1,
        chunk_size: Optional[int] = None,
    ):
        self.batch_id = str(uuid.uuid4())[:8]
        self.flush_size = flush_size
        self.status_filter = status_filter or ['muito_alto', 'alto', 'medio']
        self.limit = limit
        self.chunk_size = chunk_size or CHUNK_SIZE

        self._task: Optional[asyncio.Task] = None
        self.total = 0
        self.status = "idle"
        self._start_time: float = 0
        self._proxy_health: dict = {}
        self._connection_samples: List[int] = []
        self._sampler_task: Optional[asyncio.Task] = None

        self._processed = 0
        self._success_count = 0
        self._error_count = 0
        self._in_progress = 0
        self._peak_in_progress = 0
        self._flushes_done = 0
        self._buffer: List[CompanyResult] = []
        self._buffer_lock = asyncio.Lock()
        self._last_errors: List[dict] = []

        self._processing_times: List[float] = []
        self._error_categories: Dict[str, int] = {}
        self._pages_per_company: List[int] = []
        self._retries_total: int = 0

        self._links_in_html_total: int = 0
        self._links_after_filter_total: int = 0
        self._links_selected_total: int = 0
        self._subpages_attempted_total: int = 0
        self._subpages_ok_total: int = 0
        self._subpages_skipped_total: int = 0
        self._subpage_error_cats: Dict[str, int] = {}
        self._main_page_failures: int = 0
        self._main_page_fail_reasons: Dict[str, int] = {}
        self._zero_links_companies: int = 0

        self._probe_times: List[float] = []
        self._probe_ok: int = 0
        self._probe_fail: int = 0
        self._probe_fail_reasons: Dict[str, int] = {}
        self._main_scrape_times: List[float] = []
        self._main_scrape_ok: int = 0
        self._main_scrape_fail: int = 0
        self._main_scrape_fail_reasons: Dict[str, int] = {}
        self._subpages_times: List[float] = []
        self._subpage_individual_ok: List[float] = []
        self._subpage_individual_fail: List[float] = []
        self._subpage_sem_wait_ok: List[float] = []
        self._subpage_sem_wait_fail: List[float] = []
        self._subpage_http_ok: List[float] = []
        self._subpage_http_fail: List[float] = []
        self._domain_subpage_success_rates: List[float] = []
        self._subpage_errors_by_quartile: List[Dict[str, int]] = [{}, {}, {}, {}]

    @property
    def processed(self) -> int:
        return self._processed

    @property
    def success_count(self) -> int:
        return self._success_count

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def in_progress(self) -> int:
        return self._in_progress

    @property
    def flushes_done(self) -> int:
        return self._flushes_done

    @property
    def last_errors(self) -> List[dict]:
        return self._last_errors[-10:]

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    async def initialize(self):
        if self.limit:
            self.total = self.limit
        else:
            db = get_db_service()
            self.total = await db.count_pending_scrape_companies(self.status_filter)

    def start(self):
        if self._task and not self._task.done():
            raise RuntimeError("Batch ja esta rodando")
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        self.status = "running"
        self._start_time = time.time()

        from app.services.scraper_manager.proxy_manager import proxy_pool
        from app.services.scraper.http_client import reset_connection_stats

        reset_connection_stats()
        self._connection_samples = []

        proxy_count = await proxy_pool.preload()
        if proxy_count == 0:
            logger.error(f"[Batch {self.batch_id}] ZERO proxies! Abortando.")
            self.status = "error"
            return

        self._proxy_health = await proxy_pool.health_check()
        providers = self._proxy_health.get("providers", {})
        any_healthy = any(p.get("healthy") for p in providers.values())
        if not any_healthy:
            logger.error(f"[Batch {self.batch_id}] Nenhum proxy healthy! Abortando.")
            self.status = "error"
            return

        logger.info(f"[Batch {self.batch_id}] Proxies OK. Carregando empresas...")
        all_companies = await self._load_all_companies()

        if not all_companies:
            logger.warning(f"[Batch {self.batch_id}] Nenhuma empresa pendente.")
            self.status = "completed"
            return

        self.total = len(all_companies)
        cs = self.chunk_size
        total_chunks = (self.total + cs - 1) // cs
        logger.info(
            f"[Batch {self.batch_id}] {self.total} empresas em "
            f"{total_chunks} chunks de {cs}"
        )

        try:
            self._sampler_task = asyncio.create_task(self._sample_connections())

            for chunk_start in range(0, len(all_companies), cs):
                chunk = all_companies[chunk_start:chunk_start + cs]
                chunk_num = chunk_start // cs + 1

                logger.info(
                    f"[Batch {self.batch_id}] Chunk {chunk_num}/{total_chunks}: "
                    f"{len(chunk)} empresas (progresso: {self._processed}/{self.total})"
                )

                tasks = [self._process_company(c) for c in chunk]
                await asyncio.gather(*tasks)
                await self._flush_buffer(force=True)

                if chunk_start + cs < len(all_companies):
                    await proxy_pool.preload()
                    logger.info(
                        f"[Batch {self.batch_id}] Chunk {chunk_num} concluído. "
                        f"Sessões renovadas. "
                        f"{self._success_count} ok, {self._error_count} erros até agora."
                    )

            self._sampler_task.cancel()
            self.status = "completed"
            elapsed = time.time() - self._start_time
            logger.info(
                f"[Batch {self.batch_id}] CONCLUIDO em {elapsed:.0f}s: "
                f"{self._success_count} ok, {self._error_count} erros"
            )
        except asyncio.CancelledError:
            await self._flush_buffer(force=True)
            self.status = "cancelled"
        except Exception as e:
            logger.error(f"[Batch {self.batch_id}] Erro fatal: {e}", exc_info=True)
            await self._flush_buffer(force=True)
            self.status = "error"

    async def _sample_connections(self):
        """Amostra conexões ativas a cada 1s para histograma de carga."""
        from app.services.scraper.http_client import get_connection_stats
        try:
            while True:
                stats = get_connection_stats()
                self._connection_samples.append(stats["active"])
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def _process_company(self, company: Dict[str, Any]):
        cnpj = company['cnpj_basico']
        url = company['website_url']
        discovery_id = company.get('wd_id')

        sticky_proxy = proxy_pool.get_sticky_proxy() or ""

        self._in_progress += 1
        self._peak_in_progress = max(self._peak_in_progress, self._in_progress)
        t0 = time.perf_counter()

        try:
            result_obj = await self._do_scrape(cnpj, url, discovery_id, proxy=sticky_proxy)
        except Exception as e:
            result_obj = CompanyResult(
                cnpj_basico=cnpj, discovery_id=discovery_id,
                website_url=url, error=f"{type(e).__name__}: {str(e)[:200]}",
            )

        result_obj.processing_time_ms = (time.perf_counter() - t0) * 1000
        self._in_progress -= 1

        pending_flush = None
        async with self._buffer_lock:
            self._buffer.append(result_obj)
            self._processed += 1
            bisect.insort(self._processing_times, result_obj.processing_time_ms)
            if result_obj.pages_scraped > 0:
                self._pages_per_company.append(result_obj.pages_scraped)
            self._retries_total += result_obj.retries_used

            if result_obj.success:
                self._success_count += 1
            else:
                self._error_count += 1
                cat = _classify_error(result_obj.error or "")
                self._error_categories[cat] = self._error_categories.get(cat, 0) + 1

            if len(self._buffer) >= self.flush_size:
                pending_flush = self._buffer
                self._buffer = []

        if pending_flush is not None:
            await self._flush_records(pending_flush)

    async def _do_scrape(self, cnpj: str, url: str, discovery_id: Optional[int], proxy: str = "") -> CompanyResult:
        result = await scrape_all_subpages(
            url=url, max_subpages=MAX_SUBPAGES,
            ctx_label=f"[B{self.batch_id}]", request_id=cnpj,
            proxy=proxy,
        )
        self._aggregate_scrape_meta(result)
        pages = result.pages
        total_pages = len(pages) if pages else 0
        successful_pages = [p for p in (pages or []) if p.success]

        pw = json.dumps({"num_links": len(result.all_links), "links": result.all_links})

        if not successful_pages:
            error_msg = "Nenhum conteudo obtido"
            if pages:
                first_err = next((p.error for p in pages if p.error), None)
                if first_err:
                    error_msg = f"Nenhum conteudo obtido: {first_err}"
            return CompanyResult(
                cnpj_basico=cnpj, discovery_id=discovery_id, website_url=url,
                error=_build_error_summary(result, error_msg),
                total_pages_attempted=total_pages,
                page_website=pw,
            )

        parts = []
        visited = []
        for page in successful_pages:
            parts.append(f"--- PAGE START: {page.url} ---\n{page.content}\n--- PAGE END ---")
            visited.append(page.url)

        ps = json.dumps({"num_links": len(visited), "links": visited})

        aggregated = "\n\n".join(parts)
        if len(aggregated.strip()) < 100:
            return CompanyResult(
                cnpj_basico=cnpj, discovery_id=discovery_id, website_url=url,
                error=_build_error_summary(result, f"Conteudo insuficiente ({len(aggregated)} chars)"),
                pages_scraped=len(successful_pages), total_pages_attempted=total_pages,
                page_website=pw, page_scraped=ps,
            )

        chunks = process_content(aggregated)
        if not chunks:
            return CompanyResult(
                cnpj_basico=cnpj, discovery_id=discovery_id, website_url=url,
                error=_build_error_summary(result, "Nenhum chunk gerado"),
                pages_scraped=len(successful_pages), total_pages_attempted=total_pages,
                page_website=pw, page_scraped=ps,
            )

        for chunk in chunks:
            if not hasattr(chunk, 'pages_included') or not chunk.pages_included:
                chunk.pages_included = visited[:5]

        return CompanyResult(
            cnpj_basico=cnpj, discovery_id=discovery_id, website_url=url,
            chunks=chunks, success=True,
            pages_scraped=len(successful_pages), total_pages_attempted=total_pages,
            page_website=pw, page_scraped=ps,
        )

    def _aggregate_scrape_meta(self, result: ScrapeResult) -> None:
        self._links_in_html_total += result.links_in_html
        self._links_after_filter_total += result.links_after_filter
        self._links_selected_total += result.links_selected
        self._subpages_attempted_total += result.subpages_attempted
        self._subpages_ok_total += result.subpages_ok
        self._subpages_skipped_total += result.subpages_skipped

        if not result.main_page_ok:
            self._main_page_failures += 1
            reason = result.main_page_fail_reason or "unknown"
            bucket = _bucket_fail_reason(reason)
            self._main_page_fail_reasons[bucket] = self._main_page_fail_reasons.get(bucket, 0) + 1
        if result.links_in_html == 0 and result.main_page_ok:
            self._zero_links_companies += 1
        for cat, count in result.subpage_errors.items():
            self._subpage_error_cats[cat] = self._subpage_error_cats.get(cat, 0) + count

        if result.probe_time_ms > 0:
            self._probe_times.append(result.probe_time_ms)
        if result.probe_ok:
            self._probe_ok += 1
        else:
            self._probe_fail += 1
            reason = result.main_page_fail_reason or "unknown"
            bucket = _bucket_fail_reason(reason)
            self._probe_fail_reasons[bucket] = self._probe_fail_reasons.get(bucket, 0) + 1

        if result.probe_ok and result.main_scrape_time_ms > 0:
            self._main_scrape_times.append(result.main_scrape_time_ms)
        if result.main_page_ok:
            self._main_scrape_ok += 1
        elif result.probe_ok:
            self._main_scrape_fail += 1
            reason = result.main_page_fail_reason or "unknown"
            bucket = _bucket_fail_reason(reason)
            self._main_scrape_fail_reasons[bucket] = self._main_scrape_fail_reasons.get(bucket, 0) + 1

        if result.main_page_ok and result.subpages_time_ms > 0:
            self._subpages_times.append(result.subpages_time_ms)

        if result.subpages_attempted > 0:
            rate = result.subpages_ok / result.subpages_attempted * 100
            self._domain_subpage_success_rates.append(rate)

        if result.subpage_errors and self.total > 0:
            progress = self._processed / self.total
            qi = min(3, int(progress * 4))
            for cat, count in result.subpage_errors.items():
                bucket = self._subpage_errors_by_quartile[qi]
                bucket[cat] = bucket.get(cat, 0) + count

        if result.pages and result.main_page_ok:
            for page in result.pages[1:]:
                if page.response_time_ms > 0:
                    if page.success:
                        bisect.insort(self._subpage_individual_ok, page.response_time_ms)
                        bisect.insort(self._subpage_sem_wait_ok, page.sem_wait_ms)
                        bisect.insort(self._subpage_http_ok, page.http_time_ms)
                    else:
                        bisect.insort(self._subpage_individual_fail, page.response_time_ms)
                        bisect.insort(self._subpage_sem_wait_fail, page.sem_wait_ms)
                        bisect.insort(self._subpage_http_fail, page.http_time_ms)

    async def _flush_buffer(self, force: bool = False):
        async with self._buffer_lock:
            if not self._buffer:
                return
            to_flush = self._buffer
            self._buffer = []
        await self._flush_records(to_flush)

    async def _flush_records(self, to_flush: List[CompanyResult]):
        if not to_flush:
            return
        records = []
        for result in to_flush:
            if result.success and result.chunks:
                for chunk in result.chunks:
                    page_source = None
                    if hasattr(chunk, 'pages_included') and chunk.pages_included:
                        page_source = ','.join(chunk.pages_included[:5])
                    records.append((
                        result.cnpj_basico, result.discovery_id,
                        result.website_url, chunk.index, chunk.total_chunks,
                        chunk.content, chunk.tokens, page_source, None,
                        result.page_website, result.page_scraped,
                    ))
            else:
                records.append((
                    result.cnpj_basico, result.discovery_id,
                    result.website_url, 0, 0, None, 0, None, result.error,
                    result.page_website, result.page_scraped,
                ))
        try:
            db = get_db_service()
            await db.save_scrape_results_mega_batch(records)
            self._flushes_done += 1
            logger.info(f"[Batch {self.batch_id}] Flush #{self._flushes_done}: {len(to_flush)} empresas, {len(records)} records")
        except Exception as e:
            logger.error(f"[Batch {self.batch_id}] Flush error: {e}", exc_info=True)

    async def _load_all_companies(self) -> List[Dict[str, Any]]:
        db = get_db_service()
        all_companies = []
        last_id = 0
        page_size = 5000

        while True:
            if self.limit and len(all_companies) >= self.limit:
                break
            remaining = (self.limit - len(all_companies)) if self.limit else page_size
            fetch_size = min(page_size, remaining)
            companies = await db.get_pending_scrape_companies(
                limit=fetch_size, after_id=last_id, status_filter=self.status_filter,
            )
            if not companies:
                break
            all_companies.extend(companies)
            last_id = max(c['wd_id'] for c in companies)
            if self.limit and len(all_companies) >= self.limit:
                all_companies = all_companies[:self.limit]
                break
        return all_companies

    def get_status(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        processed = self._processed
        throughput = (processed / elapsed * 60) if elapsed > 0 else 0
        remaining = self.total - processed
        eta = (remaining / (throughput / 60)) / 60 if throughput > 0 else None
        success_rate = round(self._success_count / processed * 100, 1) if processed > 0 else 0

        times_sorted = sorted(self._processing_times)
        time_pcts = _percentiles(times_sorted, [50, 60, 70, 80, 90, 95, 99])
        avg_time = round(sum(times_sorted) / len(times_sorted), 1) if times_sorted else 0
        min_time = round(times_sorted[0], 1) if times_sorted else 0
        max_time = round(times_sorted[-1], 1) if times_sorted else 0
        avg_pages = round(sum(self._pages_per_company) / len(self._pages_per_company), 1) if self._pages_per_company else 0

        probe_times_sorted = sorted(self._probe_times)
        main_times_sorted = sorted(self._main_scrape_times)
        sub_times_sorted = sorted(self._subpages_times)

        probe_entered = self._probe_ok + self._probe_fail
        main_entered = self._probe_ok

        stage_funnel = {
            "probe": {
                "entered": probe_entered,
                "ok": self._probe_ok,
                "fail": self._probe_fail,
                "success_rate_pct": round(self._probe_ok / probe_entered * 100, 1) if probe_entered > 0 else 0,
                "fail_reasons": dict(sorted(self._probe_fail_reasons.items(), key=lambda x: -x[1])) if self._probe_fail_reasons else {},
                "time_ms": _percentiles(probe_times_sorted, [50, 75, 90, 95, 99]) if probe_times_sorted else {},
            },
            "main_page": {
                "entered": main_entered,
                "ok": self._main_scrape_ok,
                "fail": self._main_scrape_fail,
                "success_rate_pct": round(self._main_scrape_ok / main_entered * 100, 1) if main_entered > 0 else 0,
                "fail_reasons": dict(sorted(self._main_scrape_fail_reasons.items(), key=lambda x: -x[1])) if self._main_scrape_fail_reasons else {},
                "time_ms": _percentiles(main_times_sorted, [50, 75, 90, 95, 99]) if main_times_sorted else {},
            },
            "subpages": {
                "entered": self._main_scrape_ok,
                "attempted": self._subpages_attempted_total,
                "ok": self._subpages_ok_total,
                "fail": self._subpages_attempted_total - self._subpages_ok_total,
                "skipped_circuit_breaker": self._subpages_skipped_total,
                "success_rate_pct": round(self._subpages_ok_total / self._subpages_attempted_total * 100, 1) if self._subpages_attempted_total > 0 else 0,
                "success_rate_real_pct": round(self._subpages_ok_total / max(1, self._subpages_attempted_total + self._subpages_skipped_total) * 100, 1),
                "fail_reasons": dict(sorted(self._subpage_error_cats.items(), key=lambda x: -x[1])) if self._subpage_error_cats else {},
                "total_time_per_company_ms": _percentiles(sub_times_sorted, [50, 75, 90, 95, 99]) if sub_times_sorted else {},
                "individual_ok_ms": {
                    "count": len(self._subpage_individual_ok),
                    **_percentiles(self._subpage_individual_ok, [50, 75, 90, 95, 99]),
                } if self._subpage_individual_ok else {},
                "individual_fail_ms": {
                    "count": len(self._subpage_individual_fail),
                    **_percentiles(self._subpage_individual_fail, [50, 75, 90, 95, 99]),
                } if self._subpage_individual_fail else {},
                "sem_wait_ok_ms": {
                    "count": len(self._subpage_sem_wait_ok),
                    **_percentiles(self._subpage_sem_wait_ok, [50, 75, 90, 95, 99]),
                } if self._subpage_sem_wait_ok else {},
                "sem_wait_fail_ms": {
                    "count": len(self._subpage_sem_wait_fail),
                    **_percentiles(self._subpage_sem_wait_fail, [50, 75, 90, 95, 99]),
                } if self._subpage_sem_wait_fail else {},
                "http_time_ok_ms": {
                    "count": len(self._subpage_http_ok),
                    **_percentiles(self._subpage_http_ok, [50, 75, 90, 95, 99]),
                } if self._subpage_http_ok else {},
                "http_time_fail_ms": {
                    "count": len(self._subpage_http_fail),
                    **_percentiles(self._subpage_http_fail, [50, 75, 90, 95, 99]),
                } if self._subpage_http_fail else {},
            },
            "overall_funnel_pct": success_rate,
        }

        http_histogram = _http_time_histogram(self._subpage_http_ok, self._subpage_http_fail)

        rates = self._domain_subpage_success_rates
        domain_dist = {}
        if rates:
            domain_dist = {
                "total_domains_with_subpages": len(rates),
                "100pct_success": sum(1 for r in rates if r >= 100),
                "50_99pct_success": sum(1 for r in rates if 50 <= r < 100),
                "1_49pct_success": sum(1 for r in rates if 0 < r < 50),
                "0pct_success": sum(1 for r in rates if r == 0),
                "avg_success_rate_pct": round(sum(rates) / len(rates), 1),
            }

        error_timeline = {
            "q1_0_25pct": self._subpage_errors_by_quartile[0] or {},
            "q2_25_50pct": self._subpage_errors_by_quartile[1] or {},
            "q3_50_75pct": self._subpage_errors_by_quartile[2] or {},
            "q4_75_100pct": self._subpage_errors_by_quartile[3] or {},
        }

        links_in_html = self._links_in_html_total
        links_selected = self._links_selected_total
        subpages_attempted = self._subpages_attempted_total
        subpages_ok = self._subpages_ok_total

        infra = self._get_infrastructure_stats()
        diagnosis = _build_failure_diagnosis(self._main_page_fail_reasons, processed)

        inst_elapsed = elapsed
        inst_tp = (processed / inst_elapsed * 60) if inst_elapsed > 0 else 0

        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "total": self.total,
            "processed": processed,
            "success_count": self._success_count,
            "error_count": self._error_count,
            "success_rate_pct": success_rate,
            "remaining": remaining,
            "in_progress": self._in_progress,
            "peak_in_progress": self._peak_in_progress,
            "throughput_per_min": round(throughput, 1),
            "eta_minutes": round(eta, 1) if eta else None,
            "elapsed_seconds": round(elapsed, 1),
            "flushes_done": self._flushes_done,
            "buffer_size": self.buffer_size,
            "processing_time_ms": {"avg": avg_time, "min": min_time, "max": max_time, **time_pcts},
            "error_breakdown": dict(sorted(self._error_categories.items(), key=lambda x: -x[1])),
            "pages_per_company_avg": avg_pages,
            "total_retries": self._retries_total,
            "failure_diagnosis": diagnosis,
            "stage_funnel": stage_funnel,
            "http_time_histogram": http_histogram,
            "domain_success_distribution": domain_dist,
            "error_timeline_by_quartile": error_timeline,
            "subpage_pipeline": {
                "links_in_html_total": links_in_html,
                "links_after_filter": self._links_after_filter_total,
                "links_selected": links_selected,
                "avg_links_per_company": round(links_in_html / processed, 1) if processed > 0 else 0,
                "avg_selected_per_company": round(links_selected / processed, 1) if processed > 0 else 0,
                "link_filter_rate_pct": round((1 - links_selected / links_in_html) * 100, 1) if links_in_html > 0 else 0,
                "zero_links_companies": self._zero_links_companies,
                "zero_links_pct": round(self._zero_links_companies / processed * 100, 1) if processed > 0 else 0,
                "main_page_failures": self._main_page_failures,
                "main_page_success_rate_pct": round((processed - self._main_page_failures) / processed * 100, 1) if processed > 0 else 0,
                "main_page_fail_reasons": dict(sorted(self._main_page_fail_reasons.items(), key=lambda x: -x[1])),
                "subpages_attempted": subpages_attempted,
                "subpages_ok": subpages_ok,
                "subpages_failed": subpages_attempted - subpages_ok,
                "subpages_skipped": self._subpages_skipped_total,
                "subpage_success_rate_pct": round(subpages_ok / subpages_attempted * 100, 1) if subpages_attempted > 0 else 0,
                "avg_subpages_per_company": round(subpages_attempted / processed, 1) if processed > 0 else 0,
                "subpage_error_breakdown": dict(sorted(self._subpage_error_cats.items(), key=lambda x: -x[1])),
            },
            "infrastructure": infra,
            "last_errors": self.last_errors,
            "instances": [{
                "id": 0, "status": self.status,
                "processed": processed, "success": self._success_count,
                "errors": self._error_count, "throughput_per_min": round(inst_tp, 1),
            }],
        }

    def _get_infrastructure_stats(self) -> dict:
        stats: Dict[str, Any] = {}
        try:
            from app.services.scraper_manager.proxy_manager import proxy_pool
            pool_status = proxy_pool.get_status()
            if self._proxy_health:
                pool_status["health_check"] = self._proxy_health
            stats["proxy"] = pool_status
        except Exception:
            stats["proxy"] = {"error": "unavailable"}

        try:
            from app.services.scraper.http_client import get_connection_stats
            stats["connections"] = get_connection_stats()
            stats["connections"]["samples"] = self._conn_samples_summary()
        except Exception:
            stats["connections"] = {"error": "unavailable"}

        try:
            from app.services.scraper.constants import (
                REQUEST_TIMEOUT, SUBPAGE_TIMEOUT, MAX_SUBPAGES,
                PER_DOMAIN_CONCURRENT, STAGGER_DELAY,
                CIRCUIT_BREAKER_THRESHOLD, FLUSH_SIZE, MIN_CONTENT_LENGTH,
                MAX_CONCURRENT_711, MAX_CONCURRENT_DECODO,
            )
            stats["config"] = {
                "request_timeout": REQUEST_TIMEOUT,
                "subpage_timeout": SUBPAGE_TIMEOUT,
                "max_subpages": MAX_SUBPAGES,
                "per_domain_concurrent": PER_DOMAIN_CONCURRENT,
                "stagger_delay": STAGGER_DELAY,
                "circuit_breaker_threshold": CIRCUIT_BREAKER_THRESHOLD,
                "flush_size": FLUSH_SIZE,
                "min_content_length": MIN_CONTENT_LENGTH,
                "max_concurrent_711": MAX_CONCURRENT_711,
                "max_concurrent_decodo": MAX_CONCURRENT_DECODO,
                "chunk_size": self.chunk_size,
            }
        except Exception:
            pass
        return stats

    def _conn_samples_summary(self) -> dict:
        samples = self._connection_samples
        if not samples:
            return {}
        vals = sorted(samples)
        n = len(vals)
        return {
            "count": n,
            "min": vals[0],
            "max": vals[-1],
            "avg": round(sum(vals) / n, 1),
            "p50": vals[int(n * 0.5)],
            "p75": vals[int(n * 0.75)] if n > 3 else vals[-1],
            "p90": vals[int(n * 0.9)] if n > 9 else vals[-1],
            "p95": vals[int(n * 0.95)] if n > 19 else vals[-1],
        }

    async def cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


_active_batch: Optional[BatchScrapeProcessor] = None


def get_active_batch() -> Optional[BatchScrapeProcessor]:
    return _active_batch


def set_active_batch(batch: Optional[BatchScrapeProcessor]):
    global _active_batch
    _active_batch = batch
