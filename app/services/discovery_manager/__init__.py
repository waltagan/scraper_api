"""
Discovery Manager - Controle de APIs externas de busca.

Este módulo centraliza todo o controle de infraestrutura para discovery:
- Gerenciamento da API Serper (rate limiting por token bucket)
- Cache de buscas recentes
- Rate limiting (200 req/s para Serper)

A lógica de negócio de discovery permanece em app/services/discovery/
"""

from .serper_manager import (
    SerperManager,
    serper_manager,
    search_serper,
)
from .search_cache import (
    SearchCache,
    search_cache,
)
from .rate_limiter import (
    TokenBucketRateLimiter,
    serper_rate_limiter,
)

__all__ = [
    # Serper
    "SerperManager",
    "serper_manager",
    "search_serper",
    # Cache
    "SearchCache",
    "search_cache",
    # Rate Limiter
    "TokenBucketRateLimiter",
    "serper_rate_limiter",
]
