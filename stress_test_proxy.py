"""
Stress test do proxy 711Proxy com URLs reais do banco de dados.
Testa concorrências: 250, 500, 800, 1200, 1500, 2000.
Coleta estatísticas detalhadas para identificar limites de degradação.
"""

import asyncio
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL = True
except ImportError:
    HAS_CURL = False

DATABASE_URL = os.getenv("DATABASE_URL", "")
SCHEMA = "busca_fornecedor"

STICKY_API_URL = (
    "http://us.rotgbapi.711proxy.com:8089/gen"
    "?zone=custom&ptype=1&region=BR&count=900"
    "&proto=http&stype=json&sessType=sticky&sessTime=30&sessAuto=1"
)

CONCURRENCY_LEVELS = [250, 500, 800, 1200, 1500, 2000]
TIMEOUT_SECONDS = 20

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
]


@dataclass
class RequestResult:
    url: str
    status_code: int = 0
    success: bool = False
    elapsed_ms: float = 0.0
    error: str = ""
    error_type: str = ""
    content_length: int = 0
    ttfb_ms: float = 0.0


@dataclass
class LevelResult:
    concurrency: int
    total_urls: int = 0
    total_time_s: float = 0.0
    results: List[RequestResult] = field(default_factory=list)
    connection_samples: List[int] = field(default_factory=list)
    peak_connections: int = 0


active_connections = 0
peak_connections = 0


async def fetch_sticky_sessions() -> tuple:
    """Busca host e portas sticky da API 711Proxy."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(STICKY_API_URL)
        resp.raise_for_status()
        data = resp.json()

    entries = data.get("data", [])
    if not entries:
        raise RuntimeError("API 711Proxy retornou 0 entries")

    ports = [e["port"] for e in entries if "port" in e]
    hosts = {e["ip"] for e in entries if "ip" in e}
    if len(hosts) != 1:
        raise RuntimeError(f"Múltiplos hosts: {hosts}")

    host = hosts.pop()
    log(f"Proxy host: {host} | Portas: {ports[0]}-{ports[-1]} ({len(ports)} total)")
    return host, ports


async def load_urls_from_db(count: int) -> List[str]:
    """Carrega URLs de empresas com scrape bem-sucedido (error IS NULL)."""
    log(f"Conectando ao DB...")
    conn = await asyncpg.connect(DATABASE_URL)
    log(f"DB conectado. Buscando {count} URLs com scrape OK...")
    try:
        rows = await conn.fetch(f"""
            SELECT website_url FROM (
                SELECT DISTINCT website_url
                FROM "{SCHEMA}".scraped_chunks
                WHERE error IS NULL
                  AND website_url IS NOT NULL
                  AND website_url != ''
            ) sub
            ORDER BY random()
            LIMIT $1
        """, count)
        urls = [r["website_url"] for r in rows]
        log(f"DB: {len(urls)} URLs com scrape OK carregadas")
        return urls
    finally:
        await conn.close()


async def make_request(
    session: "AsyncSession",
    url: str,
    proxy_url: str,
    semaphore: asyncio.Semaphore,
) -> RequestResult:
    global active_connections, peak_connections

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    result = RequestResult(url=url)
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    async with semaphore:
        active_connections += 1
        if active_connections > peak_connections:
            peak_connections = active_connections

        t0 = time.perf_counter()
        try:
            resp = await session.get(
                url, headers=headers, proxy=proxy_url,
                timeout=TIMEOUT_SECONDS, allow_redirects=True, max_redirects=5,
            )
            elapsed = time.perf_counter() - t0
            result.elapsed_ms = elapsed * 1000
            result.status_code = resp.status_code
            result.content_length = len(resp.content) if resp.content else 0

            if resp.status_code == 200:
                result.success = True
            else:
                result.error = f"http_{resp.status_code}"
                result.error_type = f"http_{resp.status_code}"

        except Exception as e:
            elapsed = time.perf_counter() - t0
            result.elapsed_ms = elapsed * 1000
            err = str(e).lower()
            if "timeout" in err or "timed out" in err:
                result.error_type = "timeout"
            elif "connect" in err or "refused" in err:
                result.error_type = "connection"
            elif "ssl" in err or "certificate" in err:
                result.error_type = "ssl"
            elif "resolve" in err or "dns" in err or "nodename" in err:
                result.error_type = "dns"
            elif "reset" in err or "broken" in err or "aborted" in err:
                result.error_type = "reset"
            else:
                result.error_type = "other"
            result.error = f"{type(e).__name__}: {str(e)[:100]}"

        finally:
            active_connections -= 1

    return result


async def sample_connections(samples: List[int], stop_event: asyncio.Event):
    global active_connections
    try:
        while not stop_event.is_set():
            samples.append(active_connections)
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass


def percentiles(values: List[float]) -> Dict[str, float]:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    return {
        "min": round(s[0], 1),
        "p25": round(s[int(n * 0.25)], 1),
        "p50": round(s[int(n * 0.5)], 1),
        "p75": round(s[int(n * 0.75)], 1),
        "p90": round(s[int(n * 0.9)], 1),
        "p95": round(s[int(n * 0.95)], 1),
        "p99": round(s[min(int(n * 0.99), n - 1)], 1),
        "max": round(s[-1], 1),
        "avg": round(statistics.mean(values), 1),
        "stdev": round(statistics.stdev(values), 1) if len(values) > 1 else 0,
    }


def analyze_level(lr: LevelResult) -> Dict[str, Any]:
    ok = [r for r in lr.results if r.success]
    fail = [r for r in lr.results if not r.success]

    ok_times = [r.elapsed_ms for r in ok]
    fail_times = [r.elapsed_ms for r in fail]
    all_times = [r.elapsed_ms for r in lr.results]

    error_types = defaultdict(int)
    for r in fail:
        error_types[r.error_type] += 1

    ok_sizes = [r.content_length for r in ok if r.content_length > 0]
    total_bytes = sum(r.content_length for r in lr.results)

    # Bandwidth
    bandwidth_mbps = (total_bytes * 8 / 1_000_000) / lr.total_time_s if lr.total_time_s > 0 else 0

    # Time buckets para entender distribuição temporal
    time_buckets = defaultdict(lambda: {"ok": 0, "fail": 0})
    for r in lr.results:
        if r.elapsed_ms < 3000:
            b = "0-3s"
        elif r.elapsed_ms < 6000:
            b = "3-6s"
        elif r.elapsed_ms < 10000:
            b = "6-10s"
        elif r.elapsed_ms < 15000:
            b = "10-15s"
        elif r.elapsed_ms < 20000:
            b = "15-20s"
        else:
            b = "20s+"
        key = "ok" if r.success else "fail"
        time_buckets[b][key] += 1

    # Error timeline: primeiro/último 50%
    mid = len(lr.results) // 2
    first_half_errors = sum(1 for r in lr.results[:mid] if not r.success)
    second_half_errors = sum(1 for r in lr.results[mid:] if not r.success)

    conn_samples = lr.connection_samples

    return {
        "concurrency": lr.concurrency,
        "total_urls": lr.total_urls,
        "total_time_s": round(lr.total_time_s, 1),
        "throughput_per_min": round(lr.total_urls / lr.total_time_s * 60, 1) if lr.total_time_s > 0 else 0,
        "success": len(ok),
        "fail": len(fail),
        "success_rate_pct": round(len(ok) / len(lr.results) * 100, 1) if lr.results else 0,
        "latency_all_ms": percentiles(all_times),
        "latency_ok_ms": percentiles(ok_times),
        "latency_fail_ms": percentiles(fail_times),
        "error_breakdown": dict(sorted(error_types.items(), key=lambda x: -x[1])),
        "content_size_bytes": percentiles(ok_sizes) if ok_sizes else {},
        "total_data_mb": round(total_bytes / 1_000_000, 2),
        "bandwidth_mbps": round(bandwidth_mbps, 2),
        "connections": {
            "peak": lr.peak_connections,
            "samples": percentiles(conn_samples) if conn_samples else {},
        },
        "time_histogram": dict(sorted(time_buckets.items())),
        "error_distribution": {
            "first_half": first_half_errors,
            "second_half": second_half_errors,
        },
    }


async def run_level(
    concurrency: int,
    urls: List[str],
    sticky_host: str,
    sticky_ports: List[int],
) -> Dict[str, Any]:
    global active_connections, peak_connections
    active_connections = 0
    peak_connections = 0

    test_urls = urls[:concurrency]
    log(f"")
    log(f"{'='*60}")
    log(f"  NIVEL {concurrency} conexões ({len(test_urls)} URLs)")
    log(f"{'='*60}")

    sem = asyncio.Semaphore(concurrency)
    session = AsyncSession(impersonate="chrome131", verify=False, max_clients=concurrency + 100)

    samples: List[int] = []
    stop_event = asyncio.Event()
    sampler = asyncio.create_task(sample_connections(samples, stop_event))

    completed = 0
    ok_count = 0

    async def tracked_request(url_: str, proxy_: str) -> RequestResult:
        nonlocal completed, ok_count
        r = await make_request(session, url_, proxy_, sem)
        completed += 1
        if r.success:
            ok_count += 1
        if completed % 100 == 0 or completed == len(test_urls):
            pct = ok_count / completed * 100 if completed else 0
            log(f"  [{concurrency}] {completed}/{len(test_urls)} done "
                f"| OK: {pct:.0f}% | active: {active_connections} | peak: {peak_connections}")
        return r

    t0 = time.perf_counter()

    tasks = []
    for i, url in enumerate(test_urls):
        port = sticky_ports[i % len(sticky_ports)]
        proxy_url = f"http://{sticky_host}:{port}"
        tasks.append(tracked_request(url, proxy_url))

    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - t0

    stop_event.set()
    sampler.cancel()

    lr = LevelResult(
        concurrency=concurrency,
        total_urls=len(test_urls),
        total_time_s=total_time,
        results=results,
        connection_samples=samples,
        peak_connections=peak_connections,
    )

    analysis = analyze_level(lr)

    log(f"  Tempo: {total_time:.1f}s | Success: {analysis['success_rate_pct']}% "
        f"| Peak conn: {peak_connections} | BW: {analysis['bandwidth_mbps']} Mbps")
    log(f"  OK latency p50: {analysis['latency_ok_ms'].get('p50', 'N/A')}ms "
        f"| p90: {analysis['latency_ok_ms'].get('p90', 'N/A')}ms")
    log(f"  Errors: {analysis['error_breakdown']}")

    await session.close()
    return analysis


def generate_markdown(all_results: List[Dict[str, Any]], sticky_host: str) -> str:
    lines = [
        "# Stress Test Proxy 711Proxy — Resultados",
        "",
        f"**Data:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Proxy Host:** {sticky_host}",
        f"**Timeout:** {TIMEOUT_SECONDS}s",
        f"**Níveis testados:** {', '.join(str(r['concurrency']) for r in all_results)}",
        f"**URLs:** reais do banco PostgreSQL (empresas brasileiras)",
        "",
        "---",
        "",
        "## Resumo Comparativo",
        "",
        "| Conc. | Success% | OK | Fail | Tempo(s) | Throughput/min | Peak Conn | BW (Mbps) | Data (MB) |",
        "|-------|----------|-----|------|----------|----------------|-----------|-----------|-----------|",
    ]

    for r in all_results:
        lines.append(
            f"| {r['concurrency']} | {r['success_rate_pct']}% | {r['success']} | {r['fail']} "
            f"| {r['total_time_s']} | {r['throughput_per_min']} | {r['connections']['peak']} "
            f"| {r['bandwidth_mbps']} | {r['total_data_mb']} |"
        )

    lines += [
        "",
        "## Latência (ms) — Requests OK",
        "",
        "| Conc. | p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |",
        "|-------|-----|-----|-----|-----|-----|-----|-----|-----|-------|",
    ]
    for r in all_results:
        lat = r.get("latency_ok_ms", {})
        if lat:
            lines.append(
                f"| {r['concurrency']} | {lat.get('p25','-')} | {lat.get('p50','-')} "
                f"| {lat.get('p75','-')} | {lat.get('p90','-')} | {lat.get('p95','-')} "
                f"| {lat.get('p99','-')} | {lat.get('max','-')} | {lat.get('avg','-')} "
                f"| {lat.get('stdev','-')} |"
            )

    lines += [
        "",
        "## Latência (ms) — Requests FAIL",
        "",
        "| Conc. | p50 | p90 | p99 | max | avg |",
        "|-------|-----|-----|-----|-----|-----|",
    ]
    for r in all_results:
        lat = r.get("latency_fail_ms", {})
        if lat:
            lines.append(
                f"| {r['concurrency']} | {lat.get('p50','-')} | {lat.get('p90','-')} "
                f"| {lat.get('p99','-')} | {lat.get('max','-')} | {lat.get('avg','-')} |"
            )

    lines += [
        "",
        "## Conexões Ativas (amostras a cada 0.5s)",
        "",
        "| Conc. | Peak | p50 | p75 | p90 | p95 | max | avg |",
        "|-------|------|-----|-----|-----|-----|-----|-----|",
    ]
    for r in all_results:
        c = r.get("connections", {}).get("samples", {})
        if c:
            lines.append(
                f"| {r['concurrency']} | {r['connections']['peak']} "
                f"| {c.get('p50','-')} | {c.get('p75','-')} "
                f"| {c.get('p90','-')} | {c.get('p95','-')} "
                f"| {c.get('max','-')} | {c.get('avg','-')} |"
            )

    lines += [
        "",
        "## Breakdown de Erros",
        "",
        "| Conc. | timeout | connection | dns | ssl | reset | http_4xx | http_5xx | other |",
        "|-------|---------|------------|-----|-----|-------|----------|----------|-------|",
    ]
    for r in all_results:
        eb = r.get("error_breakdown", {})
        lines.append(
            f"| {r['concurrency']} "
            f"| {eb.get('timeout', 0)} | {eb.get('connection', 0)} "
            f"| {eb.get('dns', 0)} | {eb.get('ssl', 0)} "
            f"| {eb.get('reset', 0)} "
            f"| {sum(v for k, v in eb.items() if 'http_4' in k)} "
            f"| {sum(v for k, v in eb.items() if 'http_5' in k)} "
            f"| {eb.get('other', 0)} |"
        )

    lines += [
        "",
        "## Histograma de Tempo (OK vs FAIL por bucket)",
        "",
    ]
    for r in all_results:
        lines.append(f"### {r['concurrency']} conexões")
        lines.append("")
        lines.append("| Bucket | OK | FAIL |")
        lines.append("|--------|-----|------|")
        for bucket, counts in r.get("time_histogram", {}).items():
            lines.append(f"| {bucket} | {counts['ok']} | {counts['fail']} |")
        lines.append("")

    lines += [
        "## Distribuição de Erros (1ª vs 2ª metade)",
        "",
        "| Conc. | 1ª metade | 2ª metade | Tendência |",
        "|-------|-----------|-----------|-----------|",
    ]
    for r in all_results:
        ed = r.get("error_distribution", {})
        f1 = ed.get("first_half", 0)
        f2 = ed.get("second_half", 0)
        trend = "estável" if abs(f1 - f2) < max(f1, f2, 1) * 0.2 else ("piora" if f2 > f1 else "melhora")
        lines.append(f"| {r['concurrency']} | {f1} | {f2} | {trend} |")

    lines += [
        "",
        "## Content Size (bytes) — Requests OK",
        "",
        "| Conc. | p50 | p90 | max | avg | total_MB |",
        "|-------|-----|-----|-----|-----|----------|",
    ]
    for r in all_results:
        cs = r.get("content_size_bytes", {})
        if cs:
            lines.append(
                f"| {r['concurrency']} | {cs.get('p50','-')} | {cs.get('p90','-')} "
                f"| {cs.get('max','-')} | {cs.get('avg','-')} | {r['total_data_mb']} |"
            )

    lines += ["", "---", "", "## Dados Brutos (JSON)", "", "```json"]
    lines.append(json.dumps(all_results, indent=2, ensure_ascii=False))
    lines.append("```")

    return "\n".join(lines)


async def main():
    if not HAS_CURL:
        log("ERRO: curl_cffi não instalado")
        return

    log("=" * 60)
    log("  STRESS TEST PROXY 711Proxy")
    log("=" * 60)

    sticky_host, sticky_ports = await fetch_sticky_sessions()

    max_urls = max(CONCURRENCY_LEVELS)
    urls = await load_urls_from_db(max_urls)

    if len(urls) < max_urls:
        log(f"WARN: Apenas {len(urls)} URLs disponíveis (pedido: {max_urls})")
        urls = urls * (max_urls // len(urls) + 1)

    random.shuffle(urls)

    all_results = []
    for level in CONCURRENCY_LEVELS:
        result = await run_level(level, urls, sticky_host, sticky_ports)
        all_results.append(result)
        log(f"Aguardando 10s para proxy estabilizar...")
        await asyncio.sleep(10)

    md = generate_markdown(all_results, sticky_host)
    output_file = "stress_test_proxy_results.md"
    with open(output_file, "w") as f:
        f.write(md)
    log(f"{'='*60}")
    log(f"RESULTADOS SALVOS EM: {output_file}")
    log(f"{'='*60}")

    json_file = "stress_test_proxy_results.json"
    with open(json_file, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    log(f"JSON bruto: {json_file}")


if __name__ == "__main__":
    asyncio.run(main())
