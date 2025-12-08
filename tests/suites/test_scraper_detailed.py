"""
Teste ULTRA DETALHADO do Serviço de Scraping v2.0.

OBJETIVO: Identificar TODAS as variáveis que causam inconsistência nos resultados.

VARIÁVEIS MONITORADAS:
1. PROXY: Latência, falhas, rotação, IP usado
2. REDE: DNS, conexão, SSL, TTFB, download
3. SITES: Response time, status codes, headers (rate-limit)
4. LLM: Response time, tokens, provider
5. CIRCUIT BREAKER: Estado, acionamentos, domínios bloqueados
6. SISTEMA: CPU, memória (se disponível)
7. VARIABILIDADE: Desvio padrão entre execuções

ETAPAS MAPEADAS:
1-8. [Mesmas etapas anteriores + métricas detalhadas]
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
import json
import logging
import time
import socket
import statistics
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple
from urllib.parse import urlparse
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# DATACLASSES PARA MÉTRICAS ULTRA DETALHADAS
# ============================================================================

@dataclass
class ProxyMetrics:
    """Métricas detalhadas de proxy."""
    proxy_url: str = ""
    proxy_ip: str = ""
    latency_ms: float = 0.0
    connection_time_ms: float = 0.0
    success: bool = True
    error: str = ""
    request_count: int = 0
    failure_count: int = 0


@dataclass
class NetworkMetrics:
    """Métricas detalhadas de rede."""
    dns_resolution_ms: float = 0.0
    connection_ms: float = 0.0
    ssl_handshake_ms: float = 0.0
    ttfb_ms: float = 0.0  # Time to First Byte
    download_ms: float = 0.0
    total_ms: float = 0.0
    bytes_downloaded: int = 0


@dataclass
class SiteResponseMetrics:
    """Métricas de resposta do site."""
    url: str = ""
    status_code: int = 0
    response_time_ms: float = 0.0
    content_length: int = 0
    has_rate_limit_header: bool = False
    rate_limit_remaining: Optional[int] = None
    retry_after: Optional[int] = None
    server_header: str = ""
    cloudflare_detected: bool = False


@dataclass
class LLMMetrics:
    """Métricas de chamadas LLM."""
    provider: str = ""
    model: str = ""
    response_time_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    success: bool = True
    error: str = ""


@dataclass
class CircuitBreakerState:
    """Estado do circuit breaker."""
    initial_open_domains: List[str] = field(default_factory=list)
    final_open_domains: List[str] = field(default_factory=list)
    domains_opened_during_test: List[str] = field(default_factory=list)
    total_failures_recorded: int = 0


@dataclass
class SubStepMetric:
    """Métrica de uma subetapa específica."""
    name: str
    duration_ms: float = 0.0
    success: bool = True
    error: str = ""
    details: Dict = field(default_factory=dict)
    # Novas métricas
    proxy_used: str = ""
    retry_count: int = 0
    network_metrics: Optional[NetworkMetrics] = None


@dataclass
class StepMetric:
    """Métrica de uma etapa principal."""
    name: str
    step_number: int
    duration_ms: float = 0.0
    success: bool = True
    error: str = ""
    substeps: List[SubStepMetric] = field(default_factory=list)
    
    def add_substep(
        self, 
        name: str, 
        duration_ms: float, 
        success: bool = True, 
        error: str = "",
        details: Dict = None,
        proxy_used: str = "",
        retry_count: int = 0
    ):
        self.substeps.append(SubStepMetric(
            name=name,
            duration_ms=duration_ms,
            success=success,
            error=error,
            details=details or {},
            proxy_used=proxy_used,
            retry_count=retry_count
        ))


@dataclass
class ScrapeDetailedResult:
    """Resultado ultra detalhado de um scrape."""
    url: str
    empresa: str = ""
    
    # Resultado geral
    success: bool = False
    content: str = ""  # NOVO: Salvar conteúdo para LLM
    content_length: int = 0
    pages_scraped: int = 0
    documents_found: int = 0
    links_found: int = 0
    
    # Tempos
    total_time_ms: float = 0.0
    
    # Etapas detalhadas
    steps: List[StepMetric] = field(default_factory=list)
    
    # Informações do site
    site_type: str = ""
    protection_type: str = ""
    strategy_used: str = ""
    
    # NOVAS: Métricas de proxy por URL
    proxies_used: List[str] = field(default_factory=list)
    proxy_failures: int = 0
    proxy_latencies_ms: List[float] = field(default_factory=list)
    
    # NOVAS: Métricas de rede
    avg_ttfb_ms: float = 0.0
    avg_download_ms: float = 0.0
    
    # NOVAS: Métricas de LLM
    llm_calls: int = 0
    llm_total_time_ms: float = 0.0
    
    # NOVAS: Métricas de retry
    total_retries: int = 0
    
    # NOVAS: Rate limiting detectado
    rate_limit_detected: bool = False
    
    # Erros
    error: str = ""
    error_step: str = ""
    
    def add_step(self, step: StepMetric):
        self.steps.append(step)
    
    def to_dict(self) -> Dict:
        """Converte para dicionário para serialização JSON."""
        return {
            "url": self.url,
            "empresa": self.empresa,
            "success": self.success,
            "content": self.content, # NOVO
            "content_length": self.content_length,
            "pages_scraped": self.pages_scraped,
            "documents_found": self.documents_found,
            "links_found": self.links_found,
            "total_time_ms": self.total_time_ms,
            "site_type": self.site_type,
            "protection_type": self.protection_type,
            "strategy_used": self.strategy_used,
            # Novas métricas
            "proxies_used": self.proxies_used,
            "proxy_failures": self.proxy_failures,
            "proxy_latencies_ms": self.proxy_latencies_ms,
            "avg_proxy_latency_ms": statistics.mean(self.proxy_latencies_ms) if self.proxy_latencies_ms else 0,
            "proxy_latency_stddev": statistics.stdev(self.proxy_latencies_ms) if len(self.proxy_latencies_ms) > 1 else 0,
            "avg_ttfb_ms": self.avg_ttfb_ms,
            "avg_download_ms": self.avg_download_ms,
            "llm_calls": self.llm_calls,
            "llm_total_time_ms": self.llm_total_time_ms,
            "total_retries": self.total_retries,
            "rate_limit_detected": self.rate_limit_detected,
            "error": self.error,
            "error_step": self.error_step,
            "steps": [
                {
                    "name": s.name,
                    "step_number": s.step_number,
                    "duration_ms": s.duration_ms,
                    "success": s.success,
                    "error": s.error,
                    "substeps": [
                        {
                            "name": ss.name,
                            "duration_ms": ss.duration_ms,
                            "success": ss.success,
                            "error": ss.error,
                            "details": ss.details,
                            "proxy_used": ss.proxy_used,
                            "retry_count": ss.retry_count
                        }
                        for ss in s.substeps
                    ]
                }
                for s in self.steps
            ]
        }


@dataclass 
class TestMetrics:
    """Métricas agregadas do teste."""
    total: int = 0
    success: int = 0
    failed: int = 0
    timeout: int = 0
    
    # Tempos por etapa
    avg_time_total_ms: float = 0.0
    stddev_time_total_ms: float = 0.0  # NOVO: desvio padrão
    avg_time_probe_ms: float = 0.0
    avg_time_analysis_ms: float = 0.0
    avg_time_main_page_ms: float = 0.0
    avg_time_link_selection_ms: float = 0.0
    avg_time_subpages_ms: float = 0.0
    
    # Distribuição por tipo de site
    sites_static: int = 0
    sites_spa: int = 0
    sites_hybrid: int = 0
    sites_unknown: int = 0
    
    # Distribuição por proteção
    protection_none: int = 0
    protection_cloudflare: int = 0
    protection_waf: int = 0
    protection_captcha: int = 0
    protection_rate_limit: int = 0
    protection_bot_detection: int = 0
    
    # Distribuição por estratégia
    strategy_fast: int = 0
    strategy_standard: int = 0
    strategy_robust: int = 0
    strategy_aggressive: int = 0
    
    # Métricas de conteúdo
    avg_content_length: float = 0.0
    avg_pages_per_site: float = 0.0
    avg_links_per_site: float = 0.0
    
    # NOVAS: Métricas de proxy agregadas
    total_proxies_used: int = 0
    unique_proxies_used: int = 0
    avg_proxy_latency_ms: float = 0.0
    stddev_proxy_latency_ms: float = 0.0
    proxy_failure_rate: float = 0.0
    
    # NOVAS: Métricas de LLM agregadas
    total_llm_calls: int = 0
    avg_llm_time_ms: float = 0.0
    
    # NOVAS: Métricas de retry
    total_retries: int = 0
    sites_with_retries: int = 0
    
    # NOVAS: Rate limiting
    sites_rate_limited: int = 0
    
    # NOVAS: Circuit breaker
    circuit_breaker_triggers: int = 0


@dataclass
class EnvironmentMetrics:
    """Métricas do ambiente de execução."""
    timestamp: str = ""
    python_version: str = ""
    platform: str = ""
    proxy_pool_size: int = 0
    circuit_breaker_state: CircuitBreakerState = field(default_factory=CircuitBreakerState)
    initial_network_latency_ms: float = 0.0  # Ping para google.com


# ============================================================================
# FUNÇÕES AUXILIARES DE MÉTRICAS
# ============================================================================

async def measure_proxy_latency(proxy_url: str) -> Tuple[float, bool]:
    """Mede a latência de um proxy."""
    try:
        start = time.perf_counter()
        # Extrair host e porta do proxy
        parsed = urlparse(proxy_url if '://' in proxy_url else f'http://{proxy_url}')
        host = parsed.hostname
        port = parsed.port or 80
        
        # Tentar conexão TCP simples
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=5.0
        )
        writer.close()
        await writer.wait_closed()
        
        latency = (time.perf_counter() - start) * 1000
        return latency, True
    except Exception as e:
        return 0, False


async def measure_network_baseline() -> float:
    """Mede latência base da rede (sem proxy)."""
    try:
        start = time.perf_counter()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection('www.google.com', 443),
            timeout=5.0
        )
        writer.close()
        await writer.wait_closed()
        return (time.perf_counter() - start) * 1000
    except:
        return -1


def get_circuit_breaker_state() -> List[str]:
    """Retorna domínios com circuit breaker aberto."""
    from app.services.scraper.circuit_breaker import _domain_failures
    from app.services.scraper.constants import scraper_config
    
    threshold = scraper_config.circuit_breaker_threshold
    open_domains = [
        domain for domain, failures in _domain_failures.items()
        if failures >= threshold
    ]
    return open_domains


def get_all_domain_failures() -> Dict[str, int]:
    """Retorna todas as falhas por domínio."""
    from app.services.scraper.circuit_breaker import _domain_failures
    return dict(_domain_failures)


# ============================================================================
# CLASSE PRINCIPAL DO TESTE
# ============================================================================

class ScraperDetailedTest:
    """Teste ultra detalhado do serviço de scraping."""
    
    def __init__(
        self,
        discovery_report: str = None,
        max_concurrent: int = 10,
        timeout_per_url: float = 120.0,
        max_subpages: int = 30
    ):
        self.discovery_report = discovery_report
        self.max_concurrent = max_concurrent
        self.timeout = timeout_per_url
        self.max_subpages = max_subpages
        self.results: List[ScrapeDetailedResult] = []
        self.metrics = TestMetrics()
        self.environment = EnvironmentMetrics()
        
        # Tracking de proxies
        self.all_proxy_latencies: List[float] = []
        self.all_proxies_used: Set[str] = set()
        self.proxy_failures_count: int = 0
        
        # Tracking de LLM
        self.llm_call_times: List[float] = []
    
    async def collect_environment_metrics(self):
        """Coleta métricas do ambiente antes do teste."""
        import platform
        import sys
        
        self.environment.timestamp = datetime.now().isoformat()
        self.environment.python_version = sys.version
        self.environment.platform = platform.platform()
        
        # Medir latência base da rede
        self.environment.initial_network_latency_ms = await measure_network_baseline()
        
        # Estado do circuit breaker
        self.environment.circuit_breaker_state.initial_open_domains = get_circuit_breaker_state()
        
        # Tamanho do pool de proxies
        try:
            from app.core.proxy import proxy_manager
            await proxy_manager.get_next_proxy()  # Força carregamento
            self.environment.proxy_pool_size = len(proxy_manager._proxies) if hasattr(proxy_manager, '_proxies') else 0
        except:
            self.environment.proxy_pool_size = 0
        
        logger.info(f"📊 Ambiente: {self.environment.platform}")
        logger.info(f"📊 Latência base da rede: {self.environment.initial_network_latency_ms:.0f}ms")
        logger.info(f"📊 Circuit breakers abertos: {len(self.environment.circuit_breaker_state.initial_open_domains)}")
        logger.info(f"📊 Pool de proxies: {self.environment.proxy_pool_size}")
    
    def load_urls_from_discovery(self, limit: int = None) -> List[Dict]:
        """Carrega URLs do resultado do discovery."""
        if not self.discovery_report:
            reports_dir = Path("tests/reports")
            discovery_files = sorted(
                reports_dir.glob("discovery_test_*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            if discovery_files:
                self.discovery_report = str(discovery_files[0])
            else:
                raise FileNotFoundError("Nenhum relatório de discovery encontrado")
        
        with open(self.discovery_report, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        urls = []
        seen = set()
        
        for r in data.get('results', []):
            if r.get('success') and r.get('url'):
                url = r['url']
                if url not in seen:
                    seen.add(url)
                    urls.append({
                        'url': url,
                        'empresa': r.get('empresa', ''),
                        'razao_social': r.get('razao_social', '')
                    })
        
        if limit:
            urls = urls[:limit]
        
        logger.info(f"Carregadas {len(urls)} URLs únicas do discovery")
        return urls
    
    async def scrape_single_detailed(
        self, 
        url_data: Dict, 
        idx: int
    ) -> ScrapeDetailedResult:
        """
        Executa scrape de uma URL com métricas ULTRA detalhadas.
        """
        url = url_data['url']
        result = ScrapeDetailedResult(
            url=url,
            empresa=url_data.get('empresa', '')
        )
        
        overall_start = time.perf_counter()
        
        try:
            # Importar dependências
            from app.services.scraper import (
                url_prober, site_analyzer, strategy_selector,
                scraper_config, normalize_url
            )
            from app.services.scraper.http_client import cffi_scrape_safe, system_curl_scrape
            from app.services.scraper.html_parser import is_cloudflare_challenge, is_soft_404
            from app.services.scraper.link_selector import (
                select_links_with_llm, filter_non_html_links, prioritize_links
            )
            from app.services.scraper.protection_detector import protection_detector
            from app.services.scraper.circuit_breaker import is_circuit_open, record_success, record_failure
            from app.services.scraper.models import ScrapingStrategy
            from app.services.learning import site_knowledge, adaptive_config
            from app.core.proxy import proxy_manager
            
            # ================================================================
            # ETAPA 1: CONSULTA DE CONHECIMENTO PRÉVIO
            # ================================================================
            step1 = StepMetric(name="Conhecimento Prévio", step_number=1)
            step1_start = time.perf_counter()
            
            ss1_start = time.perf_counter()
            site_profile_known = site_knowledge.get_profile(url)
            has_prior_knowledge = site_profile_known and site_profile_known.total_attempts > 0
            step1.add_substep(
                "Consultar site_knowledge",
                (time.perf_counter() - ss1_start) * 1000,
                details={"has_prior_knowledge": has_prior_knowledge}
            )
            
            ss2_start = time.perf_counter()
            if has_prior_knowledge:
                known_strategy = site_profile_known.best_strategy
                known_protection = site_profile_known.protection_type
            else:
                known_strategy = adaptive_config.get_default_strategy_for_new_site()
                known_protection = "none"
            step1.add_substep(
                "Aprendizado global",
                (time.perf_counter() - ss2_start) * 1000,
                details={"known_strategy": known_strategy, "known_protection": known_protection}
            )
            
            step1.duration_ms = (time.perf_counter() - step1_start) * 1000
            result.add_step(step1)
            
            # ================================================================
            # ETAPA 2: PROBE URL
            # ================================================================
            step2 = StepMetric(name="Probe URL", step_number=2)
            step2_start = time.perf_counter()
            
            best_url = url
            probe_time = 0
            
            try:
                ss_start = time.perf_counter()
                best_url, probe_time = await asyncio.wait_for(
                    url_prober.probe(url),
                    timeout=15.0
                )
                step2.add_substep(
                    "Probe variações",
                    (time.perf_counter() - ss_start) * 1000,
                    details={"best_url": best_url, "probe_time_ms": probe_time}
                )
                
            except asyncio.TimeoutError:
                step2.add_substep("Probe variações", 15000, success=False, error="Timeout")
                step2.success = False
                step2.error = "Probe timeout"
            except Exception as e:
                step2.add_substep("Probe variações", (time.perf_counter() - step2_start) * 1000, 
                                success=False, error=str(e))
                step2.success = False
                step2.error = str(e)
            
            step2.duration_ms = (time.perf_counter() - step2_start) * 1000
            result.add_step(step2)
            
            if not step2.success:
                result.error = step2.error
                result.error_step = "Probe URL"
                result.total_time_ms = (time.perf_counter() - overall_start) * 1000
                logger.info(f"[{idx}] ❌ {url[:50]:50} | PROBE FALHOU | {result.total_time_ms:.0f}ms")
                return result
            
            url = best_url
            
            # ================================================================
            # ETAPA 3: ANÁLISE DO SITE
            # ================================================================
            step3 = StepMetric(name="Análise do Site", step_number=3)
            step3_start = time.perf_counter()
            
            try:
                ss_start = time.perf_counter()
                site_profile = await asyncio.wait_for(
                    site_analyzer.analyze(url),
                    timeout=30.0
                )
                
                result.site_type = site_profile.site_type.value
                result.protection_type = site_profile.protection_type.value
                
                step3.add_substep(
                    "Análise completa",
                    (time.perf_counter() - ss_start) * 1000,
                    details={
                        "site_type": result.site_type,
                        "protection_type": result.protection_type,
                        "response_time_ms": site_profile.response_time_ms,
                        "content_length": site_profile.content_length,
                        "requires_js": site_profile.requires_javascript
                    }
                )
                
            except asyncio.TimeoutError:
                step3.add_substep("Análise completa", 30000, success=False, error="Timeout")
                step3.success = False
                step3.error = "Analysis timeout"
            except Exception as e:
                step3.add_substep("Análise completa", (time.perf_counter() - step3_start) * 1000,
                                success=False, error=str(e))
                step3.success = False
                step3.error = str(e)
                from app.services.scraper.models import SiteProfile
                site_profile = SiteProfile(url=url)
            
            step3.duration_ms = (time.perf_counter() - step3_start) * 1000
            result.add_step(step3)
            
            # ================================================================
            # ETAPA 4: SELEÇÃO DE ESTRATÉGIAS
            # ================================================================
            step4 = StepMetric(name="Seleção de Estratégias", step_number=4)
            step4_start = time.perf_counter()
            
            ss_start = time.perf_counter()
            strategies = strategy_selector.select(site_profile)
            
            if known_strategy != "standard":
                try:
                    known_strat_enum = ScrapingStrategy(known_strategy)
                    if known_strat_enum in strategies:
                        strategies.remove(known_strat_enum)
                    strategies.insert(0, known_strat_enum)
                except ValueError:
                    pass
            
            step4.add_substep(
                "Selecionar estratégias",
                (time.perf_counter() - ss_start) * 1000,
                details={"strategies": [s.value for s in strategies]}
            )
            
            step4.duration_ms = (time.perf_counter() - step4_start) * 1000
            result.add_step(step4)
            
            # ================================================================
            # ETAPA 5: SCRAPE DA MAIN PAGE (com métricas de proxy)
            # ================================================================
            step5 = StepMetric(name="Scrape Main Page", step_number=5)
            step5_start = time.perf_counter()
            
            main_content = ""
            main_links: Set[str] = set()
            main_docs: Set[str] = set()
            strategy_that_worked = None
            
            MIN_CONTENT_LENGTH = 500
            
            for i, strategy in enumerate(strategies):
                ss_start = time.perf_counter()
                config = strategy_selector.get_strategy_config(strategy)
                
                proxy_used = ""
                retry_count = 0
                
                try:
                    proxy = None
                    if config.get("use_proxy"):
                        proxy_start = time.perf_counter()
                        proxy = await proxy_manager.get_next_proxy()
                        proxy_get_time = (time.perf_counter() - proxy_start) * 1000
                        
                        if proxy:
                            proxy_used = proxy
                            result.proxies_used.append(proxy)
                            self.all_proxies_used.add(proxy)
                            
                            # Medir latência do proxy
                            latency, proxy_ok = await measure_proxy_latency(proxy)
                            if proxy_ok:
                                result.proxy_latencies_ms.append(latency)
                                self.all_proxy_latencies.append(latency)
                            else:
                                result.proxy_failures += 1
                                self.proxy_failures_count += 1
                    
                    # Scrape com cffi
                    text, docs, links = await asyncio.wait_for(
                        cffi_scrape_safe(url, proxy),
                        timeout=config["timeout"]
                    )
                    
                    if not text or len(text) < 100:
                        retry_count += 1
                        result.total_retries += 1
                        text, docs, links = await asyncio.wait_for(
                            system_curl_scrape(url, proxy),
                            timeout=20
                        )
                    
                    content_len = len(text) if text else 0
                    
                    is_cf = is_cloudflare_challenge(text) if text else False
                    is_404 = is_soft_404(text) if text else True
                    
                    # Detectar rate limiting
                    if "rate limit" in (text or "").lower() or "too many requests" in (text or "").lower():
                        result.rate_limit_detected = True
                    
                    if content_len >= MIN_CONTENT_LENGTH and not is_cf and not is_404:
                        main_content = text
                        main_links = links
                        main_docs = docs
                        strategy_that_worked = strategy
                        
                        step5.add_substep(
                            f"Estratégia {strategy.value}",
                            (time.perf_counter() - ss_start) * 1000,
                            success=True,
                            details={
                                "content_length": content_len,
                                "links_found": len(links),
                                "docs_found": len(docs),
                                "attempt": i + 1
                            },
                            proxy_used=proxy_used,
                            retry_count=retry_count
                        )
                        break
                    else:
                        step5.add_substep(
                            f"Estratégia {strategy.value}",
                            (time.perf_counter() - ss_start) * 1000,
                            success=False,
                            error="Conteúdo insuficiente" if content_len < MIN_CONTENT_LENGTH else 
                                  "Cloudflare" if is_cf else "Soft 404",
                            details={"content_length": content_len},
                            proxy_used=proxy_used,
                            retry_count=retry_count
                        )
                        
                except asyncio.TimeoutError:
                    step5.add_substep(
                        f"Estratégia {strategy.value}",
                        config["timeout"] * 1000,
                        success=False,
                        error="Timeout",
                        proxy_used=proxy_used,
                        retry_count=retry_count
                    )
                except Exception as e:
                    step5.add_substep(
                        f"Estratégia {strategy.value}",
                        (time.perf_counter() - ss_start) * 1000,
                        success=False,
                        error=str(e)[:100],
                        proxy_used=proxy_used,
                        retry_count=retry_count
                    )
            
            step5.duration_ms = (time.perf_counter() - step5_start) * 1000
            step5.success = bool(main_content)
            
            if not step5.success:
                step5.error = "Todas estratégias falharam"
                result.error = "Main page scrape failed"
                result.error_step = "Scrape Main Page"
            else:
                result.strategy_used = strategy_that_worked.value if strategy_that_worked else ""
            
            result.add_step(step5)
            
            if not step5.success:
                result.total_time_ms = (time.perf_counter() - overall_start) * 1000
                logger.info(f"[{idx}] ❌ {url[:50]:50} | MAIN PAGE FALHOU | {result.total_time_ms:.0f}ms")
                return result
            
            # ================================================================
            # ETAPA 6: SELEÇÃO DE LINKS (LLM) - com métricas
            # ================================================================
            step6 = StepMetric(name="Seleção de Links", step_number=6)
            step6_start = time.perf_counter()
            
            target_subpages = []
            
            if main_links:
                ss_start = time.perf_counter()
                filtered_links = filter_non_html_links(main_links)
                step6.add_substep(
                    "Filtrar links não-HTML",
                    (time.perf_counter() - ss_start) * 1000,
                    details={
                        "original_count": len(main_links),
                        "filtered_count": len(filtered_links)
                    }
                )
                
                if filtered_links:
                    if len(filtered_links) <= self.max_subpages:
                        step6.add_substep(
                            "Short-circuit (poucos links)",
                            0.1,
                            details={"count": len(filtered_links)}
                        )
                        target_subpages = list(filtered_links)
                    else:
                        ss_start = time.perf_counter()
                        try:
                            target_subpages = await asyncio.wait_for(
                                select_links_with_llm(
                                    filtered_links, url, max_links=self.max_subpages
                                ),
                                timeout=30.0
                            )
                            llm_time = (time.perf_counter() - ss_start) * 1000
                            result.llm_calls += 1
                            result.llm_total_time_ms += llm_time
                            self.llm_call_times.append(llm_time)
                            
                            step6.add_substep(
                                "Seleção com LLM",
                                llm_time,
                                details={
                                    "selected_count": len(target_subpages),
                                    "llm_time_ms": llm_time
                                }
                            )
                        except asyncio.TimeoutError:
                            target_subpages = prioritize_links(filtered_links, url)[:self.max_subpages]
                            step6.add_substep(
                                "Fallback heurísticas (timeout)",
                                (time.perf_counter() - ss_start) * 1000,
                                success=False,
                                error="LLM timeout",
                                details={"selected_count": len(target_subpages)}
                            )
                        except Exception as e:
                            target_subpages = prioritize_links(filtered_links, url)[:self.max_subpages]
                            step6.add_substep(
                                "Fallback heurísticas (erro)",
                                (time.perf_counter() - ss_start) * 1000,
                                success=False,
                                error=str(e)[:100],
                                details={"selected_count": len(target_subpages)}
                            )
            else:
                step6.add_substep("Sem links para processar", 0.1, details={"count": 0})
            
            step6.duration_ms = (time.perf_counter() - step6_start) * 1000
            result.links_found = len(main_links)
            result.add_step(step6)
            
            # ================================================================
            # ETAPA 7: SCRAPE DAS SUBPÁGINAS (com métricas de proxy individual)
            # ================================================================
            step7 = StepMetric(name="Scrape Subpáginas", step_number=7)
            step7_start = time.perf_counter()
            
            subpage_contents = []
            subpage_docs: Set[str] = set()
            subpage_proxy_latencies = []
            subpage_proxy_failures = 0
            
            if target_subpages:
                chunk_size = scraper_config.chunk_size
                chunks = [
                    target_subpages[i:i + chunk_size] 
                    for i in range(0, len(target_subpages), chunk_size)
                ]
                step7.add_substep(
                    "Dividir em chunks",
                    0.1,
                    details={"total_urls": len(target_subpages), "num_chunks": len(chunks), "chunk_size": chunk_size}
                )
                
                successful_pages = 0
                failed_pages = 0
                
                for chunk_idx, chunk in enumerate(chunks):
                    chunk_start = time.perf_counter()
                    chunk_successes = 0
                    chunk_failures = 0
                    chunk_proxies = []
                    
                    for sub_url in chunk:
                        if is_circuit_open(sub_url):
                            chunk_failures += 1
                            continue
                        
                        try:
                            # Obter proxy individual para cada subpágina
                            sub_proxy_start = time.perf_counter()
                            sub_proxy = await proxy_manager.get_next_proxy()
                            
                            if sub_proxy:
                                chunk_proxies.append(sub_proxy)
                                result.proxies_used.append(sub_proxy)
                                self.all_proxies_used.add(sub_proxy)
                                
                                # Medir latência
                                latency, proxy_ok = await measure_proxy_latency(sub_proxy)
                                if proxy_ok:
                                    subpage_proxy_latencies.append(latency)
                                    result.proxy_latencies_ms.append(latency)
                                    self.all_proxy_latencies.append(latency)
                                else:
                                    subpage_proxy_failures += 1
                                    result.proxy_failures += 1
                                    self.proxy_failures_count += 1
                            
                            normalized = normalize_url(sub_url)
                            text, docs, _ = await asyncio.wait_for(
                                cffi_scrape_safe(normalized, sub_proxy),
                                timeout=15
                            )
                            
                            if not text or len(text) < 100 or is_soft_404(text):
                                result.total_retries += 1
                                text, docs, _ = await asyncio.wait_for(
                                    system_curl_scrape(normalized, sub_proxy),
                                    timeout=15
                                )
                            
                            if text and len(text) >= 100 and not is_soft_404(text):
                                subpage_contents.append(text)
                                subpage_docs.update(docs)
                                record_success(sub_url)
                                chunk_successes += 1
                            else:
                                record_failure(sub_url)
                                chunk_failures += 1
                                
                        except Exception as e:
                            record_failure(sub_url)
                            chunk_failures += 1
                    
                    successful_pages += chunk_successes
                    failed_pages += chunk_failures
                    
                    step7.add_substep(
                        f"Chunk {chunk_idx + 1}/{len(chunks)}",
                        (time.perf_counter() - chunk_start) * 1000,
                        success=chunk_successes > 0,
                        details={
                            "urls_in_chunk": len(chunk),
                            "successes": chunk_successes,
                            "failures": chunk_failures,
                            "unique_proxies": len(set(chunk_proxies)),
                            "proxy_failures": subpage_proxy_failures,
                            "avg_proxy_latency_ms": statistics.mean(subpage_proxy_latencies) if subpage_proxy_latencies else 0
                        }
                    )
                
                step7.add_substep(
                    "Consolidar resultados",
                    0.1,
                    details={
                        "total_successful": successful_pages,
                        "total_failed": failed_pages,
                        "total_docs": len(subpage_docs)
                    }
                )
            else:
                step7.add_substep("Sem subpáginas para processar", 0.1)
            
            step7.duration_ms = (time.perf_counter() - step7_start) * 1000
            result.add_step(step7)
            
            # ================================================================
            # ETAPA 8: CONSOLIDAÇÃO E APRENDIZADO
            # ================================================================
            step8 = StepMetric(name="Consolidação", step_number=8)
            step8_start = time.perf_counter()
            
            all_content = main_content
            for sc in subpage_contents:
                all_content += f"\n\n{sc}"
            
            all_docs = main_docs | subpage_docs
            
            result.content = all_content # NOVO
            result.content_length = len(all_content)
            result.pages_scraped = 1 + len(subpage_contents)
            result.documents_found = len(all_docs)
            
            step8.add_substep(
                "Consolidar conteúdo",
                0.1,
                details={
                    "total_content_length": result.content_length,
                    "total_pages": result.pages_scraped,
                    "total_documents": result.documents_found
                }
            )
            
            ss_start = time.perf_counter()
            try:
                total_time = (time.perf_counter() - overall_start) * 1000
                site_knowledge.record_success(
                    url,
                    response_time_ms=total_time,
                    strategy_used=result.strategy_used
                )
                step8.add_substep(
                    "Registrar aprendizado",
                    (time.perf_counter() - ss_start) * 1000,
                    details={"recorded": True}
                )
            except Exception as e:
                step8.add_substep(
                    "Registrar aprendizado",
                    (time.perf_counter() - ss_start) * 1000,
                    success=False,
                    error=str(e)[:50]
                )
            
            step8.duration_ms = (time.perf_counter() - step8_start) * 1000
            result.add_step(step8)
            
            # ================================================================
            # FINALIZAÇÃO
            # ================================================================
            result.success = True
            result.total_time_ms = (time.perf_counter() - overall_start) * 1000
            
            # Calcular médias
            if result.proxy_latencies_ms:
                result.avg_ttfb_ms = statistics.mean(result.proxy_latencies_ms)
            
            logger.info(
                f"[{idx}] ✅ {url[:50]:50} | "
                f"{result.content_length:>7} chars | "
                f"{result.pages_scraped:>2} pgs | "
                f"{result.total_time_ms:>6.0f}ms | "
                f"proxies:{len(result.proxies_used)} lat:{result.avg_ttfb_ms:.0f}ms"
            )
            
        except asyncio.TimeoutError:
            result.error = "Timeout geral"
            result.error_step = "Global"
            result.total_time_ms = self.timeout * 1000
            logger.info(f"[{idx}] ⏱️ {url[:50]:50} | TIMEOUT ({self.timeout}s)")
            
        except Exception as e:
            result.error = str(e)
            result.error_step = "Exception"
            result.total_time_ms = (time.perf_counter() - overall_start) * 1000
            logger.error(f"[{idx}] ❌ {url[:50]:50} | ERRO: {e}")
        
        return result
    
    async def run_test(self, limit: int = None):
        """Executa teste de scraping em paralelo."""
        from app.services.learning import site_knowledge
        from app.services.scraper.constants import scraper_config
        # Coletar métricas do ambiente
        await self.collect_environment_metrics()
        
        urls = self.load_urls_from_discovery(limit)
        # Embaralhar ordem para reduzir impacto de ordem fixa
        random.shuffle(urls)
        self.metrics.total = len(urls)
        
        logger.info("=" * 80)
        logger.info("TESTE ULTRA DETALHADO DE SCRAPING v2.0")
        logger.info("=" * 80)
        logger.info(f"URLs a testar: {len(urls)}")
        logger.info(f"Concorrência máxima: {self.max_concurrent}")
        logger.info(f"Timeout por URL: {self.timeout}s")
        logger.info(f"Max subpáginas: {self.max_subpages}")
        logger.info("=" * 80)
        
        # Concorrência: slots separados para rápidos/lentos e dobrar capacidade total
        total_slots = max(1, self.max_concurrent * 2)
        slow_slots = max(2, int(total_slots * 0.2))
        fast_slots = max(1, total_slots - slow_slots)
        fast_sem = asyncio.Semaphore(fast_slots)
        slow_sem = asyncio.Semaphore(slow_slots)
        effective_timeout = min(self.timeout, 60)  # teto global por site

        def pick_semaphore(url_data):
            profile = site_knowledge.get_profile(url_data["url"])
            if profile:
                if getattr(profile, "protection_type", "none") not in ("none", None):
                    return slow_sem
                if str(getattr(profile, "best_strategy", "")).lower() in ("robust", "aggressive"):
                    return slow_sem
                if getattr(profile, "response_time_ms", 0) > scraper_config.slow_main_threshold_ms:
                    return slow_sem
            return fast_sem
        
        async def bounded_scrape(url_data, idx):
            sem = pick_semaphore(url_data)
            async with sem:
                try:
                    return await asyncio.wait_for(
                        self.scrape_single_detailed(url_data, idx),
                        timeout=effective_timeout
                    )
                except asyncio.TimeoutError:
                    result = ScrapeDetailedResult(url=url_data["url"], empresa=url_data.get("empresa", ""))
                    result.error = "Timeout geral"
                    result.error_step = "Global"
                    result.total_time_ms = effective_timeout * 1000
                    return result
        
        start_time = time.perf_counter()
        
        tasks = [
            bounded_scrape(url_data, i + 1)
            for i, url_data in enumerate(urls)
        ]
        
        self.results = await asyncio.gather(*tasks)
        
        total_time = time.perf_counter() - start_time
        
        # Coletar estado final do circuit breaker
        self.environment.circuit_breaker_state.final_open_domains = get_circuit_breaker_state()
        self.environment.circuit_breaker_state.domains_opened_during_test = [
            d for d in self.environment.circuit_breaker_state.final_open_domains
            if d not in self.environment.circuit_breaker_state.initial_open_domains
        ]
        
        # Calcular métricas
        self._calculate_metrics()
        
        # Imprimir resultados
        self._print_results(total_time)
        
        # Salvar relatório
        self._save_report(total_time)
    
    def _calculate_metrics(self):
        """Calcula métricas agregadas incluindo variabilidade."""
        self.metrics.success = sum(1 for r in self.results if r.success)
        self.metrics.failed = sum(1 for r in self.results if not r.success and "Timeout" not in r.error)
        self.metrics.timeout = sum(1 for r in self.results if "Timeout" in r.error)
        
        successful = [r for r in self.results if r.success]
        
        if successful:
            times = [r.total_time_ms for r in successful]
            self.metrics.avg_time_total_ms = statistics.mean(times)
            self.metrics.stddev_time_total_ms = statistics.stdev(times) if len(times) > 1 else 0
            
            # Tempos por etapa
            probe_times = []
            analysis_times = []
            main_page_times = []
            link_selection_times = []
            subpage_times = []
            
            for r in successful:
                for step in r.steps:
                    if step.step_number == 2:
                        probe_times.append(step.duration_ms)
                    elif step.step_number == 3:
                        analysis_times.append(step.duration_ms)
                    elif step.step_number == 5:
                        main_page_times.append(step.duration_ms)
                    elif step.step_number == 6:
                        link_selection_times.append(step.duration_ms)
                    elif step.step_number == 7:
                        subpage_times.append(step.duration_ms)
            
            if probe_times:
                self.metrics.avg_time_probe_ms = statistics.mean(probe_times)
            if analysis_times:
                self.metrics.avg_time_analysis_ms = statistics.mean(analysis_times)
            if main_page_times:
                self.metrics.avg_time_main_page_ms = statistics.mean(main_page_times)
            if link_selection_times:
                self.metrics.avg_time_link_selection_ms = statistics.mean(link_selection_times)
            if subpage_times:
                self.metrics.avg_time_subpages_ms = statistics.mean(subpage_times)
            
            # Métricas de conteúdo
            self.metrics.avg_content_length = statistics.mean([r.content_length for r in successful])
            self.metrics.avg_pages_per_site = statistics.mean([r.pages_scraped for r in successful])
            self.metrics.avg_links_per_site = statistics.mean([r.links_found for r in successful])
        
        # Distribuição por tipo de site
        for r in self.results:
            if r.site_type == "static":
                self.metrics.sites_static += 1
            elif r.site_type == "spa":
                self.metrics.sites_spa += 1
            elif r.site_type == "hybrid":
                self.metrics.sites_hybrid += 1
            else:
                self.metrics.sites_unknown += 1
        
        # Distribuição por proteção
        for r in self.results:
            if r.protection_type == "none":
                self.metrics.protection_none += 1
            elif r.protection_type == "cloudflare":
                self.metrics.protection_cloudflare += 1
            elif r.protection_type == "waf":
                self.metrics.protection_waf += 1
            elif r.protection_type == "captcha":
                self.metrics.protection_captcha += 1
            elif r.protection_type == "rate_limit":
                self.metrics.protection_rate_limit += 1
            elif r.protection_type == "bot_detection":
                self.metrics.protection_bot_detection += 1
        
        # Distribuição por estratégia
        for r in self.results:
            if r.strategy_used == "fast":
                self.metrics.strategy_fast += 1
            elif r.strategy_used == "standard":
                self.metrics.strategy_standard += 1
            elif r.strategy_used == "robust":
                self.metrics.strategy_robust += 1
            elif r.strategy_used == "aggressive":
                self.metrics.strategy_aggressive += 1
        
        # NOVAS: Métricas de proxy agregadas
        self.metrics.total_proxies_used = len(self.all_proxy_latencies)
        self.metrics.unique_proxies_used = len(self.all_proxies_used)
        if self.all_proxy_latencies:
            self.metrics.avg_proxy_latency_ms = statistics.mean(self.all_proxy_latencies)
            self.metrics.stddev_proxy_latency_ms = statistics.stdev(self.all_proxy_latencies) if len(self.all_proxy_latencies) > 1 else 0
        self.metrics.proxy_failure_rate = self.proxy_failures_count / max(1, self.metrics.total_proxies_used) * 100
        
        # NOVAS: Métricas de LLM agregadas
        self.metrics.total_llm_calls = sum(r.llm_calls for r in self.results)
        if self.llm_call_times:
            self.metrics.avg_llm_time_ms = statistics.mean(self.llm_call_times)
        
        # NOVAS: Métricas de retry
        self.metrics.total_retries = sum(r.total_retries for r in self.results)
        self.metrics.sites_with_retries = sum(1 for r in self.results if r.total_retries > 0)
        
        # NOVAS: Rate limiting
        self.metrics.sites_rate_limited = sum(1 for r in self.results if r.rate_limit_detected)
        
        # NOVAS: Circuit breaker
        self.metrics.circuit_breaker_triggers = len(self.environment.circuit_breaker_state.domains_opened_during_test)
    
    def _print_results(self, total_time: float):
        """Imprime resultados do teste com análise de variabilidade."""
        print()
        print("=" * 80)
        print("RESULTADOS - TESTE DE SCRAPING ULTRA DETALHADO v2.0")
        print("=" * 80)
        
        taxa_sucesso = self.metrics.success / self.metrics.total * 100 if self.metrics.total > 0 else 0
        
        print(f"\n📊 RESUMO GERAL:")
        print(f"   Total URLs: {self.metrics.total}")
        print(f"   Sucesso: {self.metrics.success} ({taxa_sucesso:.1f}%)")
        print(f"   Falhas: {self.metrics.failed}")
        print(f"   Timeout: {self.metrics.timeout}")
        print(f"   Tempo total do teste: {total_time:.1f}s")
        
        print(f"\n⏱️ TEMPOS MÉDIOS POR ETAPA:")
        print(f"   Total: {self.metrics.avg_time_total_ms:.0f}ms (±{self.metrics.stddev_time_total_ms:.0f}ms)")
        print(f"   ├─ Probe URL: {self.metrics.avg_time_probe_ms:.0f}ms")
        print(f"   ├─ Análise: {self.metrics.avg_time_analysis_ms:.0f}ms")
        print(f"   ├─ Main Page: {self.metrics.avg_time_main_page_ms:.0f}ms")
        print(f"   ├─ Seleção Links: {self.metrics.avg_time_link_selection_ms:.0f}ms")
        print(f"   └─ Subpáginas: {self.metrics.avg_time_subpages_ms:.0f}ms")
        
        # NOVA SEÇÃO: Análise de Variabilidade
        print(f"\n📈 ANÁLISE DE VARIABILIDADE:")
        print(f"   Desvio padrão do tempo total: {self.metrics.stddev_time_total_ms:.0f}ms")
        cv = (self.metrics.stddev_time_total_ms / self.metrics.avg_time_total_ms * 100) if self.metrics.avg_time_total_ms > 0 else 0
        print(f"   Coeficiente de variação: {cv:.1f}%")
        if cv > 50:
            print(f"   ⚠️ ALTA VARIABILIDADE - Resultados inconsistentes!")
        elif cv > 25:
            print(f"   ⚠️ VARIABILIDADE MODERADA")
        else:
            print(f"   ✅ VARIABILIDADE BAIXA - Resultados consistentes")
        
        # NOVA SEÇÃO: Métricas de Proxy
        print(f"\n🔌 MÉTRICAS DE PROXY:")
        print(f"   Total de requests via proxy: {self.metrics.total_proxies_used}")
        print(f"   Proxies únicos usados: {self.metrics.unique_proxies_used}")
        print(f"   Latência média: {self.metrics.avg_proxy_latency_ms:.0f}ms (±{self.metrics.stddev_proxy_latency_ms:.0f}ms)")
        print(f"   Taxa de falha de proxy: {self.metrics.proxy_failure_rate:.1f}%")
        if self.metrics.proxy_failure_rate > 10:
            print(f"   ⚠️ ALTA TAXA DE FALHA DE PROXY - Considere trocar provider")
        
        # NOVA SEÇÃO: Métricas de LLM
        print(f"\n🤖 MÉTRICAS DE LLM:")
        print(f"   Total de chamadas: {self.metrics.total_llm_calls}")
        print(f"   Tempo médio por chamada: {self.metrics.avg_llm_time_ms:.0f}ms")
        
        # NOVA SEÇÃO: Retries e Rate Limiting
        print(f"\n🔄 RETRIES E RATE LIMITING:")
        print(f"   Total de retries: {self.metrics.total_retries}")
        print(f"   Sites com retries: {self.metrics.sites_with_retries}")
        print(f"   Sites com rate limit detectado: {self.metrics.sites_rate_limited}")
        
        # NOVA SEÇÃO: Circuit Breaker
        print(f"\n🔌 CIRCUIT BREAKER:")
        print(f"   Domínios bloqueados no início: {len(self.environment.circuit_breaker_state.initial_open_domains)}")
        print(f"   Domínios bloqueados durante teste: {self.metrics.circuit_breaker_triggers}")
        if self.environment.circuit_breaker_state.domains_opened_during_test:
            print(f"   Domínios que falharam:")
            for domain in self.environment.circuit_breaker_state.domains_opened_during_test:
                print(f"      - {domain}")
        
        # Tipos de site e proteção
        print(f"\n🌐 TIPOS DE SITE:")
        print(f"   Static: {self.metrics.sites_static} | SPA: {self.metrics.sites_spa} | Hybrid: {self.metrics.sites_hybrid}")
        
        print(f"\n🛡️ PROTEÇÕES DETECTADAS:")
        print(f"   Nenhuma: {self.metrics.protection_none} | Cloudflare: {self.metrics.protection_cloudflare}")
        print(f"   WAF: {self.metrics.protection_waf} | Captcha: {self.metrics.protection_captcha}")
        
        # Análise de gargalos
        print(f"\n🔍 ANÁLISE DE GARGALOS:")
        etapas = [
            ("Probe URL", self.metrics.avg_time_probe_ms),
            ("Análise", self.metrics.avg_time_analysis_ms),
            ("Main Page", self.metrics.avg_time_main_page_ms),
            ("Seleção Links", self.metrics.avg_time_link_selection_ms),
            ("Subpáginas", self.metrics.avg_time_subpages_ms),
        ]
        total_etapas = sum(t for _, t in etapas)
        
        for nome, tempo in sorted(etapas, key=lambda x: -x[1]):
            pct = tempo / total_etapas * 100 if total_etapas > 0 else 0
            bar = "█" * int(pct / 5)
            print(f"   {nome:15}: {tempo:6.0f}ms ({pct:5.1f}%) {bar}")
        
        # Top 5 mais lentos
        print(f"\n🐢 TOP 5 MAIS LENTOS:")
        sorted_by_time = sorted(self.results, key=lambda x: -x.total_time_ms)[:5]
        for r in sorted_by_time:
            status = "✅" if r.success else "❌"
            print(f"   {status} {r.url[:60]:60} | {r.total_time_ms:>8.0f}ms | proxies:{len(r.proxies_used)}")
        
        # NOVA: Identificar causas de variabilidade
        print(f"\n🔬 DIAGNÓSTICO DE INCONSISTÊNCIA:")
        
        issues = []
        if self.metrics.proxy_failure_rate > 10:
            issues.append(f"• Alta taxa de falha de proxy ({self.metrics.proxy_failure_rate:.1f}%)")
        if self.metrics.stddev_proxy_latency_ms > 500:
            issues.append(f"• Alta variação de latência de proxy (±{self.metrics.stddev_proxy_latency_ms:.0f}ms)")
        if self.metrics.circuit_breaker_triggers > 0:
            issues.append(f"• Circuit breaker acionado {self.metrics.circuit_breaker_triggers}x")
        if self.metrics.sites_rate_limited > 0:
            issues.append(f"• Rate limiting detectado em {self.metrics.sites_rate_limited} sites")
        if self.metrics.total_retries > self.metrics.total * 0.5:
            issues.append(f"• Muitos retries ({self.metrics.total_retries})")
        if self.environment.initial_network_latency_ms > 200:
            issues.append(f"• Latência de rede alta ({self.environment.initial_network_latency_ms:.0f}ms)")
        
        if issues:
            print("   Possíveis causas de variabilidade:")
            for issue in issues:
                print(f"   {issue}")
        else:
            print("   ✅ Nenhum problema significativo detectado")
        
        # Erros mais comuns
        errors = {}
        for r in self.results:
            if r.error:
                error_key = f"{r.error_step}: {r.error[:50]}"
                errors[error_key] = errors.get(error_key, 0) + 1
        
        if errors:
            print(f"\n❌ ERROS MAIS COMUNS:")
            for error, count in sorted(errors.items(), key=lambda x: -x[1])[:10]:
                print(f"   {count}x - {error}")
        
        print("=" * 80)
    
    def _save_report(self, total_time: float):
        """Salva relatório ultra detalhado em JSON."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"tests/reports/scraper_test_{timestamp}.json"
        
        report = {
            "timestamp": timestamp,
            "version": "2.0",
            "config": {
                "max_concurrent": self.max_concurrent,
                "timeout": self.timeout,
                "max_subpages": self.max_subpages,
                "total_urls": self.metrics.total,
                "discovery_report": self.discovery_report
            },
            "environment": {
                "timestamp": self.environment.timestamp,
                "python_version": self.environment.python_version,
                "platform": self.environment.platform,
                "proxy_pool_size": self.environment.proxy_pool_size,
                "initial_network_latency_ms": self.environment.initial_network_latency_ms,
                "circuit_breaker": {
                    "initial_open_domains": self.environment.circuit_breaker_state.initial_open_domains,
                    "final_open_domains": self.environment.circuit_breaker_state.final_open_domains,
                    "domains_opened_during_test": self.environment.circuit_breaker_state.domains_opened_during_test
                }
            },
            "metrics": {
                "total": self.metrics.total,
                "success": self.metrics.success,
                "failed": self.metrics.failed,
                "timeout": self.metrics.timeout,
                "taxa_sucesso": self.metrics.success / self.metrics.total * 100 if self.metrics.total > 0 else 0,
                "tempo_total_teste_s": total_time,
                "tempos_medios_ms": {
                    "total": self.metrics.avg_time_total_ms,
                    "total_stddev": self.metrics.stddev_time_total_ms,
                    "probe": self.metrics.avg_time_probe_ms,
                    "analise": self.metrics.avg_time_analysis_ms,
                    "main_page": self.metrics.avg_time_main_page_ms,
                    "selecao_links": self.metrics.avg_time_link_selection_ms,
                    "subpages": self.metrics.avg_time_subpages_ms
                },
                "proxy_metrics": {
                    "total_requests": self.metrics.total_proxies_used,
                    "unique_proxies": self.metrics.unique_proxies_used,
                    "avg_latency_ms": self.metrics.avg_proxy_latency_ms,
                    "stddev_latency_ms": self.metrics.stddev_proxy_latency_ms,
                    "failure_rate_pct": self.metrics.proxy_failure_rate
                },
                "llm_metrics": {
                    "total_calls": self.metrics.total_llm_calls,
                    "avg_time_ms": self.metrics.avg_llm_time_ms
                },
                "retry_metrics": {
                    "total_retries": self.metrics.total_retries,
                    "sites_with_retries": self.metrics.sites_with_retries
                },
                "rate_limiting": {
                    "sites_rate_limited": self.metrics.sites_rate_limited
                },
                "circuit_breaker": {
                    "triggers": self.metrics.circuit_breaker_triggers
                },
                "distribuicao_tipo_site": {
                    "static": self.metrics.sites_static,
                    "spa": self.metrics.sites_spa,
                    "hybrid": self.metrics.sites_hybrid,
                    "unknown": self.metrics.sites_unknown
                },
                "distribuicao_protecao": {
                    "none": self.metrics.protection_none,
                    "cloudflare": self.metrics.protection_cloudflare,
                    "waf": self.metrics.protection_waf,
                    "captcha": self.metrics.protection_captcha,
                    "rate_limit": self.metrics.protection_rate_limit,
                    "bot_detection": self.metrics.protection_bot_detection
                },
                "distribuicao_estrategia": {
                    "fast": self.metrics.strategy_fast,
                    "standard": self.metrics.strategy_standard,
                    "robust": self.metrics.strategy_robust,
                    "aggressive": self.metrics.strategy_aggressive
                },
                "metricas_conteudo": {
                    "avg_content_length": self.metrics.avg_content_length,
                    "avg_pages_per_site": self.metrics.avg_pages_per_site,
                    "avg_links_per_site": self.metrics.avg_links_per_site
                }
            },
            "results": [r.to_dict() for r in self.results]
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📄 Relatório salvo em: {report_file}")


# ============================================================================
# FUNÇÕES DE EXECUÇÃO
# ============================================================================

async def run_scraper_test(
    n: int = 50,
    concurrent: int = 10,
    timeout: float = 120.0,
    max_subpages: int = 30,
    discovery_report: str = None,
    # Novos parâmetros de calibração
    chunk_size: int = 10,
    fast_internal: int = 6,
    domain_limit: int = 2,
    proxy_latency: int = 200,
    slow_cap: int = 3,
    slow_timeout: int = 8,
    fast_timeout: int = 15,
    probe_threshold: int = 8000,
    main_threshold: int = 12000
):
    """Executa teste de scraping."""
    # Resetar circuit breaker antes do teste
    from app.services.scraper import reset_circuit_breaker
    from app.services.scraper.constants import scraper_config
    
    # Aplicar configurações de calibração
    scraper_config.update(
        chunk_size=chunk_size,
        fast_chunk_internal_limit=fast_internal,
        per_domain_limit=domain_limit,
        proxy_max_latency_ms=proxy_latency,
        slow_subpage_cap=slow_cap,
        slow_per_request_timeout=slow_timeout,
        fast_per_request_timeout=fast_timeout,
        slow_probe_threshold_ms=probe_threshold,
        slow_main_threshold_ms=main_threshold
    )
    
    reset_circuit_breaker()
    logger.info(f"🔄 Config: chunk={chunk_size} fast={fast_internal} dom={domain_limit} lat={proxy_latency} cap={slow_cap} to_slow={slow_timeout} to_fast={fast_timeout} th_probe={probe_threshold} th_main={main_threshold}")
    
    test = ScraperDetailedTest(
        discovery_report=discovery_report,
        max_concurrent=concurrent,
        timeout_per_url=timeout,
        max_subpages=max_subpages
    )
    await test.run_test(limit=n)
    return test.metrics


if __name__ == "__main__":
    print("=" * 80)
    print("TESTE ULTRA DETALHADO DE SCRAPING v2.0")
    print("=" * 80)
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("n", type=int, nargs="?", default=30)
    parser.add_argument("concurrent", type=int, nargs="?", default=15)
    parser.add_argument("timeout", type=float, nargs="?", default=120.0)
    parser.add_argument("max_subpages", type=int, nargs="?", default=20)
    # Parametros extras
    parser.add_argument("--chunk", type=int, default=10)
    parser.add_argument("--fast", type=int, default=6)
    parser.add_argument("--domain", type=int, default=2)
    parser.add_argument("--lat", type=int, default=200)
    parser.add_argument("--cap", type=int, default=3)
    parser.add_argument("--slow_to", type=int, default=8)
    parser.add_argument("--fast_to", type=int, default=15)
    parser.add_argument("--probe_th", type=int, default=8000)
    parser.add_argument("--main_th", type=int, default=12000)
    
    parser.add_argument("--hybrid", action="store_true", help="Executa modo híbrido (Fast + Retry)")
    
    args = parser.parse_args()
    
    print(f"Parâmetros base: n={args.n} c={args.concurrent} t={args.timeout} sub={args.max_subpages}")
    
    # Modo Híbrido (Fast Path + Retry Path)
    if hasattr(args, 'hybrid') and args.hybrid:
        print("🚀 MODO HÍBRIDO ATIVADO: Fast Track + Retry Track")
        from app.services.scraper.constants import scraper_config, FAST_TRACK_CONFIG, RETRY_TRACK_CONFIG
        
        # 1. Fast Track (Usando Config R7/SpeedCombo2 do constants)
        print("\n--- ⚡ FAST TRACK (Otimizado) ---")
        scraper_config.update(**FAST_TRACK_CONFIG)
        
        # Resetar antes de começar
        from app.services.scraper import reset_circuit_breaker
        reset_circuit_breaker()
        
        fast_metrics = asyncio.run(run_scraper_test(
            n=args.n, 
            concurrent=FAST_TRACK_CONFIG.get('site_semaphore_limit', 60), 
            timeout=FAST_TRACK_CONFIG.get('page_timeout', 35000) / 1000, 
            max_subpages=args.max_subpages
        ))
        
        failed_count = fast_metrics.total - fast_metrics.success
        
        if failed_count > 0:
            print(f"\n--- 🐢 RETRY TRACK ({failed_count} sites) ---")
            # Configuração Robusta para Retry
            scraper_config.update(**RETRY_TRACK_CONFIG)
            
            # Resetar para retry
            reset_circuit_breaker()
            
            # Executar retry (simulado nos próximos N sites pois não temos fila real aqui)
            retry_metrics = asyncio.run(run_scraper_test(
                n=failed_count, 
                concurrent=RETRY_TRACK_CONFIG.get('site_semaphore_limit', 5), 
                timeout=RETRY_TRACK_CONFIG.get('page_timeout', 120000) / 1000, 
                max_subpages=args.max_subpages
            ))
            
            print("\n" + "="*80)
            print("📊 RESULTADO FINAL HÍBRIDO (SIMULADO)")
            print("="*80)
            # Assumindo que a taxa de sucesso do Retry Track se aplicaria aos que falharam
            recovered = retry_metrics.success
            total_success = fast_metrics.success + recovered
            final_rate = (total_success / args.n) * 100
            
            print(f"Sucesso Fast: {fast_metrics.success}/{args.n}")
            print(f"Recuperados : {recovered}/{failed_count}")
            print(f"Sucesso Final: {total_success}/{args.n} ({final_rate:.1f}%)")
        else:
            print("🎉 Sucesso total no Fast Track!")
            
        sys.exit(0)
    
    asyncio.run(run_scraper_test(
        args.n, args.concurrent, args.timeout, args.max_subpages,
        chunk_size=args.chunk,
        fast_internal=args.fast,
        domain_limit=args.domain,
        proxy_latency=args.lat,
        slow_cap=args.cap,
        slow_timeout=args.slow_to,
        fast_timeout=args.fast_to,
        probe_threshold=args.probe_th,
        main_threshold=args.main_th
    ))


