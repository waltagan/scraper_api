"""
Schemas Pydantic para endpoint Batch Scrape v2.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any


class BatchScrapeRequest(BaseModel):
    """Request para iniciar batch scrape."""
    limit: Optional[int] = Field(None, description="Maximo de empresas a processar (None = todas pendentes)")
    worker_count: int = Field(2000, ge=1, le=20000, description="Numero total de workers (divididos entre instancias)")
    flush_size: int = Field(1000, ge=10, le=5000, description="Tamanho do buffer antes de flush no DB")
    instances: int = Field(10, ge=1, le=50, description="Numero de instancias paralelas de processamento")
    status_filter: List[str] = Field(
        default=['muito_alto', 'alto', 'medio'],
        description="Lista de discovery_status para filtrar"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "limit": 10000,
                "worker_count": 2000,
                "flush_size": 1000,
                "instances": 10,
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
    instances: int
    message: str


class InstanceStatus(BaseModel):
    """Status de uma instância individual."""
    id: int
    status: str
    processed: int
    success: int
    errors: int
    throughput_per_min: float


class ProcessingTimeStats(BaseModel):
    """Estatísticas de tempo de processamento com percentis."""
    avg: float = Field(description="Tempo medio (ms)")
    min: float = Field(description="Tempo minimo (ms)")
    max: float = Field(description="Tempo maximo (ms)")
    p50: float = Field(description="Percentil 50 (mediana)")
    p60: float = Field(description="Percentil 60")
    p70: float = Field(description="Percentil 70")
    p80: float = Field(description="Percentil 80")
    p90: float = Field(description="Percentil 90")
    p95: float = Field(description="Percentil 95")
    p99: float = Field(description="Percentil 99")


class BatchStatusResponse(BaseModel):
    """Response com status do batch em andamento."""
    batch_id: str
    status: str = Field(description="running, completed, cancelled, error")
    total: int
    processed: int
    success_count: int
    error_count: int
    success_rate_pct: float = Field(0, description="Taxa de sucesso (%)")
    remaining: int
    in_progress: int
    peak_in_progress: int = Field(0, description="Pico maximo de workers ativos simultaneamente")
    throughput_per_min: float
    eta_minutes: Optional[float]
    elapsed_seconds: float = Field(0, description="Tempo decorrido (s)")
    flushes_done: int
    buffer_size: int
    processing_time_ms: ProcessingTimeStats = Field(
        default_factory=lambda: ProcessingTimeStats(
            avg=0, min=0, max=0, p50=0, p60=0, p70=0, p80=0, p90=0, p95=0, p99=0
        ),
        description="Percentis de tempo de processamento por empresa (ms)"
    )
    error_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="Contagem de erros por categoria (dns, timeout, ssl, cloudflare, etc.)"
    )
    pages_per_company_avg: float = Field(0, description="Media de paginas extraidas por empresa")
    total_retries: int = Field(0, description="Total de retries realizados")
    infrastructure: Dict[str, Any] = Field(
        default_factory=dict,
        description="Stats de proxy_pool, concurrency, rate_limiter, circuit_breaker"
    )
    last_errors: List[dict] = Field(default_factory=list, description="Ultimos 10 erros")
    instances: List[InstanceStatus] = Field(default_factory=list, description="Status por instancia")
