"""
Proxy Manager - Gerenciamento centralizado de proxies para scraping.

Gerencia:
- Pool de proxies com rotação
- Sistema de quarentena para proxies problemáticos
- Teste de latência antes de uso
- Métricas de saúde dos proxies
"""

import asyncio
import logging
import time
import random
from urllib.parse import urlparse
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProxyHealth:
    """Status de saúde de um proxy."""
    proxy: str
    failures: int = 0
    successes: int = 0
    last_latency_ms: float = 0
    last_success_time: float = 0
    last_failure_time: float = 0
    quarantine_until: float = 0
    
    @property
    def is_quarantined(self) -> bool:
        return time.time() < self.quarantine_until
    
    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        if total == 0:
            return 1.0  # Novo proxy, assumir saudável
        return self.successes / total


class ProxyPool:
    """
    Pool de proxies com gerenciamento de saúde e quarentena.
    
    Features:
    - Rotação automática de proxies
    - Quarentena para proxies com falhas consecutivas
    - Teste de latência TCP antes de uso
    - Métricas de performance por proxy
    """
    
    def __init__(
        self,
        max_failures: int = 3,
        quarantine_seconds: int = 120,
        max_latency_ms: float = 300,
        latency_test_timeout: float = 5.0
    ):
        """
        Args:
            max_failures: Falhas consecutivas antes de quarentena
            quarantine_seconds: Duração da quarentena em segundos
            max_latency_ms: Latência máxima aceitável em ms
            latency_test_timeout: Timeout do teste de latência
        """
        self._max_failures = max_failures
        self._quarantine_seconds = quarantine_seconds
        self._max_latency_ms = max_latency_ms
        self._latency_test_timeout = latency_test_timeout
        
        self._health: Dict[str, ProxyHealth] = {}
        self._lock = asyncio.Lock()
        
        # Referência ao ProxyManager original para obter lista de proxies
        self._source_manager = None
        
        # Métricas globais
        self._total_requests = 0
        self._successful_requests = 0
        self._quarantined_count = 0
        
        logger.info(
            f"ProxyPool: max_failures={max_failures}, "
            f"quarantine={quarantine_seconds}s, max_latency={max_latency_ms}ms"
        )
    
    def set_source_manager(self, manager):
        """Define o gerenciador fonte de proxies."""
        self._source_manager = manager
    
    async def _test_latency(self, proxy_url: str) -> Tuple[float, bool]:
        """
        Testa conexão TCP básica ao host do proxy para medir latência.
        
        Returns:
            Tuple de (latência_ms, sucesso)
        """
        try:
            parsed = urlparse(
                proxy_url if "://" in proxy_url else f"http://{proxy_url}"
            )
            host = parsed.hostname
            port = parsed.port or 80
            
            start = time.perf_counter()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self._latency_test_timeout
            )
            writer.close()
            await writer.wait_closed()
            
            latency_ms = (time.perf_counter() - start) * 1000
            return latency_ms, True
            
        except Exception:
            return 0, False
    
    def _get_health(self, proxy: str) -> ProxyHealth:
        """Obtém ou cria registro de saúde para um proxy."""
        if proxy not in self._health:
            self._health[proxy] = ProxyHealth(proxy=proxy)
        return self._health[proxy]
    
    async def get_healthy_proxy(self, max_attempts: int = 3) -> Optional[str]:
        """
        Obtém um proxy saudável do pool.
        
        Critérios de seleção:
        1. Não estar em quarentena
        2. Latência dentro do limite aceitável
        
        Args:
            max_attempts: Máximo de tentativas
            
        Returns:
            URL do proxy ou None se não encontrar proxy saudável
        """
        if not self._source_manager:
            from app.core.proxy import proxy_manager
            self._source_manager = proxy_manager
        
        for attempt in range(max_attempts):
            # Obter proxy do pool fonte
            proxy = await self._source_manager.get_next_proxy()
            if not proxy:
                continue
            
            health = self._get_health(proxy)
            
            # Verificar quarentena
            if health.is_quarantined:
                logger.debug(f"[ProxyPool] Proxy {proxy[:30]}... em quarentena")
                continue
            
            # Testar latência
            latency, ok = await self._test_latency(proxy)
            
            if ok and latency <= self._max_latency_ms:
                health.last_latency_ms = latency
                self._total_requests += 1
                logger.debug(f"[ProxyPool] Proxy selecionado: {proxy[:30]}... ({latency:.0f}ms)")
                return proxy
            
            # Latência alta ou falha - registrar
            if not ok:
                self.record_failure(proxy, "latency_test_failed")
            elif latency > self._max_latency_ms:
                logger.debug(f"[ProxyPool] Proxy {proxy[:30]}... latência alta: {latency:.0f}ms")
        
        logger.warning(f"[ProxyPool] Nenhum proxy saudável após {max_attempts} tentativas")
        return None
    
    def record_success(self, proxy: str):
        """Registra sucesso de uso de um proxy."""
        if not proxy:
            return
            
        health = self._get_health(proxy)
        health.successes += 1
        health.failures = 0  # Reset de falhas consecutivas
        health.last_success_time = time.time()
        health.quarantine_until = 0  # Remove quarentena se existir
        
        self._successful_requests += 1
    
    def record_failure(self, proxy: str, reason: str = "unknown"):
        """
        Registra falha de uso de um proxy.
        
        Se atingir máximo de falhas, coloca em quarentena.
        """
        if not proxy:
            return
            
        health = self._get_health(proxy)
        health.failures += 1
        health.last_failure_time = time.time()
        
        if health.failures >= self._max_failures:
            health.quarantine_until = time.time() + self._quarantine_seconds
            self._quarantined_count += 1
            logger.debug(
                f"[ProxyPool] Proxy {proxy[:30]}... em quarentena "
                f"({health.failures} falhas, razão: {reason})"
            )
    
    def is_quarantined(self, proxy: str) -> bool:
        """Verifica se proxy está em quarentena."""
        if not proxy:
            return False
        health = self._get_health(proxy)
        return health.is_quarantined
    
    def update_config(
        self,
        max_failures: Optional[int] = None,
        quarantine_seconds: Optional[int] = None,
        max_latency_ms: Optional[float] = None
    ):
        """Atualiza configurações do pool."""
        if max_failures is not None:
            self._max_failures = max_failures
        if quarantine_seconds is not None:
            self._quarantine_seconds = quarantine_seconds
        if max_latency_ms is not None:
            self._max_latency_ms = max_latency_ms
            
        logger.info(
            f"ProxyPool: Configuração atualizada - "
            f"max_failures={self._max_failures}, "
            f"quarantine={self._quarantine_seconds}s, "
            f"max_latency={self._max_latency_ms}ms"
        )
    
    def get_status(self) -> dict:
        """Retorna status do pool de proxies."""
        healthy = sum(1 for h in self._health.values() if not h.is_quarantined)
        quarantined = sum(1 for h in self._health.values() if h.is_quarantined)
        
        success_rate = 0
        if self._total_requests > 0:
            success_rate = self._successful_requests / self._total_requests
        
        return {
            "total_tracked": len(self._health),
            "healthy_count": healthy,
            "quarantined_count": quarantined,
            "total_requests": self._total_requests,
            "successful_requests": self._successful_requests,
            "success_rate": f"{success_rate:.1%}",
            "config": {
                "max_failures": self._max_failures,
                "quarantine_seconds": self._quarantine_seconds,
                "max_latency_ms": self._max_latency_ms
            }
        }
    
    def get_proxy_health(self, proxy: str) -> Optional[dict]:
        """Retorna informações de saúde de um proxy específico."""
        if proxy not in self._health:
            return None
            
        health = self._health[proxy]
        return {
            "proxy": proxy[:30] + "...",
            "failures": health.failures,
            "successes": health.successes,
            "success_rate": f"{health.success_rate:.1%}",
            "last_latency_ms": health.last_latency_ms,
            "is_quarantined": health.is_quarantined,
            "quarantine_remaining": max(0, health.quarantine_until - time.time())
        }
    
    def clear_quarantine(self, proxy: Optional[str] = None):
        """Limpa quarentena de um proxy específico ou de todos."""
        if proxy:
            if proxy in self._health:
                self._health[proxy].quarantine_until = 0
                self._health[proxy].failures = 0
                logger.info(f"[ProxyPool] Quarentena removida: {proxy[:30]}...")
        else:
            for health in self._health.values():
                health.quarantine_until = 0
                health.failures = 0
            logger.info("[ProxyPool] Quarentena removida de todos os proxies")
    
    def reset_metrics(self):
        """Reseta métricas globais (não afeta quarentena)."""
        self._total_requests = 0
        self._successful_requests = 0
        self._quarantined_count = 0
        logger.info("[ProxyPool] Métricas resetadas")


# Instância singleton
proxy_pool = ProxyPool()


# Funções de conveniência para compatibilidade
async def get_healthy_proxy(max_attempts: int = 3) -> Optional[str]:
    """Obtém proxy saudável (para compatibilidade)."""
    return await proxy_pool.get_healthy_proxy(max_attempts)


def record_proxy_failure(proxy: str, reason: str = "unknown"):
    """Registra falha de proxy (para compatibilidade)."""
    proxy_pool.record_failure(proxy, reason)


def record_proxy_success(proxy: str):
    """Registra sucesso de proxy (para compatibilidade)."""
    proxy_pool.record_success(proxy)





