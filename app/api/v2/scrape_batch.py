"""
Endpoint Batch Scrape v2 - Scraping em massa simplificado.
"""
import logging
from fastapi import APIRouter, HTTPException
from app.schemas.v2.scrape_batch import (
    BatchScrapeRequest,
    BatchScrapeResponse,
    BatchStatusResponse,
)
from app.services.batch_scrape_processor import (
    BatchScrapeProcessor,
    get_active_batch,
    set_active_batch,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/scrape/batch", response_model=BatchScrapeResponse)
async def start_batch_scrape(request: BatchScrapeRequest) -> BatchScrapeResponse:
    """
    Inicia batch scrape. Concorrencia controlada pelo semaforo global (2000).
    """
    existing = get_active_batch()
    if existing and existing.status == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Batch {existing.batch_id} ja esta rodando. "
                   f"Use GET /v2/scrape/batch/status para acompanhar."
        )

    processor = BatchScrapeProcessor(
        worker_count=request.worker_count,
        flush_size=request.flush_size,
        status_filter=request.status_filter,
        limit=request.limit,
        chunk_size=request.chunk_size,
        probe_only=request.probe_only,
    )
    set_active_batch(processor)
    await processor.initialize()
    processor.start()

    logger.info(
        f"Batch {processor.batch_id} iniciado: "
        f"workers={processor.worker_count}, flush={request.flush_size}, "
        f"limit={request.limit}, probe_only={request.probe_only}"
    )

    return BatchScrapeResponse(
        success=True,
        batch_id=processor.batch_id,
        total_companies=processor.total,
        worker_count=processor.worker_count,
        flush_size=request.flush_size,
        instances=request.instances,
        message=f"Batch {processor.batch_id} iniciado (sliding_window={processor.worker_count}).",
    )


@router.get("/scrape/batch/status", response_model=BatchStatusResponse)
async def get_batch_status() -> BatchStatusResponse:
    """Retorna status do batch."""
    batch = get_active_batch()
    if not batch:
        raise HTTPException(status_code=404, detail="Nenhum batch ativo.")

    status = batch.get_status()
    return BatchStatusResponse(**status)


@router.post("/scrape/batch/cancel")
async def cancel_batch_scrape():
    """Cancela o batch scrape em andamento."""
    batch = get_active_batch()
    if not batch or batch.status != "running":
        raise HTTPException(status_code=404, detail="Nenhum batch rodando.")

    await batch.cancel()
    return {"success": True, "message": f"Batch {batch.batch_id} cancelado."}
