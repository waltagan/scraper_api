"""
Proxy Manager - Pool de proxies com rotação round-robin e health check.

Estratégia:
- Pre-load de TODOS os proxies no startup (antes do primeiro request)
- Health check pré-batch: testa todos e filtra mortos
- Round-robin atômico sobre proxies SAUDÁVEIS
- Tracking de falhas por proxy para métricas
- Todas requisições DEVEM passar pelo proxy (nunca IP local)
"""

import asyncio
import logging
import time
from typing import Optional, Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TEST_URL = "http://httpbin.org/ip"
HEALTH_CHECK_TIMEOUT = 8
HEALTH_CHECK_CONCURRENCY = 50


@dataclass
class ProxyStats:
    """Métricas de uso de um proxy (apenas tracking, sem bloqueio)."""
    proxy: str
    requests: int = 0
    successes: int = 0
    failures: int = 0
    last_used: float = 0
    consecutive_failures: int = 0


@dataclass
class HealthCheckResult:
    """Resultado do health check de um proxy."""
    proxy: str
    healthy: bool
    latency_ms: float = 0
    error: str = ""


class ProxyPool:
    """
    Pool de proxies com rotação round-robin + health check pré-batch.
    Após health_check(), apenas proxies saudáveis entram na rotação.
    """

    def __init__(self):
        self._all_proxies: List[str] = []
        self._proxies: List[str] = []
        self._index: int = 0
        self._lock = asyncio.Lock()
        self._stats: Dict[str, ProxyStats] = {}
        self._loaded = False
        self._health_checked = False
        self._health_results: List[HealthCheckResult] = []
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0

    async def preload(self) -> int:
        """
        Carrega todos os proxies do Webshare.
        Retorna quantidade de proxies carregados.
        """
        from app.core.proxy import proxy_manager
        await proxy_manager._refresh_proxies(force=True)
        self._all_proxies = list(proxy_manager.proxies)

        if not self._all_proxies:
            logger.error("[ProxyPool] ❌ ZERO proxies carregados do Webshare!")
            return 0

        self._proxies = list(self._all_proxies)
        for p in self._all_proxies:
            if p not in self._stats:
                self._stats[p] = ProxyStats(proxy=p)

        self._loaded = True
        self._index = 0
        logger.info(f"[ProxyPool] ✅ {len(self._all_proxies)} proxies carregados")
        return len(self._all_proxies)

    async def health_check(
        self,
        test_url: str = TEST_URL,
        timeout: int = HEALTH_CHECK_TIMEOUT,
        concurrency: int = HEALTH_CHECK_CONCURRENCY,
    ) -> dict:
        """
        Testa TODOS os proxies e filtra mortos da rotação.
        Retorna estatísticas detalhadas do health check.
        """
        if not self._all_proxies:
            await self.preload()
        if not self._all_proxies:
            return {"error": "no proxies loaded"}

        logger.info(
            f"[ProxyPool] 🏥 Health check: testando {len(self._all_proxies)} "
            f"proxies contra {test_url} (timeout={timeout}s, concurrency={concurrency})"
        )

        sem = asyncio.Semaphore(concurrency)
        results: List[HealthCheckResult] = []
        start = time.perf_counter()

        async def test_one(proxy: str) -> HealthCheckResult:
            async with sem:
                t0 = time.perf_counter()
                try:
                    from curl_cffi.requests import AsyncSession
                    async with AsyncSession(
                        impersonate="chrome120",
                        proxy=proxy,
                        timeout=timeout,
                        verify=False,
                    ) as session:
                        resp = await asyncio.wait_for(
                            session.get(test_url), timeout=timeout
                        )
                        latency = (time.perf_counter() - t0) * 1000
                        if resp.status_code == 200:
                            return HealthCheckResult(
                                proxy=proxy, healthy=True, latency_ms=latency
                            )
                        return HealthCheckResult(
                            proxy=proxy, healthy=False, latency_ms=latency,
                            error=f"status_{resp.status_code}",
                        )
                except Exception as e:
                    latency = (time.perf_counter() - t0) * 1000
                    err_name = type(e).__name__
                    return HealthCheckResult(
                        proxy=proxy, healthy=False, latency_ms=latency,
                        error=err_name,
                    )

        tasks = [test_one(p) for p in self._all_proxies]
        results = await asyncio.gather(*tasks)
        total_time = (time.perf_counter() - start) * 1000

        self._health_results = list(results)
        healthy = [r for r in results if r.healthy]
        dead = [r for r in results if not r.healthy]

        if healthy:
            self._proxies = [r.proxy for r in healthy]
        else:
            logger.error("[ProxyPool] ❌ ZERO proxies saudáveis! Mantendo pool original.")
            self._proxies = list(self._all_proxies)

        self._index = 0
        self._health_checked = True

        latencies = [r.latency_ms for r in healthy] if healthy else [0]
        latencies.sort()

        error_cats: Dict[str, int] = {}
        for r in dead:
            error_cats[r.error] = error_cats.get(r.error, 0) + 1

        stats = {
            "total_tested": len(results),
            "healthy": len(healthy),
            "dead": len(dead),
            "healthy_pct": round(len(healthy) / len(results) * 100, 1) if results else 0,
            "pool_active": len(self._proxies),
            "check_time_ms": round(total_time),
            "latency_ms": {
                "avg": round(sum(latencies) / len(latencies), 1),
                "min": round(latencies[0], 1),
                "max": round(latencies[-1], 1),
                "p50": round(latencies[len(latencies) // 2], 1),
                "p95": round(latencies[int(len(latencies) * 0.95)], 1) if len(latencies) > 1 else round(latencies[0], 1),
            },
            "error_breakdown": error_cats,
        }

        logger.info(
            f"[ProxyPool] 🏥 Health check concluído em {total_time:.0f}ms: "
            f"{len(healthy)}/{len(results)} saudáveis ({stats['healthy_pct']}%), "
            f"latência média={stats['latency_ms']['avg']:.0f}ms"
        )

        return stats

    def get_health_status(self) -> dict:
        """Retorna resultados do último health check."""
        if not self._health_checked:
            return {"health_checked": False}
        healthy = sum(1 for r in self._health_results if r.healthy)
        return {
            "health_checked": True,
            "total_tested": len(self._health_results),
            "healthy": healthy,
            "dead": len(self._health_results) - healthy,
            "pool_active": len(self._proxies),
        }

    def get_next_proxy(self) -> Optional[str]:
        """
        Retorna o próximo proxy via round-robin (apenas saudáveis pós-health-check).
        """
        if not self._proxies:
            return None

        idx = self._index % len(self._proxies)
        self._index += 1
        proxy = self._proxies[idx]

        self._total_requests += 1
        stats = self._stats.get(proxy)
        if stats:
            stats.requests += 1
            stats.last_used = time.time()

        return proxy

    async def get_healthy_proxy(self, max_attempts: int = 5) -> Optional[str]:
        """Compatibilidade com código existente."""
        if not self._loaded or not self._proxies:
            loaded = await self.preload()
            if loaded == 0:
                logger.error("[ProxyPool] ❌ Pool vazio!")
                return None
        return self.get_next_proxy()

    def record_success(self, proxy: str):
        """Registra sucesso (apenas métricas)."""
        if not proxy:
            return
        self._successful_requests += 1
        stats = self._stats.get(proxy)
        if stats:
            stats.successes += 1
            stats.consecutive_failures = 0

    def record_failure(self, proxy: str, reason: str = "unknown"):
        """Registra falha (apenas métricas)."""
        if not proxy:
            return
        self._failed_requests += 1
        stats = self._stats.get(proxy)
        if stats:
            stats.failures += 1
            stats.consecutive_failures += 1

    def get_status(self) -> dict:
        """Retorna status do pool."""
        if not self._proxies:
            return {"loaded": False, "total": 0}

        total_outcomes = self._successful_requests + self._failed_requests
        status = {
            "loaded": self._loaded,
            "total_proxies": len(self._all_proxies),
            "active_proxies": len(self._proxies),
            "health_checked": self._health_checked,
            "proxy_allocations": self._total_requests,
            "total_outcomes": total_outcomes,
            "successful": self._successful_requests,
            "failed": self._failed_requests,
            "success_rate": (
                f"{self._successful_requests / total_outcomes:.1%}"
                if total_outcomes > 0 else "N/A"
            ),
        }
        return status

    def reset_metrics(self):
        """Reseta métricas."""
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        for s in self._stats.values():
            s.requests = 0
            s.successes = 0
            s.failures = 0
            s.consecutive_failures = 0
        logger.info("[ProxyPool] Métricas resetadas")


proxy_pool = ProxyPool()


async def get_healthy_proxy(max_attempts: int = 5) -> Optional[str]:
    """Obtém proxy via round-robin (compatibilidade)."""
    return await proxy_pool.get_healthy_proxy(max_attempts)


def record_proxy_failure(proxy: str, reason: str = "unknown"):
    """Registra falha de proxy (compatibilidade)."""
    proxy_pool.record_failure(proxy, reason)


def record_proxy_success(proxy: str):
    """Registra sucesso de proxy (compatibilidade)."""
    proxy_pool.record_success(proxy)
