"""
TESTE FINAL DE PRODUÇÃO - STRESS TEST ULTRA DETALHADO v1.0

Este teste executa o fluxo completo do sistema para todas as empresas:
Discovery → Scrape → Profile (LLM)

INDICADORES COLETADOS:
1. GLOBAIS: Taxa de sucesso, tempo total, throughput, distribuições
2. INDIVIDUAIS: Métricas por empresa (cada etapa)
3. SUBETAPAS: Discovery, Scrape, Profile detalhados
4. INFRAESTRUTURA: Proxy, LLM providers, rate limits, circuit breaker

Objetivo: Identificar gargalos finais antes de subir para produção.
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
import statistics
import platform
import psutil
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict
from enum import Enum

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS E CONSTANTES
# ============================================================================

class ProcessingStage(Enum):
    """Estágios do processamento."""
    DISCOVERY = "discovery"
    SCRAPE = "scrape"
    PROFILE = "profile"


class ResultStatus(Enum):
    """Status do resultado."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


# ============================================================================
# DATACLASSES PARA MÉTRICAS ULTRA DETALHADAS
# ============================================================================

@dataclass
class SubStepMetric:
    """Métrica de uma subetapa."""
    name: str
    duration_ms: float = 0.0
    success: bool = True
    error: str = ""
    details: Dict = field(default_factory=dict)


@dataclass
class DiscoveryMetrics:
    """Métricas detalhadas do Discovery."""
    total_time_ms: float = 0.0
    success: bool = False
    site_found: str = ""
    
    # Subetapas
    search_time_ms: float = 0.0
    llm_analysis_time_ms: float = 0.0
    
    # Detalhes
    search_results_count: int = 0
    search_results_filtered: int = 0
    llm_provider_used: str = ""
    llm_retries: int = 0
    
    # Erros
    error: str = ""
    error_stage: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ScrapeMetrics:
    """Métricas detalhadas do Scrape."""
    total_time_ms: float = 0.0
    success: bool = False
    content_length: int = 0
    
    # Subetapas
    probe_time_ms: float = 0.0
    analysis_time_ms: float = 0.0
    main_page_time_ms: float = 0.0
    link_selection_time_ms: float = 0.0
    subpages_time_ms: float = 0.0
    
    # Detalhes
    site_type: str = ""
    protection_type: str = ""
    strategy_used: str = ""
    pages_scraped: int = 0
    links_found: int = 0
    documents_found: int = 0
    
    # Proxy
    proxies_used: List[str] = field(default_factory=list)
    proxy_failures: int = 0
    avg_proxy_latency_ms: float = 0.0
    
    # Retries
    total_retries: int = 0
    rate_limit_detected: bool = False
    
    # Erros
    error: str = ""
    error_stage: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ProfileMetrics:
    """Métricas detalhadas do Profile (LLM)."""
    total_time_ms: float = 0.0
    success: bool = False
    
    # Subetapas
    chunking_time_ms: float = 0.0
    llm_processing_time_ms: float = 0.0
    merge_time_ms: float = 0.0
    
    # Detalhes
    input_tokens_estimated: int = 0
    chunks_created: int = 0
    chunks_processed: int = 0
    providers_used: List[str] = field(default_factory=list)
    
    # Qualidade do Perfil
    company_name_found: bool = False
    products_count: int = 0
    services_count: int = 0
    contacts_found: bool = False
    certifications_count: int = 0
    
    # Completude (campos preenchidos / campos totais)
    completeness_score: float = 0.0
    
    # Erros
    error: str = ""
    error_stage: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CompanyResult:
    """Resultado completo do processamento de uma empresa."""
    # Identificação
    cnpj: str = ""
    razao_social: str = ""
    nome_fantasia: str = ""
    uf: str = ""
    cnae: str = ""
    
    # Resultado geral
    status: str = "pending"  # success, partial, failed, timeout, skipped
    total_time_ms: float = 0.0
    
    # Métricas por etapa
    discovery: DiscoveryMetrics = field(default_factory=DiscoveryMetrics)
    scrape: ScrapeMetrics = field(default_factory=ScrapeMetrics)
    profile: ProfileMetrics = field(default_factory=ProfileMetrics)
    
    # Resultado final
    site_url: str = ""
    profile_data: Dict = field(default_factory=dict)
    
    # Erros gerais
    error: str = ""
    error_stage: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "cnpj": self.cnpj,
            "razao_social": self.razao_social,
            "nome_fantasia": self.nome_fantasia,
            "uf": self.uf,
            "cnae": self.cnae,
            "status": self.status,
            "total_time_ms": self.total_time_ms,
            "site_url": self.site_url,
            "discovery": self.discovery.to_dict(),
            "scrape": self.scrape.to_dict(),
            "profile": self.profile.to_dict(),
            "profile_data": self.profile_data,
            "error": self.error,
            "error_stage": self.error_stage
        }


@dataclass
class GlobalMetrics:
    """Métricas globais agregadas."""
    # Contagens
    total_empresas: int = 0
    success: int = 0
    partial: int = 0
    failed: int = 0
    timeout: int = 0
    skipped: int = 0
    
    # Taxas
    taxa_sucesso: float = 0.0
    taxa_discovery: float = 0.0
    taxa_scrape: float = 0.0
    taxa_profile: float = 0.0
    
    # Tempos
    tempo_total_teste_s: float = 0.0
    throughput_empresas_por_minuto: float = 0.0
    
    # Tempos médios (ms)
    avg_total_time_ms: float = 0.0
    stddev_total_time_ms: float = 0.0
    avg_discovery_time_ms: float = 0.0
    avg_scrape_time_ms: float = 0.0
    avg_profile_time_ms: float = 0.0
    
    # Percentis
    p50_time_ms: float = 0.0
    p90_time_ms: float = 0.0
    p95_time_ms: float = 0.0
    p99_time_ms: float = 0.0
    
    # Discovery
    sites_encontrados: int = 0
    discovery_llm_retries: int = 0
    
    # Scrape
    avg_content_length: float = 0.0
    avg_pages_per_site: float = 0.0
    total_proxies_used: int = 0
    unique_proxies: int = 0
    proxy_failure_rate: float = 0.0
    sites_with_protection: int = 0
    sites_rate_limited: int = 0
    
    # Profile
    avg_completeness_score: float = 0.0
    avg_chunks_per_site: float = 0.0
    total_llm_calls: int = 0
    
    # Distribuições
    dist_status: Dict[str, int] = field(default_factory=dict)
    dist_site_type: Dict[str, int] = field(default_factory=dict)
    dist_protection: Dict[str, int] = field(default_factory=dict)
    dist_strategy: Dict[str, int] = field(default_factory=dict)
    dist_uf: Dict[str, int] = field(default_factory=dict)
    dist_llm_provider: Dict[str, int] = field(default_factory=dict)
    
    # Erros
    top_errors: Dict[str, int] = field(default_factory=dict)
    errors_by_stage: Dict[str, int] = field(default_factory=dict)


@dataclass
class SystemMetrics:
    """Métricas do sistema durante o teste."""
    timestamp_start: str = ""
    timestamp_end: str = ""
    python_version: str = ""
    platform_info: str = ""
    
    # Recursos
    cpu_count: int = 0
    memory_total_gb: float = 0.0
    memory_used_start_gb: float = 0.0
    memory_used_end_gb: float = 0.0
    memory_peak_gb: float = 0.0
    
    # Rede
    initial_network_latency_ms: float = 0.0
    
    # Configurações
    max_concurrent: int = 0
    timeout_per_empresa: float = 0.0
    
    # Circuit Breaker
    circuit_breaker_initial_open: List[str] = field(default_factory=list)
    circuit_breaker_final_open: List[str] = field(default_factory=list)
    circuit_breaker_triggered: int = 0


# ============================================================================
# CLASSE PRINCIPAL DO TESTE
# ============================================================================

class FinalProductionTest:
    """Teste final de produção ultra detalhado."""
    
    def __init__(
        self,
        max_concurrent: int = 50,
        timeout_per_empresa: float = 120.0,
        max_subpages: int = 30
    ):
        self.max_concurrent = max_concurrent
        self.timeout = timeout_per_empresa
        self.max_subpages = max_subpages
        
        self.results: List[CompanyResult] = []
        self.global_metrics = GlobalMetrics()
        self.system_metrics = SystemMetrics()
        
        # Tracking
        self.all_proxies: Set[str] = set()
        self.proxy_failures: int = 0
        self.llm_providers_used: Dict[str, int] = defaultdict(int)
        
        # Progress
        self.processed_count = 0
        self.success_count = 0
        self.failed_count = 0
        self.start_time = 0
    
    def load_empresas(self, limit: int = None) -> List[Dict]:
        """Carrega empresas do arquivo JSON."""
        data_file = Path(__file__).parent.parent / "data_empresas.json"
        
        with open(data_file, 'r', encoding='utf-8') as f:
            empresas = json.load(f)
        
        if limit:
            empresas = empresas[:limit]
        
        logger.info(f"📂 Carregadas {len(empresas)} empresas de {data_file.name}")
        return empresas
    
    async def collect_system_metrics_start(self):
        """Coleta métricas do sistema no início."""
        self.system_metrics.timestamp_start = datetime.now().isoformat()
        self.system_metrics.python_version = sys.version
        self.system_metrics.platform_info = platform.platform()
        self.system_metrics.cpu_count = psutil.cpu_count()
        self.system_metrics.memory_total_gb = psutil.virtual_memory().total / (1024**3)
        self.system_metrics.memory_used_start_gb = psutil.virtual_memory().used / (1024**3)
        self.system_metrics.max_concurrent = self.max_concurrent
        self.system_metrics.timeout_per_empresa = self.timeout
        
        # Medir latência de rede
        try:
            start = time.perf_counter()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection('www.google.com', 443),
                timeout=5.0
            )
            writer.close()
            await writer.wait_closed()
            self.system_metrics.initial_network_latency_ms = (time.perf_counter() - start) * 1000
        except:
            self.system_metrics.initial_network_latency_ms = -1
        
        # Circuit breaker
        try:
            from app.services.scraper.circuit_breaker import _domain_failures
            from app.services.scraper.constants import scraper_config
            threshold = scraper_config.circuit_breaker_threshold
            self.system_metrics.circuit_breaker_initial_open = [
                d for d, f in _domain_failures.items() if f >= threshold
            ]
        except:
            pass
        
        logger.info(f"💻 Sistema: {self.system_metrics.platform_info}")
        logger.info(f"💻 CPUs: {self.system_metrics.cpu_count} | RAM: {self.system_metrics.memory_total_gb:.1f}GB")
        logger.info(f"🌐 Latência de rede: {self.system_metrics.initial_network_latency_ms:.0f}ms")
    
    async def collect_system_metrics_end(self):
        """Coleta métricas do sistema no final."""
        self.system_metrics.timestamp_end = datetime.now().isoformat()
        self.system_metrics.memory_used_end_gb = psutil.virtual_memory().used / (1024**3)
        
        # Circuit breaker final
        try:
            from app.services.scraper.circuit_breaker import _domain_failures
            from app.services.scraper.constants import scraper_config
            threshold = scraper_config.circuit_breaker_threshold
            self.system_metrics.circuit_breaker_final_open = [
                d for d, f in _domain_failures.items() if f >= threshold
            ]
            self.system_metrics.circuit_breaker_triggered = len(
                set(self.system_metrics.circuit_breaker_final_open) - 
                set(self.system_metrics.circuit_breaker_initial_open)
            )
        except:
            pass
    
    async def process_empresa(
        self, 
        empresa: Dict, 
        idx: int,
        semaphore: asyncio.Semaphore
    ) -> CompanyResult:
        """
        Processa uma empresa completa: Discovery → Scrape → Profile.
        """
        async with semaphore:
            result = CompanyResult(
                cnpj=f"{empresa.get('cnpj_basico', '')}{empresa.get('cnpj_ordem', '')}{empresa.get('cnpj_dv', '')}",
                razao_social=empresa.get('razao_social', ''),
                nome_fantasia=empresa.get('nome_fantasia', ''),
                uf=empresa.get('uf', ''),
                cnae=empresa.get('cnae_fiscal', '')
            )
            
            overall_start = time.perf_counter()
            
            try:
                # ============================================================
                # ETAPA 1: DISCOVERY
                # ============================================================
                discovery_result = await self._run_discovery(empresa, result)
                
                if not discovery_result.success or not discovery_result.site_found:
                    result.status = "skipped"
                    result.error = "Site não encontrado"
                    result.error_stage = "discovery"
                    result.total_time_ms = (time.perf_counter() - overall_start) * 1000
                    self._update_progress(result)
                    return result
                
                result.site_url = discovery_result.site_found
                
                # ============================================================
                # ETAPA 2: SCRAPE
                # ============================================================
                scrape_result = await self._run_scrape(result.site_url, result)
                
                if not scrape_result.success or scrape_result.content_length < 500:
                    result.status = "failed"
                    result.error = scrape_result.error or "Conteúdo insuficiente"
                    result.error_stage = "scrape"
                    result.total_time_ms = (time.perf_counter() - overall_start) * 1000
                    self._update_progress(result)
                    return result
                
                # ============================================================
                # ETAPA 3: PROFILE (LLM)
                # ============================================================
                profile_result = await self._run_profile(scrape_result, result)
                
                if not profile_result.success:
                    result.status = "partial" if result.discovery.success else "failed"
                    result.error = profile_result.error or "Falha no LLM"
                    result.error_stage = "profile"
                else:
                    result.status = "success"
                
                result.total_time_ms = (time.perf_counter() - overall_start) * 1000
                self._update_progress(result)
                return result
                
            except asyncio.TimeoutError:
                result.status = "timeout"
                result.error = f"Timeout global ({self.timeout}s)"
                result.total_time_ms = self.timeout * 1000
                self._update_progress(result)
                return result
                
            except Exception as e:
                result.status = "failed"
                result.error = str(e)
                result.error_stage = "exception"
                result.total_time_ms = (time.perf_counter() - overall_start) * 1000
                logger.error(f"[{idx}] ❌ Exceção: {e}")
                self._update_progress(result)
                return result
    
    async def _run_discovery(
        self, 
        empresa: Dict, 
        result: CompanyResult
    ) -> DiscoveryMetrics:
        """Executa etapa de Discovery."""
        from app.services.discovery.discovery_service import find_company_website
        
        metrics = DiscoveryMetrics()
        start = time.perf_counter()
        
        try:
            # Preparar dados
            razao = empresa.get('razao_social', '')
            fantasia = empresa.get('nome_fantasia', '')
            cnpj_full = f"{empresa.get('cnpj_basico', '')}{empresa.get('cnpj_ordem', '')}{empresa.get('cnpj_dv', '')}"
            
            # Executar discovery com timeout
            discovery_start = time.perf_counter()
            site = await asyncio.wait_for(
                find_company_website(
                    razao_social=razao,
                    nome_fantasia=fantasia,
                    cnpj=cnpj_full,
                    municipio=empresa.get('municipio', None)
                ),
                timeout=60.0
            )
            
            metrics.total_time_ms = (time.perf_counter() - start) * 1000
            
            if site:
                metrics.success = True
                metrics.site_found = site
            else:
                metrics.success = False
                metrics.error = "Nenhum site encontrado"
                
        except asyncio.TimeoutError:
            metrics.total_time_ms = 60000
            metrics.error = "Timeout (60s)"
            metrics.error_stage = "discovery_timeout"
            
        except Exception as e:
            metrics.total_time_ms = (time.perf_counter() - start) * 1000
            metrics.error = str(e)
            metrics.error_stage = "discovery_exception"
        
        result.discovery = metrics
        return metrics
    
    async def _run_scrape(
        self, 
        url: str, 
        result: CompanyResult
    ) -> ScrapeMetrics:
        """Executa etapa de Scrape."""
        from app.services.scraper.scraper_service import scrape_url
        
        metrics = ScrapeMetrics()
        start = time.perf_counter()
        
        try:
            # Executar scrape com timeout
            content, docs, visited = await asyncio.wait_for(
                scrape_url(url, max_subpages=self.max_subpages),
                timeout=90.0
            )
            
            metrics.total_time_ms = (time.perf_counter() - start) * 1000
            
            if content and len(content) >= 500:
                metrics.success = True
                metrics.content_length = len(content)
                metrics.pages_scraped = len(visited) if visited else 1
                metrics.documents_found = len(docs) if docs else 0
                
                # Guardar conteúdo para profile
                metrics._content = content
            else:
                metrics.success = False
                metrics.content_length = len(content) if content else 0
                metrics.error = "Conteúdo insuficiente"
                
        except asyncio.TimeoutError:
            metrics.total_time_ms = 90000
            metrics.error = "Timeout (90s)"
            metrics.error_stage = "scrape_timeout"
            
        except Exception as e:
            metrics.total_time_ms = (time.perf_counter() - start) * 1000
            metrics.error = str(e)
            metrics.error_stage = "scrape_exception"
        
        result.scrape = metrics
        return metrics
    
    async def _run_profile(
        self, 
        scrape_metrics: ScrapeMetrics, 
        result: CompanyResult
    ) -> ProfileMetrics:
        """Executa etapa de Profile (LLM)."""
        from app.services.llm.llm_service import get_llm_service
        from app.services.llm.content_chunker import estimate_tokens
        
        metrics = ProfileMetrics()
        start = time.perf_counter()
        
        try:
            content = getattr(scrape_metrics, '_content', '')
            if not content:
                metrics.error = "Sem conteúdo para analisar"
                result.profile = metrics
                return metrics
            
            # Estimar tokens
            metrics.input_tokens_estimated = estimate_tokens(content)
            
            # Executar análise com timeout
            llm_service = get_llm_service()
            
            profile = await asyncio.wait_for(
                llm_service.analyze(content),
                timeout=120.0
            )
            
            metrics.total_time_ms = (time.perf_counter() - start) * 1000
            
            if profile:
                metrics.success = True
                
                # Calcular métricas de qualidade
                if profile.identity and profile.identity.company_name:
                    metrics.company_name_found = True
                
                if profile.offerings:
                    metrics.products_count = len(profile.offerings.products or [])
                    metrics.services_count = len(profile.offerings.services or [])
                
                if profile.contact:
                    has_email = bool(profile.contact.emails)
                    has_phone = bool(profile.contact.phones)
                    metrics.contacts_found = has_email or has_phone
                
                if profile.reputation:
                    metrics.certifications_count = len(profile.reputation.certifications or [])
                
                # Calcular completude
                metrics.completeness_score = self._calculate_completeness(profile)
                
                # Guardar dados do perfil
                result.profile_data = profile.model_dump() if hasattr(profile, 'model_dump') else {}
            else:
                metrics.error = "Perfil vazio"
                
        except asyncio.TimeoutError:
            metrics.total_time_ms = 120000
            metrics.error = "Timeout (120s)"
            metrics.error_stage = "profile_timeout"
            
        except Exception as e:
            metrics.total_time_ms = (time.perf_counter() - start) * 1000
            metrics.error = str(e)
            metrics.error_stage = "profile_exception"
        
        result.profile = metrics
        return metrics
    
    def _calculate_completeness(self, profile) -> float:
        """Calcula score de completude do perfil (0-100)."""
        total_fields = 0
        filled_fields = 0
        
        # Identity (peso maior)
        identity_fields = ['company_name', 'description', 'tagline']
        for field in identity_fields:
            total_fields += 2  # Peso 2
            if profile.identity and getattr(profile.identity, field, None):
                filled_fields += 2
        
        # Classification
        class_fields = ['industry', 'business_model', 'target_audience']
        for field in class_fields:
            total_fields += 1
            if profile.classification and getattr(profile.classification, field, None):
                filled_fields += 1
        
        # Offerings (peso maior)
        total_fields += 3
        if profile.offerings:
            if profile.offerings.products and len(profile.offerings.products) > 0:
                filled_fields += 1.5
            if profile.offerings.services and len(profile.offerings.services) > 0:
                filled_fields += 1.5
        
        # Reputation
        total_fields += 2
        if profile.reputation:
            if profile.reputation.certifications:
                filled_fields += 1
            if profile.reputation.partnerships:
                filled_fields += 1
        
        # Contact
        total_fields += 2
        if profile.contact:
            if profile.contact.emails:
                filled_fields += 1
            if profile.contact.phones:
                filled_fields += 1
        
        return (filled_fields / total_fields) * 100 if total_fields > 0 else 0
    
    def _update_progress(self, result: CompanyResult):
        """Atualiza contadores de progresso."""
        self.processed_count += 1
        
        if result.status == "success":
            self.success_count += 1
            icon = "✅"
        elif result.status == "partial":
            icon = "⚠️"
        elif result.status == "skipped":
            icon = "⏭️"
        elif result.status == "timeout":
            icon = "⏱️"
        else:
            self.failed_count += 1
            icon = "❌"
        
        # Log de progresso a cada 10 empresas ou em eventos importantes
        if self.processed_count % 10 == 0 or result.status in ["success", "timeout"]:
            elapsed = time.perf_counter() - self.start_time
            rate = self.processed_count / elapsed if elapsed > 0 else 0
            
            logger.info(
                f"[{self.processed_count:4d}] {icon} {result.nome_fantasia[:30]:30} | "
                f"{result.status:8} | {result.total_time_ms:>7.0f}ms | "
                f"Taxa: {rate:.1f}/s | ✅{self.success_count} ❌{self.failed_count}"
            )
    
    def _calculate_global_metrics(self, total_time: float):
        """Calcula métricas globais agregadas."""
        m = self.global_metrics
        
        m.total_empresas = len(self.results)
        m.tempo_total_teste_s = total_time
        m.throughput_empresas_por_minuto = (m.total_empresas / total_time) * 60 if total_time > 0 else 0
        
        # Contagens por status
        m.success = sum(1 for r in self.results if r.status == "success")
        m.partial = sum(1 for r in self.results if r.status == "partial")
        m.failed = sum(1 for r in self.results if r.status == "failed")
        m.timeout = sum(1 for r in self.results if r.status == "timeout")
        m.skipped = sum(1 for r in self.results if r.status == "skipped")
        
        # Taxas
        total_processados = m.total_empresas - m.skipped
        m.taxa_sucesso = (m.success / total_processados * 100) if total_processados > 0 else 0
        m.taxa_discovery = (sum(1 for r in self.results if r.discovery.success) / m.total_empresas * 100) if m.total_empresas > 0 else 0
        m.taxa_scrape = (sum(1 for r in self.results if r.scrape.success) / m.total_empresas * 100) if m.total_empresas > 0 else 0
        m.taxa_profile = (sum(1 for r in self.results if r.profile.success) / m.total_empresas * 100) if m.total_empresas > 0 else 0
        
        # Sites encontrados
        m.sites_encontrados = sum(1 for r in self.results if r.discovery.site_found)
        
        # Tempos
        all_times = [r.total_time_ms for r in self.results if r.status != "skipped"]
        if all_times:
            m.avg_total_time_ms = statistics.mean(all_times)
            m.stddev_total_time_ms = statistics.stdev(all_times) if len(all_times) > 1 else 0
            
            sorted_times = sorted(all_times)
            n = len(sorted_times)
            m.p50_time_ms = sorted_times[int(n * 0.5)]
            m.p90_time_ms = sorted_times[int(n * 0.9)]
            m.p95_time_ms = sorted_times[int(n * 0.95)]
            m.p99_time_ms = sorted_times[int(n * 0.99)] if n > 100 else sorted_times[-1]
        
        # Tempos por etapa
        discovery_times = [r.discovery.total_time_ms for r in self.results if r.discovery.total_time_ms > 0]
        scrape_times = [r.scrape.total_time_ms for r in self.results if r.scrape.total_time_ms > 0]
        profile_times = [r.profile.total_time_ms for r in self.results if r.profile.total_time_ms > 0]
        
        if discovery_times:
            m.avg_discovery_time_ms = statistics.mean(discovery_times)
        if scrape_times:
            m.avg_scrape_time_ms = statistics.mean(scrape_times)
        if profile_times:
            m.avg_profile_time_ms = statistics.mean(profile_times)
        
        # Scrape metrics
        content_lengths = [r.scrape.content_length for r in self.results if r.scrape.success]
        pages = [r.scrape.pages_scraped for r in self.results if r.scrape.success]
        if content_lengths:
            m.avg_content_length = statistics.mean(content_lengths)
        if pages:
            m.avg_pages_per_site = statistics.mean(pages)
        
        # Profile metrics
        completeness = [r.profile.completeness_score for r in self.results if r.profile.success]
        if completeness:
            m.avg_completeness_score = statistics.mean(completeness)
        
        # Distribuições
        m.dist_status = {
            "success": m.success,
            "partial": m.partial,
            "failed": m.failed,
            "timeout": m.timeout,
            "skipped": m.skipped
        }
        
        # Distribuição por UF
        for r in self.results:
            if r.uf:
                m.dist_uf[r.uf] = m.dist_uf.get(r.uf, 0) + 1
        
        # Distribuição por tipo de site
        for r in self.results:
            if r.scrape.site_type:
                m.dist_site_type[r.scrape.site_type] = m.dist_site_type.get(r.scrape.site_type, 0) + 1
        
        # Distribuição por proteção
        for r in self.results:
            if r.scrape.protection_type:
                m.dist_protection[r.scrape.protection_type] = m.dist_protection.get(r.scrape.protection_type, 0) + 1
        
        # Erros
        for r in self.results:
            if r.error:
                error_key = f"{r.error_stage}: {r.error[:50]}"
                m.top_errors[error_key] = m.top_errors.get(error_key, 0) + 1
            if r.error_stage:
                m.errors_by_stage[r.error_stage] = m.errors_by_stage.get(r.error_stage, 0) + 1
    
    def _print_results(self):
        """Imprime resultados formatados."""
        m = self.global_metrics
        s = self.system_metrics
        
        print()
        print("=" * 100)
        print("                    RELATÓRIO FINAL - TESTE DE PRODUÇÃO v1.0")
        print("=" * 100)
        
        print(f"\n📅 Período: {s.timestamp_start} → {s.timestamp_end}")
        print(f"💻 Sistema: {s.platform_info}")
        print(f"🔧 Configuração: {m.total_empresas} empresas | {self.max_concurrent} concurrent | {self.timeout}s timeout")
        
        print(f"\n{'═' * 50}")
        print("📊 MÉTRICAS GLOBAIS")
        print(f"{'═' * 50}")
        
        print(f"\n┌{'─'*48}┐")
        print(f"│ {'RESULTADOS':^46} │")
        print(f"├{'─'*48}┤")
        print(f"│ Total Empresas:     {m.total_empresas:>26} │")
        print(f"│ ✅ Sucesso:         {m.success:>20} ({m.taxa_sucesso:.1f}%) │")
        print(f"│ ⚠️  Parcial:         {m.partial:>26} │")
        print(f"│ ❌ Falha:           {m.failed:>26} │")
        print(f"│ ⏱️  Timeout:         {m.timeout:>26} │")
        print(f"│ ⏭️  Skipped:         {m.skipped:>26} │")
        print(f"└{'─'*48}┘")
        
        print(f"\n┌{'─'*48}┐")
        print(f"│ {'TEMPOS (ms)':^46} │")
        print(f"├{'─'*48}┤")
        print(f"│ Tempo Total Teste:  {m.tempo_total_teste_s:>20.1f}s │")
        print(f"│ Throughput:         {m.throughput_empresas_por_minuto:>18.1f}/min │")
        print(f"│ Média por empresa:  {m.avg_total_time_ms:>22.0f} │")
        print(f"│ Desvio Padrão:      {m.stddev_total_time_ms:>22.0f} │")
        print(f"│ P50:                {m.p50_time_ms:>22.0f} │")
        print(f"│ P90:                {m.p90_time_ms:>22.0f} │")
        print(f"│ P95:                {m.p95_time_ms:>22.0f} │")
        print(f"│ P99:                {m.p99_time_ms:>22.0f} │")
        print(f"└{'─'*48}┘")
        
        print(f"\n┌{'─'*48}┐")
        print(f"│ {'TEMPOS POR ETAPA (ms)':^46} │")
        print(f"├{'─'*48}┤")
        print(f"│ Discovery:          {m.avg_discovery_time_ms:>22.0f} │")
        print(f"│ Scrape:             {m.avg_scrape_time_ms:>22.0f} │")
        print(f"│ Profile:            {m.avg_profile_time_ms:>22.0f} │")
        print(f"└{'─'*48}┘")
        
        print(f"\n┌{'─'*48}┐")
        print(f"│ {'TAXAS POR ETAPA':^46} │")
        print(f"├{'─'*48}┤")
        print(f"│ Discovery:          {m.taxa_discovery:>22.1f}% │")
        print(f"│ Scrape:             {m.taxa_scrape:>22.1f}% │")
        print(f"│ Profile:            {m.taxa_profile:>22.1f}% │")
        print(f"└{'─'*48}┘")
        
        print(f"\n┌{'─'*48}┐")
        print(f"│ {'QUALIDADE DOS PERFIS':^46} │")
        print(f"├{'─'*48}┤")
        print(f"│ Completude Média:   {m.avg_completeness_score:>20.1f}% │")
        print(f"│ Conteúdo Médio:     {m.avg_content_length:>18.0f} chars │")
        print(f"│ Páginas por Site:   {m.avg_pages_per_site:>22.1f} │")
        print(f"└{'─'*48}┘")
        
        # Distribuição por Status
        print(f"\n📈 DISTRIBUIÇÃO POR STATUS:")
        for status, count in sorted(m.dist_status.items(), key=lambda x: -x[1]):
            pct = count / m.total_empresas * 100 if m.total_empresas > 0 else 0
            bar = "█" * int(pct / 2)
            print(f"   {status:12}: {count:>5} ({pct:5.1f}%) {bar}")
        
        # Distribuição por UF (top 10)
        if m.dist_uf:
            print(f"\n🗺️  DISTRIBUIÇÃO POR UF (Top 10):")
            for uf, count in sorted(m.dist_uf.items(), key=lambda x: -x[1])[:10]:
                pct = count / m.total_empresas * 100 if m.total_empresas > 0 else 0
                bar = "█" * int(pct / 2)
                print(f"   {uf:5}: {count:>5} ({pct:5.1f}%) {bar}")
        
        # Distribuição por tipo de site
        if m.dist_site_type:
            print(f"\n🌐 DISTRIBUIÇÃO POR TIPO DE SITE:")
            for site_type, count in sorted(m.dist_site_type.items(), key=lambda x: -x[1]):
                pct = count / m.total_empresas * 100 if m.total_empresas > 0 else 0
                print(f"   {site_type:12}: {count:>5} ({pct:5.1f}%)")
        
        # Distribuição por proteção
        if m.dist_protection:
            print(f"\n🛡️  DISTRIBUIÇÃO POR PROTEÇÃO:")
            for protection, count in sorted(m.dist_protection.items(), key=lambda x: -x[1]):
                pct = count / m.total_empresas * 100 if m.total_empresas > 0 else 0
                print(f"   {protection:15}: {count:>5} ({pct:5.1f}%)")
        
        # Erros
        if m.top_errors:
            print(f"\n❌ PRINCIPAIS ERROS (Top 10):")
            for error, count in sorted(m.top_errors.items(), key=lambda x: -x[1])[:10]:
                print(f"   {count:>4}x │ {error}")
        
        if m.errors_by_stage:
            print(f"\n📍 ERROS POR ESTÁGIO:")
            for stage, count in sorted(m.errors_by_stage.items(), key=lambda x: -x[1]):
                print(f"   {stage:20}: {count:>5}")
        
        # Sistema
        print(f"\n{'═' * 50}")
        print("💻 MÉTRICAS DO SISTEMA")
        print(f"{'═' * 50}")
        print(f"   RAM Início:        {s.memory_used_start_gb:.2f} GB")
        print(f"   RAM Final:         {s.memory_used_end_gb:.2f} GB")
        print(f"   RAM Delta:         {s.memory_used_end_gb - s.memory_used_start_gb:.2f} GB")
        print(f"   Circuit Breakers:  {s.circuit_breaker_triggered} acionados")
        
        # Análise de gargalos
        print(f"\n{'═' * 50}")
        print("🔍 ANÁLISE DE GARGALOS")
        print(f"{'═' * 50}")
        
        total_etapas = m.avg_discovery_time_ms + m.avg_scrape_time_ms + m.avg_profile_time_ms
        if total_etapas > 0:
            etapas = [
                ("Discovery", m.avg_discovery_time_ms),
                ("Scrape", m.avg_scrape_time_ms),
                ("Profile", m.avg_profile_time_ms),
            ]
            for nome, tempo in sorted(etapas, key=lambda x: -x[1]):
                pct = tempo / total_etapas * 100
                bar = "█" * int(pct / 5)
                print(f"   {nome:12}: {tempo:>8.0f}ms ({pct:5.1f}%) {bar}")
        
        # Top 5 mais lentos
        print(f"\n🐢 TOP 5 MAIS LENTOS:")
        sorted_by_time = sorted(self.results, key=lambda x: -x.total_time_ms)[:5]
        for r in sorted_by_time:
            status_icon = "✅" if r.status == "success" else "❌"
            print(f"   {status_icon} {r.nome_fantasia[:40]:40} │ {r.total_time_ms:>8.0f}ms │ {r.status}")
        
        # Diagnóstico
        print(f"\n{'═' * 50}")
        print("🩺 DIAGNÓSTICO")
        print(f"{'═' * 50}")
        
        issues = []
        
        if m.taxa_sucesso < 90:
            issues.append(f"⚠️  Taxa de sucesso abaixo de 90% ({m.taxa_sucesso:.1f}%)")
        
        if m.avg_total_time_ms > 90000:
            issues.append(f"⚠️  Tempo médio acima de 90s ({m.avg_total_time_ms/1000:.1f}s)")
        
        if m.taxa_discovery < 80:
            issues.append(f"⚠️  Taxa de Discovery baixa ({m.taxa_discovery:.1f}%)")
        
        if m.taxa_scrape < 85:
            issues.append(f"⚠️  Taxa de Scrape baixa ({m.taxa_scrape:.1f}%)")
        
        if m.taxa_profile < 90:
            issues.append(f"⚠️  Taxa de Profile baixa ({m.taxa_profile:.1f}%)")
        
        if m.avg_completeness_score < 85:
            issues.append(f"⚠️  Completude de perfil baixa ({m.avg_completeness_score:.1f}%)")
        
        cv = (m.stddev_total_time_ms / m.avg_total_time_ms * 100) if m.avg_total_time_ms > 0 else 0
        if cv > 50:
            issues.append(f"⚠️  Alta variabilidade nos tempos (CV={cv:.1f}%)")
        
        if s.circuit_breaker_triggered > 5:
            issues.append(f"⚠️  Muitos circuit breakers acionados ({s.circuit_breaker_triggered})")
        
        if issues:
            print("   Problemas detectados:")
            for issue in issues:
                print(f"      {issue}")
        else:
            print("   ✅ Nenhum problema crítico detectado!")
        
        print("\n" + "=" * 100)
    
    def _save_report(self):
        """Salva relatório detalhado em JSON."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = Path(__file__).parent.parent / "reports" / f"final_production_test_{timestamp}.json"
        report_file.parent.mkdir(exist_ok=True)
        
        report = {
            "version": "1.0",
            "type": "final_production_test",
            "timestamp": timestamp,
            "config": {
                "max_concurrent": self.max_concurrent,
                "timeout_per_empresa": self.timeout,
                "max_subpages": self.max_subpages,
                "total_empresas": len(self.results)
            },
            "system": {
                "timestamp_start": self.system_metrics.timestamp_start,
                "timestamp_end": self.system_metrics.timestamp_end,
                "python_version": self.system_metrics.python_version,
                "platform": self.system_metrics.platform_info,
                "cpu_count": self.system_metrics.cpu_count,
                "memory_total_gb": self.system_metrics.memory_total_gb,
                "memory_start_gb": self.system_metrics.memory_used_start_gb,
                "memory_end_gb": self.system_metrics.memory_used_end_gb,
                "network_latency_ms": self.system_metrics.initial_network_latency_ms,
                "circuit_breaker_triggered": self.system_metrics.circuit_breaker_triggered
            },
            "global_metrics": {
                "total": self.global_metrics.total_empresas,
                "success": self.global_metrics.success,
                "partial": self.global_metrics.partial,
                "failed": self.global_metrics.failed,
                "timeout": self.global_metrics.timeout,
                "skipped": self.global_metrics.skipped,
                "taxa_sucesso": self.global_metrics.taxa_sucesso,
                "taxa_discovery": self.global_metrics.taxa_discovery,
                "taxa_scrape": self.global_metrics.taxa_scrape,
                "taxa_profile": self.global_metrics.taxa_profile,
                "tempo_total_s": self.global_metrics.tempo_total_teste_s,
                "throughput_por_minuto": self.global_metrics.throughput_empresas_por_minuto,
                "tempos_ms": {
                    "avg_total": self.global_metrics.avg_total_time_ms,
                    "stddev_total": self.global_metrics.stddev_total_time_ms,
                    "avg_discovery": self.global_metrics.avg_discovery_time_ms,
                    "avg_scrape": self.global_metrics.avg_scrape_time_ms,
                    "avg_profile": self.global_metrics.avg_profile_time_ms,
                    "p50": self.global_metrics.p50_time_ms,
                    "p90": self.global_metrics.p90_time_ms,
                    "p95": self.global_metrics.p95_time_ms,
                    "p99": self.global_metrics.p99_time_ms
                },
                "qualidade": {
                    "avg_completeness": self.global_metrics.avg_completeness_score,
                    "avg_content_length": self.global_metrics.avg_content_length,
                    "avg_pages_per_site": self.global_metrics.avg_pages_per_site
                },
                "distribuicoes": {
                    "status": self.global_metrics.dist_status,
                    "uf": dict(self.global_metrics.dist_uf),
                    "site_type": dict(self.global_metrics.dist_site_type),
                    "protection": dict(self.global_metrics.dist_protection)
                },
                "erros": {
                    "top_errors": dict(self.global_metrics.top_errors),
                    "by_stage": dict(self.global_metrics.errors_by_stage)
                }
            },
            "results": [r.to_dict() for r in self.results]
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📄 Relatório salvo em: {report_file}")
        return report_file
    
    async def run(self, limit: int = None):
        """Executa o teste completo."""
        # Carregar empresas
        empresas = self.load_empresas(limit)
        
        # Coletar métricas do sistema
        await self.collect_system_metrics_start()
        
        # Reset circuit breaker
        try:
            from app.services.scraper import reset_circuit_breaker
            reset_circuit_breaker()
            logger.info("🔄 Circuit breaker resetado")
        except:
            pass
        
        print()
        print("=" * 100)
        print("                    TESTE FINAL DE PRODUÇÃO - INICIANDO")
        print("=" * 100)
        print(f"📊 Total de empresas: {len(empresas)}")
        print(f"⚡ Concorrência: {self.max_concurrent}")
        print(f"⏱️  Timeout: {self.timeout}s")
        print("=" * 100)
        print()
        
        # Semáforo para controlar concorrência
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # Iniciar timer
        self.start_time = time.perf_counter()
        
        # Criar tasks
        tasks = [
            self.process_empresa(empresa, i + 1, semaphore)
            for i, empresa in enumerate(empresas)
        ]
        
        # Executar em paralelo
        self.results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Processar exceções
        final_results = []
        for i, result in enumerate(self.results):
            if isinstance(result, Exception):
                error_result = CompanyResult(
                    razao_social=empresas[i].get('razao_social', ''),
                    status="failed",
                    error=str(result)
                )
                final_results.append(error_result)
            else:
                final_results.append(result)
        self.results = final_results
        
        # Tempo total
        total_time = time.perf_counter() - self.start_time
        
        # Coletar métricas finais
        await self.collect_system_metrics_end()
        
        # Calcular métricas globais
        self._calculate_global_metrics(total_time)
        
        # Imprimir resultados
        self._print_results()
        
        # Salvar relatório
        report_file = self._save_report()
        
        return self.global_metrics, report_file


# ============================================================================
# FUNÇÃO PRINCIPAL
# ============================================================================

async def run_final_test(
    n: int = None,
    concurrent: int = 50,
    timeout: float = 120.0,
    max_subpages: int = 30
):
    """Executa o teste final de produção."""
    test = FinalProductionTest(
        max_concurrent=concurrent,
        timeout_per_empresa=timeout,
        max_subpages=max_subpages
    )
    
    return await test.run(limit=n)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Teste Final de Produção")
    parser.add_argument("n", type=int, nargs="?", default=None,
                        help="Número de empresas (None = todas)")
    parser.add_argument("--concurrent", "-c", type=int, default=50,
                        help="Concorrência máxima (default: 50)")
    parser.add_argument("--timeout", "-t", type=float, default=120.0,
                        help="Timeout por empresa em segundos (default: 120)")
    parser.add_argument("--subpages", "-s", type=int, default=30,
                        help="Máximo de subpáginas (default: 30)")
    
    args = parser.parse_args()
    
    print()
    print("=" * 100)
    print("            🚀 TESTE FINAL DE PRODUÇÃO - STRESS TEST ULTRA DETALHADO 🚀")
    print("=" * 100)
    print()
    print(f"   Empresas: {args.n or 'TODAS'}")
    print(f"   Concorrência: {args.concurrent}")
    print(f"   Timeout: {args.timeout}s")
    print(f"   Max Subpáginas: {args.subpages}")
    print()
    
    try:
        asyncio.run(run_final_test(
            n=args.n,
            concurrent=args.concurrent,
            timeout=args.timeout,
            max_subpages=args.subpages
        ))
    except KeyboardInterrupt:
        print("\n\n🛑 Teste interrompido pelo usuário.")
    except Exception as e:
        print(f"\n\n❌ Erro fatal: {e}")
        traceback.print_exc()



