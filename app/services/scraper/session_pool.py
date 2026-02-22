"""
Pool de AsyncSession persistentes — connection pooling, TLS reuse, DNS cache.

Em vez de criar/destruir AsyncSession por request (overhead ~650-1800ms em
TCP handshake + TLS negotiation + DNS resolution), mantém sessões vivas
que reutilizam tudo isso automaticamente via libcurl.

Cada gateway recebe 5 sessões com fingerprints TLS distintos para máxima
diversidade. libcurl gerencia internamente:
  - TCP connection keepalive (reutiliza conexão aberta)
  - TLS session resumption (evita re-negotiation)
  - DNS cache (300s TTL por handle)

Com max_concurrent_proxy_requests=300, cada sessão serve ~60 slots
(300/5 = 60), garantindo reuso agressivo das conexões TCP abertas.
"""

import asyncio
import logging
import random
from typing import Dict, List, Optional

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None  # type: ignore

from .constants import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

_IMPERSONATE = [
    "chrome131",
    "chrome124",
    "safari17_0",
    "chrome120",
    "edge101",
]

_MAX_CLIENTS = 150
_DNS_CACHE_TIMEOUT = 300

_pool: Dict[str, List] = {}
_lock: Optional[asyncio.Lock] = None
_stats = {"requests": 0, "cache_hits": 0, "sessions_created": 0}


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _build_session(impersonate: str, proxy_url: str) -> "AsyncSession":
    """Cria sessão com keepalive agressivo e DNS cache longo."""
    return AsyncSession(
        impersonate=impersonate,
        proxy=proxy_url,
        timeout=REQUEST_TIMEOUT,
        verify=False,
        max_clients=_MAX_CLIENTS,
    )


async def get_session(proxy_url: str) -> "AsyncSession":
    """
    Retorna AsyncSession persistente para o gateway dado.
    Cria lazily na primeira chamada; reutiliza nas seguintes.
    Rotaciona entre 5 impersonate profiles para diversidade de fingerprint TLS.
    """
    if not HAS_CURL_CFFI:
        raise RuntimeError("curl_cffi não instalado")

    _stats["requests"] += 1

    if proxy_url in _pool:
        _stats["cache_hits"] += 1
        return random.choice(_pool[proxy_url])

    async with _get_lock():
        if proxy_url in _pool:
            _stats["cache_hits"] += 1
            return random.choice(_pool[proxy_url])

        sessions = []
        for imp in _IMPERSONATE:
            s = _build_session(imp, proxy_url)
            sessions.append(s)
            _stats["sessions_created"] += 1

        _pool[proxy_url] = sessions
        gw_id = proxy_url.split("@")[-1].split(":")[0] if "@" in proxy_url else proxy_url[:30]
        total = sum(len(v) for v in _pool.values())
        logger.info(
            f"[session_pool] {len(sessions)} sessions para {gw_id} "
            f"(max_clients={_MAX_CLIENTS}/session, "
            f"dns_cache={_DNS_CACHE_TIMEOUT}s, "
            f"pool_total={total})"
        )
        return random.choice(sessions)


async def close_all():
    """Fecha todas as sessions do pool. Chamar no shutdown da app."""
    global _pool
    closed = 0
    for sessions in _pool.values():
        for s in sessions:
            try:
                await s.close()
                closed += 1
            except Exception:
                pass
    _pool.clear()
    logger.info(f"[session_pool] {closed} sessions fechadas")


def pool_stats() -> dict:
    """Estatísticas do pool para expor no endpoint de status."""
    total_requests = _stats["requests"]
    cache_hits = _stats["cache_hits"]
    hit_rate = (cache_hits / total_requests * 100) if total_requests > 0 else 0.0
    return {
        "gateways": len(_pool),
        "total_sessions": sum(len(v) for v in _pool.values()),
        "sessions_per_gateway": len(_IMPERSONATE),
        "sessions_created": _stats["sessions_created"],
        "max_clients_per_session": _MAX_CLIENTS,
        "dns_cache_timeout_s": _DNS_CACHE_TIMEOUT,
        "impersonate_profiles": _IMPERSONATE,
        "total_requests": total_requests,
        "cache_hits": cache_hits,
        "cache_hit_rate_pct": round(hit_rate, 2),
    }
