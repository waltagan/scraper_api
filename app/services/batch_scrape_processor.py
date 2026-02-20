"""
Batch Scrape Processor - Pipeline de scraping em massa.

Suporta N instâncias paralelas, cada uma com seus próprios workers,
processando partições diferentes das empresas pendentes.
"""

import asyncio
import bisect
import concurrent.futures
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from app.services.scraper import scrape_all_subpages
from app.core.chunking import process_content
from app.services.database_service import get_db_service

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


def _percentiles(sorted_values: List[float], pcts: List[int]) -> Dict[str, float]:
    n = len(sorted_values)
    if n == 0:
        return {f"p{p}": 0 for p in pcts}
    result = {}
    for p in pcts:
        idx = int(n * p / 100)
        idx = min(idx, n - 1)
        result[f"p{p}"] = round(sorted_values[idx], 1)
    return result


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
    """Uma instância individual de batch processing com seus próprios workers."""

    def __init__(
        self,
        instance_id: int,
        batch_id: str,
        worker_count: int,
        flush_size: int,
        companies: List[Dict[str, Any]],
    ):
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

    async def run(self):
        """Executa esta instância: carrega queue, roda workers, flush final."""
        self.status = "running"
        self._start_time = time.time()
        label = f"[Batch {self.batch_id} I{self.instance_id}]"

        logger.info(
            f"{label} Iniciando: {self.total} empresas, {self.worker_count} workers"
        )

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
            logger.info(
                f"{label} Concluido em {elapsed:.0f}s: "
                f"{self.success_count} sucesso, {self.error_count} erros"
            )
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
            elapsed_ms = (time.perf_counter() - t0) * 1000
            result.processing_time_ms = elapsed_ms

            self.in_progress -= 1

            pending_flush = None
            async with self._buffer_lock:
                self._buffer.append(result)
                self.processed += 1

                bisect.insort(self._processing_times_sorted, elapsed_ms)
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

    async def _process_company(
        self, company: Dict[str, Any], worker_id: int
    ) -> CompanyResult:
        cnpj = company['cnpj_basico']
        url = company['website_url']
        discovery_id = company.get('wd_id')
        max_retries = 2

        for attempt in range(max_retries + 1):
            try:
                pages = await scrape_all_subpages(
                    url=url, max_subpages=50,
                    ctx_label=f"[B{self.batch_id}I{self.instance_id}]",
                    request_id=cnpj,
                )

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
                        website_url=url, error=error_msg[:500],
                        total_pages_attempted=total_pages, retries_used=attempt,
                    )

                parts = []
                visited = []
                for page in successful_pages:
                    parts.append(
                        f"--- PAGE START: {page.url} ---\n{page.content}\n--- PAGE END ---"
                    )
                    visited.append(page.url)

                aggregated = "\n\n".join(parts)
                if len(aggregated.strip()) < 100:
                    return CompanyResult(
                        cnpj_basico=cnpj, discovery_id=discovery_id,
                        website_url=url,
                        error=f"Conteudo agregado insuficiente ({len(aggregated)} chars)",
                        pages_scraped=len(successful_pages),
                        total_pages_attempted=total_pages, retries_used=attempt,
                    )

                chunks = process_content(aggregated)
                if not chunks:
                    return CompanyResult(
                        cnpj_basico=cnpj, discovery_id=discovery_id,
                        website_url=url, error="Nenhum chunk gerado apos processamento",
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

                short_tb = traceback.format_exc()[-300:]
                self._record_error(cnpj, url, error_msg)
                return CompanyResult(
                    cnpj_basico=cnpj, discovery_id=discovery_id,
                    website_url=url, error=f"{error_msg} | {short_tb}"[:500],
                    retries_used=attempt,
                )

        return CompanyResult(
            cnpj_basico=cnpj, discovery_id=discovery_id,
            website_url=url, error="Maximo de retries atingido",
            retries_used=max_retries,
        )

    async def _flush_buffer(self, force: bool = False):
        """Flush chamado em contextos onde o buffer ainda não foi extraído."""
        if not force:
            to_flush = self._buffer
            self._buffer = []
        else:
            async with self._buffer_lock:
                to_flush = self._buffer
                self._buffer = []

        if to_flush:
            await self._flush_buffer_data(to_flush)

    async def _flush_buffer_data(self, to_flush: list):
        """Escreve resultados no DB — executa FORA do lock para não bloquear workers."""
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
            label = f"[Batch {self.batch_id} I{self.instance_id}]"
            logger.info(
                f"{label} Flush #{self.flushes_done}: "
                f"{len(to_flush)} empresas, {len(records)} records"
            )
        except Exception as e:
            logger.error(f"[Batch {self.batch_id} I{self.instance_id}] Flush error: {e}", exc_info=True)
            self._record_error("FLUSH", "DB", str(e))

    def _record_error(self, cnpj: str, url: str, error: str):
        self.last_errors.append({
            "cnpj": cnpj, "url": url[:80], "error": error[:200],
            "time": time.time(),
        })
        if len(self.last_errors) > 10:
            self.last_errors = self.last_errors[-10:]


class BatchScrapeProcessor:
    """
    Orquestrador multi-instância.

    Carrega todas as empresas pendentes, divide em N partições iguais,
    e lança N BatchInstance em paralelo, cada uma com seus workers.
    """

    def __init__(
        self,
        worker_count: int = 2000,
        flush_size: int = 1000,
        status_filter: Optional[List[str]] = None,
        limit: Optional[int] = None,
        instances: int = 10,
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
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=400)
        )

        from app.services.scraper.constants import FAST_TRACK_CONFIG, scraper_config
        from app.services.scraper_manager import concurrency_manager
        from app.services.scraper_manager.proxy_manager import proxy_pool
        scraper_config.update(**FAST_TRACK_CONFIG)
        concurrency_manager.update_limits(
            global_limit=FAST_TRACK_CONFIG.get('site_semaphore_limit', 5000),
            per_domain_limit=FAST_TRACK_CONFIG.get('per_domain_limit', 25),
        )

        proxy_count = await proxy_pool.preload()
        if proxy_count == 0:
            logger.error(f"[Batch {self.batch_id}] ❌ ZERO proxies! Abortando.")
            self.status = "error"
            return

        # Carregar TODAS as empresas pendentes de uma vez
        logger.info(
            f"[Batch {self.batch_id}] Carregando empresas pendentes..."
        )
        all_companies = await self._load_all_companies()

        if not all_companies:
            logger.warning(f"[Batch {self.batch_id}] Nenhuma empresa pendente.")
            self.status = "completed"
            return

        self.total = len(all_companies)

        # Dividir em N partições
        workers_per_instance = max(1, self.worker_count // self.num_instances)
        partitions = self._partition(all_companies, self.num_instances)

        logger.info(
            f"[Batch {self.batch_id}] {self.total} empresas, "
            f"{self.num_instances} instâncias × {workers_per_instance} workers, "
            f"{proxy_count} proxies"
        )

        try:
            self._instances = []
            tasks = []
            for idx, partition in enumerate(partitions):
                if not partition:
                    continue
                inst = BatchInstance(
                    instance_id=idx,
                    batch_id=self.batch_id,
                    worker_count=workers_per_instance,
                    flush_size=self.flush_size,
                    companies=partition,
                )
                self._instances.append(inst)
                tasks.append(asyncio.create_task(inst.run()))

            await asyncio.gather(*tasks)

            self.status = "completed"
            elapsed = time.time() - self._start_time
            logger.info(
                f"[Batch {self.batch_id}] CONCLUIDO em {elapsed:.0f}s: "
                f"{self.success_count} sucesso, {self.error_count} erros, "
                f"{self.flushes_done} flushes, {self.num_instances} instâncias"
            )
        except asyncio.CancelledError:
            logger.warning(f"[Batch {self.batch_id}] Cancelado")
            self.status = "cancelled"
        except Exception as e:
            logger.error(f"[Batch {self.batch_id}] Erro fatal: {e}", exc_info=True)
            self.status = "error"

    async def _load_all_companies(self) -> List[Dict[str, Any]]:
        """Carrega todas as empresas pendentes via paginação."""
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
                limit=fetch_size,
                after_id=last_id,
                status_filter=self.status_filter,
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
        """Divide lista em N partições equilibradas (round-robin)."""
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
                "id": inst.instance_id,
                "status": inst.status,
                "processed": inst.processed,
                "success": inst.success_count,
                "errors": inst.error_count,
                "throughput_per_min": round(inst_tp, 1),
            })

            all_times.extend(inst._processing_times_sorted)
            all_pages.extend(inst._pages_per_company)
            total_retries += inst._retries_total
            peak_in_progress += inst._peak_in_progress
            for cat, count in inst._error_categories.items():
                all_error_cats[cat] = all_error_cats.get(cat, 0) + count

        all_times.sort()

        pct_levels = [50, 60, 70, 80, 90, 95, 99]
        time_percentiles = _percentiles(all_times, pct_levels)

        avg_time = round(sum(all_times) / len(all_times), 1) if all_times else 0
        min_time = round(all_times[0], 1) if all_times else 0
        max_time = round(all_times[-1], 1) if all_times else 0
        avg_pages = round(sum(all_pages) / len(all_pages), 1) if all_pages else 0

        success_rate = round(self.success_count / processed * 100, 1) if processed > 0 else 0

        infra = self._get_infrastructure_stats()

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
            "processing_time_ms": {
                "avg": avg_time,
                "min": min_time,
                "max": max_time,
                **time_percentiles,
            },
            "error_breakdown": dict(sorted(all_error_cats.items(), key=lambda x: -x[1])),
            "pages_per_company_avg": avg_pages,
            "total_retries": total_retries,
            "infrastructure": infra,
            "last_errors": self.last_errors,
            "instances": instance_stats,
        }

    def _get_infrastructure_stats(self) -> dict:
        """Coleta métricas dos componentes de infraestrutura."""
        stats: Dict[str, Any] = {}
        try:
            from app.services.scraper_manager.proxy_manager import proxy_pool
            stats["proxy_pool"] = proxy_pool.get_status()
        except Exception:
            stats["proxy_pool"] = {"error": "unavailable"}
        try:
            from app.services.scraper_manager import concurrency_manager
            stats["concurrency"] = concurrency_manager.get_status()
        except Exception:
            stats["concurrency"] = {"error": "unavailable"}
        try:
            from app.services.scraper_manager import domain_rate_limiter
            stats["rate_limiter"] = domain_rate_limiter.get_status()
        except Exception:
            stats["rate_limiter"] = {"error": "unavailable"}
        try:
            from app.services.scraper_manager import circuit_breaker
            stats["circuit_breaker"] = circuit_breaker.get_status()
        except Exception:
            stats["circuit_breaker"] = {"error": "unavailable"}
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
