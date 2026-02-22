"""
Proxy Manager — modo direto.
Retorna a URL do proxy gateway (711Proxy). Sem pool, sem metricas complexas.
"""

import os
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_GATEWAY_URL = os.getenv("PROXY_GATEWAY_URL", "")


class ProxyPool:
    """Pool minimo — apenas entrega a URL do proxy."""

    def __init__(self):
        self._gateway_url: str = _GATEWAY_URL
        self._loaded = bool(self._gateway_url)

    async def preload(self) -> int:
        self._gateway_url = os.getenv("PROXY_GATEWAY_URL", "")
        self._loaded = bool(self._gateway_url)
        if self._loaded:
            logger.info(f"[ProxyPool] Gateway: {self._gateway_url[:50]}...")
        else:
            logger.warning("[ProxyPool] PROXY_GATEWAY_URL nao configurada.")
        return 1 if self._loaded else 0

    async def health_check(self, test_url: str = "http://httpbin.org/ip", timeout: int = 8) -> dict:
        if not self._gateway_url:
            return {"mode": "direct_ip", "healthy": False, "errors": ["no gateway url"]}

        from app.services.scraper.http_client import get_shared_session
        latencies = []
        errors = []
        for _ in range(3):
            t0 = time.perf_counter()
            try:
                session = get_shared_session()
                resp = await asyncio.wait_for(
                    session.get(test_url, proxy=self._gateway_url, timeout=timeout),
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    latencies.append((time.perf_counter() - t0) * 1000)
                else:
                    errors.append(f"status_{resp.status_code}")
            except Exception as e:
                errors.append(type(e).__name__)

        healthy = len(latencies) > 0
        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        logger.info(f"[ProxyPool] Health {'OK' if healthy else 'FALHA'}: {len(latencies)}/3 OK, lat={avg_lat:.0f}ms")
        return {
            "mode": "direct_ip", "healthy": healthy,
            "tests_ok": len(latencies), "tests_failed": len(errors),
            "latency_ms": {"avg": round(avg_lat, 1)} if latencies else {},
            "errors": errors or None,
        }

    def get_next_proxy(self):
        return self._gateway_url

    def get_status(self) -> dict:
        return {
            "loaded": self._loaded,
            "mode": "direct_ip",
            "gateway_url": self._gateway_url[:50] + "..." if self._gateway_url else "",
        }


proxy_pool = ProxyPool()


async def get_healthy_proxy(max_attempts: int = 5):
    if not proxy_pool._loaded:
        await proxy_pool.preload()
    return proxy_pool.get_next_proxy()


def record_proxy_failure(proxy: str, reason: str = "unknown"):
    pass


def record_proxy_success(proxy: str):
    pass
