"""
Proxy Manager - Pool de proxies com rotação e health check.

Dois modos de operação:
1. LIST MODE (Webshare): Pre-load de todos os proxies, health check, round-robin/weighted.
2. GATEWAY MODE (711Proxy): Single endpoint com rotação automática pelo provider.
   - Não precisa de health check individual (1 gateway = N IPs rotativos)
   - Não precisa de weighted selection (provider faz o balanceamento)
   - Concorrência ilimitada no proxy (provider gerencia)
"""

import asyncio
import logging
import random
import time
from typing import Optional, Dict, List, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TEST_URL = "http://httpbin.org/ip"
HEALTH_CHECK_TIMEOUT = 8
HEALTH_CHECK_CONCURRENCY = 50

WARMUP_REQUESTS = 500
WEIGHT_UPDATE_INTERVAL = 200
MIN_OUTCOMES_FOR_WEIGHT = 5
DISCARD_THRESHOLD = 0.10


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
    Pool de proxies com dois modos:
    - List mode: round-robin/weighted + health check (Webshare datacenter)
    - Gateway mode: single rotating endpoint (711Proxy residential)
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
        self._weighted_proxies: List[str] = []
        self._weights: List[float] = []
        self._last_weight_update: int = 0
        self._discarded_proxies: Set[str] = set()
        self._gateway_mode = False
        self._gateway_url: str = ""

    async def preload(self) -> int:
        """Carrega proxies. Detecta automaticamente gateway vs list mode."""
        from app.core.proxy import proxy_manager

        if proxy_manager.is_gateway_mode:
            self._gateway_mode = True
            self._gateway_url = proxy_manager.gateway_url
            self._all_proxies = [self._gateway_url]
            self._proxies = [self._gateway_url]
            self._stats[self._gateway_url] = ProxyStats(proxy=self._gateway_url)
            self._loaded = True
            logger.info(
                f"[ProxyPool] 🌐 GATEWAY MODE ativo — "
                f"endpoint: {self._gateway_url[:50]}... "
                f"(rotação automática pelo provider, sem health check individual)"
            )
            return 1

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
        logger.info(f"[ProxyPool] ✅ {len(self._all_proxies)} proxies carregados (list mode)")
        return len(self._all_proxies)

    async def health_check(
        self,
        test_url: str = TEST_URL,
        timeout: int = HEALTH_CHECK_TIMEOUT,
        concurrency: int = HEALTH_CHECK_CONCURRENCY,
    ) -> dict:
        """Testa proxies e filtra mortos. Em gateway mode, faz teste rápido do endpoint."""
        if self._gateway_mode:
            return await self._gateway_health_check(test_url, timeout)

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
                    from app.services.scraper.constants import get_random_impersonate
                    async with AsyncSession(
                        impersonate=get_random_impersonate(),
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
                "p95": round(
                    latencies[int(len(latencies) * 0.95)], 1
                ) if len(latencies) > 1 else round(latencies[0], 1),
            },
            "error_breakdown": error_cats,
        }

        logger.info(
            f"[ProxyPool] 🏥 Health check concluído em {total_time:.0f}ms: "
            f"{len(healthy)}/{len(results)} saudáveis ({stats['healthy_pct']}%), "
            f"latência média={stats['latency_ms']['avg']:.0f}ms"
        )

        return stats

    async def _gateway_health_check(self, test_url: str, timeout: int) -> dict:
        """Health check simplificado para gateway mode — testa 3x para medir latência."""
        logger.info(f"[ProxyPool] 🌐 Gateway health check: testando {self._gateway_url[:50]}...")
        latencies = []
        errors = []
        start = time.perf_counter()

        for i in range(3):
            t0 = time.perf_counter()
            try:
                from curl_cffi.requests import AsyncSession
                from app.services.scraper.constants import get_random_impersonate
                async with AsyncSession(
                    impersonate=get_random_impersonate(),
                    proxy=self._gateway_url,
                    timeout=timeout,
                    verify=False,
                ) as session:
                    resp = await asyncio.wait_for(session.get(test_url), timeout=timeout)
                    lat = (time.perf_counter() - t0) * 1000
                    if resp.status_code == 200:
                        latencies.append(lat)
                    else:
                        errors.append(f"status_{resp.status_code}")
            except Exception as e:
                errors.append(type(e).__name__)

        total_time = (time.perf_counter() - start) * 1000
        healthy = len(latencies) > 0
        self._health_checked = True

        if healthy:
            self._health_results = [
                HealthCheckResult(
                    proxy=self._gateway_url, healthy=True,
                    latency_ms=sum(latencies) / len(latencies)
                )
            ]
        else:
            self._health_results = [
                HealthCheckResult(
                    proxy=self._gateway_url, healthy=False,
                    error=errors[0] if errors else "unknown"
                )
            ]

        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        stats = {
            "mode": "gateway",
            "gateway_url": self._gateway_url[:50] + "...",
            "tests_run": 3,
            "tests_ok": len(latencies),
            "tests_failed": len(errors),
            "healthy": healthy,
            "pool_active": 1 if healthy else 0,
            "check_time_ms": round(total_time),
            "latency_ms": {
                "avg": round(avg_lat, 1),
                "min": round(min(latencies), 1) if latencies else 0,
                "max": round(max(latencies), 1) if latencies else 0,
            },
            "errors": errors if errors else None,
        }

        status_emoji = "✅" if healthy else "❌"
        logger.info(
            f"[ProxyPool] 🌐 Gateway health check {status_emoji}: "
            f"{len(latencies)}/3 OK, latência média={avg_lat:.0f}ms"
        )
        return stats

    def get_health_status(self) -> dict:
        """Retorna resultados do último health check."""
        if not self._health_checked:
            return {"health_checked": False}
        if self._gateway_mode:
            return {
                "health_checked": True,
                "mode": "gateway",
                "gateway_healthy": any(r.healthy for r in self._health_results),
                "pool_active": 1,
            }
        healthy = sum(1 for r in self._health_results if r.healthy)
        return {
            "health_checked": True,
            "total_tested": len(self._health_results),
            "healthy": healthy,
            "dead": len(self._health_results) - healthy,
            "pool_active": len(self._proxies),
        }

    def get_next_proxy(self) -> Optional[str]:
        """Retorna proxy. Em gateway mode, sempre retorna o gateway URL."""
        if self._gateway_mode:
            self._total_requests += 1
            stats = self._stats.get(self._gateway_url)
            if stats:
                stats.requests += 1
                stats.last_used = time.time()
            return self._gateway_url
        proxy = self._select_proxy()
        if proxy:
            self._track_allocation(proxy)
        return proxy

    def get_proxy_excluding(self, exclude: Optional[Set[str]] = None) -> Optional[str]:
        """Retorna proxy evitando os do set.
        Em gateway mode, sempre retorna o gateway (auto-rotação)."""
        if self._gateway_mode:
            return self.get_next_proxy()
        if not exclude:
            return self.get_next_proxy()
        proxy = self._select_proxy(exclude=exclude)
        if proxy:
            self._track_allocation(proxy)
        return proxy

    def _track_allocation(self, proxy: str):
        self._total_requests += 1
        stats = self._stats.get(proxy)
        if stats:
            stats.requests += 1
            stats.last_used = time.time()

    def _select_proxy(self, exclude: Optional[Set[str]] = None) -> Optional[str]:
        if not self._proxies:
            return None
        total_outcomes = self._successful_requests + self._failed_requests
        if total_outcomes < WARMUP_REQUESTS:
            return self._round_robin_select(exclude)
        if total_outcomes - self._last_weight_update >= WEIGHT_UPDATE_INTERVAL:
            self._update_proxy_weights()
        if self._weighted_proxies and self._weights:
            return self._weighted_select(exclude)
        return self._round_robin_select(exclude)

    def _round_robin_select(self, exclude: Optional[Set[str]] = None) -> Optional[str]:
        if not self._proxies:
            return None
        for _ in range(len(self._proxies)):
            idx = self._index % len(self._proxies)
            self._index += 1
            proxy = self._proxies[idx]
            if not exclude or proxy not in exclude:
                return proxy
        idx = self._index % len(self._proxies)
        self._index += 1
        return self._proxies[idx]

    def _weighted_select(self, exclude: Optional[Set[str]] = None) -> Optional[str]:
        if not exclude:
            return random.choices(
                self._weighted_proxies, weights=self._weights, k=1
            )[0]
        candidates = [
            (p, w) for p, w in zip(self._weighted_proxies, self._weights)
            if p not in exclude
        ]
        if not candidates:
            return self._round_robin_select(exclude)
        proxies, weights = zip(*candidates)
        return random.choices(proxies, weights=weights, k=1)[0]

    def _update_proxy_weights(self):
        """Recalcula pesos: sqrt(success_rate). Desativado em gateway mode."""
        if self._gateway_mode:
            return

        active: List[str] = []
        weights: List[float] = []
        discarded: Set[str] = set()

        for proxy in self._proxies:
            stats = self._stats.get(proxy)
            if not stats:
                active.append(proxy)
                weights.append(1.0)
                continue
            outcomes = stats.successes + stats.failures
            if outcomes < MIN_OUTCOMES_FOR_WEIGHT:
                active.append(proxy)
                weights.append(1.0)
                continue
            rate = stats.successes / outcomes
            if rate < DISCARD_THRESHOLD:
                discarded.add(proxy)
                continue
            active.append(proxy)
            weights.append(max(0.1, rate ** 0.5))

        self._weighted_proxies = active
        self._weights = weights
        self._discarded_proxies = discarded
        self._last_weight_update = self._successful_requests + self._failed_requests

        if discarded:
            logger.info(
                f"[ProxyPool] ⚖️ Pesos atualizados: {len(active)} ativos, "
                f"{len(discarded)} descartados (<{DISCARD_THRESHOLD*100:.0f}% success)"
            )

    async def get_healthy_proxy(self, max_attempts: int = 5) -> Optional[str]:
        """Compatibilidade com código existente."""
        if self._gateway_mode:
            return self._gateway_url
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
        if not self._proxies and not self._gateway_mode:
            return {"loaded": False, "total": 0}

        total_outcomes = self._successful_requests + self._failed_requests
        status = {
            "loaded": self._loaded,
            "mode": "gateway" if self._gateway_mode else "list",
            "total_proxies": 1 if self._gateway_mode else len(self._all_proxies),
            "active_proxies": 1 if self._gateway_mode else len(self._proxies),
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
        if self._gateway_mode:
            status["gateway_url"] = self._gateway_url[:50] + "..."
            status["note"] = "Gateway mode: IPs rotativos automáticos pelo provider"
        else:
            status["weighted_proxies"] = len(self._weighted_proxies)
            status["discarded_proxies"] = len(self._discarded_proxies)
            status["smart_routing"] = total_outcomes >= WARMUP_REQUESTS
            status["per_proxy_analysis"] = self.get_per_proxy_analysis()
        return status

    def get_per_proxy_analysis(self, min_requests: int = 3) -> dict:
        """Analisa performance individual. Não aplicável em gateway mode."""
        if self._gateway_mode:
            total_outcomes = self._successful_requests + self._failed_requests
            rate = (
                self._successful_requests / total_outcomes * 100
            ) if total_outcomes > 0 else 0
            return {
                "mode": "gateway",
                "total_outcomes": total_outcomes,
                "success_rate_pct": round(rate, 1),
                "note": "Análise per-proxy não aplicável em gateway mode",
            }

        rates: List[float] = []
        used_count = 0
        unused_count = 0
        proxy_details: List[dict] = []

        for s in self._stats.values():
            outcomes = s.successes + s.failures
            if outcomes == 0:
                unused_count += 1
                continue
            used_count += 1
            rate = s.successes / outcomes * 100
            if outcomes >= min_requests:
                rates.append(rate)
                proxy_details.append({
                    "proxy_id": s.proxy[-12:],
                    "requests": s.requests,
                    "outcomes": outcomes,
                    "successes": s.successes,
                    "failures": s.failures,
                    "success_rate_pct": round(rate, 1),
                })

        if not rates:
            return {"proxies_analyzed": 0}

        rates.sort()
        n = len(rates)

        buckets = {
            "90_100_pct": sum(1 for r in rates if r >= 90),
            "70_90_pct": sum(1 for r in rates if 70 <= r < 90),
            "50_70_pct": sum(1 for r in rates if 50 <= r < 70),
            "30_50_pct": sum(1 for r in rates if 30 <= r < 50),
            "10_30_pct": sum(1 for r in rates if 10 <= r < 30),
            "0_10_pct": sum(1 for r in rates if r < 10),
        }

        avg_rate = sum(rates) / n
        variance = sum((r - avg_rate) ** 2 for r in rates) / n
        std_dev = variance ** 0.5

        proxy_details.sort(key=lambda x: x["success_rate_pct"])
        worst_5 = proxy_details[:5]
        best_5 = proxy_details[-5:][::-1]

        return {
            "proxies_analyzed": n,
            "proxies_used": used_count,
            "proxies_unused": unused_count,
            "success_rate_distribution": {
                "avg_pct": round(avg_rate, 1),
                "std_dev_pct": round(std_dev, 1),
                "min_pct": round(rates[0], 1),
                "max_pct": round(rates[-1], 1),
                "p10": round(rates[int(n * 0.10)], 1),
                "p25": round(rates[int(n * 0.25)], 1),
                "p50": round(rates[n // 2], 1),
                "p75": round(rates[int(n * 0.75)], 1),
                "p90": round(rates[int(n * 0.90)], 1),
            },
            "buckets": buckets,
            "verdict": self._verdict(std_dev, avg_rate),
            "worst_5": worst_5,
            "best_5": best_5,
        }

    @staticmethod
    def _verdict(std_dev: float, avg_rate: float) -> str:
        """Gera diagnóstico baseado na distribuição."""
        if std_dev < 10:
            return (
                f"UNIFORME — todos os proxies têm taxa similar (~{avg_rate:.0f}%). "
                f"O problema NÃO é proxy individual, é como os sites "
                f"respondem ao tipo de proxy (datacenter)."
            )
        elif std_dev < 25:
            return (
                f"MODERADA — variação moderada (std={std_dev:.0f}%). "
                f"Maioria dos proxies performa similar, alguns outliers."
            )
        else:
            return (
                f"DISPERSA — grande variação (std={std_dev:.0f}%). "
                f"Alguns proxies são muito piores que outros. "
                f"Filtrar proxies ruins pode ajudar."
            )

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
