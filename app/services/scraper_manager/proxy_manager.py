"""
Proxy Manager — Suporte a 3 modos: gateway, byport, combined.

- gateway: Endpoint rotativo 711Proxy (us.rotgb) — ideal para rotating IPs.
- byport:  Portas dedicadas com IPs sticky — alta concorrência por porta.
- combined: Usa ambos para máximo throughput.
"""

import asyncio
import itertools
import logging
import time
from typing import Optional, Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

VALID_MODES = ("gateway", "byport", "combined")


@dataclass
class ProxyStats:
    requests: int = 0
    successes: int = 0
    failures: int = 0


class ProxyPool:
    """
    Pool multi-modo com round-robin para byport.
    O mode é configurado por batch — padrão é gateway.
    """

    def __init__(self):
        self._gateway_url: str = ""
        self._byport_urls: List[str] = []
        self._mode: str = "gateway"
        self._loaded = False
        self._health_checked = False

        self._stats_gateway = ProxyStats()
        self._stats_byport = ProxyStats()
        self._byport_cycle = itertools.cycle([])
        self._combined_cycle = itertools.cycle([])

    @property
    def mode(self) -> str:
        return self._mode

    async def preload(self) -> int:
        from app.core.proxy import proxy_manager

        if proxy_manager.is_gateway_mode:
            self._gateway_url = proxy_manager.gateway_url

        if proxy_manager.byport_urls:
            self._byport_urls = list(proxy_manager.byport_urls)
            self._byport_cycle = itertools.cycle(self._byport_urls)

        self._loaded = True
        count = (1 if self._gateway_url else 0) + len(self._byport_urls)
        logger.info(
            f"[ProxyPool] Carregado: gateway={'sim' if self._gateway_url else 'nao'}, "
            f"byport={len(self._byport_urls)} portas, total={count}"
        )
        return count

    def set_mode(self, mode: str):
        if mode not in VALID_MODES:
            raise ValueError(f"Modo invalido: {mode}. Use: {VALID_MODES}")

        if mode == "byport" and not self._byport_urls:
            raise ValueError("Modo byport requer PROXY_BYPORT_URLS configurado")
        if mode == "gateway" and not self._gateway_url:
            raise ValueError("Modo gateway requer PROXY_GATEWAY_URL configurado")
        if mode == "combined" and (not self._gateway_url or not self._byport_urls):
            raise ValueError("Modo combined requer PROXY_GATEWAY_URL e PROXY_BYPORT_URLS")

        old = self._mode
        self._mode = mode

        self._byport_cycle = itertools.cycle(self._byport_urls) if self._byport_urls else itertools.cycle([])
        if mode == "combined":
            all_urls = [self._gateway_url] + self._byport_urls
            self._combined_cycle = itertools.cycle(all_urls)

        logger.info(f"[ProxyPool] Modo alterado: {old} -> {mode}")

    async def health_check(self, test_url: str = "http://httpbin.org/ip", timeout: int = 8) -> dict:
        results = {}

        if self._gateway_url and self._mode in ("gateway", "combined"):
            results["gateway"] = await self._check_endpoint(
                self._gateway_url, "gateway", test_url, timeout
            )

        if self._byport_urls and self._mode in ("byport", "combined"):
            bp_results = []
            for url in self._byport_urls[:5]:
                r = await self._check_endpoint(url, "byport", test_url, timeout, attempts=1)
                bp_results.append(r)
            ok = sum(1 for r in bp_results if r.get("healthy"))
            results["byport"] = {
                "mode": "byport",
                "ports_total": len(self._byport_urls),
                "ports_tested": len(bp_results),
                "ports_healthy": ok,
                "healthy": ok > 0,
            }

        self._health_checked = True
        overall = all(v.get("healthy", False) for v in results.values())
        results["mode"] = self._mode
        results["healthy"] = overall
        return results

    async def _check_endpoint(
        self, proxy_url: str, label: str, test_url: str, timeout: int, attempts: int = 3
    ) -> dict:
        latencies = []
        errors = []
        for _ in range(attempts):
            t0 = time.perf_counter()
            try:
                from curl_cffi.requests import AsyncSession
                from app.services.scraper.constants import get_random_impersonate
                async with AsyncSession(
                    impersonate=get_random_impersonate(),
                    proxy=proxy_url, timeout=timeout, verify=False,
                ) as session:
                    resp = await asyncio.wait_for(session.get(test_url), timeout=timeout)
                    lat = (time.perf_counter() - t0) * 1000
                    if resp.status_code == 200:
                        latencies.append(lat)
                    else:
                        errors.append(f"status_{resp.status_code}")
            except Exception as e:
                errors.append(type(e).__name__)
        healthy = len(latencies) > 0
        avg = sum(latencies) / len(latencies) if latencies else 0
        logger.info(f"[ProxyPool] Health {label}: {'OK' if healthy else 'FALHA'} ({len(latencies)}/{attempts}, {avg:.0f}ms)")
        return {
            "mode": label,
            "healthy": healthy,
            "tests_ok": len(latencies),
            "tests_failed": len(errors),
            "latency_ms": {"avg": round(avg, 1)} if latencies else {},
        }

    def get_next_proxy(self) -> Optional[str]:
        if self._mode == "gateway":
            self._stats_gateway.requests += 1
            return self._gateway_url
        elif self._mode == "byport":
            self._stats_byport.requests += 1
            return next(self._byport_cycle, None)
        else:
            url = next(self._combined_cycle, None)
            if url == self._gateway_url:
                self._stats_gateway.requests += 1
            else:
                self._stats_byport.requests += 1
            return url

    def get_proxy_excluding(self, exclude=None) -> Optional[str]:
        return self.get_next_proxy()

    def record_success(self, proxy: str = ""):
        if proxy == self._gateway_url:
            self._stats_gateway.successes += 1
        else:
            self._stats_byport.successes += 1

    def record_failure(self, proxy: str = "", reason: str = ""):
        if proxy == self._gateway_url:
            self._stats_gateway.failures += 1
        else:
            self._stats_byport.failures += 1

    def get_status(self) -> dict:
        def _rate(s: ProxyStats) -> str:
            t = s.successes + s.failures
            return f"{s.successes / t:.1%}" if t > 0 else "N/A"

        return {
            "loaded": self._loaded,
            "mode": self._mode,
            "health_checked": self._health_checked,
            "gateway": {
                "url": self._gateway_url[:50] + "..." if self._gateway_url else "",
                "available": bool(self._gateway_url),
                "requests": self._stats_gateway.requests,
                "successes": self._stats_gateway.successes,
                "failures": self._stats_gateway.failures,
                "success_rate": _rate(self._stats_gateway),
            },
            "byport": {
                "ports": len(self._byport_urls),
                "available": bool(self._byport_urls),
                "requests": self._stats_byport.requests,
                "successes": self._stats_byport.successes,
                "failures": self._stats_byport.failures,
                "success_rate": _rate(self._stats_byport),
            },
        }

    def reset_metrics(self):
        self._stats_gateway = ProxyStats()
        self._stats_byport = ProxyStats()


proxy_pool = ProxyPool()


async def get_healthy_proxy(max_attempts: int = 5) -> Optional[str]:
    if not proxy_pool._loaded:
        await proxy_pool.preload()
    return proxy_pool.get_next_proxy()


def record_proxy_failure(proxy: str, reason: str = "unknown"):
    proxy_pool.record_failure(proxy, reason)


def record_proxy_success(proxy: str):
    proxy_pool.record_success(proxy)
