"""
Scraper Manager - Controle de Infraestrutura de Scraping.

Este módulo centraliza todo o controle de infraestrutura do scraper:
- Concorrência por domínio
- Pool de proxies com quarentena
- Circuit breaker centralizado
- Rate limiting por domínio

A lógica de negócio de scraping permanece em app/services/scraper/
"""

from .concurrency_manager import (
    ConcurrencyManager,
    concurrency_manager,
    get_domain_semaphore,
    acquire_domain_slot,
    release_domain_slot,
)
from .proxy_manager import (
    ProxyPool,
    proxy_pool,
    get_healthy_proxy,
    record_proxy_failure,
    record_proxy_success,
)
from .circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    circuit_breaker,
    is_circuit_open,
    record_failure,
    record_success,
    get_failure_count,
    reset_circuit,
)
from .rate_limiter import (
    DomainRateLimiter,
    domain_rate_limiter,
)

__all__ = [
    # Concurrency
    "ConcurrencyManager",
    "concurrency_manager",
    "get_domain_semaphore",
    "acquire_domain_slot",
    "release_domain_slot",
    # Proxy
    "ProxyPool",
    "proxy_pool",
    "get_healthy_proxy",
    "record_proxy_failure", 
    "record_proxy_success",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitState",
    "circuit_breaker",
    "is_circuit_open",
    "record_failure",
    "record_success",
    "get_failure_count",
    "reset_circuit",
    # Rate Limiter
    "DomainRateLimiter",
    "domain_rate_limiter",
]





