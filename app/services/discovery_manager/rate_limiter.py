"""
Rate Limiter para Discovery - Controle de taxa de requisições.

Implementa Token Bucket para controlar requisições por segundo,
diferente de semáforo que controla concorrência.

O Serper API tem limite de 200 req/s, não 200 concurrent.
Este rate limiter permite todas as requisições passarem respeitando
o limite de taxa, sem bloquear por tempo de resposta.
"""

import asyncio
import logging
import time
from typing import Optional
from dataclasses import dataclass

from app.services.concurrency_manager.config_loader import (
    get_section as get_concurrency_section,
)

logger = logging.getLogger(__name__)


@dataclass
class RateLimiterMetrics:
    """Métricas do rate limiter."""
    total_acquired: int = 0
    total_waited: int = 0
    total_timeouts: int = 0
    total_wait_time_ms: float = 0
    
    @property
    def avg_wait_time_ms(self) -> float:
        if self.total_waited == 0:
            return 0
        return self.total_wait_time_ms / self.total_waited


class TokenBucketRateLimiter:
    """
    Rate Limiter baseado em Token Bucket.
    
    Permite controlar a TAXA de requisições (req/s), não a CONCORRÊNCIA.
    
    Diferença importante:
    - Semáforo: Limita quantas requisições ESTÃO em andamento simultaneamente
    - Token Bucket: Limita quantas requisições PODEM SER INICIADAS por segundo
    
    Para o Serper com limite de 200 req/s:
    - Com semáforo de 200: Se cada req demora 2s, throughput = 100 req/s ❌
    - Com Token Bucket de 200/s: Throughput = 200 req/s ✅
    
    Features:
    - Burst inicial configurável
    - Reabastecimento contínuo baseado em tempo
    - Métricas de uso
    - Thread-safe para uso assíncrono
    """
    
    def __init__(
        self,
        rate_per_second: float = 200.0,
        max_burst: int = 200,
        name: str = "serper"
    ):
        """
        Args:
            rate_per_second: Taxa máxima de requisições por segundo
            max_burst: Máximo de tokens acumulados (capacidade de burst)
            name: Nome para identificação em logs
        """
        self.rate_per_second = rate_per_second
        self.max_burst = max_burst
        self.name = name
        
        # Estado do bucket
        self._tokens = float(max_burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        
        # Métricas
        self._metrics = RateLimiterMetrics()
        
        logger.info(
            f"🚦 TokenBucketRateLimiter[{name}]: "
            f"rate={rate_per_second}/s, burst={max_burst}"
        )
    
    def _refill(self) -> None:
        """
        Reabastece tokens baseado no tempo decorrido.
        
        Chamado internamente antes de cada acquire.
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        
        # Calcular tokens a adicionar
        tokens_to_add = elapsed * self.rate_per_second
        
        # Atualizar tokens (limitado ao max_burst)
        self._tokens = min(self.max_burst, self._tokens + tokens_to_add)
        self._last_refill = now
    
    async def acquire(self, timeout: float = 30.0) -> bool:
        """
        Adquire permissão para fazer uma requisição.
        
        Espera até ter um token disponível ou timeout.
        
        Args:
            timeout: Tempo máximo de espera em segundos
            
        Returns:
            True se adquiriu permissão, False se timeout
        """
        start_time = time.monotonic()
        deadline = start_time + timeout
        waited = False
        
        while True:
            async with self._lock:
                self._refill()
                
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    
                    # Registrar métricas
                    self._metrics.total_acquired += 1
                    if waited:
                        wait_time_ms = (time.monotonic() - start_time) * 1000
                        self._metrics.total_waited += 1
                        self._metrics.total_wait_time_ms += wait_time_ms
                    
                    return True
            
            # Verificar timeout
            now = time.monotonic()
            if now >= deadline:
                self._metrics.total_timeouts += 1
                logger.warning(
                    f"⏰ TokenBucket[{self.name}]: Timeout após {timeout:.1f}s "
                    f"(tokens={self._tokens:.2f})"
                )
                return False
            
            # Calcular tempo de espera
            waited = True
            tokens_needed = 1.0 - self._tokens
            wait_time = tokens_needed / self.rate_per_second
            
            # Limitar espera para não bloquear muito
            actual_wait = min(wait_time, deadline - now, 0.01)  # Max 10ms por iteração
            
            await asyncio.sleep(actual_wait)
    
    def try_acquire(self) -> bool:
        """
        Tenta adquirir permissão sem esperar.
        
        Returns:
            True se adquiriu imediatamente, False se não há tokens
        """
        self._refill()
        
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            self._metrics.total_acquired += 1
            return True
        
        return False
    
    @property
    def available_tokens(self) -> float:
        """Retorna quantidade de tokens disponíveis."""
        self._refill()
        return self._tokens
    
    @property
    def utilization(self) -> float:
        """
        Taxa de utilização (0.0 a 1.0).
        
        1.0 significa que o bucket está vazio (alta utilização).
        """
        return 1.0 - (self._tokens / self.max_burst)
    
    def get_status(self) -> dict:
        """Retorna status e métricas do rate limiter."""
        return {
            "name": self.name,
            "tokens_available": round(self.available_tokens, 2),
            "max_burst": self.max_burst,
            "rate_per_second": self.rate_per_second,
            "utilization": f"{self.utilization:.1%}",
            "metrics": {
                "total_acquired": self._metrics.total_acquired,
                "total_waited": self._metrics.total_waited,
                "total_timeouts": self._metrics.total_timeouts,
                "avg_wait_time_ms": round(self._metrics.avg_wait_time_ms, 2)
            }
        }
    
    def reset_metrics(self):
        """Reseta métricas."""
        self._metrics = RateLimiterMetrics()
        logger.info(f"TokenBucket[{self.name}]: Métricas resetadas")
    
    def update_config(
        self,
        rate_per_second: Optional[float] = None,
        max_burst: Optional[int] = None
    ):
        """
        Atualiza configurações do rate limiter.
        
        Args:
            rate_per_second: Nova taxa por segundo
            max_burst: Novo limite de burst
        """
        if rate_per_second is not None:
            self.rate_per_second = rate_per_second
        
        if max_burst is not None:
            self.max_burst = max_burst
            # Ajustar tokens atuais se exceder novo limite
            self._tokens = min(self._tokens, max_burst)
        
        logger.info(
            f"TokenBucket[{self.name}]: Configuração atualizada - "
            f"rate={self.rate_per_second}/s, burst={self.max_burst}"
        )


_SERPER_CFG = get_concurrency_section("discovery/serper", {})

# Instância singleton para uso no SerperManager
serper_rate_limiter = TokenBucketRateLimiter(
    rate_per_second=_SERPER_CFG.get("rate_per_second", 190.0),  # margem de segurança
    max_burst=_SERPER_CFG.get("max_burst", 200),
    name="serper"
)

