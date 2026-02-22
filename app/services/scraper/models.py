"""
Modelos de dados para o módulo de scraping.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class ScrapedPage:
    """Resultado do scrape de uma página."""
    url: str
    content: str
    links: List[str] = field(default_factory=list)
    document_links: List[str] = field(default_factory=list)
    status_code: int = 200
    response_time_ms: float = 0.0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return bool(self.content) and len(self.content) >= 100 and not self.error


@dataclass
class ScrapeResult:
    """Resultado de scrape_company com metadados do pipeline."""
    pages: List[ScrapedPage] = field(default_factory=list)
    links_in_html: int = 0
    links_after_filter: int = 0
    links_selected: int = 0
    subpages_attempted: int = 0
    subpages_ok: int = 0
    subpage_errors: Dict[str, int] = field(default_factory=dict)
    main_page_ok: bool = False
    total_time_ms: float = 0.0
    main_page_fail_reason: str = ""

    probe_time_ms: float = 0.0
    probe_ok: bool = False
    main_scrape_time_ms: float = 0.0
    subpages_time_ms: float = 0.0
