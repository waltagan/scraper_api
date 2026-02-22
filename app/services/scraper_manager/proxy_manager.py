"""
Proxy Manager — Gateway mode only (711Proxy residential).
Multi-gateway: distribui requests entre GLOBAL e US via proxy_gate.
O proxy_gate.py controla semáforos e seleção; este módulo mantém métricas.
"""

import asyncio
import logging
import time
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProxyStats:
    """Métricas de uso do proxy gateway."""
    requests: int = 0
    successes: int = 0
    failures: int = 0


class ProxyPool:
    """
    Pool simplificado — gateway mode only.
    O provider (711Proxy) faz rotação automática de IPs.
    proxy_gate.py gerencia seleção de gateway e semáforos.
    """

    def __init__(self):
        self._gateway_url: str = ""
        self._loaded = False
        self._stats = ProxyStats()
        self._health_checked = False

    async def preload(self) -> int:
        from app.core.proxy import proxy_manager

        if not proxy_manager.is_gateway_mode:
            logger.warning("[ProxyPool] List mode não suportado. Configure PROXY_GATEWAY_URL.")
            return 0

        self._gateway_url = proxy_manager.gateway_url
        self._loaded = True
        logger.info(f"[ProxyPool] Gateway mode ativo — endpoint: {self._gateway_url[:50]}...")
        return 1

    async def health_check(self, test_url: str = "http://httpbin.org/ip", timeout: int = 8) -> dict:
        logger.info(f"[ProxyPool] Gateway health check: {self._gateway_url[:50]}...")
        latencies = []
        errors = []

        for _ in range(3):
            t0 = time.perf_counter()
            try:
                from app.services.scraper.proxy_gate import acquire_proxy_slot
                from app.services.scraper.session_pool import get_session
                async with acquire_proxy_slot() as proxy:
                    session = await get_session(proxy)
                    resp = await asyncio.wait_for(
                        session.get(test_url, timeout=timeout), timeout=timeout,
                    )
                    lat = (time.perf_counter() - t0) * 1000
                    if resp.status_code == 200:
                        latencies.append(lat)
                    else:
                        errors.append(f"status_{resp.status_code}")
            except Exception as e:
                errors.append(type(e).__name__)

        self._health_checked = True
        healthy = len(latencies) > 0
        avg_lat = sum(latencies) / len(latencies) if latencies else 0

        stats = {
            "mode": "multi_gateway",
            "healthy": healthy,
            "pool_active": 1 if healthy else 0,
            "tests_ok": len(latencies),
            "tests_failed": len(errors),
            "latency_ms": {"avg": round(avg_lat, 1)} if latencies else {},
            "errors": errors or None,
        }

        emoji = "OK" if healthy else "FALHA"
        logger.info(f"[ProxyPool] Gateway health check {emoji}: {len(latencies)}/3 OK, latência={avg_lat:.0f}ms")
        return stats

    def get_next_proxy(self) -> Optional[str]:
        self._stats.requests += 1
        return self._gateway_url

    def get_proxy_excluding(self, exclude=None) -> Optional[str]:
        return self.get_next_proxy()

    def record_success(self, proxy: str = ""):
        self._stats.successes += 1

    def record_failure(self, proxy: str = "", reason: str = ""):
        self._stats.failures += 1

    def get_status(self) -> dict:
        total = self._stats.successes + self._stats.failures
        try:
            from app.services.scraper.proxy_gate import get_gate_stats
            gate = get_gate_stats()
        except Exception:
            gate = {}

        try:
            from app.services.scraper.session_pool import pool_stats
            sess = pool_stats()
        except Exception:
            sess = {}

        return {
            "loaded": self._loaded,
            "mode": "multi_gateway",
            "gateway_url": self._gateway_url[:50] + "..." if self._gateway_url else "",
            "health_checked": self._health_checked,
            "total_requests": self._stats.requests,
            "successes": self._stats.successes,
            "failures": self._stats.failures,
            "success_rate": f"{self._stats.successes / total:.1%}" if total > 0 else "N/A",
            "gate": gate,
            "session_pool": sess,
        }

    def reset_metrics(self):
        self._stats = ProxyStats()


proxy_pool = ProxyPool()


async def get_healthy_proxy(max_attempts: int = 5) -> Optional[str]:
    if not proxy_pool._loaded:
        await proxy_pool.preload()
    return proxy_pool.get_next_proxy()


def record_proxy_failure(proxy: str, reason: str = "unknown"):
    proxy_pool.record_failure(proxy, reason)


def record_proxy_success(proxy: str):
    proxy_pool.record_success(proxy)
