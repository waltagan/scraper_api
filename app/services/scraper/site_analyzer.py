"""
Analisador de sites para determinar tipo e proteções.
Faz probe inicial do site para decidir melhor estratégia de scraping.
"""

import asyncio
import time
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

from .models import SiteProfile, SiteType, ProtectionType, ScrapingStrategy
from .protection_detector import protection_detector
from .constants import DEFAULT_HEADERS, build_headers

logger = logging.getLogger(__name__)


class SiteAnalyzer:
    """Analisa sites para determinar tipo e proteções."""
    
    # Assinaturas de SPA
    SPA_SIGNATURES = [
        "react",
        "__next",
        "__nuxt",
        "ng-app",
        "ng-controller",
        "data-v-",
        "vue-",
        "ember",
        "_app.js",
        "main.js",
        "bundle.js"
    ]
    
    # Assinaturas de conteúdo mínimo (indica SPA sem renderização)
    MINIMAL_CONTENT_SIGNATURES = [
        "<div id=\"root\"></div>",
        "<div id=\"app\"></div>",
        "<div id=\"__next\"></div>",
        "loading...",
        "please wait",
        "javascript required"
    ]
    
    def __init__(self, timeout: float = 7.0, probe_attempts: int = 1):
        self.timeout = timeout
        self.probe_attempts = probe_attempts
    
    async def analyze(self, url: str, ctx_label: str = "") -> SiteProfile:
        """
        Analisa site e retorna perfil completo com recomendações.
        
        Args:
            url: URL do site para analisar
            ctx_label: Label de contexto para logs
        
        Returns:
            SiteProfile com informações e recomendações
        """
        logger.info(f"{ctx_label}🔍 Analisando site: {url}")
        
        profile = SiteProfile(url=url)
        
        try:
            # 1. Fazer probe inicial
            html, headers, status, response_time = await self._probe_site(url)
            
            profile.response_time_ms = response_time
            profile.status_code = status
            profile.headers = headers
            profile.content_length = len(html) if html else 0
            profile.raw_html = html
            
            if not html or status >= 400:
                profile.error_message = f"Status {status}" if status >= 400 else "Sem conteúdo"
                profile.best_strategy = ScrapingStrategy.AGGRESSIVE
                return profile
            
            # 2. Detectar proteção
            profile.protection_type = protection_detector.detect(
                response_headers=headers,
                response_body=html,
                status_code=status
            )
            
            # 3. Detectar tipo de site
            profile.site_type = self._detect_site_type(html)
            profile.requires_javascript = profile.site_type in (SiteType.SPA, SiteType.HYBRID)
            
            # 4. Verificar robots.txt (DESABILITADO para performance)
            # robots_allowed = await self._check_robots_txt(url)
            # profile.has_robots_txt = robots_allowed is not None
            # profile.robots_allows_crawl = robots_allowed if robots_allowed is not None else True
            profile.has_robots_txt = False
            profile.robots_allows_crawl = True
            
            # 5. Determinar melhor estratégia
            profile.best_strategy = self._select_best_strategy(profile)
            
            logger.info(
                f"{ctx_label}✅ Análise completa: tipo={profile.site_type.value}, "
                f"proteção={profile.protection_type.value}, "
                f"estratégia={profile.best_strategy.value}"
            )
            
        except Exception as e:
            logger.error(f"{ctx_label}❌ Erro ao analisar {url}: {e}")
            profile.error_message = str(e)
            profile.best_strategy = ScrapingStrategy.ROBUST
        
        return profile
    
    async def _probe_site(self, url: str) -> Tuple[str, dict, int, float]:
        """Faz probe do site via proxy com retry automático em erros de proxy."""
        if not HAS_CURL_CFFI:
            raise RuntimeError("curl_cffi não está instalado")

        from app.services.scraper_manager.proxy_manager import (
            proxy_pool, record_proxy_success, record_proxy_failure,
        )

        max_retries = 2
        used_proxies: set = set()

        for attempt in range(max_retries):
            proxy = (
                proxy_pool.get_proxy_excluding(used_proxies)
                if used_proxies else proxy_pool.get_next_proxy()
            )
            if proxy:
                used_proxies.add(proxy)

            headers_to_send, impersonate = build_headers()

            try:
                async with AsyncSession(
                    impersonate=impersonate,
                    proxy=proxy,
                    timeout=self.timeout,
                    verify=False,
                ) as session:
                    start = time.perf_counter()
                    resp = await session.get(url, headers=headers_to_send)
                    elapsed = (time.perf_counter() - start) * 1000

                    if proxy:
                        record_proxy_success(proxy)
                    return resp.text, dict(resp.headers), resp.status_code, elapsed

            except Exception as e:
                if proxy:
                    record_proxy_failure(proxy, str(e)[:80])

                if attempt < max_retries - 1:
                    err_str = str(e).lower()
                    if any(x in err_str for x in ("timeout", "connect", "refused", "reset")):
                        logger.info(f"🔄 Analyzer retry {attempt+2}/{max_retries} para {url}")
                        continue
                logger.debug(f"Analyzer probe falhou: {e}")
                return "", {}, 0, self.timeout * 1000

        return "", {}, 0, self.timeout * 1000
    
    def _detect_site_type(self, html: str) -> SiteType:
        """Detecta se o site é SPA, estático ou híbrido."""
        if not html:
            return SiteType.UNKNOWN
        
        html_lower = html.lower()
        
        # Verificar conteúdo mínimo (indica SPA não renderizado)
        is_minimal = any(sig in html_lower for sig in self.MINIMAL_CONTENT_SIGNATURES)
        
        # Contar assinaturas de SPA
        spa_count = sum(1 for sig in self.SPA_SIGNATURES if sig in html_lower)
        
        # Verificar quantidade de conteúdo textual
        # Remove tags e conta caracteres
        from bs4 import BeautifulSoup
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for tag in soup(["script", "style", "noscript"]):
                tag.extract()
            text_content = soup.get_text(strip=True)
            text_length = len(text_content)
        except:
            text_length = len(html)
        
        # Determinar tipo
        if is_minimal and text_length < 500:
            return SiteType.SPA
        elif spa_count >= 3 and text_length < 2000:
            return SiteType.HYBRID
        elif spa_count >= 2:
            return SiteType.HYBRID
        else:
            return SiteType.STATIC
    
    async def _check_robots_txt(self, url: str) -> Optional[bool]:
        """
        Verifica robots.txt do site.
        
        Returns:
            True se permite crawl, False se não permite, None se não existe
        """
        if not HAS_CURL_CFFI:
            return None
        
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        try:
            async with AsyncSession(
                impersonate=build_headers()[1],
                timeout=5.0,
                verify=False
            ) as session:
                resp = await session.get(robots_url)
                
                if resp.status_code != 200:
                    return None
                
                content = resp.text.lower()
                
                # Verificar se bloqueia todos os user-agents
                if "user-agent: *" in content:
                    lines = content.split('\n')
                    in_all_section = False
                    for line in lines:
                        line = line.strip()
                        if line.startswith("user-agent: *"):
                            in_all_section = True
                        elif line.startswith("user-agent:"):
                            in_all_section = False
                        elif in_all_section and line.startswith("disallow: /"):
                            if line == "disallow: /":
                                return False
                
                return True
                
        except Exception as e:
            logger.debug(f"Erro ao verificar robots.txt: {e}")
            return None
    
    def _select_best_strategy(self, profile: SiteProfile) -> ScrapingStrategy:
        """Seleciona melhor estratégia baseado no perfil do site."""
        
        # Se tem proteção, usar estratégia apropriada
        if profile.protection_type == ProtectionType.CLOUDFLARE:
            return ScrapingStrategy.AGGRESSIVE
        
        if profile.protection_type in (ProtectionType.WAF, ProtectionType.BOT_DETECTION):
            return ScrapingStrategy.ROBUST
        
        if profile.protection_type == ProtectionType.RATE_LIMIT:
            return ScrapingStrategy.STANDARD  # Com delays maiores
        
        # Se é SPA, precisa de estratégia mais robusta
        if profile.site_type == SiteType.SPA:
            return ScrapingStrategy.ROBUST
        
        if profile.site_type == SiteType.HYBRID:
            return ScrapingStrategy.STANDARD
        
        # Site estático com tempo de resposta bom
        if profile.response_time_ms < 1000:
            return ScrapingStrategy.FAST
        
        # Site lento
        if profile.response_time_ms > 3000:
            return ScrapingStrategy.ROBUST
        
        return ScrapingStrategy.STANDARD


# Instância singleton
site_analyzer = SiteAnalyzer()

