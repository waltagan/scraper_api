"""
Schemas Pydantic para endpoint Batch Scrape v2.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List


class BatchScrapeRequest(BaseModel):
    """Request para iniciar batch scrape."""
    limit: Optional[int] = Field(None, description="Maximo de empresas a processar (None = todas pendentes)")
    worker_count: int = Field(600, ge=1, le=1000, description="Numero de workers paralelos")
    flush_size: int = Field(1000, ge=10, le=5000, description="Tamanho do buffer antes de flush no DB")
    status_filter: List[str] = Field(
        default=['muito_alto', 'alto', 'medio'],
        description="Lista de discovery_status para filtrar"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "limit": 10000,
                "worker_count": 600,
                "flush_size": 1000,
                "status_filter": ["muito_alto", "alto", "medio"]
            }
        }
    )


class BatchScrapeResponse(BaseModel):
    """Response ao iniciar batch scrape."""
    success: bool
    batch_id: str
    total_companies: int
    worker_count: int
    flush_size: int
    message: str


class BatchStatusResponse(BaseModel):
    """Response com status do batch em andamento."""
    batch_id: str
    status: str = Field(description="running, completed, cancelled, error")
    total: int
    processed: int
    success_count: int
    error_count: int
    remaining: int
    in_progress: int
    throughput_per_min: float
    eta_minutes: Optional[float]
    flushes_done: int
    buffer_size: int
    last_errors: List[dict] = Field(default_factory=list, description="Ultimos 10 erros")
