"""
Proxy Manager — modo direto.
Retorna a URL do proxy (IP direto 711Proxy). IPs rotativos ilimitados.
Sem pool, sem gate, sem semáforo — worker é o único limite.
"""

import asyncio
import logging
import os
import time
from typing import Optional
from dataclasses import dataclass

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

logger = logging.getLogger(__name__)


@dataclass
class ProxyStats:
    requests: int = 0
    successes: int = 0
    failures: int = 0


class ProxyPool:
    """Pool mínimo — apenas entrega a URL do proxy e conta métricas."""

    def __init__(self):
        self._gateway_url: str = ""
        self._loaded = False
        self._stats = ProxyStats()
        self._health_checked = False

    async def preload(self) -> int:
        from app.core.proxy import proxy_manager

        if not proxy_manager.is_gateway_mode:
            logger.warning("[ProxyPool] Configure PROXY_GATEWAY_URL.")
            return 0

        self._gateway_url = proxy_manager.gateway_url
        self._loaded = True
        logger.info(f"[ProxyPool] Proxy direto: {self._gateway_url[:50]}...")
        return 1

    async def health_check(self, test_url: str = "http://httpbin.org/ip", timeout: int = 8) -> dict:
        logger.info(f"[ProxyPool] Health check: {self._gateway_url[:50]}...")
        latencies = []
        errors = []

        for _ in range(3):
            t0 = time.perf_counter()
            try:
                if not HAS_CURL_CFFI:
                    errors.append("no_curl_cffi")
                    continue
                async with AsyncSession(
                    impersonate="chrome131", verify=False, max_clients=1,
                ) as session:
                    resp = await asyncio.wait_for(
                        session.get(test_url, proxy=self._gateway_url, timeout=timeout),
                        timeout=timeout,
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

        status = "OK" if healthy else "FALHA"
        logger.info(f"[ProxyPool] Health check {status}: {len(latencies)}/3 OK, latência={avg_lat:.0f}ms")

        return {
            "mode": "direct_ip",
            "healthy": healthy,
            "tests_ok": len(latencies),
            "tests_failed": len(errors),
            "latency_ms": {"avg": round(avg_lat, 1)} if latencies else {},
            "errors": errors or None,
        }

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
        return {
            "loaded": self._loaded,
            "mode": "direct_ip",
            "gateway_url": self._gateway_url[:50] + "..." if self._gateway_url else "",
            "health_checked": self._health_checked,
            "total_requests": self._stats.requests,
            "successes": self._stats.successes,
            "failures": self._stats.failures,
            "success_rate": f"{self._stats.successes / total:.1%}" if total > 0 else "N/A",
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
