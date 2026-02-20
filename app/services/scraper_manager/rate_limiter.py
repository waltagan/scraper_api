"""
Rate Limiter por Domínio - Controle de taxa de requisições por domínio.

Implementa rate limiting por domínio para evitar sobrecarregar
sites específicos durante o scraping.
"""

import asyncio
import logging
import time
from urllib.parse import urlparse
from typing import Dict, Optional
from dataclasses import dataclass

from app.services.concurrency_manager.config_loader import (
    get_section as get_concurrency_section,
)

logger = logging.getLogger(__name__)


@dataclass
class DomainBucket:
    """Token bucket para um domínio específico."""
    domain: str
    tokens: float
    max_tokens: int
    refill_rate: float  # tokens por segundo
    last_refill: float
    
    def refill(self):
        """Reabastece tokens baseado no tempo passado."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)
        self.last_refill = now


class DomainRateLimiter:
    """
    Rate limiter por domínio usando algoritmo Token Bucket.
    
    Cada domínio tem seu próprio bucket de tokens que controla
    a taxa máxima de requisições por minuto.
    
    Features:
    - Taxa configurável por minuto
    - Burst capacity (picos permitidos)
    - Detecção automática de domínios problemáticos
    - Métricas de utilização
    """
    
    def __init__(
        self,
        requests_per_minute: Optional[int] = None,
        burst_size: Optional[int] = None,
        slow_domain_rpm: Optional[int] = None
    ):
        """
        Args:
            requests_per_minute: Taxa padrão de requisições por minuto por domínio
            burst_size: Máximo de requisições em burst
            slow_domain_rpm: Taxa para domínios marcados como lentos
        """
        cfg = get_concurrency_section("scraper/scraper_domain", {})
        self._default_rpm = requests_per_minute if requests_per_minute is not None else cfg.get("requests_per_minute", 60)
        self._burst_size = burst_size if burst_size is not None else cfg.get("burst_size", 10)
        self._slow_domain_rpm = slow_domain_rpm if slow_domain_rpm is not None else cfg.get("slow_domain_rpm", 20)
        
        self._buckets: Dict[str, DomainBucket] = {}
        self._slow_domains: set = set()
        self._domain_locks: Dict[str, asyncio.Lock] = {}
        
        # Métricas
        self._total_requests = 0
        self._throttled_requests = 0
        
        logger.info(
            f"DomainRateLimiter: rpm={self._default_rpm}, "
            f"burst={self._burst_size}, slow_rpm={self._slow_domain_rpm}"
        )
    
    def _extract_domain(self, url: str) -> str:
        """Extrai domínio de uma URL."""
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return "unknown"
    
    def _get_bucket(self, domain: str) -> DomainBucket:
        """Obtém ou cria bucket para um domínio."""
        if domain not in self._buckets:
            rpm = (
                self._slow_domain_rpm 
                if domain in self._slow_domains 
                else self._default_rpm
            )
            refill_rate = rpm / 60.0  # tokens por segundo
            
            self._buckets[domain] = DomainBucket(
                domain=domain,
                tokens=float(self._burst_size),
                max_tokens=self._burst_size,
                refill_rate=refill_rate,
                last_refill=time.monotonic()
            )
        return self._buckets[domain]
    
    def _get_domain_lock(self, domain: str) -> asyncio.Lock:
        """Retorna ou cria lock para um domínio."""
        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()
        return self._domain_locks[domain]

    async def acquire(self, url: str, timeout: float = 30.0) -> bool:
        """
        Adquire permissão para fazer requisição a um domínio.
        Usa lock per-domain para evitar contention global com muitos workers.
        """
        domain = self._extract_domain(url)
        domain_lock = self._get_domain_lock(domain)
        start_time = time.monotonic()
        
        while True:
            async with domain_lock:
                bucket = self._get_bucket(domain)
                bucket.refill()
                
                if bucket.tokens >= 1:
                    bucket.tokens -= 1
                    self._total_requests += 1
                    return True
            
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                self._throttled_requests += 1
                logger.warning(
                    f"[RateLimiter] Timeout para {domain} após {elapsed:.1f}s"
                )
                return False
            
            wait_time = self._get_wait_time(bucket)
            remaining_timeout = timeout - elapsed
            actual_wait = min(wait_time, remaining_timeout, 0.5)
            
            await asyncio.sleep(actual_wait)
    
    def try_acquire(self, url: str) -> bool:
        """
        Tenta adquirir permissão sem esperar.
        
        Returns:
            True se adquiriu, False se não há token disponível
        """
        domain = self._extract_domain(url)
        bucket = self._get_bucket(domain)
        bucket.refill()
        
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            self._total_requests += 1
            return True
        
        return False
    
    def _get_wait_time(self, bucket: DomainBucket) -> float:
        """Calcula tempo estimado até próximo token disponível."""
        if bucket.tokens >= 1:
            return 0.0
        tokens_needed = 1 - bucket.tokens
        return tokens_needed / bucket.refill_rate
    
    def get_wait_time(self, url: str) -> float:
        """Retorna tempo de espera estimado para um domínio."""
        domain = self._extract_domain(url)
        bucket = self._get_bucket(domain)
        bucket.refill()
        return self._get_wait_time(bucket)
    
    def mark_domain_slow(self, url: str):
        """Marca um domínio como lento (reduz taxa)."""
        domain = self._extract_domain(url)
        if domain not in self._slow_domains:
            self._slow_domains.add(domain)
            # Recriar bucket com taxa menor
            refill_rate = self._slow_domain_rpm / 60.0
            if domain in self._buckets:
                self._buckets[domain].refill_rate = refill_rate
            logger.info(f"🐢 Domínio marcado como lento (rate limit): {domain}")
    
    def unmark_domain_slow(self, url: str):
        """Remove marcação de domínio lento."""
        domain = self._extract_domain(url)
        if domain in self._slow_domains:
            self._slow_domains.discard(domain)
            refill_rate = self._default_rpm / 60.0
            if domain in self._buckets:
                self._buckets[domain].refill_rate = refill_rate
            logger.info(f"🚀 Domínio restaurado para taxa normal: {domain}")
    
    def update_config(
        self,
        requests_per_minute: Optional[int] = None,
        burst_size: Optional[int] = None,
        slow_domain_rpm: Optional[int] = None
    ):
        """Atualiza configurações do rate limiter."""
        if requests_per_minute is not None:
            self._default_rpm = requests_per_minute
            # Atualizar buckets existentes (não-lentos)
            for domain, bucket in self._buckets.items():
                if domain not in self._slow_domains:
                    bucket.refill_rate = requests_per_minute / 60.0
        
        if burst_size is not None:
            self._burst_size = burst_size
            # Atualizar max_tokens dos buckets
            for bucket in self._buckets.values():
                bucket.max_tokens = burst_size
        
        if slow_domain_rpm is not None:
            self._slow_domain_rpm = slow_domain_rpm
            # Atualizar buckets de domínios lentos
            for domain in self._slow_domains:
                if domain in self._buckets:
                    self._buckets[domain].refill_rate = slow_domain_rpm / 60.0
        
        logger.info(
            f"DomainRateLimiter: Configuração atualizada - "
            f"rpm={self._default_rpm}, burst={self._burst_size}"
        )
    
    def get_status(self) -> dict:
        """Retorna status geral do rate limiter."""
        throttle_rate = 0
        if self._total_requests > 0:
            throttle_rate = self._throttled_requests / self._total_requests
        
        return {
            "domains_tracked": len(self._buckets),
            "slow_domains_count": len(self._slow_domains),
            "total_requests": self._total_requests,
            "throttled_requests": self._throttled_requests,
            "throttle_rate": f"{throttle_rate:.1%}",
            "config": {
                "default_rpm": self._default_rpm,
                "burst_size": self._burst_size,
                "slow_domain_rpm": self._slow_domain_rpm
            }
        }
    
    def get_domain_status(self, url: str) -> dict:
        """Retorna status de um domínio específico."""
        domain = self._extract_domain(url)
        bucket = self._get_bucket(domain)
        bucket.refill()
        
        return {
            "domain": domain,
            "is_slow": domain in self._slow_domains,
            "available_tokens": round(bucket.tokens, 2),
            "max_tokens": bucket.max_tokens,
            "refill_rate_per_min": round(bucket.refill_rate * 60, 1),
            "wait_time": f"{self._get_wait_time(bucket):.2f}s"
        }
    
    def reset(self, url: Optional[str] = None):
        """Reseta rate limiter."""
        if url:
            domain = self._extract_domain(url)
            if domain in self._buckets:
                del self._buckets[domain]
            logger.info(f"[RateLimiter] Reset para {domain}")
        else:
            self._buckets.clear()
            self._slow_domains.clear()
            logger.info("[RateLimiter] Reset completo")
    
    def reset_metrics(self):
        """Reseta apenas métricas."""
        self._total_requests = 0
        self._throttled_requests = 0
        logger.info("[RateLimiter] Métricas resetadas")


# Instância singleton
domain_rate_limiter = DomainRateLimiter()



