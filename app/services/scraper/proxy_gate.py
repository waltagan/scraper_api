"""
Semáforo global que limita conexões simultâneas ao proxy.

Suporta reconfiguração dinâmica via configure_gate() para ajustar
o limite conforme o modo de proxy ativo (gateway, byport, combined).

IMPORTANTE: o tempo de espera na fila do semáforo NÃO conta no
timeout da request — o timeout só começa após adquirir a vaga.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from .constants import (
    MAX_CONCURRENT_PROXY_REQUESTS,
    BYPORT_MAX_CONCURRENT,
    COMBINED_MAX_CONCURRENT,
)

logger = logging.getLogger(__name__)

_semaphore: Optional[asyncio.Semaphore] = None
_current_limit: int = 0
_pending: int = 0
_active: int = 0

MODE_LIMITS = {
    "gateway": MAX_CONCURRENT_PROXY_REQUESTS,
    "byport": BYPORT_MAX_CONCURRENT,
    "combined": COMBINED_MAX_CONCURRENT,
}


def configure_gate(mode: str = "gateway", custom_limit: int = 0):
    """Reconfigura o semáforo para o modo de proxy ativo."""
    global _semaphore, _current_limit, _pending, _active

    limit = custom_limit if custom_limit > 0 else MODE_LIMITS.get(mode, MAX_CONCURRENT_PROXY_REQUESTS)

    if limit == _current_limit and _semaphore is not None:
        return

    _semaphore = asyncio.Semaphore(limit)
    _current_limit = limit
    _pending = 0
    _active = 0
    logger.info(f"[proxy_gate] Semáforo configurado: mode={mode}, max={limit}")


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore, _current_limit
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROXY_REQUESTS)
        _current_limit = MAX_CONCURRENT_PROXY_REQUESTS
        logger.info(f"[proxy_gate] Semáforo inicializado (default): max={MAX_CONCURRENT_PROXY_REQUESTS}")
    return _semaphore


@asynccontextmanager
async def acquire_proxy_slot():
    """
    Context manager que garante vaga antes de fazer a request.

    Uso:
        async with acquire_proxy_slot():
            resp = await session.get(url, ...)
    """
    global _pending, _active
    _pending += 1

    try:
        sem = _get_semaphore()
        await sem.acquire()
        _pending -= 1
        _active += 1

        try:
            yield
        finally:
            _active -= 1
            sem.release()
    except BaseException:
        _pending -= 1
        raise


def get_gate_stats() -> dict:
    return {
        "max_slots": _current_limit or MAX_CONCURRENT_PROXY_REQUESTS,
        "active": _active,
        "pending": _pending,
    }
