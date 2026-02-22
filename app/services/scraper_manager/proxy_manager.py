"""
Proxy Manager — Sticky sessions mode (711Proxy residential).
Carrega sticky sessions do CSV, sem semáforo, IPs pré-alocados.
"""

import asyncio
import logging
import time
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProxyStats:
    requests: int = 0
    successes: int = 0
    failures: int = 0


class ProxyPool:
    """
    Pool baseado em sticky sessions.
    O session_pool.py gerencia as sessões e distribuição.
    """

    def __init__(self):
        self._loaded = False
        self._stats = ProxyStats()
        self._health_checked = False
        self._sessions_count = 0

    async def preload(self) -> int:
        from app.services.scraper.session_pool import load_sticky_pool
        count = await load_sticky_pool()
        self._sessions_count = count
        self._loaded = count > 0
        if self._loaded:
            logger.info(f"[ProxyPool] {count} sticky sessions carregadas")
        else:
            logger.error("[ProxyPool] Falha ao carregar sticky sessions!")
        return count

    async def health_check(self, test_url: str = "http://httpbin.org/ip", timeout: int = 15) -> dict:
        logger.info("[ProxyPool] Health check com sticky sessions...")
        latencies = []
        errors = []

        for _ in range(3):
            t0 = time.perf_counter()
            try:
                from app.services.scraper.session_pool import get_session
                sticky = get_session()
                resp = await asyncio.wait_for(
                    sticky.session.get(test_url, timeout=timeout), timeout=timeout,
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
            "mode": "sticky_sessions",
            "healthy": healthy,
            "sessions_loaded": self._sessions_count,
            "tests_ok": len(latencies),
            "tests_failed": len(errors),
            "latency_ms": {"avg": round(avg_lat, 1)} if latencies else {},
            "errors": errors or None,
        }

        label = "OK" if healthy else "FALHA"
        logger.info(f"[ProxyPool] Health check {label}: {len(latencies)}/3 OK, latência={avg_lat:.0f}ms")
        return stats

    def record_success(self, proxy: str = ""):
        self._stats.successes += 1

    def record_failure(self, proxy: str = "", reason: str = ""):
        self._stats.failures += 1

    def get_status(self) -> dict:
        total = self._stats.successes + self._stats.failures
        try:
            from app.services.scraper.session_pool import pool_stats
            sess = pool_stats()
        except Exception:
            sess = {}

        return {
            "loaded": self._loaded,
            "mode": "sticky_sessions",
            "sessions_count": self._sessions_count,
            "health_checked": self._health_checked,
            "total_requests": self._stats.requests,
            "successes": self._stats.successes,
            "failures": self._stats.failures,
            "success_rate": f"{self._stats.successes / total:.1%}" if total > 0 else "N/A",
            "session_pool": sess,
        }

    def reset_metrics(self):
        self._stats = ProxyStats()


proxy_pool = ProxyPool()


async def get_healthy_proxy(max_attempts: int = 5) -> Optional[str]:
    if not proxy_pool._loaded:
        await proxy_pool.preload()
    return "sticky"


def record_proxy_failure(proxy: str, reason: str = "unknown"):
    proxy_pool.record_failure(proxy, reason)


def record_proxy_success(proxy: str):
    proxy_pool.record_success(proxy)
