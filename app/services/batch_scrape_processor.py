"""
Batch Scrape Processor - Pipeline de scraping em massa.

Carrega empresas paginadas do website_discovery, processa com pool
de workers continuos, e faz flush em lotes de N empresas no PostgreSQL.
"""

import asyncio
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


def _is_transient(error_msg: str) -> bool:
    lower = error_msg.lower()
    return any(kw in lower for kw in TRANSIENT_KEYWORDS)


@dataclass
class CompanyResult:
    cnpj_basico: str
    discovery_id: Optional[int]
    website_url: str
    chunks: List[Any] = field(default_factory=list)
    error: Optional[str] = None
    success: bool = False


class BatchScrapeProcessor:
    """
    Processador de batch scraping com workers continuos e buffer de flush.
    """

    def __init__(
        self,
        worker_count: int = 600,
        flush_size: int = 1000,
        status_filter: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ):
        self.batch_id = str(uuid.uuid4())[:8]
        self.worker_count = worker_count
        self.flush_size = flush_size
        self.status_filter = status_filter or ['muito_alto', 'alto', 'medio']
        self.limit = limit

        self._queue: asyncio.Queue = asyncio.Queue(maxsize=worker_count * 2)
        self._buffer: List[CompanyResult] = []
        self._buffer_lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None

        # Metricas
        self.total = 0
        self.processed = 0
        self.success_count = 0
        self.error_count = 0
        self.in_progress = 0
        self.flushes_done = 0
        self.last_errors: List[dict] = []
        self.status = "idle"
        self._start_time: float = 0
        self._producer_done = False

    async def initialize(self):
        """Conta empresas pendentes antes de iniciar (chamado pelo endpoint)."""
        if self.limit:
            self.total = self.limit
        else:
            db = get_db_service()
            self.total = await db.count_pending_scrape_companies(self.status_filter)

    def start(self):
        """Inicia o batch processing em background."""
        if self._task and not self._task.done():
            raise RuntimeError("Batch ja esta rodando")
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        """Orquestra producer + workers + flush final."""
        self.status = "running"
        self._start_time = time.time()

        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=200)
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

        logger.info(
            f"[Batch {self.batch_id}] Iniciando: {self.total} empresas, "
            f"{self.worker_count} workers, {proxy_count} proxies, "
            f"flush a cada {self.flush_size}"
        )

        try:
            ramp_batch = 100
            workers = []
            for i in range(self.worker_count):
                workers.append(asyncio.create_task(self._worker(i)))
                if (i + 1) % ramp_batch == 0 and i + 1 < self.worker_count:
                    logger.info(
                        f"[Batch {self.batch_id}] Ramp-up: {i+1}/{self.worker_count} workers"
                    )
                    await asyncio.sleep(0.5)

            logger.info(
                f"[Batch {self.batch_id}] Todos {self.worker_count} workers ativos"
            )

            await self._producer()
            self._producer_done = True

            for _ in range(self.worker_count):
                await self._queue.put(None)

            await asyncio.gather(*workers)

            await self._flush_buffer(force=True)

            self.status = "completed"
            elapsed = time.time() - self._start_time
            logger.info(
                f"[Batch {self.batch_id}] Concluido em {elapsed:.0f}s: "
                f"{self.success_count} sucesso, {self.error_count} erros, "
                f"{self.flushes_done} flushes"
            )
        except asyncio.CancelledError:
            logger.warning(f"[Batch {self.batch_id}] Cancelado, fazendo flush final...")
            await self._flush_buffer(force=True)
            self.status = "cancelled"
        except Exception as e:
            logger.error(f"[Batch {self.batch_id}] Erro fatal: {e}", exc_info=True)
            await self._flush_buffer(force=True)
            self.status = "error"

    async def _producer(self):
        """Carrega empresas do DB via cursor-based pagination (id > last_id)."""
        db = get_db_service()
        last_id = 0
        page_size = 5000
        loaded = 0

        while True:
            if self.limit and loaded >= self.limit:
                break

            remaining = (self.limit - loaded) if self.limit else page_size
            fetch_size = min(page_size, remaining)

            companies = await db.get_pending_scrape_companies(
                limit=fetch_size,
                after_id=last_id,
                status_filter=self.status_filter,
            )

            if not companies:
                break

            for company in companies:
                await self._queue.put(company)
                loaded += 1
                if self.limit and loaded >= self.limit:
                    break

            last_id = max(c['wd_id'] for c in companies)
            logger.info(
                f"[Batch {self.batch_id}] Producer: {loaded}/{self.total} carregados "
                f"(last_id={last_id})"
            )

        if loaded != self.total:
            logger.info(
                f"[Batch {self.batch_id}] Producer finalizado: "
                f"total ajustado de {self.total} para {loaded}"
            )
            self.total = loaded

    async def _worker(self, worker_id: int):
        """Worker continuo: puxa da queue, processa, coloca no buffer."""
        while True:
            item = await self._queue.get()
            if item is None:
                break

            self.in_progress += 1
            result = await self._process_company(item, worker_id)
            self.in_progress -= 1

            async with self._buffer_lock:
                self._buffer.append(result)
                self.processed += 1
                if result.success:
                    self.success_count += 1
                else:
                    self.error_count += 1

                if len(self._buffer) >= self.flush_size:
                    await self._flush_buffer()

    async def _process_company(
        self, company: Dict[str, Any], worker_id: int
    ) -> CompanyResult:
        """Processa uma empresa com retry para erros transientes."""
        cnpj = company['cnpj_basico']
        url = company['website_url']
        discovery_id = company.get('wd_id')
        max_retries = 2

        for attempt in range(max_retries + 1):
            try:
                pages = await scrape_all_subpages(
                    url=url, max_subpages=50, ctx_label=f"[B{self.batch_id}]", request_id=cnpj
                )

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
                        website_url=url, error=error_msg[:500]
                    )

                # Agregar conteudo
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
                        error=f"Conteudo agregado insuficiente ({len(aggregated)} chars)"
                    )

                chunks = process_content(aggregated)
                if not chunks:
                    return CompanyResult(
                        cnpj_basico=cnpj, discovery_id=discovery_id,
                        website_url=url, error="Nenhum chunk gerado apos processamento"
                    )

                for chunk in chunks:
                    if not hasattr(chunk, 'pages_included') or not chunk.pages_included:
                        chunk.pages_included = visited[:5]

                return CompanyResult(
                    cnpj_basico=cnpj, discovery_id=discovery_id,
                    website_url=url, chunks=chunks, success=True
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
                    website_url=url, error=f"{error_msg} | {short_tb}"[:500]
                )

        return CompanyResult(
            cnpj_basico=cnpj, discovery_id=discovery_id,
            website_url=url, error="Maximo de retries atingido"
        )

    async def _flush_buffer(self, force: bool = False):
        """Converte buffer em records e insere no DB."""
        if not force:
            to_flush = self._buffer
            self._buffer = []
        else:
            async with self._buffer_lock:
                to_flush = self._buffer
                self._buffer = []

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
                        result.cnpj_basico,
                        result.discovery_id,
                        result.website_url,
                        chunk.index,
                        chunk.total_chunks,
                        chunk.content,
                        chunk.tokens,
                        page_source,
                        None,  # error = NULL
                    ))
            else:
                records.append((
                    result.cnpj_basico,
                    result.discovery_id,
                    result.website_url,
                    0,     # chunk_index
                    0,     # total_chunks
                    None,  # chunk_content = NULL
                    0,     # token_count
                    None,  # page_source
                    result.error,
                ))

        try:
            db = get_db_service()
            await db.save_scrape_results_mega_batch(records)
            self.flushes_done += 1
            logger.info(
                f"[Batch {self.batch_id}] Flush #{self.flushes_done}: "
                f"{len(to_flush)} empresas, {len(records)} records"
            )
        except Exception as e:
            logger.error(
                f"[Batch {self.batch_id}] Erro no flush: {e}", exc_info=True
            )
            self._record_error("FLUSH", "DB", str(e))

    def _record_error(self, cnpj: str, url: str, error: str):
        self.last_errors.append({
            "cnpj": cnpj, "url": url[:80], "error": error[:200],
            "time": time.time()
        })
        if len(self.last_errors) > 10:
            self.last_errors = self.last_errors[-10:]

    def get_status(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        throughput = (self.processed / elapsed * 60) if elapsed > 0 else 0
        remaining = self.total - self.processed
        eta = (remaining / (throughput / 60)) / 60 if throughput > 0 else None

        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "total": self.total,
            "processed": self.processed,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "remaining": remaining,
            "in_progress": self.in_progress,
            "throughput_per_min": round(throughput, 1),
            "eta_minutes": round(eta, 1) if eta else None,
            "flushes_done": self.flushes_done,
            "buffer_size": len(self._buffer),
            "last_errors": self.last_errors,
        }

    async def cancel(self):
        """Cancela o batch e faz flush do que tem no buffer."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


# Singleton do batch ativo
_active_batch: Optional[BatchScrapeProcessor] = None


def get_active_batch() -> Optional[BatchScrapeProcessor]:
    return _active_batch


def set_active_batch(batch: Optional[BatchScrapeProcessor]):
    global _active_batch
    _active_batch = batch
