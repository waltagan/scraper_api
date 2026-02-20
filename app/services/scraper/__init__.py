"""
Módulo de Scraping — pipeline simplificado.
probe → scrape main → heuristic links → scrape subpages.
"""

from .html_parser import (
    parse_html,
    is_cloudflare_challenge,
    is_soft_404,
    normalize_url,
)
from .link_selector import (
    extract_and_prioritize_links,
    prioritize_links,
    filter_non_html_links,
)
from .models import ScrapedPage, ScrapeResult
from .url_prober import url_prober, URLProber, URLNotReachable, ProbeErrorType

try:
    from .scraper_service import scrape_all_subpages
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"curl_cffi não disponível: {e}")

    async def scrape_all_subpages(url: str, max_subpages: int = 5, ctx_label: str = "", request_id: str = ""):
        return ScrapeResult()


__all__ = [
    'scrape_all_subpages',
    'parse_html',
    'is_cloudflare_challenge',
    'is_soft_404',
    'normalize_url',
    'extract_and_prioritize_links',
    'prioritize_links',
    'filter_non_html_links',
    'ScrapedPage',
    'ScrapeResult',
    'url_prober',
    'URLProber',
    'URLNotReachable',
    'ProbeErrorType',
]
