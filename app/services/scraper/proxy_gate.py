"""
Semáforo global que limita conexões simultâneas ao proxy gateway.

O gateway 711Proxy degrada acima de ~1000-1500 conexões simultâneas.
Este módulo garante que nunca ultrapassamos esse limite, fazendo
workers excedentes esperarem LOCALMENTE (microsegundos) em vez de
sobrecarregar o gateway (que causaria timeouts de 30s+).

IMPORTANTE: o tempo de espera na fila do semáforo NÃO conta no
timeout da request — o timeout só começa após adquirir a vaga.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from .constants import MAX_CONCURRENT_PROXY_REQUESTS

logger = logging.getLogger(__name__)

_semaphore: Optional[asyncio.Semaphore] = None
_pending: int = 0
_active: int = 0


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy init — precisa ser chamado dentro de um event loop."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROXY_REQUESTS)
        logger.info(
            f"[proxy_gate] Semáforo inicializado: max={MAX_CONCURRENT_PROXY_REQUESTS} conexões simultâneas"
        )
    return _semaphore


@asynccontextmanager
async def acquire_proxy_slot():
    """
    Context manager que garante vaga no gateway antes de fazer a request.

    Uso:
        async with acquire_proxy_slot():
            # timeout da request começa AQUI, não antes
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
    """Retorna métricas do semáforo para monitoramento."""
    return {
        "max_slots": MAX_CONCURRENT_PROXY_REQUESTS,
        "active": _active,
        "pending": _pending,
    }
