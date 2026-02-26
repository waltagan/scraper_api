"""
Métricas Prometheus para o fluxo unificado de scrape_main e saturação do servidor.
"""
import asyncio
import os
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram

try:
    import psutil
except ImportError:  # pragma: no cover - ambiente sem psutil
    psutil = None


unified_requests_total = Counter(
    "scrape_unified_requests_total",
    "Total de requisições por provider/etapa/status",
    ["provider", "stage", "status", "run"],
)

unified_errors_total = Counter(
    "scrape_unified_errors_total",
    "Total de erros por provider/etapa/tipo",
    ["provider", "stage", "error_type", "run"],
)

unified_latency_seconds = Histogram(
    "scrape_unified_latency_seconds",
    "Latência por provider/etapa",
    ["provider", "stage", "run"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
)

unified_inflight_requests = Gauge(
    "scrape_unified_inflight_requests",
    "Requisições em voo por provider/etapa",
    ["provider", "stage", "run"],
)

unified_queue_depth = Gauge(
    "scrape_unified_queue_depth",
    "Profundidade da fila do batch unificado por etapa",
    ["stage", "run"],
)

unified_pending_results_depth = Gauge(
    "scrape_unified_pending_results_depth",
    "Quantidade de resultados em buffer aguardando persistência",
    ["mode", "run"],
)

unified_company_total_seconds = Histogram(
    "scrape_unified_company_total_seconds",
    "Tempo total por empresa no fluxo unificado",
    ["provider", "status", "run"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 240),
)

unified_batch_run_seconds = Histogram(
    "scrape_unified_batch_run_seconds",
    "Duração total de execução de um run do batch unificado",
    ["mode", "status", "run"],
    buckets=(5, 10, 30, 60, 120, 180, 240, 300, 600, 1200),
)

unified_batch_flush_seconds = Histogram(
    "scrape_unified_batch_flush_seconds",
    "Duração de cada flush de persistência no banco",
    ["mode", "run"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20),
)

unified_batch_flush_records = Histogram(
    "scrape_unified_batch_flush_records",
    "Quantidade de registros persistidos por flush",
    ["mode", "run"],
    buckets=(1, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000),
)

unified_parse_workers = Gauge(
    "scrape_unified_parse_workers",
    "Número de processos paralelos (ProcessPool) configurados para parsing HTML",
    ["run"],
)

unified_company_load_seconds = Histogram(
    "scrape_unified_company_load_seconds",
    "Tempo para carregar empresas do banco de dados",
    ["run"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20),
)

unified_company_load_count = Histogram(
    "scrape_unified_company_load_count",
    "Quantidade de empresas carregadas por fetch",
    ["run"],
    buckets=(1, 10, 50, 100, 500, 1000, 2000, 5000),
)

http_inflight_requests = Gauge(
    "scrape_http_inflight_requests",
    "Quantidade de requisições HTTP em andamento na API",
)

http_request_duration_seconds = Histogram(
    "scrape_http_request_duration_seconds",
    "Latência de requisições HTTP da API",
    ["method", "path", "status_class"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30),
)

server_cpu_percent = Gauge(
    "scrape_server_cpu_percent",
    "Uso de CPU do processo da API em percentual",
)

server_memory_rss_bytes = Gauge(
    "scrape_server_memory_rss_bytes",
    "Memória RSS do processo da API em bytes",
)

server_open_fds = Gauge(
    "scrape_server_open_fds",
    "Descritores de arquivo abertos pelo processo da API",
)

server_loadavg_1m = Gauge(
    "scrape_server_loadavg_1m",
    "Load average do host em 1 minuto",
)

server_event_loop_lag_seconds = Gauge(
    "scrape_server_event_loop_lag_seconds",
    "Lag do event loop observado por amostragem periódica",
)

_collector_task: Optional[asyncio.Task] = None
_collector_stop: Optional[asyncio.Event] = None


def _sanitize_path_for_labels(path: str) -> str:
    if path.startswith("/v2/scrape/main-page/unified"):
        return "/v2/scrape/main-page/unified*"
    if path.startswith("/v2/scrape/main-page"):
        return "/v2/scrape/main-page*"
    if path.startswith("/v2/"):
        return "/v2/*"
    if path in {"/metrics", "/metrics/"}:
        return "/metrics"
    if path == "/health":
        return "/health"
    return "other"


def _normalize_run_label(run: Optional[str]) -> str:
    return (run or "unknown").strip() or "unknown"


def observe_request(provider: str, stage: str, status: str, elapsed_s: float, run: Optional[str] = None):
    run_label = _normalize_run_label(run)
    unified_requests_total.labels(provider=provider, stage=stage, status=status, run=run_label).inc()
    unified_latency_seconds.labels(provider=provider, stage=stage, run=run_label).observe(max(elapsed_s, 0.0))


def observe_error(provider: str, stage: str, error_type: str, run: Optional[str] = None):
    run_label = _normalize_run_label(run)
    unified_errors_total.labels(provider=provider, stage=stage, error_type=error_type, run=run_label).inc()


def observe_company_total(provider: str, status: str, elapsed_s: float, run: Optional[str] = None):
    run_label = _normalize_run_label(run)
    unified_company_total_seconds.labels(provider=provider, status=status, run=run_label).observe(max(elapsed_s, 0.0))


def observe_batch_run(save_mode: str, status: str, elapsed_s: float, run: Optional[str] = None):
    run_label = _normalize_run_label(run)
    unified_batch_run_seconds.labels(mode=save_mode, status=status, run=run_label).observe(max(elapsed_s, 0.0))


def observe_batch_flush(save_mode: str, records: int, elapsed_s: float, run: Optional[str] = None):
    run_label = _normalize_run_label(run)
    unified_batch_flush_seconds.labels(mode=save_mode, run=run_label).observe(max(elapsed_s, 0.0))
    unified_batch_flush_records.labels(mode=save_mode, run=run_label).observe(max(float(records), 0.0))


def observe_company_load(elapsed_s: float, count: int, run: Optional[str] = None):
    run_label = _normalize_run_label(run)
    unified_company_load_seconds.labels(run=run_label).observe(max(elapsed_s, 0.0))
    unified_company_load_count.labels(run=run_label).observe(max(float(count), 0.0))


def observe_http_request(method: str, path: str, status_code: int, elapsed_s: float):
    status_class = f"{status_code // 100}xx"
    path_label = _sanitize_path_for_labels(path)
    http_request_duration_seconds.labels(
        method=method.upper(),
        path=path_label,
        status_class=status_class,
    ).observe(max(elapsed_s, 0.0))


async def _server_metrics_collector_loop(interval_seconds: float):
    proc = psutil.Process(os.getpid()) if psutil else None
    if proc:
        proc.cpu_percent(interval=None)
    loop = asyncio.get_running_loop()
    last_tick = loop.time()

    while _collector_stop and not _collector_stop.is_set():
        await asyncio.sleep(interval_seconds)
        now = loop.time()
        lag = max(0.0, now - last_tick - interval_seconds)
        last_tick = now
        server_event_loop_lag_seconds.set(lag)

        if not proc:
            continue
        try:
            server_cpu_percent.set(proc.cpu_percent(interval=None))
            server_memory_rss_bytes.set(proc.memory_info().rss)
            if hasattr(proc, "num_fds"):
                server_open_fds.set(proc.num_fds())
            try:
                server_loadavg_1m.set(os.getloadavg()[0])
            except OSError:
                pass
        except Exception:
            # Evita quebrar a aplicação por falha de coleta de métrica.
            pass


def start_server_metrics_collector(interval_seconds: float = 1.0):
    global _collector_task, _collector_stop
    if _collector_task is not None:
        return
    _collector_stop = asyncio.Event()
    _collector_task = asyncio.create_task(_server_metrics_collector_loop(interval_seconds))


async def stop_server_metrics_collector():
    global _collector_task, _collector_stop
    if _collector_task is None or _collector_stop is None:
        return
    _collector_stop.set()
    try:
        await _collector_task
    except Exception:
        pass
    _collector_task = None
    _collector_stop = None

