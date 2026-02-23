"""
Stress Test Unificado — 711Proxy + Decodo + Evomi
Testa os 3 providers simultaneamente por nível de carga.
Níveis: 800, 1200, 1500, 2000 links.
URLs: website_discovery com discovery_status = 'alto'.
Timeout: 40s.
Gera relatório .md e .json com estatísticas, percentis, gráficos ASCII e análise comparativa.

Métricas de degradação granulares:
- Stress test puro: todas as N URLs disparam simultaneamente, sem semáforo
- Timeline de sucesso/erro em janelas de 5s
- Série temporal de bandwidth (MB/s) por janela
- Série temporal de latência p50/p90 por janela
- Coeficiente de variação de latência (instabilidade do proxy sob carga total)
- Taxa de erro acumulada ao longo do tempo
- Pico e média de conexões ativas simultâneas
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL = True
except ImportError:
    HAS_CURL = False

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "")
SCHEMA = "busca_fornecedor"

# Stress test puro: todas as N URLs disparam simultaneamente sem semáforo.
CONCURRENCY_LEVELS = [800, 1200, 1500, 2000]
TIMEOUT_SECONDS = 40

PROXY_711_API = (
    "http://us.rotgbapi.711proxy.com:8089/gen"
    "?zone=custom&ptype=1&region=BR&count=900"
    "&proto=http&stype=json&sessType=sticky&sessTime=30&sessAuto=1"
)
PROXY_DECODO_CSV = "data_decodo_ips.csv"
PROXY_EVOMI_TXT = "proxies_evomi.txt"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
]

PROVIDER_LABELS = {
    "711proxy": "711Proxy",
    "decodo": "Decodo",
    "evomi": "Evomi",
}


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class RequestResult:
    url: str
    provider: str
    status_code: int = 0
    success: bool = False
    elapsed_ms: float = 0.0
    http_time_ms: float = 0.0     # tempo efetivo de rede (= elapsed no stress puro)
    error: str = ""
    error_type: str = ""
    content_length: int = 0
    started_at: float = 0.0       # timestamp absoluto de início (relativo ao t0 do nível)
    completed_at: float = 0.0     # timestamp absoluto de conclusão


@dataclass
class ProviderLevelResult:
    provider: str
    concurrency: int
    total_urls: int = 0
    total_time_s: float = 0.0
    level_start_ts: float = 0.0   # timestamp absoluto do início do nível
    results: List[RequestResult] = field(default_factory=list)
    connection_samples: List[int] = field(default_factory=list)
    bytes_samples: List[float] = field(default_factory=list)   # bytes acumulados a cada 0.5s
    peak_connections: int = 0


# ---------------------------------------------------------------------------
# Carregamento de proxies
# ---------------------------------------------------------------------------
async def load_711_proxies() -> List[str]:
    """Busca portas sticky da API 711Proxy e retorna lista de URLs."""
    log("[711Proxy] Buscando sessões sticky na API...")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(PROXY_711_API)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 200:
            log(f"[711Proxy] API erro: code={data.get('code')}, msg={data.get('msg')}")
            return []

        entries = data.get("data", [])
        if not entries:
            log("[711Proxy] API retornou 0 entries")
            return []

        ports = [e["port"] for e in entries if "port" in e]
        hosts = {e["ip"] for e in entries if "ip" in e}
        if len(hosts) != 1:
            log(f"[711Proxy] Múltiplos hosts: {hosts}")
            return []

        host = hosts.pop()
        proxies = [f"http://{host}:{p}" for p in ports]
        log(f"[711Proxy] OK: {len(proxies)} proxies | host={host} | portas {ports[0]}-{ports[-1]}")
        return proxies
    except Exception as e:
        log(f"[711Proxy] Falha ao buscar proxies: {e}")
        return []


def load_decodo_proxies() -> List[str]:
    """Carrega proxy URLs do CSV Decodo (formato: http://user:pass@host:port)."""
    if not os.path.exists(PROXY_DECODO_CSV):
        log(f"[Decodo] CSV não encontrado: {PROXY_DECODO_CSV}")
        return []
    with open(PROXY_DECODO_CSV) as f:
        proxies = [line.strip() for line in f if line.strip()]
    log(f"[Decodo] OK: {len(proxies)} proxies | portas {proxies[0].split(':')[-1]}-{proxies[-1].split(':')[-1]}")
    return proxies


def _parse_evomi_line(line: str) -> Optional[str]:
    """
    Converte linha Evomi para URL de proxy padrão.
    Formato de entrada: http://host:port:user:password_params
    Formato de saída:   http://user:password_params@host:port
    """
    line = line.strip()
    if not line:
        return None
    # Remove o scheme
    if "://" in line:
        scheme, rest = line.split("://", 1)
    else:
        scheme, rest = "http", line

    parts = rest.split(":")
    # Esperado: host, port, user, password
    if len(parts) < 4:
        return None

    host = parts[0]
    port = parts[1]
    user = parts[2]
    password = ":".join(parts[3:])  # senha pode conter ':'

    return f"{scheme}://{user}:{password}@{host}:{port}"


def load_evomi_proxies() -> List[str]:
    """Carrega e converte proxy URLs do arquivo Evomi."""
    if not os.path.exists(PROXY_EVOMI_TXT):
        log(f"[Evomi] Arquivo não encontrado: {PROXY_EVOMI_TXT}")
        return []
    proxies = []
    with open(PROXY_EVOMI_TXT) as f:
        for line in f:
            url = _parse_evomi_line(line)
            if url:
                proxies.append(url)
    if proxies:
        log(f"[Evomi] OK: {len(proxies)} proxies carregados")
    else:
        log("[Evomi] Nenhum proxy válido encontrado")
    return proxies


# ---------------------------------------------------------------------------
# Carregamento de URLs do banco
# ---------------------------------------------------------------------------
async def load_urls_from_db(count: int) -> List[str]:
    """Carrega URLs de website_discovery com discovery_status = 'alto'."""
    log(f"[DB] Conectando... buscando {count} URLs (discovery_status=alto)")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(f"""
            SELECT website_url
            FROM "{SCHEMA}".website_discovery
            WHERE discovery_status = 'alto'
              AND website_url IS NOT NULL
              AND website_url != ''
            ORDER BY random()
            LIMIT $1
        """, count)
        urls = [r["website_url"] for r in rows]
        log(f"[DB] {len(urls)} URLs carregadas")
        return urls
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Execução de requests
# ---------------------------------------------------------------------------
def _classify_error(err_str: str) -> str:
    e = err_str.lower()
    if "timeout" in e or "timed out" in e:
        return "timeout"
    if "connect" in e or "refused" in e:
        return "connection"
    if "ssl" in e or "certificate" in e:
        return "ssl"
    if "resolve" in e or "dns" in e or "nodename" in e or "name or service" in e:
        return "dns"
    if "reset" in e or "broken" in e or "aborted" in e:
        return "reset"
    if "407" in e or "proxy auth" in e or "proxy_auth" in e:
        return "proxy_auth"
    return "other"


async def make_request(
    session: "AsyncSession",
    url: str,
    proxy_url: str,
    provider: str,
    active_ref: List[int],
    bytes_counter: List[int],
    level_t0: float,
) -> RequestResult:
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    result = RequestResult(url=url, provider=provider)
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.google.com/",
    }

    t0 = time.perf_counter()
    result.started_at = t0 - level_t0
    active_ref[0] += 1
    try:
        resp = await session.get(
            url, headers=headers, proxy=proxy_url,
            timeout=TIMEOUT_SECONDS, allow_redirects=True, max_redirects=5,
        )
        t_done = time.perf_counter()
        result.elapsed_ms = (t_done - t0) * 1000
        result.http_time_ms = result.elapsed_ms
        result.completed_at = t_done - level_t0
        result.status_code = resp.status_code
        result.content_length = len(resp.content) if resp.content else 0
        bytes_counter[0] += result.content_length

        if resp.status_code == 200:
            result.success = True
        else:
            result.error = f"http_{resp.status_code}"
            result.error_type = f"http_{resp.status_code}"

    except Exception as e:
        t_done = time.perf_counter()
        result.elapsed_ms = (t_done - t0) * 1000
        result.http_time_ms = result.elapsed_ms
        result.completed_at = t_done - level_t0
        result.error_type = _classify_error(str(e))
        result.error = f"{type(e).__name__}: {str(e)[:120]}"
    finally:
        active_ref[0] -= 1

    return result


async def _sampler(
    active_ref: List[int],
    samples: List[int],
    bytes_counter: List[int],
    bytes_samples: List[float],
    stop_event: asyncio.Event,
):
    """Amostra conexões ativas e bytes acumulados a cada 0.5s."""
    prev_bytes = 0
    try:
        while not stop_event.is_set():
            samples.append(active_ref[0])
            cur_bytes = bytes_counter[0]
            # MB/s nesta janela de 0.5s
            delta_mb = (cur_bytes - prev_bytes) / 1_000_000
            bytes_samples.append(round(delta_mb / 0.5, 3))  # MB/s
            prev_bytes = cur_bytes
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Estatísticas
# ---------------------------------------------------------------------------
def percentiles(values: List[float]) -> Dict[str, float]:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)

    def pct(p: float) -> float:
        return round(s[min(int(n * p), n - 1)], 1)

    return {
        "min": round(s[0], 1),
        "p25": pct(0.25),
        "p50": pct(0.50),
        "p75": pct(0.75),
        "p90": pct(0.90),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "max": round(s[-1], 1),
        "avg": round(statistics.mean(values), 1),
        "stdev": round(statistics.stdev(values), 1) if len(values) > 1 else 0.0,
    }


def _build_timeline(
    results: List[RequestResult],
    total_time_s: float,
    window_s: float = 5.0,
) -> List[Dict[str, Any]]:
    """
    Divide o teste em janelas de `window_s` segundos e calcula por janela:
    - ok, fail, success_rate
    - latência p50/p90 dos requests que completaram nessa janela
    - bandwidth MB/s (bytes recebidos / duração da janela)
    """
    if not results or total_time_s <= 0:
        return []

    n_windows = max(1, int(total_time_s / window_s) + 1)
    windows: List[Dict] = [
        {
            "window_start_s": round(i * window_s, 1),
            "window_end_s": round((i + 1) * window_s, 1),
            "ok": 0, "fail": 0,
            "latencies_ok": [],
            "http_times": [],
            "bytes": 0,
        }
        for i in range(n_windows)
    ]

    for r in results:
        idx = int(r.completed_at / window_s)
        if idx >= n_windows:
            idx = n_windows - 1
        w = windows[idx]
        if r.success:
            w["ok"] += 1
            w["latencies_ok"].append(r.http_time_ms)
        else:
            w["fail"] += 1
        w["http_times"].append(r.http_time_ms)
        w["bytes"] += r.content_length

    timeline = []
    for w in windows:
        total_w = w["ok"] + w["fail"]
        if total_w == 0:
            continue
        lat_ok = sorted(w["latencies_ok"])
        n_ok = len(lat_ok)
        p50_ok = lat_ok[int(n_ok * 0.5)] if n_ok else 0
        p90_ok = lat_ok[int(n_ok * 0.9)] if n_ok else 0

        all_http = sorted(w["http_times"])
        n_http = len(all_http)
        p50_http = all_http[int(n_http * 0.5)] if n_http else 0

        bw_mbs = round(w["bytes"] / 1_000_000 / window_s, 3)

        timeline.append({
            "t": f"{w['window_start_s']:.0f}s-{w['window_end_s']:.0f}s",
            "ok": w["ok"],
            "fail": w["fail"],
            "total": total_w,
            "success_pct": round(w["ok"] / total_w * 100, 1),
            "lat_ok_p50_ms": round(p50_ok, 1),
            "lat_ok_p90_ms": round(p90_ok, 1),
            "lat_all_p50_ms": round(p50_http, 1),
            "bw_mbs": bw_mbs,
        })

    return timeline


def _saturation_analysis(
    results: List[RequestResult],
    connection_samples: List[int],
    concurrency: int,
) -> Dict[str, Any]:
    """
    Stress test puro (sem semáforo): analisa degradação pelo comportamento
    da latência e das conexões ativas ao longo do tempo.

    - cv_latency: coeficiente de variação (stdev/média) da latência HTTP.
      >1.0 → proxy muito instável sob carga total
      <0.5 → proxy estável mesmo sob carga total

    - peak_active_pct: pico de conexões ativas vs total de URLs.
      Indica quantas chegaram a estar ativas ao mesmo tempo de fato.

    - avg_active: média de conexões ativas durante o teste (amostras 0.5s).
    """
    if not results:
        return {}

    http_times = [r.http_time_ms for r in results if r.http_time_ms > 0]
    elapsed_all = [r.elapsed_ms for r in results]

    avg_elapsed = statistics.mean(elapsed_all) if elapsed_all else 1

    cv_latency = 0.0
    if http_times and len(http_times) > 1:
        mean_http = statistics.mean(http_times)
        stdev_http = statistics.stdev(http_times)
        cv_latency = round(stdev_http / mean_http, 3) if mean_http > 0 else 0

    peak_active = max(connection_samples) if connection_samples else 0
    avg_active = round(statistics.mean(connection_samples), 1) if connection_samples else 0
    peak_active_pct = round(peak_active / concurrency * 100, 1) if concurrency > 0 else 0

    # Diagnóstico baseado em latência e instabilidade
    if cv_latency > 1.5:
        bottleneck = "proxy severamente sobrecarregado — latência extremamente instável sob carga total"
    elif cv_latency > 1.0:
        bottleneck = "proxy instável sob carga — alta variância de latência; proxy rotacionando IPs ruins ou saturado"
    elif avg_elapsed > 25000:
        bottleneck = "proxy lento — latência média alta; bandwidth ou capacidade do proxy esgotada"
    elif avg_elapsed > 15000:
        bottleneck = "proxy sob pressão — latência elevada mas ainda funcional"
    else:
        bottleneck = "proxy saudável — absorveu a carga sem degradação severa"

    return {
        "avg_http_time_ms": round(statistics.mean(http_times), 1) if http_times else 0,
        "avg_elapsed_ms": round(avg_elapsed, 1),
        "cv_latency": cv_latency,
        "peak_active": peak_active,
        "peak_active_pct": peak_active_pct,
        "avg_active_connections": avg_active,
        "bottleneck_diagnosis": bottleneck,
    }


def analyze_provider_level(plr: ProviderLevelResult) -> Dict[str, Any]:
    ok = [r for r in plr.results if r.success]
    fail = [r for r in plr.results if not r.success]

    ok_times = [r.elapsed_ms for r in ok]
    fail_times = [r.elapsed_ms for r in fail]
    all_times = [r.elapsed_ms for r in plr.results]
    http_times = [r.http_time_ms for r in plr.results if r.http_time_ms > 0]

    error_types: Dict[str, int] = defaultdict(int)
    for r in fail:
        error_types[r.error_type] += 1

    ok_sizes = [r.content_length for r in ok if r.content_length > 0]
    total_bytes = sum(r.content_length for r in plr.results)
    bw_mbps = (total_bytes * 8 / 1_000_000) / plr.total_time_s if plr.total_time_s > 0 else 0

    # Histograma de tempo
    buckets = ["0-3s", "3-6s", "6-10s", "10-15s", "15-20s", "20-30s", "30-40s", "40s+"]
    time_histogram: Dict[str, Dict[str, int]] = {b: {"ok": 0, "fail": 0} for b in buckets}
    for r in plr.results:
        ms = r.elapsed_ms
        if ms < 3000:
            b = "0-3s"
        elif ms < 6000:
            b = "3-6s"
        elif ms < 10000:
            b = "6-10s"
        elif ms < 15000:
            b = "10-15s"
        elif ms < 20000:
            b = "15-20s"
        elif ms < 30000:
            b = "20-30s"
        elif ms < 40000:
            b = "30-40s"
        else:
            b = "40s+"
        time_histogram[b]["ok" if r.success else "fail"] += 1

    # Distribuição de erros por terços do teste
    n = len(plr.results)
    t1 = n // 3
    t2 = 2 * n // 3
    errors_t1 = sum(1 for r in plr.results[:t1] if not r.success)
    errors_t2 = sum(1 for r in plr.results[t1:t2] if not r.success)
    errors_t3 = sum(1 for r in plr.results[t2:] if not r.success)

    # Ponto de degradação: primeiro bucket de tempo com >20% falhas
    degradation_point = None
    for b in buckets:
        bdata = time_histogram[b]
        total_b = bdata["ok"] + bdata["fail"]
        if total_b > 10 and bdata["fail"] / total_b > 0.20:
            degradation_point = b
            break

    # Timeline granular (janelas de 5s)
    timeline = _build_timeline(plr.results, plr.total_time_s, window_s=5.0)

    # Análise de saturação
    saturation = _saturation_analysis(plr.results, plr.connection_samples, plr.concurrency)

    # Série temporal de bandwidth (amostras do sampler)
    bw_series = plr.bytes_samples  # MB/s por janela de 0.5s
    bw_series_stats = percentiles(bw_series) if bw_series else {}

    # Taxa de erro acumulada: a cada 10% das requests, qual o erro acumulado
    cumulative_error_rate = []
    step = max(1, n // 10)
    for i in range(step, n + 1, step):
        chunk = plr.results[:i]
        errs = sum(1 for r in chunk if not r.success)
        cumulative_error_rate.append({
            "at_request": i,
            "pct_complete": round(i / n * 100, 0),
            "error_rate_pct": round(errs / i * 100, 1),
        })

    return {
        "provider": plr.provider,
        "concurrency": plr.concurrency,
        "total_urls": plr.total_urls,
        "total_time_s": round(plr.total_time_s, 1),
        "throughput_per_min": round(plr.total_urls / plr.total_time_s * 60, 1) if plr.total_time_s > 0 else 0,
        "success": len(ok),
        "fail": len(fail),
        "success_rate_pct": round(len(ok) / len(plr.results) * 100, 1) if plr.results else 0,
        "latency_all_ms": percentiles(all_times),
        "latency_ok_ms": percentiles(ok_times),
        "latency_fail_ms": percentiles(fail_times),
        "http_time_ms": percentiles(http_times),
        "error_breakdown": dict(sorted(error_types.items(), key=lambda x: -x[1])),
        "content_size_bytes": percentiles(ok_sizes) if ok_sizes else {},
        "total_data_mb": round(total_bytes / 1_000_000, 2),
        "bandwidth_mbps": round(bw_mbps, 2),
        "bandwidth_series_mbs": bw_series_stats,
        "connections": {
            "peak": plr.peak_connections,
            "samples": percentiles(plr.connection_samples) if plr.connection_samples else {},
        },
        "time_histogram": time_histogram,
        "error_distribution_thirds": {
            "t1_first_third": errors_t1,
            "t2_mid_third": errors_t2,
            "t3_last_third": errors_t3,
        },
        "degradation_point": degradation_point,
        "timeline_5s": timeline,
        "saturation": saturation,
        "cumulative_error_rate": cumulative_error_rate,
    }


# ---------------------------------------------------------------------------
# Execução por provider + nível
# ---------------------------------------------------------------------------
async def run_provider_level(
    provider: str,
    total_urls: int,
    urls: List[str],
    proxy_urls: List[str],
) -> Dict[str, Any]:
    """Stress test puro: todas as N URLs disparam simultaneamente, sem semáforo."""
    test_urls = urls[:total_urls]
    label = PROVIDER_LABELS.get(provider, provider)
    n_total = len(test_urls)

    log(f"  [{label}] disparando {n_total} requests simultâneos agora")

    session = AsyncSession(impersonate="chrome131", verify=False, max_clients=n_total + 100)

    active_ref = [0]
    peak_ref = [0]
    bytes_counter = [0]
    samples: List[int] = []
    bytes_samples: List[float] = []
    stop_event = asyncio.Event()
    sampler_task = asyncio.create_task(
        _sampler(active_ref, samples, bytes_counter, bytes_samples, stop_event)
    )

    completed = 0
    ok_count = 0
    lock = asyncio.Lock()
    t0 = time.perf_counter()
    log_step = max(100, n_total // 10)

    async def tracked(url_: str, proxy_: str) -> RequestResult:
        nonlocal completed, ok_count
        r = await make_request(session, url_, proxy_, provider, active_ref, bytes_counter, t0)
        async with lock:
            completed += 1
            if r.success:
                ok_count += 1
            cur_active = active_ref[0]
            if cur_active > peak_ref[0]:
                peak_ref[0] = cur_active
            if completed % log_step == 0 or completed == n_total:
                pct = ok_count / completed * 100 if completed else 0
                log(f"  [{label}|{n_total}] {completed}/{n_total} "
                    f"| OK: {pct:.0f}% | ativos: {cur_active} | peak: {peak_ref[0]}")
        return r

    tasks = [
        tracked(url, proxy_urls[i % len(proxy_urls)])
        for i, url in enumerate(test_urls)
    ]
    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - t0

    stop_event.set()
    sampler_task.cancel()
    await session.close()

    plr = ProviderLevelResult(
        provider=provider,
        concurrency=n_total,
        total_urls=n_total,
        total_time_s=total_time,
        level_start_ts=t0,
        results=list(results),
        connection_samples=samples,
        bytes_samples=bytes_samples,
        peak_connections=peak_ref[0],
    )
    analysis = analyze_provider_level(plr)
    sat = analysis.get("saturation", {})
    log(f"  [{label}|{n_total}] DONE {total_time:.1f}s "
        f"| success={analysis['success_rate_pct']}% "
        f"| p50={analysis['latency_ok_ms'].get('p50','?')}ms "
        f"| p90={analysis['latency_ok_ms'].get('p90','?')}ms "
        f"| cv={sat.get('cv_latency','?')} "
        f"| diagnóstico: {sat.get('bottleneck_diagnosis','?')}")
    return analysis


# ---------------------------------------------------------------------------
# Execução de um nível — providers sequencialmente (isolados)
# ---------------------------------------------------------------------------
async def run_level_all_providers(
    concurrency: int,
    urls: List[str],
    proxies_711: List[str],
    proxies_decodo: List[str],
    proxies_evomi: List[str],
    only_provider: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    log("")
    log("=" * 70)
    log(f"  NÍVEL {concurrency} — providers sequenciais (isolados)")
    log("=" * 70)

    providers_to_run = []
    if proxies_711 and only_provider in (None, "711proxy"):
        providers_to_run.append(("711proxy", proxies_711))
    if proxies_decodo and only_provider in (None, "decodo"):
        providers_to_run.append(("decodo", proxies_decodo))
    if proxies_evomi and only_provider in (None, "evomi"):
        providers_to_run.append(("evomi", proxies_evomi))

    if not providers_to_run:
        log("ERRO: Nenhum provider disponível")
        return {}

    level_results: Dict[str, Dict[str, Any]] = {}

    for i, (provider, proxy_list) in enumerate(providers_to_run):
        # Novo shuffle para cada provider — URLs diferentes, teste justo
        random.shuffle(urls)
        result = await run_provider_level(provider, concurrency, urls, proxy_list)
        level_results[provider] = result

        # Pausa entre providers para o SO liberar conexões/memória
        if i < len(providers_to_run) - 1:
            log(f"  Pausa 10s antes do próximo provider...")
            await asyncio.sleep(10)

    _print_level_comparison(concurrency, level_results)
    return level_results


def _print_level_comparison(concurrency: int, results: Dict[str, Dict[str, Any]]):
    log("")
    log(f"  --- Comparativo nível {concurrency} ---")
    log(f"  {'Provider':<12} {'Success%':>9} {'p50ms':>7} {'p90ms':>7} {'p99ms':>7} {'Erros':>6} {'BW Mbps':>8}")
    log(f"  {'-'*12} {'-'*9} {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*8}")
    for provider, r in results.items():
        label = PROVIDER_LABELS.get(provider, provider)
        lat = r.get("latency_ok_ms", {})
        log(
            f"  {label:<12} {r['success_rate_pct']:>8}% "
            f"{lat.get('p50','-'):>7} {lat.get('p90','-'):>7} {lat.get('p99','-'):>7} "
            f"{r['fail']:>6} {r['bandwidth_mbps']:>8}"
        )


# ---------------------------------------------------------------------------
# Gráficos ASCII
# ---------------------------------------------------------------------------
def _bar(value: float, max_val: float, width: int = 30) -> str:
    if max_val == 0:
        return " " * width
    filled = int(round(value / max_val * width))
    return "█" * filled + "░" * (width - filled)


def generate_ascii_charts(all_levels: Dict[int, Dict[str, Dict[str, Any]]]) -> str:
    lines = []
    providers = list(PROVIDER_LABELS.keys())
    levels = sorted(all_levels.keys())

    # --- Gráfico 1: Success Rate por nível ---
    lines += ["", "## Gráfico: Taxa de Sucesso (%) por Nível de Carga", ""]
    lines.append(f"{'Nível':<8} {'Provider':<12} {'%':>5}  {'Barra'}")
    lines.append("-" * 65)
    for level in levels:
        for provider in providers:
            r = all_levels[level].get(provider)
            if not r:
                continue
            pct = r["success_rate_pct"]
            label = PROVIDER_LABELS.get(provider, provider)
            bar = _bar(pct, 100, 30)
            lines.append(f"{level:<8} {label:<12} {pct:>5.1f}%  {bar}")
        lines.append("")

    # --- Gráfico 2: Latência p50 por nível ---
    lines += ["", "## Gráfico: Latência p50 (ms) por Nível de Carga", ""]
    # Encontra o max p50 para escala
    max_p50 = max(
        (all_levels[l].get(p, {}).get("latency_ok_ms", {}).get("p50", 0) or 0)
        for l in levels for p in providers
    ) or 1
    lines.append(f"{'Nível':<8} {'Provider':<12} {'p50ms':>7}  {'Barra'}")
    lines.append("-" * 65)
    for level in levels:
        for provider in providers:
            r = all_levels[level].get(provider)
            if not r:
                continue
            p50 = r.get("latency_ok_ms", {}).get("p50", 0) or 0
            label = PROVIDER_LABELS.get(provider, provider)
            bar = _bar(p50, max_p50, 30)
            lines.append(f"{level:<8} {label:<12} {p50:>7}ms  {bar}")
        lines.append("")

    # --- Gráfico 3: Throughput por nível ---
    lines += ["", "## Gráfico: Throughput (req/min) por Nível de Carga", ""]
    max_tp = max(
        (all_levels[l].get(p, {}).get("throughput_per_min", 0) or 0)
        for l in levels for p in providers
    ) or 1
    lines.append(f"{'Nível':<8} {'Provider':<12} {'req/min':>8}  {'Barra'}")
    lines.append("-" * 65)
    for level in levels:
        for provider in providers:
            r = all_levels[level].get(provider)
            if not r:
                continue
            tp = r.get("throughput_per_min", 0) or 0
            label = PROVIDER_LABELS.get(provider, provider)
            bar = _bar(tp, max_tp, 30)
            lines.append(f"{level:<8} {label:<12} {tp:>8.0f}  {bar}")
        lines.append("")

    # --- Gráfico 4: Evolução de erros por terços ---
    lines += ["", "## Gráfico: Distribuição de Erros por Terço do Teste", ""]
    lines.append("(Mostra se os erros aumentam ao longo do tempo — indica degradação)")
    lines.append("")
    for level in levels:
        lines.append(f"### Nível {level}")
        lines.append(f"{'Provider':<12} {'1º terço':>9} {'2º terço':>9} {'3º terço':>9}  {'Tendência'}")
        lines.append("-" * 55)
        for provider in providers:
            r = all_levels[level].get(provider)
            if not r:
                continue
            ed = r.get("error_distribution_thirds", {})
            t1 = ed.get("t1_first_third", 0)
            t2 = ed.get("t2_mid_third", 0)
            t3 = ed.get("t3_last_third", 0)
            label = PROVIDER_LABELS.get(provider, provider)
            if t1 == 0 and t2 == 0 and t3 == 0:
                trend = "sem erros"
            elif t3 > t1 * 1.3:
                trend = "↑ piora"
            elif t3 < t1 * 0.7:
                trend = "↓ melhora"
            else:
                trend = "→ estável"
            lines.append(f"{label:<12} {t1:>9} {t2:>9} {t3:>9}  {trend}")
        lines.append("")

    # --- Gráfico 5: Coeficiente de Variação de Latência ---
    lines += ["", "## Gráfico: Coeficiente de Variação de Latência (CV)", ""]
    lines.append("(CV = stdev/média | >1.0 = proxy muito instável | <0.5 = estável)")
    lines.append("")
    max_cv = max(
        (all_levels[l].get(p, {}).get("saturation", {}).get("cv_latency", 0) or 0)
        for l in levels for p in providers
    ) or 1
    lines.append(f"{'Nível':<8} {'Provider':<12} {'CV':>6}  {'Barra'}")
    lines.append("-" * 65)
    for level in levels:
        for provider in providers:
            r = all_levels[level].get(provider)
            if not r:
                continue
            cv = r.get("saturation", {}).get("cv_latency", 0) or 0
            label = PROVIDER_LABELS.get(provider, provider)
            bar = _bar(cv, max(max_cv, 2.0), 30)
            lines.append(f"{level:<8} {label:<12} {cv:>6.3f}  {bar}")
        lines.append("")

    # --- Gráfico 6: Bandwidth série temporal (p50 MB/s) ---
    lines += ["", "## Gráfico: Bandwidth p50 (MB/s) por Nível", ""]
    lines.append("(Calculado a partir de amostras de 0.5s durante o teste)")
    lines.append("")
    max_bw = max(
        (all_levels[l].get(p, {}).get("bandwidth_series_mbs", {}).get("p50", 0) or 0)
        for l in levels for p in providers
    ) or 1
    lines.append(f"{'Nível':<8} {'Provider':<12} {'p50 MB/s':>9}  {'Barra'}")
    lines.append("-" * 65)
    for level in levels:
        for provider in providers:
            r = all_levels[level].get(provider)
            if not r:
                continue
            bw = r.get("bandwidth_series_mbs", {}).get("p50", 0) or 0
            label = PROVIDER_LABELS.get(provider, provider)
            bar = _bar(bw, max_bw, 30)
            lines.append(f"{level:<8} {label:<12} {bw:>9.3f}  {bar}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Análise de carga ideal e máxima
# ---------------------------------------------------------------------------
def generate_capacity_analysis(all_levels: Dict[int, Dict[str, Dict[str, Any]]]) -> str:
    lines = ["", "## Análise de Capacidade por Provider", ""]
    providers = list(PROVIDER_LABELS.keys())
    levels = sorted(all_levels.keys())

    for provider in providers:
        label = PROVIDER_LABELS.get(provider, provider)
        lines.append(f"### {label}")
        lines.append("")

        ideal_load = None
        max_load = None
        degradation_level = None

        for level in levels:
            r = all_levels[level].get(provider)
            if not r:
                continue
            pct = r["success_rate_pct"]
            p90 = r.get("latency_ok_ms", {}).get("p90", 0) or 0

            # Carga ideal: success >= 90% e p90 <= 15s
            if pct >= 90 and p90 <= 15000:
                ideal_load = level

            # Carga máxima: último nível com success >= 70%
            if pct >= 70:
                max_load = level

            # Ponto de degradação: primeiro nível com success < 80%
            if pct < 80 and degradation_level is None:
                degradation_level = level

        lines.append(f"- **Carga ideal** (success ≥90%, p90 ≤15s): **{ideal_load or 'N/A'}** links")
        lines.append(f"- **Carga máxima** (success ≥70%): **{max_load or 'N/A'}** links")
        lines.append(f"- **Ponto de degradação** (success <80%): **{degradation_level or 'não atingido'}**")
        lines.append("")

        # Tabela de performance por nível
        lines.append(f"| Nível | Success% | p50ms | p90ms | p99ms | Erros | BW Mbps | Avaliação |")
        lines.append(f"|-------|----------|-------|-------|-------|-------|---------|-----------|")
        for level in levels:
            r = all_levels[level].get(provider)
            if not r:
                continue
            pct = r["success_rate_pct"]
            lat = r.get("latency_ok_ms", {})
            p50 = lat.get("p50", "-")
            p90 = lat.get("p90", "-")
            p99 = lat.get("p99", "-")
            erros = r["fail"]
            bw = r["bandwidth_mbps"]

            if pct >= 90:
                avaliacao = "✅ Ótimo"
            elif pct >= 80:
                avaliacao = "⚠️ Aceitável"
            elif pct >= 70:
                avaliacao = "🔶 Degradado"
            else:
                avaliacao = "❌ Crítico"

            lines.append(f"| {level} | {pct}% | {p50} | {p90} | {p99} | {erros} | {bw} | {avaliacao} |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Comparativo final entre providers
# ---------------------------------------------------------------------------
def generate_provider_comparison(all_levels: Dict[int, Dict[str, Dict[str, Any]]]) -> str:
    lines = ["", "## Comparativo Geral entre Providers", ""]
    providers = list(PROVIDER_LABELS.keys())
    levels = sorted(all_levels.keys())

    # Tabela de success rate
    lines.append("### Taxa de Sucesso (%) por Nível")
    lines.append("")
    header = "| Nível |" + "".join(f" {PROVIDER_LABELS[p]:^12} |" for p in providers)
    sep = "|-------|" + "".join(f"{'-'*14}|" for _ in providers)
    lines.append(header)
    lines.append(sep)
    for level in levels:
        row = f"| {level:<5} |"
        for p in providers:
            r = all_levels[level].get(p)
            val = f"{r['success_rate_pct']}%" if r else "N/A"
            row += f" {val:^12} |"
        lines.append(row)
    lines.append("")

    # Tabela de latência p50
    lines.append("### Latência p50 (ms) por Nível")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    for level in levels:
        row = f"| {level:<5} |"
        for p in providers:
            r = all_levels[level].get(p)
            val = str(r.get("latency_ok_ms", {}).get("p50", "N/A")) + "ms" if r else "N/A"
            row += f" {val:^12} |"
        lines.append(row)
    lines.append("")

    # Tabela de latência p90
    lines.append("### Latência p90 (ms) por Nível")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    for level in levels:
        row = f"| {level:<5} |"
        for p in providers:
            r = all_levels[level].get(p)
            val = str(r.get("latency_ok_ms", {}).get("p90", "N/A")) + "ms" if r else "N/A"
            row += f" {val:^12} |"
        lines.append(row)
    lines.append("")

    # Tabela de throughput
    lines.append("### Throughput (req/min) por Nível")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    for level in levels:
        row = f"| {level:<5} |"
        for p in providers:
            r = all_levels[level].get(p)
            val = str(r.get("throughput_per_min", "N/A")) if r else "N/A"
            row += f" {val:^12} |"
        lines.append(row)
    lines.append("")

    # Tabela de CV de Latência
    lines.append("### Coeficiente de Variação de Latência por Nível")
    lines.append("(>1.0 = proxy instável/sobrecarregado | <0.5 = estável)")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    for level in levels:
        row = f"| {level:<5} |"
        for p in providers:
            r = all_levels[level].get(p)
            val = str(r.get("saturation", {}).get("cv_latency", "N/A")) if r else "N/A"
            row += f" {val:^12} |"
        lines.append(row)
    lines.append("")

    # Tabela de diagnóstico de gargalo
    lines.append("### Diagnóstico de Gargalo por Nível")
    lines.append("")
    lines.append("| Nível | Provider | Diagnóstico |")
    lines.append("|-------|----------|-------------|")
    for level in levels:
        for p in providers:
            r = all_levels[level].get(p)
            if not r:
                continue
            diag = r.get("saturation", {}).get("bottleneck_diagnosis", "N/A")
            lines.append(f"| {level} | {PROVIDER_LABELS[p]} | {diag} |")
    lines.append("")

    # Ranking por nível
    lines.append("### Ranking de Melhor Provider por Nível (por success rate)")
    lines.append("")
    lines.append("| Nível | 1º | 2º | 3º |")
    lines.append("|-------|-----|-----|-----|")
    for level in levels:
        ranking = []
        for p in providers:
            r = all_levels[level].get(p)
            if r:
                ranking.append((PROVIDER_LABELS[p], r["success_rate_pct"]))
        ranking.sort(key=lambda x: -x[1])
        while len(ranking) < 3:
            ranking.append(("N/A", 0))
        lines.append(
            f"| {level} | {ranking[0][0]} ({ranking[0][1]}%) "
            f"| {ranking[1][0]} ({ranking[1][1]}%) "
            f"| {ranking[2][0]} ({ranking[2][1]}%) |"
        )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Geração do relatório Markdown
# ---------------------------------------------------------------------------
def generate_markdown(
    all_levels: Dict[int, Dict[str, Dict[str, Any]]],
    meta: Dict[str, Any],
) -> str:
    levels = sorted(all_levels.keys())
    providers = list(PROVIDER_LABELS.keys())

    lines = [
        "# Stress Test Unificado — 711Proxy + Decodo + Evomi",
        "",
        f"**Data:** {meta['timestamp']}",
        f"**Timeout:** {TIMEOUT_SECONDS}s",
        f"**Níveis testados:** {', '.join(str(l) for l in levels)}",
        f"**Fonte de URLs:** `busca_fornecedor.website_discovery` (discovery_status = 'alto')",
        f"**711Proxy:** {meta.get('proxies_711', 0)} proxies",
        f"**Decodo:** {meta.get('proxies_decodo', 0)} proxies",
        f"**Evomi:** {meta.get('proxies_evomi', 0)} proxies",
        "",
        "---",
        "",
    ]

    # Comparativo geral
    lines.append(generate_provider_comparison(all_levels))

    # Análise de capacidade
    lines.append(generate_capacity_analysis(all_levels))

    # Gráficos ASCII
    lines.append(generate_ascii_charts(all_levels))

    # Detalhes por nível
    lines += ["", "---", "", "## Detalhes por Nível de Carga", ""]

    for level in levels:
        lines.append(f"### Nível {level} links")
        lines.append("")

        for provider in providers:
            r = all_levels[level].get(provider)
            if not r:
                continue
            label = PROVIDER_LABELS.get(provider, provider)
            lines.append(f"#### {label} — {level} links")
            lines.append("")

            lat_ok = r.get("latency_ok_ms", {})
            lat_fail = r.get("latency_fail_ms", {})
            eb = r.get("error_breakdown", {})

            lines += [
                f"- **Success:** {r['success']} / {r['total_urls']} ({r['success_rate_pct']}%)",
                f"- **Tempo total:** {r['total_time_s']}s",
                f"- **Throughput:** {r['throughput_per_min']} req/min",
                f"- **Bandwidth:** {r['bandwidth_mbps']} Mbps | **Dados:** {r['total_data_mb']} MB",
                f"- **Peak connections:** {r['connections']['peak']}",
                f"- **Ponto de degradação:** {r.get('degradation_point') or 'não detectado'}",
                "",
                "**Latência OK (ms):**",
                "",
                "| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |",
                "|-----|-----|-----|-----|-----|-----|-----|-----|-------|",
                f"| {lat_ok.get('p25','-')} | {lat_ok.get('p50','-')} | {lat_ok.get('p75','-')} "
                f"| {lat_ok.get('p90','-')} | {lat_ok.get('p95','-')} | {lat_ok.get('p99','-')} "
                f"| {lat_ok.get('max','-')} | {lat_ok.get('avg','-')} | {lat_ok.get('stdev','-')} |",
                "",
            ]

            if lat_fail:
                lines += [
                    "**Latência FAIL (ms):**",
                    "",
                    "| p50 | p90 | p99 | max | avg |",
                    "|-----|-----|-----|-----|-----|",
                    f"| {lat_fail.get('p50','-')} | {lat_fail.get('p90','-')} "
                    f"| {lat_fail.get('p99','-')} | {lat_fail.get('max','-')} | {lat_fail.get('avg','-')} |",
                    "",
                ]

            if eb:
                lines += [
                    "**Breakdown de Erros:**",
                    "",
                    "| Tipo | Quantidade |",
                    "|------|------------|",
                ]
                for etype, cnt in sorted(eb.items(), key=lambda x: -x[1]):
                    lines.append(f"| {etype} | {cnt} |")
                lines.append("")

            # Diagnóstico de saturação
            sat = r.get("saturation", {})
            if sat:
                lines += [
                    "**Diagnóstico sob Carga Total:**",
                    "",
                    f"> **{sat.get('bottleneck_diagnosis', 'N/A')}**",
                    "",
                    "| Métrica | Valor | Interpretação |",
                    "|---------|-------|---------------|",
                    f"| Avg HTTP Time | {sat.get('avg_http_time_ms', 0)}ms | Tempo médio efetivo de rede |",
                    f"| CV Latência | {sat.get('cv_latency', 0)} | Instabilidade (>1.0 = muito instável) |",
                    f"| Peak Ativo | {sat.get('peak_active', 0)} ({sat.get('peak_active_pct', 0)}%) | Pico de conexões ativas simultâneas |",
                    f"| Média Ativo | {sat.get('avg_active_connections', 0)} | Média de conexões ativas (amostras 0.5s) |",
                    "",
                ]

            # HTTP time percentis
            ht = r.get("http_time_ms", {})
            if ht:
                lines += [
                    "**Tempo HTTP Efetivo (ms) — sem tempo em fila:**",
                    "",
                    "| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |",
                    "|-----|-----|-----|-----|-----|-----|-----|-----|",
                    f"| {ht.get('p25','-')} | {ht.get('p50','-')} | {ht.get('p75','-')} "
                    f"| {ht.get('p90','-')} | {ht.get('p95','-')} | {ht.get('p99','-')} "
                    f"| {ht.get('max','-')} | {ht.get('avg','-')} |",
                    "",
                ]

            # Bandwidth série temporal
            bw_s = r.get("bandwidth_series_mbs", {})
            if bw_s:
                lines += [
                    "**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**",
                    "",
                    "| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |",
                    "|-----|-----|-----|-----|-----|-----|-----|-------|",
                    f"| {bw_s.get('p25','-')} | {bw_s.get('p50','-')} | {bw_s.get('p75','-')} "
                    f"| {bw_s.get('p90','-')} | {bw_s.get('p95','-')} | {bw_s.get('max','-')} "
                    f"| {bw_s.get('avg','-')} | {bw_s.get('stdev','-')} |",
                    "",
                ]

            # Histograma
            lines += [
                "**Histograma de Tempo:**",
                "",
                "| Bucket | OK | FAIL | Total | FAIL% |",
                "|--------|-----|------|-------|-------|",
            ]
            for bucket, counts in r.get("time_histogram", {}).items():
                total_b = counts["ok"] + counts["fail"]
                if total_b > 0:
                    fail_pct = round(counts["fail"] / total_b * 100, 1)
                    lines.append(
                        f"| {bucket} | {counts['ok']} | {counts['fail']} | {total_b} | {fail_pct}% |"
                    )
            lines.append("")

            # Timeline granular 5s
            timeline = r.get("timeline_5s", [])
            if timeline:
                lines += [
                    "**Timeline Granular (janelas de 5s):**",
                    "",
                    "| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |",
                    "|--------|-----|------|----------|-----------|-----------|---------|",
                ]
                for tw in timeline:
                    lines.append(
                        f"| {tw['t']} | {tw['ok']} | {tw['fail']} | {tw['success_pct']}% "
                        f"| {tw['lat_ok_p50_ms']} | {tw['lat_ok_p90_ms']} "
                        f"| {tw['bw_mbs']} |"
                    )
                lines.append("")

            # Taxa de erro acumulada
            cum = r.get("cumulative_error_rate", [])
            if cum:
                lines += [
                    "**Taxa de Erro Acumulada ao Longo do Teste:**",
                    "",
                    "| Req completadas | % do total | Taxa de erro |",
                    "|-----------------|------------|--------------|",
                ]
                for c in cum:
                    lines.append(
                        f"| {c['at_request']} | {c['pct_complete']:.0f}% | {c['error_rate_pct']}% |"
                    )
                lines.append("")

            # Distribuição de erros por terços
            ed = r.get("error_distribution_thirds", {})
            lines += [
                "**Erros por Terço do Teste:**",
                "",
                "| 1º terço | 2º terço | 3º terço | Tendência |",
                "|----------|----------|----------|-----------|",
            ]
            t1 = ed.get("t1_first_third", 0)
            t2 = ed.get("t2_mid_third", 0)
            t3 = ed.get("t3_last_third", 0)
            if t3 > t1 * 1.3:
                trend = "↑ piora ao longo do tempo"
            elif t3 < t1 * 0.7:
                trend = "↓ melhora ao longo do tempo"
            else:
                trend = "→ estável"
            lines.append(f"| {t1} | {t2} | {t3} | {trend} |")
            lines.append("")

        lines.append("---")
        lines.append("")

    # JSON bruto
    lines += ["", "## Dados Brutos (JSON)", "", "```json"]
    flat_results = {}
    for level, providers_data in all_levels.items():
        flat_results[str(level)] = providers_data
    lines.append(json.dumps(flat_results, indent=2, ensure_ascii=False))
    lines.append("```")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    parser = argparse.ArgumentParser(description="Stress test unificado de proxies")
    parser.add_argument(
        "--provider",
        choices=["711proxy", "decodo", "evomi"],
        default=None,
        help="Rodar apenas um provider (padrão: todos sequencialmente)",
    )
    args = parser.parse_args()

    if not HAS_CURL:
        log("ERRO: curl_cffi não instalado. Execute: pip install curl_cffi")
        return

    provider_label = args.provider.upper() if args.provider else "711Proxy + Decodo + Evomi"
    log("=" * 70)
    log(f"  STRESS TEST UNIFICADO — {provider_label}")
    log("=" * 70)

    # Carrega proxies
    proxies_711, proxies_decodo, proxies_evomi = await asyncio.gather(
        load_711_proxies(),
        asyncio.to_thread(load_decodo_proxies),
        asyncio.to_thread(load_evomi_proxies),
    )

    if not any([proxies_711, proxies_decodo, proxies_evomi]):
        log("ERRO: Nenhum provider com proxies disponíveis")
        return

    log(f"Providers ativos: "
        f"711Proxy={'✓' if proxies_711 else '✗'} ({len(proxies_711)}) | "
        f"Decodo={'✓' if proxies_decodo else '✗'} ({len(proxies_decodo)}) | "
        f"Evomi={'✓' if proxies_evomi else '✗'} ({len(proxies_evomi)})")

    # Carrega URLs
    max_urls = max(CONCURRENCY_LEVELS)
    urls = await load_urls_from_db(max_urls)

    if not urls:
        log("ERRO: Nenhuma URL carregada do banco")
        return

    if len(urls) < max_urls:
        log(f"WARN: Apenas {len(urls)} URLs disponíveis (pedido: {max_urls}). Repetindo URLs...")
        urls = (urls * (max_urls // len(urls) + 2))[:max_urls]

    random.shuffle(urls)

    meta = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "proxies_711": len(proxies_711),
        "proxies_decodo": len(proxies_decodo),
        "proxies_evomi": len(proxies_evomi),
        "total_urls_available": len(urls),
    }

    # Executa todos os níveis
    all_levels: Dict[int, Dict[str, Dict[str, Any]]] = {}

    for i, level in enumerate(CONCURRENCY_LEVELS):
        level_results = await run_level_all_providers(
            level, urls, proxies_711, proxies_decodo, proxies_evomi,
            only_provider=args.provider,
        )
        all_levels[level] = level_results

        if i < len(CONCURRENCY_LEVELS) - 1:
            log(f"Aguardando 15s antes do próximo nível...")
            await asyncio.sleep(15)

    # Gera relatório
    log("")
    log("=" * 70)
    log("  GERANDO RELATÓRIO...")
    log("=" * 70)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    md_file = f"stress_test_unified_results_{timestamp}.md"
    json_file = f"stress_test_unified_results_{timestamp}.json"

    md = generate_markdown(all_levels, meta)
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md)

    flat_json = {str(k): v for k, v in all_levels.items()}
    flat_json["_meta"] = meta
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(flat_json, f, indent=2, ensure_ascii=False)

    log(f"Relatório Markdown: {md_file}")
    log(f"Dados JSON:         {json_file}")
    log("=" * 70)
    log("CONCLUÍDO")
    log("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
