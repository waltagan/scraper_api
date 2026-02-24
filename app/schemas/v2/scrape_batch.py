"""
Schemas Pydantic para endpoint Batch Scrape v2.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from app.services.scraper.constants import BATCH_MAX_WORKERS


class BatchScrapeRequest(BaseModel):
    """Request para iniciar batch scrape."""
    limit: Optional[int] = Field(None, description="Maximo de empresas a processar (None = todas pendentes)")
    worker_count: int = Field(
        BATCH_MAX_WORKERS,
        ge=1,
        le=20000,
        description="Numero total de workers no sliding window.",
    )
    flush_size: int = Field(1000, ge=10, le=5000, description="Tamanho do buffer antes de flush no DB")
    instances: int = Field(10, ge=1, le=50, description="Numero de instancias paralelas de processamento")
    status_filter: List[str] = Field(
        default=['muito_alto', 'alto', 'medio'],
        description="Lista de discovery_status para filtrar"
    )
    chunk_size: Optional[int] = Field(None, ge=100, le=10000, description="Empresas por chunk (None = usa config)")
    probe_only: bool = Field(False, description="Se true, executa apenas probe+main page sem subpages")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "limit": 10000,
                "worker_count": BATCH_MAX_WORKERS,
                "flush_size": 1000,
                "instances": 10,
                "status_filter": ["muito_alto", "alto", "medio"],
                "chunk_size": 1000,
                "probe_only": False
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
    failure_diagnosis: Dict[str, Any] = Field(
        default_factory=dict,
        description="Diagnóstico de falhas separado por categoria: site_offline, proxy_infra, blocked, content_issue"
    )
    provider_stats: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métricas por provider (processed/success/errors + breakdown de erros)"
    )
    stage_funnel: Dict[str, Any] = Field(
        default_factory=dict,
        description="Funil por etapa: probe → main_page → subpages, com entered/ok/fail/fail_reasons/time_ms"
    )
    http_time_histogram: Dict[str, Any] = Field(
        default_factory=dict,
        description="Distribuição de requests OK/FAIL por faixa de tempo HTTP (0-3s, 3-6s, ..., 21s+)"
    )
    domain_success_distribution: Dict[str, Any] = Field(
        default_factory=dict,
        description="Distribuição de taxa de sucesso de subpages por domínio (100%, 50-99%, 1-49%, 0%)"
    )
    error_timeline_by_quartile: Dict[str, Any] = Field(
        default_factory=dict,
        description="Erros de subpage por quartil de progresso do batch (q1=0-25%, q2=25-50%, q3=50-75%, q4=75-100%)"
    )
    subpage_pipeline: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metricas do pipeline de subpages: links encontrados/filtrados/selecionados, "
                    "subpages tentadas/sucesso/falha, breakdown de erros"
    )
    infrastructure: Dict[str, Any] = Field(
        default_factory=dict,
        description="Stats de proxy_pool, concurrency, rate_limiter, circuit_breaker"
    )
    last_errors: List[dict] = Field(default_factory=list, description="Ultimos 10 erros")
    instances: List[InstanceStatus] = Field(default_factory=list, description="Status por instancia")
