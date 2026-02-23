"""
Proxy Manager — modo direto + sticky sessions.
Retorna URL do proxy gateway (711Proxy).
Sticky sessions: cada porta = IP de saída fixo (30min).
"""

import json
import os
import asyncio
import logging
import time
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_GATEWAY_URL = os.getenv("PROXY_GATEWAY_URL", "")
_STICKY_SESSIONS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "711_sesions.json",
)


class ProxyPool:
    """Pool com sticky sessions — cada empresa usa um IP fixo."""

    def __init__(self):
        self._gateway_url: str = _GATEWAY_URL
        self._loaded = bool(self._gateway_url)
        self._sticky_ports: List[int] = []
        self._sticky_index: int = 0
        self._base_host: str = ""
        self._base_auth: str = ""

    async def preload(self) -> int:
        self._gateway_url = os.getenv("PROXY_GATEWAY_URL", "")
        self._loaded = bool(self._gateway_url)
        if self._loaded:
            parsed = urlparse(self._gateway_url)
            self._base_host = parsed.hostname or ""
            self._base_auth = f"{parsed.username}:{parsed.password}" if parsed.username else ""
            self._load_sticky_sessions()
            logger.info(
                f"[ProxyPool] Gateway: {self._gateway_url[:50]}... | "
                f"Sticky sessions: {len(self._sticky_ports)}"
            )
        else:
            logger.warning("[ProxyPool] PROXY_GATEWAY_URL nao configurada.")
        return 1 if self._loaded else 0

    def _load_sticky_sessions(self):
        try:
            if os.path.exists(_STICKY_SESSIONS_FILE):
                with open(_STICKY_SESSIONS_FILE, "r") as f:
                    data = json.load(f)
                entries = data.get("data", [])
                self._sticky_ports = [e["port"] for e in entries if "port" in e]
                logger.info(f"[ProxyPool] Loaded {len(self._sticky_ports)} sticky sessions from file")
            else:
                logger.warning(f"[ProxyPool] Sticky sessions file not found: {_STICKY_SESSIONS_FILE}")
        except Exception as e:
            logger.error(f"[ProxyPool] Failed to load sticky sessions: {e}")

    def get_sticky_proxy(self) -> Optional[str]:
        """Retorna proxy URL com porta sticky (round-robin). Mesma porta = mesmo IP.
        Portas sticky usam IP Whitelist (sem credenciais), não username/password."""
        if not self._sticky_ports or not self._base_host:
            return None
        port = self._sticky_ports[self._sticky_index % len(self._sticky_ports)]
        self._sticky_index += 1
        return f"http://{self._base_host}:{port}"

    async def health_check(self, test_url: str = "http://httpbin.org/ip", timeout: int = 8) -> dict:
        if not self._gateway_url:
            return {"mode": "direct_ip", "healthy": False, "errors": ["no gateway url"]}

        from app.services.scraper.http_client import get_shared_session
        latencies = []
        errors = []

        sticky_proxy = self.get_sticky_proxy()
        test_proxy = sticky_proxy or self._gateway_url
        label = "sticky" if sticky_proxy else "gateway"

        for _ in range(3):
            t0 = time.perf_counter()
            try:
                session = get_shared_session()
                resp = await asyncio.wait_for(
                    session.get(test_url, proxy=test_proxy, timeout=timeout),
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
        logger.info(
            f"[ProxyPool] Health {label} {'OK' if healthy else 'FALHA'}: "
            f"{len(latencies)}/3 OK, lat={avg_lat:.0f}ms"
        )
        return {
            "mode": "sticky_sessions" if self._sticky_ports else "direct_ip",
            "healthy": healthy,
            "tests_ok": len(latencies), "tests_failed": len(errors),
            "latency_ms": {"avg": round(avg_lat, 1)} if latencies else {},
            "sticky_sessions_loaded": len(self._sticky_ports),
            "test_type": label,
            "errors": errors or None,
        }

    def get_next_proxy(self):
        return self._gateway_url

    def get_status(self) -> dict:
        return {
            "loaded": self._loaded,
            "mode": "sticky_sessions" if self._sticky_ports else "direct_ip",
            "gateway_url": self._gateway_url[:50] + "..." if self._gateway_url else "",
            "sticky_sessions": len(self._sticky_ports),
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
