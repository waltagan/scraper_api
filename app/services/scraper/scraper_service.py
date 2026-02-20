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
    SiteProfile, ScrapedContent, ScrapedPage, ScrapingStrategy, ProtectionType
)
from enum import Enum

from .constants import scraper_config, DEFAULT_HEADERS, FAST_TRACK_CONFIG, RETRY_TRACK_CONFIG
from .html_parser import is_cloudflare_challenge, is_soft_404, normalize_url, parse_html
from .link_selector import select_links_with_llm, filter_non_html_links, prioritize_links
from .site_analyzer import site_analyzer
from .protection_detector import protection_detector, ProtectionType
from .strategy_selector import strategy_selector
from .url_prober import url_prober, URLNotReachable, ProbeErrorType
from .http_client import cffi_scrape, cffi_scrape_safe

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
    domain_rate_limiter,
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


def _try_reuse_analyzer_html(
    url: str,
    site_profile: SiteProfile,
    strategies: List[ScrapingStrategy],
) -> Optional[ScrapedPage]:
    """
    Reutiliza o HTML capturado pelo site_analyzer como main page.
    Se o analyzer já trouxe HTML com conteúdo real, usa ele - mesmo
    que protection_detector tenha sinalizado (falsos positivos comuns).
    Rejeita apenas se HTML vazio, challenge real, ou soft 404.
    """
    if not site_profile.raw_html:
        logger.debug(f"[reuse] {url}: sem raw_html")
        return None
    if site_profile.status_code and site_profile.status_code >= 400:
        logger.debug(f"[reuse] {url}: status {site_profile.status_code}")
        return None

    text, docs, links = parse_html(site_profile.raw_html, url)

    if not text or len(text) < 100:
        logger.debug(f"[reuse] {url}: conteúdo curto ({len(text) if text else 0} chars)")
        return None
    if is_cloudflare_challenge(text):
        logger.debug(f"[reuse] {url}: cloudflare challenge real")
        return None
    if is_soft_404(text):
        logger.debug(f"[reuse] {url}: soft 404")
        return None

    return ScrapedPage(
        url=url,
        content=text,
        links=list(links),
        document_links=list(docs),
        status_code=site_profile.status_code or 200,
        response_time_ms=site_profile.response_time_ms,
        strategy_used=strategies[0] if strategies else ScrapingStrategy.FAST,
    )


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

    # 4. SCRAPE MAIN PAGE (reutilizar HTML do analyzer quando possível)
    main_page = _try_reuse_analyzer_html(url, site_profile, strategies)
    if not main_page or not main_page.success:
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

    Fluxo otimizado (v4):
    1. Analyze direto (skip probe - o GET do analyzer segue redirects)
    2. Se analyzer falhou, tenta probe de variações como fallback
    3. Reutiliza HTML do analyzer como main page (zero GET extra)
    4. Filtrar e priorizar links via heurísticas
    5. Scrape subpages em batch
    6. RESCUE se main page tem pouco conteúdo

    Args:
        url: URL base do site
        max_subpages: Número máximo de subpáginas a processar
        ctx_label: Label de contexto para logs
        request_id: ID da requisição

    Returns:
        Lista de ScrapedPage (incluindo main page e subpages)
    """
    overall_start = time.perf_counter()
    phases = {}

    # 1. ANALYZE DIRETO (skip probe - curl_cffi segue redirects automaticamente)
    t0 = time.perf_counter()
    site_profile = await site_analyzer.analyze(url, ctx_label=ctx_label)
    phases['analyze'] = (time.perf_counter() - t0) * 1000

    used_probe = False
    # 2. SE ANALYZER FALHOU, FALLBACK PARA PROBE DE VARIAÇÕES
    if not site_profile.raw_html or (site_profile.status_code and site_profile.status_code >= 400):
        logger.info(
            f"{ctx_label}📡 Analyzer falhou (html={bool(site_profile.raw_html)}, "
            f"status={site_profile.status_code}), tentando probe..."
        )
        try:
            t0 = time.perf_counter()
            best_url, probe_time = await url_prober.probe(url)
            phases['probe'] = (time.perf_counter() - t0) * 1000
            used_probe = True
            if best_url != url:
                url = best_url
                t0 = time.perf_counter()
                site_profile = await site_analyzer.analyze(url, ctx_label=ctx_label)
                phases['analyze_retry'] = (time.perf_counter() - t0) * 1000
        except URLNotReachable as e:
            log_msg = e.get_log_message() if hasattr(e, 'get_log_message') else str(e)
            logger.error(f"{ctx_label} ❌ URL inacessível: {url} - {log_msg}")
            return []
        except Exception as e:
            logger.warning(f"{ctx_label} ⚠️ Probe fallback falhou: {e}")

    # 3. SELECIONAR ESTRATÉGIAS
    strategies = strategy_selector.select(site_profile)

    # 4. REUTILIZAR HTML DO ANALYZER COMO MAIN PAGE
    t0 = time.perf_counter()
    main_page = _try_reuse_analyzer_html(url, site_profile, strategies)
    reused = main_page is not None and main_page.success
    if not reused:
        logger.info(
            f"{ctx_label}📄 Reuse falhou (prot={site_profile.protection_type.value}, "
            f"status={site_profile.status_code}), chamando _scrape_main_page..."
        )
        main_page = await _scrape_main_page(url, strategies, site_profile, ctx_label, request_id)
    phases['main_page'] = (time.perf_counter() - t0) * 1000

    if not main_page or not main_page.success:
        error_diagnosis = _diagnose_scrape_failure(main_page, url)
        elapsed = (time.perf_counter() - overall_start) * 1000
        logger.error(
            f"{ctx_label} ❌ Falha main page {url} ({elapsed:.0f}ms) "
            f"phases={phases} - {error_diagnosis['log_message']}"
        )
        return []

    # 5. SLOW MODE: TTFB real do site (response_time_ms do analyzer)
    site_response_ms = site_profile.response_time_ms or 0
    slow_mode = site_response_ms > scraper_config.slow_probe_threshold_ms

    if slow_mode:
        concurrency_manager.mark_domain_slow(url)

    per_request_timeout = (
        scraper_config.slow_per_request_timeout
        if slow_mode else
        scraper_config.fast_per_request_timeout
    )

    logger.info(
        f"{ctx_label}🏁 {url[:60]} | analyze={phases.get('analyze',0):.0f}ms "
        f"{'probe=' + str(int(phases.get('probe',0))) + 'ms ' if used_probe else ''}"
        f"reuse={'✅' if reused else '❌'} main={phases.get('main_page',0):.0f}ms "
        f"TTFB={site_response_ms:.0f}ms slow={'🐢' if slow_mode else '🚀'} "
        f"links={len(main_page.links)} prot={site_profile.protection_type.value}"
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
    ok = len([p for p in all_pages if p.success])
    fail = len(all_pages) - ok
    logger.info(
        f"{ctx_label}✅ {url[:50]} | {ok}/{len(all_pages)} ok | "
        f"total={total_time_ms:.0f}ms phases={phases} "
        f"subpages_target={len(target_subpages) if target_subpages else 0}"
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
    """Executa estratégia de scraping (SEMPRE via proxy)."""
    headers = DEFAULT_HEADERS.copy()

    if config.get("rotate_ua"):
        headers["User-Agent"] = random.choice(USER_AGENTS)

    proxy = proxy_pool.get_next_proxy()
    if not proxy:
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
    """Executa o scrape real (SEMPRE via proxy, sem fallback system_curl)."""
    try:
        text, docs, links = await cffi_scrape_safe(url, proxy)

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

    if subpage_cap:
        target_subpages = target_subpages[:subpage_cap]

    config = strategy_selector.get_strategy_config(main_strategy)
    effective_timeout = per_request_timeout or config["timeout"]

    logger.info(
        f"{ctx_label}📦 subpages: {len(target_subpages)} urls, "
        f"timeout={effective_timeout}s, slow={slow_mode}, cap={subpage_cap}"
    )

    results = []

    batch_size = scraper_config.batch_size
    batches = [target_subpages[i:i + batch_size] for i in range(0, len(target_subpages), batch_size)]

    total_processed = 0

    shared_proxy = proxy_pool.get_next_proxy()
    shared_session = None
    try:
        if HAS_CURL_CFFI and AsyncSession:
            shared_session = AsyncSession(
                impersonate="chrome120",
                proxy=shared_proxy,
                timeout=effective_timeout,
                verify=False
            )

        for batch_idx, batch in enumerate(batches):
            batch_start = time.perf_counter()

            batch_results = await _scrape_batch_parallel(
                batch,
                main_strategy,
                effective_timeout,
                total_processed,
                len(target_subpages),
                ctx_label,
                request_id,
                shared_session=shared_session,
            )
            results.extend(batch_results)
            total_processed += len(batch)

            batch_duration = time.perf_counter() - batch_start
            ok = len([r for r in batch_results if r.success])
            logger.info(
                f"{ctx_label}📦 batch {batch_idx+1}/{len(batches)}: "
                f"{ok}/{len(batch)} ok em {batch_duration:.1f}s"
            )

            if batch_idx < len(batches) - 1:
                delay = random.uniform(
                    scraper_config.batch_min_delay,
                    scraper_config.batch_max_delay
                )
                await asyncio.sleep(delay)
    finally:
        if shared_session:
            try:
                await shared_session.close()
            except Exception:
                pass

    return results


async def _scrape_batch_parallel(
    urls: List[str],
    main_strategy: ScrapingStrategy,
    effective_timeout: int,
    start_index: int,
    total_urls: int,
    ctx_label: str = "",
    request_id: str = "",
    shared_session=None,
) -> List[ScrapedPage]:
    """Processa um batch de URLs em paralelo (TODAS via proxy)."""

    async def scrape_with_delay(i: int, url: str) -> ScrapedPage:
        if i > 0:
            await asyncio.sleep(scraper_config.intra_batch_delay)

        if is_circuit_open(url):
            return ScrapedPage(url=url, content="", error="Circuit open")

        normalized_url = normalize_url(url)

        try:
            if not await domain_rate_limiter.acquire(url, timeout=5.0):
                return ScrapedPage(url=normalized_url, content="", error="Rate limit timeout")

            async with concurrency_manager.acquire(url, timeout=5.0, request_id=request_id, substage="subpages"):
                if shared_session:
                    page = await _scrape_single_subpage(
                        normalized_url, shared_session, effective_timeout, ctx_label
                    )
                else:
                    sub_proxy = proxy_pool.get_next_proxy()
                    async with AsyncSession(
                        impersonate="chrome120",
                        proxy=sub_proxy,
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

        except TimeoutError:
            record_failure(url)
            return ScrapedPage(url=normalized_url, content="", error="Timeout acquiring slot")
        except Exception as e:
            record_failure(url)
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
    """Faz scrape de uma única subpágina usando sessão compartilhada."""
    try:
        text, docs, _ = await asyncio.wait_for(
            cffi_scrape(url, proxy=None, session=session),
            timeout=per_request_timeout
        )

        if not text or len(text) < 100 or is_soft_404(text) or is_cloudflare_challenge(text):
            return ScrapedPage(url=url, content="", error="Empty or soft 404")

        return ScrapedPage(
            url=url,
            content=text,
            document_links=list(docs),
            status_code=200
        )

    except Exception as e:
        return ScrapedPage(url=url, content="", error=str(e))


