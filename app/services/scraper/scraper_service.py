"""
Serviço principal de scraping v3.0.
Orquestra todo o processo de scrape - APENAS LÓGICA DE NEGÓCIO.

A infraestrutura (concorrência, proxies, circuit breaker) é gerenciada por:
- app/services/scraper_manager/
- app/services/concurrency_manager/
"""

import asyncio
import time
import logging
import random
from urllib.parse import urlparse
from typing import List, Tuple, Optional


try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

from .models import (
    SiteProfile, ScrapedContent, ScrapedPage, ScrapingStrategy
)
from enum import Enum

from .constants import scraper_config, DEFAULT_HEADERS, FAST_TRACK_CONFIG, RETRY_TRACK_CONFIG
from .html_parser import is_cloudflare_challenge, is_soft_404, normalize_url
from .link_selector import select_links_with_llm, filter_non_html_links, prioritize_links
from .site_analyzer import site_analyzer
from .protection_detector import protection_detector, ProtectionType
from .strategy_selector import strategy_selector
from .url_prober import url_prober, URLNotReachable, ProbeErrorType
from .http_client import cffi_scrape, cffi_scrape_safe, system_curl_scrape

# Importar managers de infraestrutura
from app.services.scraper_manager import (
    concurrency_manager,
    proxy_pool,
    circuit_breaker,
    is_circuit_open,
    record_failure,
    record_success,
    get_healthy_proxy,
    record_proxy_failure,
    record_proxy_success,
)

logger = logging.getLogger(__name__)


class FailureType(Enum):
    """Tipos de falha para classificação."""
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    CLOUDFLARE = "cloudflare"
    WAF = "waf"
    CAPTCHA = "captcha"
    RATE_LIMIT = "rate_limit"
    EMPTY_CONTENT = "empty_content"
    SSL_ERROR = "ssl_error"
    DNS_ERROR = "dns_error"
    UNKNOWN = "unknown"


# User-Agents para rotação
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


async def scrape_url(url: str, max_subpages: int = 100, ctx_label: str = "", request_id: str = "") -> Tuple[str, List[str], List[str]]:
    """
    Scraper adaptativo v3.0 - Apenas lógica de negócio.

    Fluxo:
    1. Probe URL (encontrar melhor variação)
    2. Analisar site (detectar proteção e tipo)
    3. Selecionar estratégia
    4. Scrape main page com fallback
    5. Extrair e selecionar links
    6. Scrape subpages em paralelo
    7. Consolidar resultados

    Returns:
        Tuple de (texto_agregado, lista_documentos, urls_visitadas)
    """
    overall_start = time.perf_counter()

    # 1. PROBE URL
    probe_start = time.perf_counter()
    try:
        best_url, probe_time = await url_prober.probe(url)
        url = best_url
    except URLNotReachable as e:
        log_msg = e.get_log_message() if hasattr(e, 'get_log_message') else str(e)
        logger.error(f"{ctx_label} ❌ URL inacessível: {url} - {log_msg}")
        return "", [], []
    except Exception as e:
        logger.warning(f"{ctx_label} ⚠️ Erro no probe, usando URL original: {e}")

    # 2. ANALISAR SITE
    analysis_start = time.perf_counter()
    site_profile = await site_analyzer.analyze(url, ctx_label=ctx_label)
    analysis_time_ms = (time.perf_counter() - analysis_start) * 1000

    # 3. SELECIONAR ESTRATÉGIAS
    strategies = strategy_selector.select(site_profile)

    # 4. SCRAPE MAIN PAGE
    main_page = await _scrape_main_page(url, strategies, site_profile, ctx_label, request_id)
    
    if not main_page or not main_page.success:
        error_diagnosis = _diagnose_scrape_failure(main_page, url)
        logger.error(f"{ctx_label} ❌ Falha ao obter main page de {url} - {error_diagnosis['log_message']}")
        return "", [], []
    
    # 5. CONFIGURAÇÃO DE PERFORMANCE
    probe_ms = probe_time if 'probe_time' in locals() else 0
    main_ms = getattr(main_page, "response_time_ms", 0) or 0
    slow_mode = (
        (probe_ms and probe_ms > scraper_config.slow_probe_threshold_ms) or
        (analysis_time_ms > scraper_config.slow_main_threshold_ms) or
        (main_ms > scraper_config.slow_main_threshold_ms)
    )
    
    # Marcar domínio como lento se necessário
    if slow_mode:
        concurrency_manager.mark_domain_slow(url)
    
    per_request_timeout = (
        scraper_config.slow_per_request_timeout
        if slow_mode else
        scraper_config.fast_per_request_timeout
    )

    # 5. SELECIONAR SUBPÁGINAS RELEVANTES
    link_selection_start = time.perf_counter()
    target_subpages = await select_links_with_llm(
        set(main_page.links), url, max_links=max_subpages, ctx_label=ctx_label, request_id=request_id
    )
    link_selection_time = (time.perf_counter() - link_selection_start) * 1000

    # 6. SCRAPE SUBPAGES
    subpages = []
    if target_subpages:
        effective_cap = scraper_config.slow_subpage_cap if slow_mode else max_subpages
        if effective_cap < 5:
            effective_cap = 10

        subpages_start = time.perf_counter()
        subpages = await _scrape_subpages_batch(
            target_subpages,
            main_page.strategy_used,
            slow_mode=slow_mode,
            subpage_cap=effective_cap,
            per_request_timeout=per_request_timeout,
            ctx_label=ctx_label,
            request_id=request_id
        )
        subpages_duration = (time.perf_counter() - subpages_start) * 1000
    
    # 8. CONSOLIDAR
    content = ScrapedContent(
        main_url=url,
        main_page=main_page,
        subpages=subpages,
        total_time_ms=(time.perf_counter() - overall_start) * 1000,
        strategies_tried=strategies
    )
    
    return content.aggregated_content, content.all_document_links, content.visited_urls


async def scrape_all_subpages(
    url: str,
    max_subpages: int = 100,
    ctx_label: str = "",
    request_id: str = ""
) -> List[ScrapedPage]:
    """
    Faz scrape de todas as subpáginas de um site usando heurísticas (sem LLM).
    
    Esta função é uma versão simplificada de scrape_url que:
    - Não usa LLM para seleção de links (usa heurísticas)
    - Mantém batch scraping assíncrono existente
    - Mantém sistema RESCUE para páginas vazias
    
    Fluxo:
    1. Probe URL (encontrar melhor variação)
    2. Analisar site (detectar proteção e tipo)
    3. Selecionar estratégia
    4. Scrape main page com fallback
    5. Filtrar e priorizar links usando heurísticas (sem LLM)
    6. Scrape subpages em batch (assíncrono)
    7. Retornar lista de ScrapedPage
    
    Args:
        url: URL base do site
        max_subpages: Número máximo de subpáginas a processar
        ctx_label: Label de contexto para logs
        request_id: ID da requisição
    
    Returns:
        Lista de ScrapedPage (incluindo main page e subpages)
    """
    overall_start = time.perf_counter()
    
    # 1. PROBE URL
    try:
        best_url, probe_time = await url_prober.probe(url)
        url = best_url
    except URLNotReachable as e:
        log_msg = e.get_log_message() if hasattr(e, 'get_log_message') else str(e)
        logger.error(f"{ctx_label} ❌ URL inacessível: {url} - {log_msg}")
        return []
    except Exception as e:
        logger.warning(f"{ctx_label} ⚠️ Erro no probe, usando URL original: {e}")
    
    # 2. ANALISAR SITE
    analysis_start = time.perf_counter()
    site_profile = await site_analyzer.analyze(url, ctx_label=ctx_label)
    analysis_time_ms = (time.perf_counter() - analysis_start) * 1000
    
    # 3. SELECIONAR ESTRATÉGIAS
    strategies = strategy_selector.select(site_profile)
    
    # 4. SCRAPE MAIN PAGE
    main_page = await _scrape_main_page(url, strategies, site_profile, ctx_label, request_id)
    
    if not main_page or not main_page.success:
        error_diagnosis = _diagnose_scrape_failure(main_page, url)
        logger.error(f"{ctx_label} ❌ Falha ao obter main page de {url} - {error_diagnosis['log_message']}")
        return []
    
    # 5. CONFIGURAÇÃO DE PERFORMANCE
    probe_ms = probe_time if 'probe_time' in locals() else 0
    main_ms = getattr(main_page, "response_time_ms", 0) or 0
    slow_mode = (
        (probe_ms and probe_ms > scraper_config.slow_probe_threshold_ms) or
        (analysis_time_ms > scraper_config.slow_main_threshold_ms) or
        (main_ms > scraper_config.slow_main_threshold_ms)
    )
    
    # Marcar domínio como lento se necessário
    if slow_mode:
        concurrency_manager.mark_domain_slow(url)
    
    per_request_timeout = (
        scraper_config.slow_per_request_timeout
        if slow_mode else
        scraper_config.fast_per_request_timeout
    )
    
    # 6. FILTRAR E PRIORIZAR LINKS USANDO HEURÍSTICAS (SEM LLM)
    link_selection_start = time.perf_counter()
    
    # Filtrar links não-HTML
    filtered_links = filter_non_html_links(set(main_page.links))
    logger.info(
        f"{ctx_label}Filtrados {len(main_page.links) - len(filtered_links)} links não-HTML. "
        f"Restam {len(filtered_links)} links válidos."
    )
    
    # Priorizar links usando heurísticas (sem LLM)
    if filtered_links:
        target_subpages = prioritize_links(filtered_links, url)[:max_subpages]
        logger.info(f"{ctx_label}Priorizados {len(target_subpages)} links usando heurísticas")
    else:
        target_subpages = []
        logger.warning(f"{ctx_label}Nenhum link válido encontrado após filtragem")
    
    link_selection_time = (time.perf_counter() - link_selection_start) * 1000
    
    # 7. SCRAPE SUBPAGES EM BATCH (ASSÍNCRONO)
    subpages = []
    if target_subpages:
        effective_cap = scraper_config.slow_subpage_cap if slow_mode else max_subpages
        if effective_cap < 5:
            effective_cap = 10
        
        subpages_start = time.perf_counter()
        subpages = await _scrape_subpages_batch(
            target_subpages,
            main_page.strategy_used,
            slow_mode=slow_mode,
            subpage_cap=effective_cap,
            per_request_timeout=per_request_timeout,
            ctx_label=ctx_label,
            request_id=request_id
        )
        subpages_duration = (time.perf_counter() - subpages_start) * 1000
        logger.info(
            f"{ctx_label}Scrape de {len(subpages)} subpages concluído em {subpages_duration:.1f}ms"
        )
    
    # 8. SISTEMA RESCUE: Se main page tem pouco conteúdo mas tem links, tentar subpages
    rescue_subpages = []
    if main_page and len(main_page.content) < 500 and main_page.links and not subpages:
        logger.info(f"{ctx_label}🆘 RESCUE: Main page tem pouco conteúdo ({len(main_page.content)} chars), tentando subpages")
        
        # Priorizar links de alta relevância para RESCUE
        rescue_links = prioritize_links(filtered_links, url)[:3]  # Máximo 3 para RESCUE
        
        if rescue_links:
            rescue_subpages = await _scrape_subpages_batch(
                rescue_links,
                main_page.strategy_used,
                slow_mode=slow_mode,
                subpage_cap=3,
                per_request_timeout=per_request_timeout,
                ctx_label=f"{ctx_label}[RESCUE] ",
                request_id=request_id
            )
            logger.info(f"{ctx_label}🆘 RESCUE: {len([p for p in rescue_subpages if p.success])} subpages resgatadas")
    
    # 9. RETORNAR LISTA DE PÁGINAS (main + subpages)
    all_pages = [main_page] + subpages + rescue_subpages
    
    total_time_ms = (time.perf_counter() - overall_start) * 1000
    logger.info(
        f"{ctx_label}✅ scrape_all_subpages concluído: {len(all_pages)} páginas "
        f"({len([p for p in all_pages if p.success])} sucesso) em {total_time_ms:.1f}ms"
    )
    
    return all_pages


async def scrape_batch_hybrid(urls: List[str], max_subpages: int = 100) -> List[Tuple[str, List[str], List[str]]]:
    """
    Processa um lote de URLs usando a estratégia Híbrida (Fast Path + Retry Path).
    
    Fase 1 (Fast Track): Processa todas URLs com timeout curto e alta concorrência.
    Fase 2 (Retry Track): Reprocessa falhas com timeout longo e limites estritos.
    """
    results = {}
    failed_urls = []
    
    # --- FASE 1: FAST TRACK ---
    scraper_config.update(**FAST_TRACK_CONFIG)
    
    # Atualizar managers com config do fast track
    concurrency_manager.update_limits(
        global_limit=FAST_TRACK_CONFIG['site_semaphore_limit'],
        per_domain_limit=FAST_TRACK_CONFIG['per_domain_limit']
    )
    
    fast_sem = asyncio.Semaphore(FAST_TRACK_CONFIG['site_semaphore_limit'])
    fast_timeout = 35.0
    
    async def fast_scrape(url):
        async with fast_sem:
            try:
                return await asyncio.wait_for(scrape_url(url, max_subpages), timeout=fast_timeout)
            except Exception as e:
                return e

    tasks = [fast_scrape(url) for url in urls]
    fast_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for url, res in zip(urls, fast_results):
        if isinstance(res, Exception) or not res or (isinstance(res, tuple) and not res[0]):
            failed_urls.append(url)
        else:
            results[url] = res
    
    if not failed_urls:
        return [results.get(url, ("", [], [])) for url in urls]
    
    # --- FASE 2: RETRY TRACK ---
    scraper_config.update(**RETRY_TRACK_CONFIG)
    
    # Atualizar managers com config do retry track
    concurrency_manager.update_limits(
        global_limit=RETRY_TRACK_CONFIG['site_semaphore_limit'],
        per_domain_limit=RETRY_TRACK_CONFIG['per_domain_limit']
    )
    
    # Resetar circuit breaker para dar nova chance
    circuit_breaker.reset()
    
    retry_sem = asyncio.Semaphore(RETRY_TRACK_CONFIG['site_semaphore_limit'])
    retry_timeout = 120.0
    
    async def retry_scrape(url):
        async with retry_sem:
            try:
                return await asyncio.wait_for(scrape_url(url, max_subpages), timeout=retry_timeout)
            except Exception as e:
                logger.error(f"❌ Falha final no Retry Track para {url}: {e}")
                return ("", [], [])

    retry_tasks = [retry_scrape(url) for url in failed_urls]
    retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)
    
    success_retry = 0
    for url, res in zip(failed_urls, retry_results):
        if isinstance(res, Exception):
            results[url] = ("", [], [])
        else:
            results[url] = res
            if res and res[0]:
                success_retry += 1
    
    return [results.get(url, ("", [], [])) for url in urls]


def _classify_error(error_message: str) -> FailureType:
    """Classifica uma mensagem de erro em um tipo de falha."""
    if not error_message:
        return FailureType.UNKNOWN
    
    error_lower = error_message.lower()
    
    if "timeout" in error_lower:
        return FailureType.TIMEOUT
    elif "cloudflare" in error_lower:
        return FailureType.CLOUDFLARE
    elif "403" in error_lower or "waf" in error_lower:
        return FailureType.WAF
    elif "captcha" in error_lower:
        return FailureType.CAPTCHA
    elif "rate" in error_lower and "limit" in error_lower:
        return FailureType.RATE_LIMIT
    elif "empty" in error_lower or "404" in error_lower:
        return FailureType.EMPTY_CONTENT
    elif "ssl" in error_lower or "certificate" in error_lower:
        return FailureType.SSL_ERROR
    elif "dns" in error_lower or "resolve" in error_lower:
        return FailureType.DNS_ERROR
    elif "connection" in error_lower or "connect" in error_lower:
        return FailureType.CONNECTION_ERROR
    
    return FailureType.UNKNOWN


def _diagnose_scrape_failure(page: Optional[ScrapedPage], url: str) -> dict:
    """Faz diagnóstico detalhado de por que o scrape falhou."""
    if not page:
        return {
            "log_message": "[❓ NO_RESPONSE] Nenhuma resposta obtida do servidor",
            "failure_type": FailureType.CONNECTION_ERROR,
            "diagnosis": "no_response"
        }
    
    error = page.error or ""
    error_lower = error.lower()
    content = page.content or ""
    content_lower = content.lower()
    status = page.status_code or 0
    
    # Verificações de diagnóstico (ordem de prioridade)
    checks = [
        # Cloudflare
        (lambda: "cloudflare" in error_lower or "cloudflare" in content_lower,
         lambda: {
             "log_message": "[🛡️ CLOUDFLARE] Site protegido por Cloudflare",
             "failure_type": FailureType.CLOUDFLARE,
             "diagnosis": "cloudflare"
         }),
        # CAPTCHA
        (lambda: "captcha" in error_lower or "captcha" in content_lower,
         lambda: {
             "log_message": "[🤖 CAPTCHA] Site exige resolução de CAPTCHA",
             "failure_type": FailureType.CAPTCHA,
             "diagnosis": "captcha"
         }),
        # 403 Forbidden
        (lambda: status == 403 or "403" in error_lower,
         lambda: {
             "log_message": "[🚫 BLOCKED_403] Acesso bloqueado pelo servidor",
             "failure_type": FailureType.WAF,
             "diagnosis": "blocked_403"
         }),
        # Rate Limit
        (lambda: status == 429 or "rate limit" in error_lower,
         lambda: {
             "log_message": "[⏳ RATE_LIMITED] Muitas requisições",
             "failure_type": FailureType.RATE_LIMIT,
             "diagnosis": "rate_limited"
         }),
        # Server Error
        (lambda: status >= 500,
         lambda: {
             "log_message": f"[💥 SERVER_ERROR_{status}] Erro interno do servidor",
             "failure_type": FailureType.CONNECTION_ERROR,
             "diagnosis": f"server_error_{status}"
         }),
        # 404
        (lambda: status == 404 or "soft 404" in error_lower,
         lambda: {
             "log_message": "[📭 NOT_FOUND] Página não encontrada",
             "failure_type": FailureType.EMPTY_CONTENT,
             "diagnosis": "not_found"
         }),
        # Timeout
        (lambda: "timeout" in error_lower,
         lambda: {
             "log_message": "[⏱️ TIMEOUT] Servidor demorou demais",
             "failure_type": FailureType.TIMEOUT,
             "diagnosis": "timeout"
         }),
        # SSL
        (lambda: "ssl" in error_lower or "certificate" in error_lower,
         lambda: {
             "log_message": "[🔒 SSL_ERROR] Problema com certificado SSL",
             "failure_type": FailureType.SSL_ERROR,
             "diagnosis": "ssl_error"
         }),
        # Conteúdo vazio
        (lambda: len(content) < 100,
         lambda: {
             "log_message": f"[📄 EMPTY_CONTENT] Conteúdo insuficiente ({len(content)} chars)",
             "failure_type": FailureType.EMPTY_CONTENT,
             "diagnosis": "empty_content"
         }),
    ]
    
    for condition, result in checks:
        if condition():
            return result()
    
    # Erro genérico
    if error:
        return {
            "log_message": f"[❓ ERROR] {error}",
            "failure_type": _classify_error(error),
            "diagnosis": "unknown_error"
        }
    
    return {
        "log_message": "[❓ UNKNOWN] Falha desconhecida no scraping",
        "failure_type": FailureType.UNKNOWN,
        "diagnosis": "unknown"
    }


async def _scrape_main_page(
    url: str,
    strategies: List[ScrapingStrategy],
    site_profile: SiteProfile,
    ctx_label: str = "",
    request_id: str = ""
) -> Optional[ScrapedPage]:
    """Faz scrape da main page com fallback entre estratégias."""
    main_start = time.perf_counter()
    total_strategies = len(strategies)
    last_reason = "error"
    
    for idx, strategy in enumerate(strategies):
        config = strategy_selector.get_strategy_config(strategy)
        
        
        try:
            page = await _execute_strategy(url, strategy, config, ctx_label)
            
            if page and page.success:
                page.response_time_ms = (time.perf_counter() - main_start) * 1000
                return page
            
            # Verificar se é proteção que bloqueia
            if page and page.content:
                protection = protection_detector.detect(
                    response_body=page.content,
                    status_code=page.status_code
                )
                if protection_detector.is_blocking_protection(protection):
                    rec = protection_detector.get_retry_recommendation(protection)
                    last_reason = "blocked"
                    logger.warning(
                        f"{ctx_label} ⚠️ Proteção {protection.value} detectada. "
                        f"Aguardando {rec['delay_seconds']}s..."
                    )
                    await asyncio.sleep(rec['delay_seconds'])
                else:
                    last_reason = "error"
            else:
                last_reason = "timeout" if not page else "error"
                    
        except asyncio.TimeoutError:
            last_reason = "timeout"
            logger.warning(f"{ctx_label} ⚠️ Estratégia {strategy.value} timeout")
            continue
        except Exception as e:
            last_reason = "error"
            logger.warning(f"{ctx_label} ⚠️ Estratégia {strategy.value} falhou: {e}")
            continue
    
    logger.error(f"{ctx_label} ❌ Todas estratégias falharam para {url}")
    return None


async def _execute_strategy(
    url: str,
    strategy: ScrapingStrategy,
    config: dict,
    ctx_label: str = ""
) -> Optional[ScrapedPage]:
    """Executa uma estratégia específica de scraping."""
    headers = DEFAULT_HEADERS.copy()
    
    # Rotação de User-Agent se configurado
    if config.get("rotate_ua"):
        headers["User-Agent"] = random.choice(USER_AGENTS)
    
    # Proxy se configurado
    proxy = None
    if config.get("use_proxy"):
        proxy = await get_healthy_proxy()
        if proxy:
            logger.info(f"{ctx_label} 🔐 Proxy selecionado: {proxy[:30]}...")
        else:
            logger.warning(f"{ctx_label} ⚠️ Nenhum proxy disponível!")
        if config.get("rotate_proxy"):
            for _ in range(3):
                try:
                    page = await _do_scrape(url, proxy, headers, config["timeout"], ctx_label)
                    if page.success:
                        page.strategy_used = strategy
                        record_proxy_success(proxy)
                        return page
                except Exception:
                    record_proxy_failure(proxy, "scrape_failed")
                    proxy = await get_healthy_proxy()
    
    page = await _do_scrape(url, proxy, headers, config["timeout"], ctx_label)
    page.strategy_used = strategy
    
    if page.success and proxy:
        record_proxy_success(proxy)
    elif not page.success and proxy:
        record_proxy_failure(proxy, page.error or "unknown")
    
    return page


async def _do_scrape(
    url: str,
    proxy: Optional[str],
    headers: dict,
    timeout: int,
    ctx_label: str = ""
) -> ScrapedPage:
    """Executa o scrape real."""
    try:
        text, docs, links = await cffi_scrape_safe(url, proxy)
        
        # Fallback para system curl se conteúdo insuficiente
        if not text or len(text) < 100:
            text, docs, links = await system_curl_scrape(url, proxy)
        
        is_404 = is_soft_404(text) if text else True
        is_cf = is_cloudflare_challenge(text) if text else False
        
        return ScrapedPage(
            url=url,
            content=text if not is_404 and not is_cf else "",
            links=list(links),
            document_links=list(docs),
            status_code=200 if text and not is_404 else 404,
            error="Soft 404" if is_404 else ("Cloudflare" if is_cf else None)
        )
        
    except Exception as e:
        return ScrapedPage(
            url=url,
            content="",
            error=str(e)
        )


async def _scrape_subpages_batch(
    target_subpages: List[str],
    main_strategy: ScrapingStrategy,
    slow_mode: bool = False,
    subpage_cap: Optional[int] = None,
    per_request_timeout: Optional[int] = None,
    ctx_label: str = "",
    request_id: str = ""
) -> List[ScrapedPage]:
    """
    Faz scrape das subpáginas usando BATCH SCRAPING.
    
    Processa em mini-batches paralelos com delays entre batches
    para simular navegação humana.
    """
    subpages_start = time.perf_counter()
    logger.info(f"{ctx_label} [Scraper] Processing {len(target_subpages)} subpages (batch mode)")
    
    if subpage_cap:
        target_subpages = target_subpages[:subpage_cap]
    
    config = strategy_selector.get_strategy_config(main_strategy)
    effective_timeout = per_request_timeout or config["timeout"]
    
    results = []
    
    # Obter proxy compartilhado para batch
    shared_proxy = await get_healthy_proxy()
    
    # Dividir em batches
    batch_size = scraper_config.batch_size
    batches = [target_subpages[i:i + batch_size] for i in range(0, len(target_subpages), batch_size)]
    
    total_processed = 0
    
    logger.info(f"{ctx_label} [Scraper] Processing {len(target_subpages)} subpages (batch mode)")
    
    for batch_idx, batch in enumerate(batches):
        batch_start = time.perf_counter()
        
        # Processar batch em paralelo
        batch_results = await _scrape_batch_parallel(
            batch,
            main_strategy,
            shared_proxy,
            effective_timeout,
            total_processed,
            len(target_subpages),
            ctx_label,
            request_id
        )
        results.extend(batch_results)
        total_processed += len(batch)
        
        batch_duration = time.perf_counter() - batch_start
        
        # Delay entre batches
        if batch_idx < len(batches) - 1:
            delay = random.uniform(
                scraper_config.batch_min_delay,
                scraper_config.batch_max_delay
            )
            logger.debug(
                f"{ctx_label} [Batch {batch_idx+1}/{len(batches)}] "
                f"Concluído em {batch_duration:.1f}s. Aguardando {delay:.1f}s..."
            )
            await asyncio.sleep(delay)
    
    return results


async def _scrape_batch_parallel(
    urls: List[str],
    main_strategy: ScrapingStrategy,
    shared_proxy: Optional[str],
    effective_timeout: int,
    start_index: int,
    total_urls: int,
    ctx_label: str = "",
    request_id: str = ""
) -> List[ScrapedPage]:
    """Processa um batch de URLs em paralelo com delays internos."""
    
    async def scrape_with_delay(i: int, url: str) -> ScrapedPage:
        # Delay proporcional à posição no batch
        if i > 0:
            await asyncio.sleep(scraper_config.intra_batch_delay * i)
        
        # Verificar circuit breaker
        if is_circuit_open(url):
            return ScrapedPage(url=url, content="", error="Circuit open")
        
        normalized_url = normalize_url(url)
        global_index = start_index + i + 1
        
        try:
            # Adquirir slot de domínio via concurrency manager
            async with concurrency_manager.acquire(url, timeout=10.0, request_id=request_id, substage="subpages"):
                logger.debug(f"{ctx_label} [Batch] {global_index}/{total_urls}: {normalized_url[:60]}")
                
                if HAS_CURL_CFFI and AsyncSession:
                    try:
                        async with AsyncSession(
                            impersonate="chrome120",
                            proxy=shared_proxy,
                            timeout=effective_timeout,
                            verify=False
                        ) as session:
                            page = await _scrape_single_subpage(
                                normalized_url, session, effective_timeout, ctx_label
                            )
                            if page.success:
                                record_success(url)
                            else:
                                record_failure(url)
                            return page
                    except Exception as e:
                        logger.debug(f"{ctx_label}    cffi failed, trying fallback: {e}")
                
                # Fallback para system_curl
                page = await _scrape_single_subpage_fallback(
                    normalized_url, shared_proxy, effective_timeout, ctx_label
                )
                
                if page.success:
                    record_success(url)
                else:
                    record_failure(url)
                
                return page
                
        except TimeoutError:
            record_failure(url)
            return ScrapedPage(url=normalized_url, content="", error="Timeout acquiring slot")
        except Exception as e:
            record_failure(url)
            logger.warning(f"{ctx_label}    ❌ [{global_index}/{total_urls}] {normalized_url[:50]} - {e}")
            return ScrapedPage(url=normalized_url, content="", error=str(e))
    
    tasks = [scrape_with_delay(i, url) for i, url in enumerate(urls)]
    results = await asyncio.gather(*tasks)
    
    return list(results)


async def _scrape_single_subpage(
    url: str,
    session: AsyncSession,
    per_request_timeout: int,
    ctx_label: str = ""
) -> ScrapedPage:
    """Faz scrape de uma única subpágina usando sessão."""
    try:
        text, docs, _ = await asyncio.wait_for(
            cffi_scrape(url, proxy=None, session=session),
            timeout=per_request_timeout
        )
        
        is_cf = is_cloudflare_challenge(text) if text else False
        
        if not text or len(text) < 100 or is_soft_404(text):
            # Fallback
            fallback_proxy = await get_healthy_proxy()
            text, docs, _ = await asyncio.wait_for(
                system_curl_scrape(url, fallback_proxy),
                timeout=per_request_timeout
            )
            
            if not text or len(text) < 100 or is_soft_404(text):
                return ScrapedPage(url=url, content="", error="Empty or soft 404")
        
        return ScrapedPage(
            url=url,
            content=text,
            document_links=list(docs),
            status_code=200
        )
        
    except Exception as e:
        return ScrapedPage(url=url, content="", error=str(e))


async def _scrape_single_subpage_fallback(
    url: str,
    proxy: Optional[str],
    per_request_timeout: int,
    ctx_label: str = ""
) -> ScrapedPage:
    """Faz scrape usando system_curl."""
    try:
        text, docs, _ = await asyncio.wait_for(
            system_curl_scrape(url, proxy),
            timeout=per_request_timeout
        )
        
        if not text or len(text) < 100 or is_soft_404(text):
            return ScrapedPage(url=url, content="", error="Empty or soft 404")
        
        logger.debug(f"{ctx_label} [Sub] ✅ {url[:60]} ({len(text)} chars)")
        return ScrapedPage(
            url=url,
            content=text,
            document_links=list(docs),
            status_code=200
        )
    except Exception as e:
        return ScrapedPage(url=url, content="", error=str(e))
