"""
Batch Scrape Processor — pipeline de scraping em massa.

N instâncias paralelas, cada uma com workers, processando partições diferentes.
Pipeline único (sem fast/retry track). Workers controlam concorrência.
"""

import asyncio
import bisect
import concurrent.futures
import json
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from app.services.scraper.scraper_service import scrape_all_subpages
from app.services.scraper.models import ScrapeResult
from app.core.chunking import process_content
from app.services.database_service import get_db_service
from app.services.scraper.constants import WORKERS_PER_INSTANCE, NUM_INSTANCES, FLUSH_SIZE

logger = logging.getLogger(__name__)

TRANSIENT_KEYWORDS = frozenset([
    "timeout", "429", "rate limit", "connection reset",
    "connection refused", "connection error", "temporarily",
    "server error", "502", "503", "504",
])

PERMANENT_KEYWORDS = frozenset([
    "dns", "resolve", "404", "not found", "ssl",
    "certificate", "cloudflare", "captcha",
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


def _build_error_summary(scrape_result: ScrapeResult, fallback_error: str = "") -> str:
    """Monta JSON estruturado com diagnóstico completo do erro de scraping."""
    pages = scrape_result.pages or []
    successful = [p for p in pages if p.success]
    failed = [p for p in pages if not p.success]

    fail_reason = scrape_result.main_page_fail_reason
    bucket = _bucket_fail_reason(fail_reason) if fail_reason else None

    summary = {
        "error_category": bucket or _classify_error(fallback_error),
        "main_page": {
            "ok": scrape_result.main_page_ok,
            "fail_reason": bucket,
        },
        "subpages": {
            "attempted": scrape_result.subpages_attempted,
            "ok": scrape_result.subpages_ok,
            "errors": scrape_result.subpage_errors or {},
        },
        "pages_total": len(pages),
        "pages_ok": len(successful),
        "pages_failed": len(failed),
        "links": {
            "in_html": scrape_result.links_in_html,
            "after_filter": scrape_result.links_after_filter,
            "selected": scrape_result.links_selected,
        },
        "processing_time_ms": round(scrape_result.total_time_ms, 1),
    }

    if not scrape_result.main_page_ok:
        summary["resumo"] = f"Main page falhou: {bucket or fail_reason or 'desconhecido'}"
    elif len(successful) == 0:
        summary["resumo"] = "Main page ok mas conteúdo insuficiente"
    elif scrape_result.subpages_attempted > 0:
        fail_rate = (scrape_result.subpages_attempted - scrape_result.subpages_ok)
        summary["resumo"] = (
            f"Main ok, {len(successful)} páginas ok, "
            f"{fail_rate}/{scrape_result.subpages_attempted} subpages falharam"
        )
    else:
        summary["resumo"] = fallback_error or "Erro desconhecido"

    return json.dumps(summary, ensure_ascii=False)


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


class BatchInstance:
    """Uma instância individual com seus próprios workers."""

    def __init__(self, instance_id: int, batch_id: str, worker_count: int,
                 flush_size: int, companies: List[Dict[str, Any]]):
        self.instance_id = instance_id
        self.batch_id = batch_id
        self.worker_count = worker_count
        self.flush_size = flush_size
        self.companies = companies

        self._queue: asyncio.Queue = asyncio.Queue(maxsize=worker_count * 2)
        self._buffer: List[CompanyResult] = []
        self._buffer_lock = asyncio.Lock()

        self.total = len(companies)
        self.processed = 0
        self.success_count = 0
        self.error_count = 0
        self.in_progress = 0
        self.flushes_done = 0
        self.last_errors: List[dict] = []
        self.status = "idle"
        self._start_time: float = 0

        self._processing_times_sorted: List[float] = []
        self._error_categories: Dict[str, int] = {}
        self._pages_per_company: List[int] = []
        self._retries_total: int = 0
        self._peak_in_progress: int = 0

        self._links_in_html_total: int = 0
        self._links_after_filter_total: int = 0
        self._links_selected_total: int = 0
        self._subpages_attempted_total: int = 0
        self._subpages_ok_total: int = 0
        self._subpage_error_cats: Dict[str, int] = {}
        self._main_page_failures: int = 0
        self._main_page_fail_reasons: Dict[str, int] = {}
        self._zero_links_companies: int = 0

        self._probe_times: List[float] = []
        self._probe_ok: int = 0
        self._probe_fail: int = 0
        self._main_scrape_times: List[float] = []
        self._main_scrape_ok: int = 0
        self._main_scrape_fail: int = 0
        self._subpages_times: List[float] = []

    async def run(self):
        self.status = "running"
        self._start_time = time.time()
        label = f"[Batch {self.batch_id} I{self.instance_id}]"
        logger.info(f"{label} Iniciando: {self.total} empresas, {self.worker_count} workers")

        try:
            ramp_batch = 200
            workers = []
            for i in range(self.worker_count):
                workers.append(asyncio.create_task(self._worker(i)))
                if (i + 1) % ramp_batch == 0 and i + 1 < self.worker_count:
                    await asyncio.sleep(0.1)

            for company in self.companies:
                await self._queue.put(company)
            for _ in range(self.worker_count):
                await self._queue.put(None)

            await asyncio.gather(*workers)
            await self._flush_buffer(force=True)

            self.status = "completed"
            elapsed = time.time() - self._start_time
            logger.info(f"{label} Concluido em {elapsed:.0f}s: {self.success_count} ok, {self.error_count} erros")
        except asyncio.CancelledError:
            await self._flush_buffer(force=True)
            self.status = "cancelled"
        except Exception as e:
            logger.error(f"{label} Erro fatal: {e}", exc_info=True)
            await self._flush_buffer(force=True)
            self.status = "error"

    async def _worker(self, worker_id: int):
        while True:
            item = await self._queue.get()
            if item is None:
                break

            self.in_progress += 1
            self._peak_in_progress = max(self._peak_in_progress, self.in_progress)

            t0 = time.perf_counter()
            result = await self._process_company(item, worker_id)
            result.processing_time_ms = (time.perf_counter() - t0) * 1000

            self.in_progress -= 1

            pending_flush = None
            async with self._buffer_lock:
                self._buffer.append(result)
                self.processed += 1
                bisect.insort(self._processing_times_sorted, result.processing_time_ms)
                if result.pages_scraped > 0:
                    self._pages_per_company.append(result.pages_scraped)
                self._retries_total += result.retries_used

                if result.success:
                    self.success_count += 1
                else:
                    self.error_count += 1
                    cat = _classify_error(result.error or "")
                    self._error_categories[cat] = self._error_categories.get(cat, 0) + 1

                if len(self._buffer) >= self.flush_size:
                    pending_flush = self._buffer
                    self._buffer = []

            if pending_flush is not None:
                await self._flush_buffer_data(pending_flush)

    async def _process_company(self, company: Dict[str, Any], worker_id: int) -> CompanyResult:
        cnpj = company['cnpj_basico']
        url = company['website_url']
        discovery_id = company.get('wd_id')
        max_retries = 2

        for attempt in range(max_retries + 1):
            try:
                result = await scrape_all_subpages(
                    url=url, max_subpages=15,
                    ctx_label=f"[B{self.batch_id}I{self.instance_id}]",
                    request_id=cnpj,
                )
                self._aggregate_scrape_meta(result)
                pages = result.pages
                total_pages = len(pages) if pages else 0
                successful_pages = [p for p in (pages or []) if p.success]

                if not successful_pages:
                    error_msg = "Nenhum conteudo obtido"
                    if pages:
                        first_err = next((p.error for p in pages if p.error), None)
                        if first_err:
                            error_msg = f"Nenhum conteudo obtido: {first_err}"
                    if attempt < max_retries and _is_transient(error_msg):
                        await asyncio.sleep(2 ** (attempt + 1))
                        continue
                    return CompanyResult(
                        cnpj_basico=cnpj, discovery_id=discovery_id,
                        website_url=url,
                        error=_build_error_summary(result, error_msg),
                        total_pages_attempted=total_pages, retries_used=attempt,
                    )

                parts = []
                visited = []
                for page in successful_pages:
                    parts.append(f"--- PAGE START: {page.url} ---\n{page.content}\n--- PAGE END ---")
                    visited.append(page.url)

                aggregated = "\n\n".join(parts)
                if len(aggregated.strip()) < 100:
                    return CompanyResult(
                        cnpj_basico=cnpj, discovery_id=discovery_id,
                        website_url=url,
                        error=_build_error_summary(result, f"Conteudo insuficiente ({len(aggregated)} chars)"),
                        pages_scraped=len(successful_pages),
                        total_pages_attempted=total_pages, retries_used=attempt,
                    )

                chunks = process_content(aggregated)
                if not chunks:
                    return CompanyResult(
                        cnpj_basico=cnpj, discovery_id=discovery_id,
                        website_url=url,
                        error=_build_error_summary(result, "Nenhum chunk gerado"),
                        pages_scraped=len(successful_pages),
                        total_pages_attempted=total_pages, retries_used=attempt,
                    )

                for chunk in chunks:
                    if not hasattr(chunk, 'pages_included') or not chunk.pages_included:
                        chunk.pages_included = visited[:5]

                return CompanyResult(
                    cnpj_basico=cnpj, discovery_id=discovery_id,
                    website_url=url, chunks=chunks, success=True,
                    pages_scraped=len(successful_pages),
                    total_pages_attempted=total_pages, retries_used=attempt,
                )
            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                if attempt < max_retries and _is_transient(error_msg):
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                self._record_error(cnpj, url, error_msg)
                exc_summary = json.dumps({
                    "error_category": _classify_error(error_msg),
                    "main_page": {"ok": False, "fail_reason": None},
                    "subpages": {"attempted": 0, "ok": 0, "errors": {}},
                    "pages_total": 0, "pages_ok": 0, "pages_failed": 0,
                    "resumo": f"Exceção no pipeline: {error_msg[:200]}",
                    "processing_time_ms": 0,
                }, ensure_ascii=False)
                return CompanyResult(
                    cnpj_basico=cnpj, discovery_id=discovery_id,
                    website_url=url, error=exc_summary,
                    retries_used=attempt,
                )

        max_retry_summary = json.dumps({
            "error_category": "max_retries",
            "main_page": {"ok": False, "fail_reason": None},
            "subpages": {"attempted": 0, "ok": 0, "errors": {}},
            "pages_total": 0, "pages_ok": 0, "pages_failed": 0,
            "resumo": "Esgotou tentativas de retry",
            "processing_time_ms": 0,
        }, ensure_ascii=False)
        return CompanyResult(
            cnpj_basico=cnpj, discovery_id=discovery_id,
            website_url=url, error=max_retry_summary, retries_used=max_retries,
        )

    def _aggregate_scrape_meta(self, result) -> None:
        self._links_in_html_total += result.links_in_html
        self._links_after_filter_total += result.links_after_filter
        self._links_selected_total += result.links_selected
        self._subpages_attempted_total += result.subpages_attempted
        self._subpages_ok_total += result.subpages_ok
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

        if result.probe_ok and result.main_scrape_time_ms > 0:
            self._main_scrape_times.append(result.main_scrape_time_ms)
        if result.main_page_ok:
            self._main_scrape_ok += 1
        elif result.probe_ok:
            self._main_scrape_fail += 1

        if result.main_page_ok and result.subpages_time_ms > 0:
            self._subpages_times.append(result.subpages_time_ms)

    async def _flush_buffer(self, force: bool = False):
        if force:
            async with self._buffer_lock:
                to_flush = self._buffer
                self._buffer = []
        else:
            to_flush = self._buffer
            self._buffer = []
        if to_flush:
            await self._flush_buffer_data(to_flush)

    async def _flush_buffer_data(self, to_flush: list):
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
                    ))
            else:
                records.append((
                    result.cnpj_basico, result.discovery_id,
                    result.website_url, 0, 0, None, 0, None, result.error,
                ))
        try:
            db = get_db_service()
            await db.save_scrape_results_mega_batch(records)
            self.flushes_done += 1
            logger.info(
                f"[Batch {self.batch_id} I{self.instance_id}] Flush #{self.flushes_done}: "
                f"{len(to_flush)} empresas, {len(records)} records"
            )
        except Exception as e:
            logger.error(f"[Batch {self.batch_id} I{self.instance_id}] Flush error: {e}", exc_info=True)

    def _record_error(self, cnpj: str, url: str, error: str):
        self.last_errors.append({"cnpj": cnpj, "url": url[:80], "error": error[:200], "time": time.time()})
        if len(self.last_errors) > 10:
            self.last_errors = self.last_errors[-10:]


class BatchScrapeProcessor:
    """Orquestrador multi-instância."""

    def __init__(
        self,
        worker_count: int = WORKERS_PER_INSTANCE * NUM_INSTANCES,
        flush_size: int = FLUSH_SIZE,
        status_filter: Optional[List[str]] = None,
        limit: Optional[int] = None,
        instances: int = NUM_INSTANCES,
    ):
        self.batch_id = str(uuid.uuid4())[:8]
        self.worker_count = worker_count
        self.flush_size = flush_size
        self.status_filter = status_filter or ['muito_alto', 'alto', 'medio']
        self.limit = limit
        self.num_instances = instances

        self._task: Optional[asyncio.Task] = None
        self._instances: List[BatchInstance] = []
        self.total = 0
        self.status = "idle"
        self._start_time: float = 0
        self._proxy_health: dict = {}

    @property
    def processed(self) -> int:
        return sum(i.processed for i in self._instances)

    @property
    def success_count(self) -> int:
        return sum(i.success_count for i in self._instances)

    @property
    def error_count(self) -> int:
        return sum(i.error_count for i in self._instances)

    @property
    def in_progress(self) -> int:
        return sum(i.in_progress for i in self._instances)

    @property
    def flushes_done(self) -> int:
        return sum(i.flushes_done for i in self._instances)

    @property
    def last_errors(self) -> List[dict]:
        all_errs = []
        for inst in self._instances:
            all_errs.extend(inst.last_errors)
        all_errs.sort(key=lambda e: e.get('time', 0), reverse=True)
        return all_errs[:10]

    @property
    def buffer_size(self) -> int:
        return sum(len(i._buffer) for i in self._instances)

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

        loop = asyncio.get_running_loop()
        loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=400))

        from app.services.scraper_manager.proxy_manager import proxy_pool

        proxy_count = await proxy_pool.preload()
        if proxy_count == 0:
            logger.error(f"[Batch {self.batch_id}] ZERO proxies! Abortando.")
            self.status = "error"
            return

        self._proxy_health = await proxy_pool.health_check()
        if not self._proxy_health.get("healthy", False):
            logger.error(f"[Batch {self.batch_id}] Gateway proxy falhou! Abortando.")
            self.status = "error"
            return

        logger.info(f"[Batch {self.batch_id}] Gateway OK. Carregando empresas...")
        all_companies = await self._load_all_companies()

        if not all_companies:
            logger.warning(f"[Batch {self.batch_id}] Nenhuma empresa pendente.")
            self.status = "completed"
            return

        self.total = len(all_companies)
        workers_per_instance = max(1, self.worker_count // self.num_instances)
        partitions = self._partition(all_companies, self.num_instances)

        logger.info(
            f"[Batch {self.batch_id}] {self.total} empresas, "
            f"{self.num_instances} instâncias x {workers_per_instance} workers"
        )

        try:
            self._instances = []
            tasks = []
            for idx, partition in enumerate(partitions):
                if not partition:
                    continue
                inst = BatchInstance(
                    instance_id=idx, batch_id=self.batch_id,
                    worker_count=workers_per_instance,
                    flush_size=self.flush_size, companies=partition,
                )
                self._instances.append(inst)
                tasks.append(asyncio.create_task(inst.run()))

            await asyncio.gather(*tasks)
            self.status = "completed"
            elapsed = time.time() - self._start_time
            logger.info(
                f"[Batch {self.batch_id}] CONCLUIDO em {elapsed:.0f}s: "
                f"{self.success_count} ok, {self.error_count} erros"
            )
        except asyncio.CancelledError:
            self.status = "cancelled"
        except Exception as e:
            logger.error(f"[Batch {self.batch_id}] Erro fatal: {e}", exc_info=True)
            self.status = "error"

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

    @staticmethod
    def _partition(items: list, n: int) -> List[list]:
        partitions = [[] for _ in range(n)]
        for idx, item in enumerate(items):
            partitions[idx % n].append(item)
        return partitions

    def get_status(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        processed = self.processed
        throughput = (processed / elapsed * 60) if elapsed > 0 else 0
        remaining = self.total - processed
        eta = (remaining / (throughput / 60)) / 60 if throughput > 0 else None

        all_times: List[float] = []
        all_error_cats: Dict[str, int] = {}
        all_pages: List[int] = []
        total_retries = 0
        peak_in_progress = 0
        instance_stats = []

        for inst in self._instances:
            inst_elapsed = time.time() - inst._start_time if inst._start_time else 0
            inst_tp = (inst.processed / inst_elapsed * 60) if inst_elapsed > 0 else 0
            instance_stats.append({
                "id": inst.instance_id, "status": inst.status,
                "processed": inst.processed, "success": inst.success_count,
                "errors": inst.error_count, "throughput_per_min": round(inst_tp, 1),
            })
            all_times.extend(inst._processing_times_sorted)
            all_pages.extend(inst._pages_per_company)
            total_retries += inst._retries_total
            peak_in_progress += inst._peak_in_progress
            for cat, count in inst._error_categories.items():
                all_error_cats[cat] = all_error_cats.get(cat, 0) + count

        links_in_html = sum(i._links_in_html_total for i in self._instances)
        links_after_filter = sum(i._links_after_filter_total for i in self._instances)
        links_selected = sum(i._links_selected_total for i in self._instances)
        subpages_attempted = sum(i._subpages_attempted_total for i in self._instances)
        subpages_ok = sum(i._subpages_ok_total for i in self._instances)
        main_page_failures = sum(i._main_page_failures for i in self._instances)
        main_page_fail_reasons: Dict[str, int] = {}
        for inst in self._instances:
            for reason, count in inst._main_page_fail_reasons.items():
                main_page_fail_reasons[reason] = main_page_fail_reasons.get(reason, 0) + count
        zero_links = sum(i._zero_links_companies for i in self._instances)
        subpage_err_cats: Dict[str, int] = {}
        for inst in self._instances:
            for cat, count in inst._subpage_error_cats.items():
                subpage_err_cats[cat] = subpage_err_cats.get(cat, 0) + count

        all_times.sort()
        time_percentiles = _percentiles(all_times, [50, 60, 70, 80, 90, 95, 99])
        avg_time = round(sum(all_times) / len(all_times), 1) if all_times else 0
        min_time = round(all_times[0], 1) if all_times else 0
        max_time = round(all_times[-1], 1) if all_times else 0
        avg_pages = round(sum(all_pages) / len(all_pages), 1) if all_pages else 0
        success_rate = round(self.success_count / processed * 100, 1) if processed > 0 else 0

        infra = self._get_infrastructure_stats()
        diagnosis = _build_failure_diagnosis(main_page_fail_reasons, processed)

        probe_times_all: List[float] = []
        main_times_all: List[float] = []
        sub_times_all: List[float] = []
        probe_ok_total = 0
        probe_fail_total = 0
        main_ok_total = 0
        main_fail_total = 0
        for inst in self._instances:
            probe_times_all.extend(inst._probe_times)
            main_times_all.extend(inst._main_scrape_times)
            sub_times_all.extend(inst._subpages_times)
            probe_ok_total += inst._probe_ok
            probe_fail_total += inst._probe_fail
            main_ok_total += inst._main_scrape_ok
            main_fail_total += inst._main_scrape_fail

        probe_times_all.sort()
        main_times_all.sort()
        sub_times_all.sort()

        probe_entered = probe_ok_total + probe_fail_total
        main_entered = probe_ok_total
        sub_entered = main_ok_total

        stage_funnel = {
            "probe": {
                "entered": probe_entered,
                "ok": probe_ok_total,
                "fail": probe_fail_total,
                "success_rate_pct": round(probe_ok_total / probe_entered * 100, 1) if probe_entered > 0 else 0,
                "time_ms": _percentiles(probe_times_all, [50, 75, 90, 95, 99]) if probe_times_all else {},
            },
            "main_page": {
                "entered": main_entered,
                "ok": main_ok_total,
                "fail": main_fail_total,
                "success_rate_pct": round(main_ok_total / main_entered * 100, 1) if main_entered > 0 else 0,
                "time_ms": _percentiles(main_times_all, [50, 75, 90, 95, 99]) if main_times_all else {},
            },
            "subpages": {
                "entered": sub_entered,
                "attempted": subpages_attempted,
                "ok": subpages_ok,
                "fail": subpages_attempted - subpages_ok,
                "success_rate_pct": round(subpages_ok / subpages_attempted * 100, 1) if subpages_attempted > 0 else 0,
                "time_ms": _percentiles(sub_times_all, [50, 75, 90, 95, 99]) if sub_times_all else {},
            },
            "overall_funnel_pct": round(self.success_count / processed * 100, 1) if processed > 0 else 0,
        }

        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "total": self.total,
            "processed": processed,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "success_rate_pct": success_rate,
            "remaining": remaining,
            "in_progress": self.in_progress,
            "peak_in_progress": peak_in_progress,
            "throughput_per_min": round(throughput, 1),
            "eta_minutes": round(eta, 1) if eta else None,
            "elapsed_seconds": round(elapsed, 1),
            "flushes_done": self.flushes_done,
            "buffer_size": self.buffer_size,
            "processing_time_ms": {"avg": avg_time, "min": min_time, "max": max_time, **time_percentiles},
            "error_breakdown": dict(sorted(all_error_cats.items(), key=lambda x: -x[1])),
            "pages_per_company_avg": avg_pages,
            "total_retries": total_retries,
            "failure_diagnosis": diagnosis,
            "stage_funnel": stage_funnel,
            "subpage_pipeline": {
                "links_in_html_total": links_in_html,
                "links_after_filter": links_after_filter,
                "links_selected": links_selected,
                "avg_links_per_company": round(links_in_html / processed, 1) if processed > 0 else 0,
                "avg_selected_per_company": round(links_selected / processed, 1) if processed > 0 else 0,
                "link_filter_rate_pct": round((1 - links_selected / links_in_html) * 100, 1) if links_in_html > 0 else 0,
                "zero_links_companies": zero_links,
                "zero_links_pct": round(zero_links / processed * 100, 1) if processed > 0 else 0,
                "main_page_failures": main_page_failures,
                "main_page_success_rate_pct": round((processed - main_page_failures) / processed * 100, 1) if processed > 0 else 0,
                "main_page_fail_reasons": dict(sorted(main_page_fail_reasons.items(), key=lambda x: -x[1])),
                "subpages_attempted": subpages_attempted,
                "subpages_ok": subpages_ok,
                "subpages_failed": subpages_attempted - subpages_ok,
                "subpage_success_rate_pct": round(subpages_ok / subpages_attempted * 100, 1) if subpages_attempted > 0 else 0,
                "avg_subpages_per_company": round(subpages_attempted / processed, 1) if processed > 0 else 0,
                "subpage_error_breakdown": dict(sorted(subpage_err_cats.items(), key=lambda x: -x[1])),
            },
            "infrastructure": infra,
            "last_errors": self.last_errors,
            "instances": instance_stats,
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
            from app.services.scraper.constants import (
                REQUEST_TIMEOUT, PROBE_TIMEOUT, MAX_RETRIES, RETRY_DELAY,
                MAX_SUBPAGES, PER_DOMAIN_CONCURRENT, WORKERS_PER_INSTANCE,
                NUM_INSTANCES, FLUSH_SIZE, MIN_CONTENT_LENGTH,
            )
            stats["config"] = {
                "request_timeout": REQUEST_TIMEOUT,
                "probe_timeout": PROBE_TIMEOUT,
                "max_retries": MAX_RETRIES,
                "retry_delay": RETRY_DELAY,
                "max_subpages": MAX_SUBPAGES,
                "per_domain_concurrent": PER_DOMAIN_CONCURRENT,
                "workers_per_instance": WORKERS_PER_INSTANCE,
                "num_instances": NUM_INSTANCES,
                "flush_size": FLUSH_SIZE,
                "min_content_length": MIN_CONTENT_LENGTH,
            }
        except Exception:
            pass

        return stats

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
