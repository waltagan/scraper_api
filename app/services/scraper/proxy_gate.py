"""
Multi-gateway proxy gate — distribui carga entre gateways 711Proxy.

Gateways ativos: GLOBAL, US (próximos da infra Railway/US).
AS e HK removidos — roteamento triangular (US→Ásia→BR) causa ~33% success vs ~57%.
EU e INA descartados — connection reset persistente.
Cada gateway tem semáforo independente; seleção por least-loaded.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import List, Optional

from .constants import MAX_CONCURRENT_PROXY_REQUESTS

logger = logging.getLogger(__name__)

GATEWAY_REGIONS = ["global", "us"]

_REGION_LABELS = {
    "global": "GLOBAL", "us": "US", "as": "AS", "hk": "HK",
    "eu": "EU", "ina": "INA",
}


@dataclass
class GatewaySlot:
    name: str
    proxy_url: str
    semaphore: Optional[asyncio.Semaphore] = None
    max_slots: int = 0
    active: int = 0
    pending: int = 0
    total_acquired: int = 0
    total_success: int = 0
    total_fail: int = 0
    latencies: List[float] = field(default_factory=list)
    _latency_window: int = 500

    def record_success(self, latency_ms: float):
        self.total_success += 1
        self._record_latency(latency_ms)

    def record_failure(self, latency_ms: float):
        self.total_fail += 1
        self._record_latency(latency_ms)

    def _record_latency(self, lat: float):
        self.latencies.append(lat)
        if len(self.latencies) > self._latency_window:
            self.latencies = self.latencies[-self._latency_window:]

    def success_rate(self) -> float:
        total = self.total_success + self.total_fail
        return (self.total_success / total * 100) if total > 0 else 0.0

    def latency_percentiles(self) -> dict:
        if not self.latencies:
            return {}
        s = sorted(self.latencies)
        n = len(s)
        return {
            "p50": round(s[n // 2]),
            "p90": round(s[int(n * 0.9)]),
            "p99": round(s[min(int(n * 0.99), n - 1)]),
            "avg": round(sum(s) / n),
        }


_gateways: List[GatewaySlot] = []
_initialized: bool = False


def _parse_gateway_urls() -> List[str]:
    """
    Lê PROXY_GATEWAY_URLS (multi, comma-separated) ou gera a partir de
    PROXY_GATEWAY_URL (single) expandindo para as 4 regiões ativas.
    """
    multi = os.getenv("PROXY_GATEWAY_URLS", "")
    if multi:
        return [u.strip() for u in multi.split(",") if u.strip()]

    single = os.getenv("PROXY_GATEWAY_URL", "")
    if not single:
        return []

    if "rotgb" in single:
        base = single
        for known in ["global.rotgb", "us.rotgb", "as.rotgb", "hk.rotgb",
                       "eu.rotgb", "ina.rotgb"]:
            if known in base:
                base = base.replace(known, "{REGION}.rotgb")
                break

        if "{REGION}" in base:
            return [base.replace("{REGION}", r) for r in GATEWAY_REGIONS]

    return [single]


def _detect_region(url: str) -> str:
    for prefix, label in _REGION_LABELS.items():
        if f"{prefix}.rotgb" in url or f"{prefix}.rot" in url:
            return label
    return "UNKNOWN"


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
        gw = GatewaySlot(
            name=_detect_region(url),
            proxy_url=url,
            semaphore=asyncio.Semaphore(slots_per_gw),
            max_slots=slots_per_gw,
        )
        _gateways.append(gw)

    total = sum(g.max_slots for g in _gateways)
    names = [f"{g.name}({g.max_slots})" for g in _gateways]
    logger.info(
        f"[proxy_gate] {len(_gateways)} gateways: {', '.join(names)} "
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
    acquired = False

    try:
        await gw.semaphore.acquire()
        acquired = True
        gw.pending -= 1
        gw.active += 1
        gw.total_acquired += 1

        try:
            yield gw.proxy_url
        finally:
            gw.active -= 1
            gw.semaphore.release()
    except BaseException:
        if not acquired:
            gw.pending -= 1
        raise


def record_gateway_result(proxy_url: str, success: bool, latency_ms: float):
    """Registra resultado (success/fail + latência) no gateway correspondente."""
    for gw in _gateways:
        if gw.proxy_url == proxy_url:
            if success:
                gw.record_success(latency_ms)
            else:
                gw.record_failure(latency_ms)
            return


def get_gate_stats() -> dict:
    _init_gateways()
    gateways = []
    total_active = 0
    total_pending = 0
    total_slots = 0
    total_success = 0
    total_fail = 0
    total_acquired = 0

    for gw in _gateways:
        total_req = gw.total_success + gw.total_fail
        util_pct = round(gw.active / gw.max_slots * 100, 1) if gw.max_slots > 0 else 0
        gateways.append({
            "name": gw.name,
            "max_slots": gw.max_slots,
            "active": gw.active,
            "pending": gw.pending,
            "total_acquired": gw.total_acquired,
            "free": gw.max_slots - gw.active,
            "utilization_pct": util_pct,
            "success": gw.total_success,
            "fail": gw.total_fail,
            "total_requests": total_req,
            "success_rate": f"{gw.success_rate():.1f}%",
            "latency_ms": gw.latency_percentiles(),
        })
        total_active += gw.active
        total_pending += gw.pending
        total_slots += gw.max_slots
        total_success += gw.total_success
        total_fail += gw.total_fail
        total_acquired += gw.total_acquired

    total_req_all = total_success + total_fail
    overall_rate = round(total_success / total_req_all * 100, 1) if total_req_all > 0 else 0

    return {
        "num_gateways": len(_gateways),
        "total_slots": total_slots,
        "total_active": total_active,
        "total_pending": total_pending,
        "total_acquired": total_acquired,
        "total_success": total_success,
        "total_fail": total_fail,
        "overall_success_rate_pct": overall_rate,
        "gateways": gateways,
    }
