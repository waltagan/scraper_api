"""
Proxy Manager — dual provider: 711Proxy + Decodo.
711Proxy: sticky sessions via API (IP Whitelist, max 800 conn).
Decodo: sticky sessions via CSV (user:pass auth, max 1500 conn).
Round-robin balanceado entre providers.
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
_DECODO_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data_decodo_ips.csv")


class ProxyPool:
    """Pool dual: 711Proxy + Decodo com round-robin balanceado."""

    def __init__(self):
        self._gateway_url: str = _GATEWAY_URL
        self._loaded = False

        self._711_proxies: List[str] = []
        self._711_index: int = 0
        self._711_host: str = ""

        self._decodo_proxies: List[str] = []
        self._decodo_index: int = 0

        self._call_counter: int = 0

    async def preload(self) -> int:
        self._gateway_url = os.getenv("PROXY_GATEWAY_URL", "")

        await self._fetch_711_sessions()
        self._load_decodo_proxies()

        total = len(self._711_proxies) + len(self._decodo_proxies)
        self._loaded = total > 0

        logger.info(
            f"[ProxyPool] 711Proxy: {len(self._711_proxies)} proxies (host={self._711_host}) | "
            f"Decodo: {len(self._decodo_proxies)} proxies | Total: {total}"
        )
        return 1 if self._loaded else 0

    async def _fetch_711_sessions(self):
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

            ports = [e["port"] for e in entries if "port" in e]
            hosts = {e["ip"] for e in entries if "ip" in e}

            if len(hosts) != 1:
                logger.error(f"[ProxyPool] API retornou múltiplos hosts: {hosts}")
                return

            self._711_host = hosts.pop()
            self._711_proxies = [f"http://{self._711_host}:{p}" for p in ports]
            logger.info(
                f"[ProxyPool] 711Proxy OK: {len(self._711_proxies)} portas "
                f"({ports[0]}-{ports[-1]})"
            )
        except Exception as e:
            logger.error(f"[ProxyPool] API 711Proxy falhou: {e}")

    def _load_decodo_proxies(self):
        """Carrega proxy URLs do CSV Decodo."""
        csv_path = os.path.normpath(_DECODO_CSV)
        if not os.path.exists(csv_path):
            logger.warning(f"[ProxyPool] CSV Decodo não encontrado: {csv_path}")
            return

        with open(csv_path) as f:
            self._decodo_proxies = [line.strip() for line in f if line.strip()]

        if self._decodo_proxies:
            logger.info(
                f"[ProxyPool] Decodo OK: {len(self._decodo_proxies)} proxies "
                f"(portas {self._decodo_proxies[0].split(':')[-1]}"
                f"-{self._decodo_proxies[-1].split(':')[-1]})"
            )

    def get_sticky_proxy(self) -> Optional[str]:
        """Retorna proxy round-robin balanceado entre 711 e Decodo.
        Ratio ~35% 711 / ~65% Decodo (proporcional aos limites 800/1500)."""
        has_711 = bool(self._711_proxies)
        has_decodo = bool(self._decodo_proxies)

        if not has_711 and not has_decodo:
            return None

        if not has_decodo:
            return self._next_711()
        if not has_711:
            return self._next_decodo()

        self._call_counter += 1
        if self._call_counter % 23 < 8:
            return self._next_711()
        return self._next_decodo()

    def _next_711(self) -> str:
        proxy = self._711_proxies[self._711_index % len(self._711_proxies)]
        self._711_index += 1
        return proxy

    def _next_decodo(self) -> str:
        proxy = self._decodo_proxies[self._decodo_index % len(self._decodo_proxies)]
        self._decodo_index += 1
        return proxy

    async def health_check(
        self, test_url: str = "http://httpbin.org/ip", timeout: int = 10
    ) -> dict:
        from app.services.scraper.http_client import get_shared_session

        results = {}
        for label, get_proxy in [("711proxy", self._next_711 if self._711_proxies else None),
                                  ("decodo", self._next_decodo if self._decodo_proxies else None)]:
            if not get_proxy:
                results[label] = {"healthy": False, "error": "no proxies loaded"}
                continue

            latencies = []
            errors = []
            proxy_url = get_proxy()
            for _ in range(2):
                t0 = time.perf_counter()
                try:
                    session = get_shared_session()
                    resp = await asyncio.wait_for(
                        session.get(test_url, proxy=proxy_url, timeout=timeout),
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
            results[label] = {
                "healthy": healthy,
                "latency_ms": round(avg_lat, 1),
                "errors": errors or None,
            }
            logger.info(
                f"[ProxyPool] Health {label}: "
                f"{'OK' if healthy else 'FALHA'} lat={avg_lat:.0f}ms"
            )

        return {
            "mode": "dual_proxy",
            "providers": results,
            "711_proxies": len(self._711_proxies),
            "decodo_proxies": len(self._decodo_proxies),
            "711_host": self._711_host,
        }

    def get_next_proxy(self):
        return self.get_sticky_proxy() or self._gateway_url

    def get_status(self) -> dict:
        return {
            "loaded": self._loaded,
            "mode": "dual_proxy",
            "711_host": self._711_host,
            "711_proxies": len(self._711_proxies),
            "decodo_proxies": len(self._decodo_proxies),
            "total_proxies": len(self._711_proxies) + len(self._decodo_proxies),
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
