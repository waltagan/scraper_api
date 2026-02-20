"""
Modelos de dados para o módulo de scraping.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class SiteType(Enum):
    """Tipo de site detectado."""
    STATIC = "static"           # Site estático tradicional
    SPA = "spa"                 # Single Page Application (React, Vue, Angular)
    HYBRID = "hybrid"           # Híbrido (parcialmente SPA)
    UNKNOWN = "unknown"         # Não foi possível determinar


class ProtectionType(Enum):
    """Tipo de proteção detectada."""
    NONE = "none"               # Sem proteção
    CLOUDFLARE = "cloudflare"   # Cloudflare
    WAF = "waf"                 # Web Application Firewall genérico
    CAPTCHA = "captcha"         # reCAPTCHA, hCaptcha
    RATE_LIMIT = "rate_limit"   # Rate limiting ativo
    BOT_DETECTION = "bot_detection"  # Detecção de bot genérica


class ScrapingStrategy(Enum):
    """Estratégia de scraping a ser utilizada."""
    FAST = "fast"               # curl_cffi sem proxy, timeout curto (10s)
    STANDARD = "standard"       # curl_cffi com proxy, timeout médio (15s)
    ROBUST = "robust"           # System curl com retry, timeout longo (20s)
    AGGRESSIVE = "aggressive"   # Rotação de UA + proxy, headers customizados


@dataclass
class SiteProfile:
    """Perfil completo de um site analisado."""
    url: str
    response_time_ms: float = 0.0
    site_type: SiteType = SiteType.UNKNOWN
    protection_type: ProtectionType = ProtectionType.NONE
    requires_javascript: bool = False
    has_robots_txt: bool = False
    robots_allows_crawl: bool = True
    best_strategy: ScrapingStrategy = ScrapingStrategy.FAST
    valid_url_variations: List[str] = field(default_factory=list)
    status_code: int = 0
    content_length: int = 0
    headers: dict = field(default_factory=dict)
    error_message: Optional[str] = None
    raw_html: Optional[str] = None


@dataclass
class ScrapedPage:
    """Resultado do scrape de uma página."""
    url: str
    content: str
    links: List[str] = field(default_factory=list)
    document_links: List[str] = field(default_factory=list)
    status_code: int = 200
    response_time_ms: float = 0.0
    strategy_used: ScrapingStrategy = ScrapingStrategy.FAST
    error: Optional[str] = None
    
    @property
    def success(self) -> bool:
        return self.content and len(self.content) >= 100 and not self.error


@dataclass
class ScrapedContent:
    """Resultado consolidado do scrape de um site completo."""
    main_url: str
    main_page: Optional[ScrapedPage] = None
    subpages: List[ScrapedPage] = field(default_factory=list)
    total_time_ms: float = 0.0
    strategies_tried: List[ScrapingStrategy] = field(default_factory=list)
    
    @property
    def aggregated_content(self) -> str:
        """Retorna todo o conteúdo concatenado."""
        parts = []
        if self.main_page and self.main_page.success:
            parts.append(f"--- PAGE START: {self.main_page.url} ---\n{self.main_page.content}\n--- PAGE END ---")
        for page in self.subpages:
            if page.success:
                parts.append(f"--- PAGE START: {page.url} ---\n{page.content}\n--- PAGE END ---")
        return "\n\n".join(parts)
    
    @property
    def all_document_links(self) -> List[str]:
        """Retorna todos os links de documentos encontrados."""
        links = set()
        if self.main_page:
            links.update(self.main_page.document_links)
        for page in self.subpages:
            links.update(page.document_links)
        return list(links)
    
    @property
    def visited_urls(self) -> List[str]:
        """Retorna todas as URLs visitadas com sucesso."""
        urls = []
        if self.main_page and self.main_page.success:
            urls.append(self.main_page.url)
        urls.extend([p.url for p in self.subpages if p.success])
        return urls
    
    @property
    def success_rate(self) -> float:
        """Taxa de sucesso das páginas."""
        total = 1 + len(self.subpages)  # main + subpages
        success = (1 if self.main_page and self.main_page.success else 0)
        success += sum(1 for p in self.subpages if p.success)
        return success / total if total > 0 else 0.0

