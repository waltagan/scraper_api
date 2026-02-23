"""
Modulo de Scraping — pipeline simplificado.
GET unico (probe+main) -> heuristic links -> scrape subpages.
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
from .url_prober import (
    url_prober,
    URLProber,
    URLNotReachable,
    ProbeErrorType,
    fast_probe_and_scrape,
)

try:
    from .scraper_service import scrape_all_subpages
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"curl_cffi nao disponivel: {e}")

    async def scrape_all_subpages(
        url: str, max_subpages: int = 5, ctx_label: str = "",
        request_id: str = "", proxy: str = "", proxy_provider: str = "",
    ):
        return ScrapeResult()


__all__ = [
    'scrape_all_subpages',
    'fast_probe_and_scrape',
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
