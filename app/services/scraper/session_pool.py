"""
Pool de sticky sessions 711Proxy — IPs residenciais pré-alocados.

Carrega sessões sticky do CSV (711_sesions.csv) no startup.
Cada sessão = 1 IP residencial brasileiro fixo por 10min (com auto-renew).
Workers pegam sessão diretamente, sem semáforo — o IP já está alocado.

Arquitetura:
  - N sessões sticky carregadas do CSV (até STICKY_POOL_SIZE)
  - Cada sessão cria 1 AsyncSession do curl_cffi com conexão TCP persistente
  - Round-robin atômico distribui sessões entre workers
  - Métricas por sessão (success/fail/latência) para monitoramento
"""

import asyncio
import csv
import logging
import os
import random
import time
from typing import Dict, List, Optional

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None  # type: ignore

from .constants import REQUEST_TIMEOUT, STICKY_POOL_SIZE

logger = logging.getLogger(__name__)
_MAX_CLIENTS = 30
_CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "711_sesions.csv")
_LATENCY_WINDOW = 200


class StickySession:
    """Uma sessão sticky com IP fixo e métricas."""

    __slots__ = (
        "proxy_url", "session", "total_success", "total_fail",
        "latencies", "in_use",
    )

    def __init__(self, proxy_url: str, session: "AsyncSession"):
        self.proxy_url = proxy_url
        self.session = session
        self.total_success = 0
        self.total_fail = 0
        self.latencies: List[float] = []
        self.in_use = 0

    def record(self, success: bool, latency_ms: float):
        if success:
            self.total_success += 1
        else:
            self.total_fail += 1
        self.latencies.append(latency_ms)
        if len(self.latencies) > _LATENCY_WINDOW:
            self.latencies = self.latencies[-_LATENCY_WINDOW:]

    def success_rate(self) -> float:
        total = self.total_success + self.total_fail
        return (self.total_success / total * 100) if total > 0 else 0.0

    def avg_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0.0


_sessions: List[StickySession] = []
_index = 0
_lock: Optional[asyncio.Lock] = None
_loaded = False
_stats = {
    "requests": 0, "sessions_loaded": 0, "csv_total": 0,
}


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _parse_proxy_line(line: str) -> str:
    """Converte formato CSV host:port:user:pass → URL http://user:pass@host:port"""
    parts = line.strip().split(":")
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    return line.strip()


def _load_csv() -> List[str]:
    """Carrega proxy URLs do CSV."""
    csv_path = os.path.abspath(_CSV_PATH)
    if not os.path.exists(csv_path):
        logger.error(f"[session_pool] CSV não encontrado: {csv_path}")
        return []

    proxies = []
    with open(csv_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                proxies.append(_parse_proxy_line(line))

    logger.info(f"[session_pool] {len(proxies)} sticky proxies no CSV")
    return proxies


async def load_sticky_pool(pool_size: int = STICKY_POOL_SIZE) -> int:
    """Carrega pool de sticky sessions. Chamado no startup do batch."""
    global _sessions, _loaded

    if _loaded and _sessions:
        return len(_sessions)

    async with _get_lock():
        if _loaded and _sessions:
            return len(_sessions)

        if not HAS_CURL_CFFI:
            raise RuntimeError("curl_cffi não instalado")

        all_proxies = _load_csv()
        if not all_proxies:
            logger.error("[session_pool] Nenhum proxy carregado!")
            return 0

        _stats["csv_total"] = len(all_proxies)
        selected = random.sample(all_proxies, min(pool_size, len(all_proxies)))

        impersonates = ["chrome131", "chrome124", "safari17_0", "chrome120", "edge101"]
        sessions = []
        for i, proxy_url in enumerate(selected):
            imp = impersonates[i % len(impersonates)]
            s = AsyncSession(
                impersonate=imp,
                proxy=proxy_url,
                timeout=REQUEST_TIMEOUT,
                verify=False,
                max_clients=_MAX_CLIENTS,
            )
            sessions.append(StickySession(proxy_url=proxy_url, session=s))

        _sessions = sessions
        _loaded = True
        _stats["sessions_loaded"] = len(sessions)

        logger.info(
            f"[session_pool] {len(sessions)} sticky sessions ativas "
            f"(de {len(all_proxies)} no CSV, max_clients={_MAX_CLIENTS})"
        )
        return len(sessions)


def get_session() -> StickySession:
    """
    Retorna próxima sticky session via round-robin.
    Sem bloqueio, sem semáforo — o IP já está alocado.
    """
    global _index

    if not _sessions:
        raise RuntimeError("Pool não carregado. Chame load_sticky_pool() primeiro.")

    _stats["requests"] += 1
    idx = _index % len(_sessions)
    _index += 1
    return _sessions[idx]


def record_result(sticky: StickySession, success: bool, latency_ms: float):
    """Registra resultado na sessão sticky."""
    sticky.record(success, latency_ms)


async def close_all():
    """Fecha todas as sessions. Chamar no shutdown."""
    global _sessions, _loaded
    closed = 0
    for ss in _sessions:
        try:
            await ss.session.close()
            closed += 1
        except Exception:
            pass
    _sessions.clear()
    _loaded = False
    logger.info(f"[session_pool] {closed} sticky sessions fechadas")


def pool_stats() -> dict:
    """Estatísticas do pool para endpoint de status."""
    if not _sessions:
        return {"loaded": False, "sessions": 0}

    total_success = sum(s.total_success for s in _sessions)
    total_fail = sum(s.total_fail for s in _sessions)
    total_req = total_success + total_fail
    all_lats = []
    for s in _sessions:
        all_lats.extend(s.latencies)

    lat_stats = {}
    if all_lats:
        all_lats.sort()
        n = len(all_lats)
        lat_stats = {
            "p50": round(all_lats[n // 2]),
            "p90": round(all_lats[int(n * 0.9)]),
            "p99": round(all_lats[min(int(n * 0.99), n - 1)]),
            "avg": round(sum(all_lats) / n),
        }

    active_sessions = sum(1 for s in _sessions if s.total_success + s.total_fail > 0)
    healthy = sum(1 for s in _sessions if s.success_rate() > 50)
    unhealthy = sum(1 for s in _sessions if s.success_rate() <= 50 and s.total_success + s.total_fail > 5)

    return {
        "loaded": _loaded,
        "mode": "sticky_sessions",
        "total_sessions": len(_sessions),
        "csv_total": _stats["csv_total"],
        "active_sessions": active_sessions,
        "healthy_sessions": healthy,
        "unhealthy_sessions": unhealthy,
        "max_clients_per_session": _MAX_CLIENTS,
        "total_requests": _stats["requests"],
        "total_success": total_success,
        "total_fail": total_fail,
        "overall_success_rate_pct": round(total_success / total_req * 100, 1) if total_req > 0 else 0,
        "latency_ms": lat_stats,
    }
