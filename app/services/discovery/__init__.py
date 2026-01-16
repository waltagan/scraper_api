"""
Módulo de Discovery v4.1

Responsável por encontrar o site oficial de uma empresa
usando busca no Google via API Serper e análise por LLM.

Infraestrutura movida para discovery_manager:
- SerperManager: Rate limiting, retry, connection pooling
- SearchCache: Cache de buscas recentes
"""

from .discovery_service import (
    find_company_website,
    search_google_serper,
    close_serper_client,
    get_discovery_status,
    is_blacklisted_domain,
    BLACKLIST_DOMAINS,
    _filter_search_results,
    DISCOVERY_TIMEOUT,
)

__all__ = [
    'find_company_website',
    'search_google_serper',
    'close_serper_client',
    'get_discovery_status',
    'is_blacklisted_domain',
    'BLACKLIST_DOMAINS',
    '_filter_search_results',
    'DISCOVERY_TIMEOUT',
]
