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
    from .scraper_service import (
        scrape_all_subpages,
        scrape_main_page_raw,
        extract_subpage_links_from_raw,
        extract_mainpage_text_from_raw,
        extract_text_and_links_from_raw,
    )
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"curl_cffi nao disponivel: {e}")

    async def scrape_all_subpages(
        url: str, max_subpages: int = 5, ctx_label: str = "",
        request_id: str = "", proxy: str = "", proxy_provider: str = "",
        probe_only: bool = False,
    ):
        return ScrapeResult()

    async def scrape_main_page_raw(url: str, timeout: int = 30, proxy: str = ""):
        return url, 0, "", "curl_cffi_not_available"

    def extract_subpage_links_from_raw(raw_content: str, base_url: str):
        return []

    def extract_mainpage_text_from_raw(raw_content: str, base_url: str):
        return ""

    def extract_text_and_links_from_raw(raw_content: str, base_url: str):
        return "", []


__all__ = [
    'scrape_all_subpages',
    'scrape_main_page_raw',
    'extract_subpage_links_from_raw',
    'extract_mainpage_text_from_raw',
    'extract_text_and_links_from_raw',
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
