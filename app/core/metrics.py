"""
Métricas Prometheus para o fluxo unificado de scrape_main.
"""
from prometheus_client import Counter, Gauge, Histogram


unified_requests_total = Counter(
    "scrape_unified_requests_total",
    "Total de requisições por provider/etapa/status",
    ["provider", "stage", "status"],
)

unified_errors_total = Counter(
    "scrape_unified_errors_total",
    "Total de erros por provider/etapa/tipo",
    ["provider", "stage", "error_type"],
)

unified_latency_seconds = Histogram(
    "scrape_unified_latency_seconds",
    "Latência por provider/etapa",
    ["provider", "stage"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
)

unified_inflight_requests = Gauge(
    "scrape_unified_inflight_requests",
    "Requisições em voo por provider/etapa",
    ["provider", "stage"],
)

unified_queue_depth = Gauge(
    "scrape_unified_queue_depth",
    "Profundidade da fila do batch unificado por etapa",
    ["stage"],
)


def observe_request(provider: str, stage: str, status: str, elapsed_s: float):
    unified_requests_total.labels(provider=provider, stage=stage, status=status).inc()
    unified_latency_seconds.labels(provider=provider, stage=stage).observe(max(elapsed_s, 0.0))


def observe_error(provider: str, stage: str, error_type: str):
    unified_errors_total.labels(provider=provider, stage=stage, error_type=error_type).inc()

