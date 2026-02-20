"""
Proxy Manager - Pool de proxies com rotação round-robin.

Estratégia:
- Pre-load de TODOS os proxies no startup (antes do primeiro request)
- Round-robin atômico (sem random, garante distribuição uniforme)
- Sem quarentena que mata o pool (nunca remove proxy da rotação)
- Tracking de falhas por proxy para métricas, mas sem bloqueio
- Todas requisições DEVEM passar pelo proxy (nunca IP local)
"""

import asyncio
import logging
import time
from typing import Optional, Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProxyStats:
    """Métricas de uso de um proxy (apenas tracking, sem bloqueio)."""
    proxy: str
    requests: int = 0
    successes: int = 0
    failures: int = 0
    last_used: float = 0
    consecutive_failures: int = 0


class ProxyPool:
    """
    Pool de proxies com rotação round-robin.

    - Pre-load obrigatório antes de usar
    - Round-robin garante distribuição uniforme entre 1000 IPs
    - NUNCA remove proxy da rotação (1000 IPs sempre disponíveis)
    - Tracking de métricas para observabilidade
    """

    def __init__(self):
        self._proxies: List[str] = []
        self._index: int = 0
        self._lock = asyncio.Lock()
        self._stats: Dict[str, ProxyStats] = {}
        self._loaded = False
        self._total_requests = 0
        self._successful_requests = 0

    async def preload(self) -> int:
        """
        Carrega todos os proxies do Webshare ANTES de iniciar o batch.
        Deve ser chamado no startup ou antes do primeiro request.
        Retorna quantidade de proxies carregados.
        """
        from app.core.proxy import proxy_manager
        await proxy_manager._refresh_proxies(force=True)
        self._proxies = list(proxy_manager.proxies)

        if not self._proxies:
            logger.error("[ProxyPool] ❌ ZERO proxies carregados do Webshare!")
            return 0

        for p in self._proxies:
            self._stats[p] = ProxyStats(proxy=p)

        self._loaded = True
        self._index = 0
        logger.info(f"[ProxyPool] ✅ {len(self._proxies)} proxies carregados (round-robin)")
        return len(self._proxies)

    def get_next_proxy(self) -> Optional[str]:
        """
        Retorna o próximo proxy via round-robin.
        Operação O(1), sem I/O, sem await, sem lock.
        NUNCA retorna None se proxies foram carregados.
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
        """
        Compatibilidade com código existente.
        Internamente usa round-robin (ignora max_attempts).
        Se pool não carregado, tenta carregar.
        """
        if not self._loaded or not self._proxies:
            loaded = await self.preload()
            if loaded == 0:
                logger.error(
                    "[ProxyPool] ❌ Proxy pool vazio! Verifique WEBSHARE_PROXY_LIST_URL"
                )
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
        """Registra falha (apenas métricas, NUNCA remove da rotação)."""
        if not proxy:
            return
        stats = self._stats.get(proxy)
        if stats:
            stats.failures += 1
            stats.consecutive_failures += 1

    def get_status(self) -> dict:
        """Retorna status do pool."""
        if not self._proxies:
            return {"loaded": False, "total": 0}

        total_failures = sum(s.failures for s in self._stats.values())
        tracked = self._successful_requests + total_failures
        return {
            "loaded": self._loaded,
            "total_proxies": len(self._proxies),
            "requests_dispatched": self._total_requests,
            "outcomes_tracked": tracked,
            "successful": self._successful_requests,
            "failed": total_failures,
            "success_rate": (
                f"{self._successful_requests / tracked:.1%}"
                if tracked > 0 else "N/A"
            ),
            "untracked": self._total_requests - tracked,
        }

    def reset_metrics(self):
        """Reseta métricas."""
        self._total_requests = 0
        self._successful_requests = 0
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
