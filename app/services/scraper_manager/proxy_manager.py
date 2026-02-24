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
from typing import List, Optional, Tuple
from app.configs.config_loader import load_config

logger = logging.getLogger(__name__)

_GATEWAY_URL = os.getenv("PROXY_GATEWAY_URL", "")
_STICKY_API_URL = (
    "http://us.rotgbapi.711proxy.com:8089/gen"
    "?zone=custom&ptype=1&region=BR&count=900"
    "&proto=http&stype=json&sessType=sticky&sessTime=30&sessAuto=1"
)
_DECODO_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data_decodo_ips.csv")
_cfg = load_config("scraper/scraper_config.json") or {}
_EVOMI_FILE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        _cfg.get("evomi_proxy_file", "proxies_evomi.txt"),
    )
)
def _parse_evomi_line(line: str) -> Optional[str]:
    """
    Converte formatos Evomi para proxy URL padrão.
    Aceita:
      - http://user:pass@host:port (já pronto)
      - http://host:port:user:pass
    """
    raw = (line or "").strip()
    if not raw or raw.startswith("#"):
        return None
    if "@" in raw and raw.startswith(("http://", "https://")):
        return raw
    try:
        scheme = "http"
        rest = raw
        if "://" in raw:
            scheme, rest = raw.split("://", 1)
        parts = rest.split(":")
        if len(parts) < 4:
            return None
        host = parts[0]
        port = parts[1]
        user = parts[2]
        password = ":".join(parts[3:])
        return f"{scheme}://{user}:{password}@{host}:{port}"
    except Exception:
        return None


class ProxyPool:
    """Pool multi-provider: 711Proxy + Decodo + Evomi com round-robin ponderado."""

    def __init__(self):
        self._gateway_url: str = _GATEWAY_URL
        self._loaded = False

        self._711_proxies: List[str] = []
        self._711_index: int = 0
        self._711_host: str = ""

        self._decodo_proxies: List[str] = []
        self._decodo_index: int = 0

        self._evomi_proxies: List[str] = []
        self._evomi_index: int = 0
        self._evomi_meta: dict = {
            "file_path": _EVOMI_FILE,
            "file_exists": False,
            "loaded_count": 0,
            "invalid_lines": 0,
            "reason": "not_loaded",
        }

        self._weighted_cycle: List[str] = []
        self._weighted_index: int = 0

    async def preload(self) -> int:
        self._gateway_url = os.getenv("PROXY_GATEWAY_URL", "")

        await self._fetch_711_sessions()
        self._load_decodo_proxies()
        self._load_evomi_proxies()
        self._build_weighted_cycle()

        total = len(self._711_proxies) + len(self._decodo_proxies) + len(self._evomi_proxies)
        self._loaded = total > 0

        logger.info(
            f"[ProxyPool] 711Proxy: {len(self._711_proxies)} proxies (host={self._711_host}) | "
            f"Decodo: {len(self._decodo_proxies)} proxies | "
            f"Evomi: {len(self._evomi_proxies)} proxies | Total: {total}"
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

    def _load_evomi_proxies(self):
        """Carrega proxy URLs do arquivo Evomi."""
        self._evomi_meta = {
            "file_path": _EVOMI_FILE,
            "file_exists": os.path.exists(_EVOMI_FILE),
            "loaded_count": 0,
            "invalid_lines": 0,
            "reason": "not_loaded",
        }
        if not self._evomi_meta["file_exists"]:
            self._evomi_meta["reason"] = "file_not_found"
            logger.warning(f"[ProxyPool] arquivo Evomi não encontrado: {_EVOMI_FILE}")
            return
        proxies: List[str] = []
        invalid = 0
        with open(_EVOMI_FILE, encoding="utf-8") as f:
            for line in f:
                parsed = _parse_evomi_line(line)
                if parsed:
                    proxies.append(parsed)
                elif (line or "").strip() and not (line or "").strip().startswith("#"):
                    invalid += 1
        self._evomi_proxies = proxies
        self._evomi_meta["loaded_count"] = len(proxies)
        self._evomi_meta["invalid_lines"] = invalid
        self._evomi_meta["reason"] = "loaded" if proxies else "empty_or_invalid_file"
        if self._evomi_proxies:
            logger.info(f"[ProxyPool] Evomi OK: {len(self._evomi_proxies)} proxies")
        else:
            logger.warning(
                f"[ProxyPool] Evomi sem proxies válidos: "
                f"path={_EVOMI_FILE} invalid_lines={invalid}"
            )

    def _build_weighted_cycle(self):
        cycle: List[str] = []
        if self._711_proxies:
            cycle.append("711proxy")
        if self._decodo_proxies:
            cycle.append("decodo")
        if self._evomi_proxies:
            cycle.append("evomi")
        self._weighted_cycle = cycle
        self._weighted_index = 0
        if cycle:
            logger.info(f"[ProxyPool] provider cycle (round_robin fixo): {cycle}")

    def get_sticky_proxy_with_provider(self) -> Optional[Tuple[str, str]]:
        """Retorna (proxy_url, provider) usando round-robin ponderado por provider."""
        if not self._weighted_cycle:
            return None
        for _ in range(len(self._weighted_cycle)):
            provider = self._weighted_cycle[self._weighted_index % len(self._weighted_cycle)]
            self._weighted_index += 1
            if provider == "711proxy" and self._711_proxies:
                return self._next_711(), "711proxy"
            if provider == "decodo" and self._decodo_proxies:
                return self._next_decodo(), "decodo"
            if provider == "evomi" and self._evomi_proxies:
                return self._next_evomi(), "evomi"
        return None

    def get_sticky_proxy(self) -> Optional[str]:
        picked = self.get_sticky_proxy_with_provider()
        if not picked:
            return None
        return picked[0]

    def get_available_providers(self) -> List[str]:
        providers: List[str] = []
        if self._711_proxies:
            providers.append("711proxy")
        if self._decodo_proxies:
            providers.append("decodo")
        if self._evomi_proxies:
            providers.append("evomi")
        return providers

    def get_sticky_proxy_for_provider(self, provider: str) -> Optional[str]:
        p = (provider or "").lower().strip()
        if p == "711proxy" and self._711_proxies:
            return self._next_711()
        if p == "decodo" and self._decodo_proxies:
            return self._next_decodo()
        if p == "evomi" and self._evomi_proxies:
            return self._next_evomi()
        return None

    def _next_711(self) -> str:
        proxy = self._711_proxies[self._711_index % len(self._711_proxies)]
        self._711_index += 1
        return proxy

    def _next_decodo(self) -> str:
        proxy = self._decodo_proxies[self._decodo_index % len(self._decodo_proxies)]
        self._decodo_index += 1
        return proxy

    def _next_evomi(self) -> str:
        proxy = self._evomi_proxies[self._evomi_index % len(self._evomi_proxies)]
        self._evomi_index += 1
        return proxy

    async def health_check(
        self, test_url: str = "http://httpbin.org/ip", timeout: int = 10
    ) -> dict:
        from app.services.scraper.http_client import get_shared_session

        results = {}
        for label, get_proxy in [
            ("711proxy", self._next_711 if self._711_proxies else None),
            ("decodo", self._next_decodo if self._decodo_proxies else None),
            ("evomi", self._next_evomi if self._evomi_proxies else None),
        ]:
            if not get_proxy:
                err = "no proxies loaded"
                if label == "evomi":
                    err = f"no proxies loaded ({self._evomi_meta.get('reason')})"
                results[label] = {"healthy": False, "error": err}
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
            "mode": "multi_proxy",
            "providers": results,
            "711_proxies": len(self._711_proxies),
            "decodo_proxies": len(self._decodo_proxies),
            "evomi_proxies": len(self._evomi_proxies),
            "711_host": self._711_host,
        }

    def get_next_proxy(self):
        return self.get_sticky_proxy() or self._gateway_url

    def get_status(self) -> dict:
        return {
            "loaded": self._loaded,
            "mode": "multi_proxy",
            "711_host": self._711_host,
            "711_proxies": len(self._711_proxies),
            "decodo_proxies": len(self._decodo_proxies),
            "evomi_proxies": len(self._evomi_proxies),
            "provider_strategy": "round_robin_fixo_pool",
            "evomi_source": self._evomi_meta,
            "total_proxies": len(self._711_proxies) + len(self._decodo_proxies) + len(self._evomi_proxies),
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
