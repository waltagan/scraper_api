"""
Multi-gateway proxy gate — distribui carga entre múltiplos gateways 711Proxy.

Cada gateway regional (US, AS, INA) tem capacidade independente de ~800
conexões simultâneas. Este módulo mantém um semáforo por gateway e
distribui requests round-robin pelo gateway com mais vagas livres.

acquire_proxy_slot() agora YIELDS a proxy_url do gateway selecionado,
eliminando a necessidade de chamar proxy_pool.get_next_proxy() separado.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import List, Optional

from .constants import MAX_CONCURRENT_PROXY_REQUESTS

logger = logging.getLogger(__name__)

GATEWAY_REGIONS = ["us", "as", "ina"]


@dataclass
class GatewaySlot:
    name: str
    proxy_url: str
    semaphore: Optional[asyncio.Semaphore] = None
    max_slots: int = 0
    active: int = 0
    pending: int = 0
    total_acquired: int = 0
    total_errors: int = 0


_gateways: List[GatewaySlot] = []
_initialized: bool = False


def _parse_gateway_urls() -> List[str]:
    """
    Lê PROXY_GATEWAY_URL (single) ou PROXY_GATEWAY_URLS (multi, comma-separated).
    Se multi não estiver configurado, gera URLs para as 3 regiões a partir da single.
    """
    multi = os.getenv("PROXY_GATEWAY_URLS", "")
    if multi:
        return [u.strip() for u in multi.split(",") if u.strip()]

    single = os.getenv("PROXY_GATEWAY_URL", "")
    if not single:
        return []

    if "us.rotgb" in single and len(GATEWAY_REGIONS) > 1:
        urls = []
        for region in GATEWAY_REGIONS:
            url = single.replace("us.rotgb", f"{region}.rotgb")
            urls.append(url)
        return urls

    return [single]


def _init_gateways() -> None:
    global _gateways, _initialized

    if _initialized:
        return

    urls = _parse_gateway_urls()
    if not urls:
        logger.warning("[proxy_gate] Nenhum gateway configurado!")
        _initialized = True
        return

    slots_per_gw = MAX_CONCURRENT_PROXY_REQUESTS

    for url in urls:
        region = "unknown"
        for r in GATEWAY_REGIONS:
            if f"{r}.rotgb" in url or f"{r}.rot" in url:
                region = r.upper()
                break

        gw = GatewaySlot(
            name=region,
            proxy_url=url,
            semaphore=asyncio.Semaphore(slots_per_gw),
            max_slots=slots_per_gw,
        )
        _gateways.append(gw)

    total = sum(g.max_slots for g in _gateways)
    names = [f"{g.name}({g.max_slots})" for g in _gateways]
    logger.info(
        f"[proxy_gate] {len(_gateways)} gateways inicializados: {', '.join(names)} "
        f"| total={total} slots"
    )
    _initialized = True


def _select_gateway() -> GatewaySlot:
    """Seleciona gateway com mais vagas livres (least-loaded)."""
    if not _gateways:
        raise RuntimeError("Nenhum proxy gateway configurado")

    if len(_gateways) == 1:
        return _gateways[0]

    best = None
    best_free = -1
    for gw in _gateways:
        free = gw.max_slots - gw.active
        if free > best_free:
            best_free = free
            best = gw

    return best  # type: ignore[return-value]


@asynccontextmanager
async def acquire_proxy_slot():
    """
    Adquire vaga no gateway com menor carga e yields a proxy_url.

    Uso:
        async with acquire_proxy_slot() as proxy_url:
            resp = await session.get(url, proxy=proxy_url)
    """
    _init_gateways()
    gw = _select_gateway()
    gw.pending += 1

    try:
        await gw.semaphore.acquire()
        gw.pending -= 1
        gw.active += 1
        gw.total_acquired += 1

        try:
            yield gw.proxy_url
        finally:
            gw.active -= 1
            gw.semaphore.release()
    except BaseException:
        gw.pending -= 1
        raise


def get_gate_stats() -> dict:
    _init_gateways()
    gateways = []
    total_active = 0
    total_pending = 0
    total_slots = 0

    for gw in _gateways:
        gateways.append({
            "name": gw.name,
            "max_slots": gw.max_slots,
            "active": gw.active,
            "pending": gw.pending,
            "total_acquired": gw.total_acquired,
            "free": gw.max_slots - gw.active,
        })
        total_active += gw.active
        total_pending += gw.pending
        total_slots += gw.max_slots

    return {
        "num_gateways": len(_gateways),
        "total_slots": total_slots,
        "total_active": total_active,
        "total_pending": total_pending,
        "gateways": gateways,
    }
