"""
Proxy Manager — sticky sessions via API 711Proxy.
Cada porta = IP de saída fixo (30min).
Carrega portas automaticamente da API no startup de cada batch.
"""

import os
import asyncio
import logging
import time
import httpx
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_GATEWAY_URL = os.getenv("PROXY_GATEWAY_URL", "")
_STICKY_API_URL = (
    "http://us.rotgbapi.711proxy.com:8089/gen"
    "?zone=custom&ptype=1&region=BR&count=900"
    "&proto=http&stype=json&sessType=sticky&sessTime=30&sessAuto=1"
)


class ProxyPool:
    """Pool com sticky sessions — cada empresa usa um IP fixo."""

    def __init__(self):
        self._gateway_url: str = _GATEWAY_URL
        self._loaded = bool(self._gateway_url)
        self._sticky_ports: List[int] = []
        self._sticky_host: str = ""
        self._sticky_index: int = 0
        self._base_host: str = ""
        self._base_auth: str = ""

    async def preload(self) -> int:
        self._gateway_url = os.getenv("PROXY_GATEWAY_URL", "")
        self._loaded = bool(self._gateway_url)
        if not self._loaded:
            logger.warning("[ProxyPool] PROXY_GATEWAY_URL nao configurada.")
            return 0

        parsed = urlparse(self._gateway_url)
        self._base_host = parsed.hostname or ""
        self._base_auth = (
            f"{parsed.username}:{parsed.password}" if parsed.username else ""
        )

        await self._fetch_sticky_sessions()

        logger.info(
            f"[ProxyPool] Sticky host: {self._sticky_host} | "
            f"Sticky sessions: {len(self._sticky_ports)}"
        )
        return 1

    async def _fetch_sticky_sessions(self):
        """Busca portas sticky da API 711Proxy."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(_STICKY_API_URL)
                resp.raise_for_status()
                data = resp.json()

            if data.get("code") != 200:
                logger.error(
                    f"[ProxyPool] API 711Proxy erro: "
                    f"code={data.get('code')}, msg={data.get('msg')}"
                )
                return

            entries = data.get("data", [])
            if not entries:
                logger.error("[ProxyPool] API 711Proxy retornou 0 entries")
                return

            self._sticky_ports = [e["port"] for e in entries if "port" in e]
            hosts = {e["ip"] for e in entries if "ip" in e}

            if len(hosts) != 1:
                logger.error(f"[ProxyPool] API retornou múltiplos hosts: {hosts}")
                return

            self._sticky_host = hosts.pop()
            logger.info(
                f"[ProxyPool] API 711Proxy OK: {len(self._sticky_ports)} portas "
                f"(host={self._sticky_host}, "
                f"ports={self._sticky_ports[0]}-{self._sticky_ports[-1]})"
            )
        except Exception as e:
            logger.error(f"[ProxyPool] API 711Proxy falhou: {e}")

    def get_sticky_proxy(self) -> Optional[str]:
        """Retorna proxy URL com porta sticky (round-robin). Mesma porta = mesmo IP.
        Portas sticky usam IP Whitelist (sem credenciais)."""
        if not self._sticky_ports or not self._sticky_host:
            return None
        port = self._sticky_ports[self._sticky_index % len(self._sticky_ports)]
        self._sticky_index += 1
        return f"http://{self._sticky_host}:{port}"

    async def health_check(
        self, test_url: str = "http://httpbin.org/ip", timeout: int = 8
    ) -> dict:
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
            "tests_ok": len(latencies),
            "tests_failed": len(errors),
            "latency_ms": {"avg": round(avg_lat, 1)} if latencies else {},
            "sticky_sessions_loaded": len(self._sticky_ports),
            "sticky_host": self._sticky_host,
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
            "sticky_host": self._sticky_host,
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
