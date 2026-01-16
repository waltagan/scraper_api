"""
Módulo de Scraping v3.0

Responsável por extrair conteúdo de websites de forma adaptativa.
Inclui detecção automática de proteções, seleção de estratégias e fallback.

REFATORADO: 
- Infraestrutura (concorrência, proxies, circuit breaker) movida para scraper_manager
- Este módulo mantém apenas lógica de negócio
"""

from .constants import scraper_config, ScraperConfig
from .html_parser import (
    parse_html,
    is_cloudflare_challenge,
    is_soft_404,
    normalize_url
)
from .link_selector import (
    select_links_with_llm,
    prioritize_links,
    filter_non_html_links
)
from .models import (
    SiteType,
    ProtectionType,
    ScrapingStrategy,
    SiteProfile,
    ScrapedPage,
    ScrapedContent
)
from .site_analyzer import site_analyzer, SiteAnalyzer
from .protection_detector import protection_detector, ProtectionDetector
from .strategy_selector import strategy_selector, StrategySelector
from .url_prober import url_prober, URLProber, URLNotReachable, ProbeErrorType

# Importar funções de infraestrutura do scraper_manager (para compatibilidade)
from app.services.scraper_manager import (
    record_failure,
    record_success,
    is_circuit_open,
    reset_circuit,
)

# Alias para compatibilidade
reset_circuit_breaker = reset_circuit

# Importação direta do scrape_url para compatibilidade
try:
    from .scraper_service import scrape_url, scrape_batch_hybrid, scrape_all_subpages
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"curl_cffi não disponível: {e}")
    
    async def scrape_url(url: str, max_subpages: int = 100, ctx_label: str = ""):
        """Stub quando curl_cffi não está disponível."""
        return "", [], []
    
    async def scrape_batch_hybrid(urls, max_subpages: int = 100):
        """Stub quando curl_cffi não está disponível."""
        return [("", [], []) for _ in urls]
    
    async def scrape_all_subpages(url: str, max_subpages: int = 100, ctx_label: str = "", request_id: str = ""):
        """Stub quando curl_cffi não está disponível."""
        return []


__all__ = [
    # Funções principais
    'scrape_url',
    'scrape_batch_hybrid',
    'scrape_all_subpages',
    
    # Configuração
    'scraper_config',
    'ScraperConfig',
    
    # Circuit Breaker (do scraper_manager)
    'record_failure',
    'record_success',
    'is_circuit_open',
    'reset_circuit_breaker',
    'reset_circuit',
    
    # HTML Parser
    'parse_html',
    'is_cloudflare_challenge',
    'is_soft_404',
    'normalize_url',
    
    # Link Selector
    'select_links_with_llm',
    'prioritize_links',
    'filter_non_html_links',
    
    # Modelos
    'SiteType',
    'ProtectionType',
    'ScrapingStrategy',
    'SiteProfile',
    'ScrapedPage',
    'ScrapedContent',
    
    # Analisadores
    'site_analyzer',
    'SiteAnalyzer',
    'protection_detector',
    'ProtectionDetector',
    'strategy_selector',
    'StrategySelector',
    'url_prober',
    'URLProber',
    'URLNotReachable',
    'ProbeErrorType',
]


def configure_scraper(**kwargs):
    """
    Configura dinamicamente os parâmetros do scraper.
    
    Parâmetros aceitos:
        site_semaphore_limit: int
        circuit_breaker_threshold: int
        page_timeout: int
        session_timeout: int
        chunk_size: int
        chunk_semaphore_limit: int
    """
    scraper_config.update(**kwargs)
    
    # Também atualizar o concurrency_manager se aplicável
    try:
        from app.services.scraper_manager import concurrency_manager
        
        if 'site_semaphore_limit' in kwargs:
            concurrency_manager.update_limits(global_limit=kwargs['site_semaphore_limit'])
        if 'per_domain_limit' in kwargs:
            concurrency_manager.update_limits(per_domain_limit=kwargs['per_domain_limit'])
    except ImportError:
        pass
