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
    SiteProfile, ScrapedContent, ScrapedPage, ScrapingStrategy, ProtectionType, ScrapeResult
)
from enum import Enum

from .constants import (
    scraper_config, FAST_TRACK_CONFIG, RETRY_TRACK_CONFIG,
    build_headers, get_random_impersonate, smart_referer,
)
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



def _try_reuse_analyzer_html(
    url: str,
    site_profile: SiteProfile,
    strategies: List[ScrapingStrategy],
) -> tuple:
    """
    Reutiliza o HTML capturado pelo site_analyzer como main page.
    Returns:
        (ScrapedPage, "") on success, or (None, "reason") on failure.
    """
    if not site_profile.raw_html:
        return None, "reuse_no_html"
    if site_profile.status_code and site_profile.status_code >= 400:
        return None, f"reuse_status_{site_profile.status_code}"

    text, docs, links = parse_html(site_profile.raw_html, url)

    if not text or len(text) < 100:
        return None, f"reuse_short_content({len(text) if text else 0}chars)"
    if is_cloudflare_challenge(text):
        return None, "reuse_cloudflare"
    if is_soft_404(text):
        return None, "reuse_soft_404"

    page = ScrapedPage(
        url=url,
        content=text,
        links=list(links),
        document_links=list(docs),
        status_code=site_profile.status_code or 200,
        response_time_ms=site_profile.response_time_ms,
        strategy_used=strategies[0] if strategies else ScrapingStrategy.FAST,
    )
    return page, ""


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

    # 1. PROBE URL (sob controle de concorrência)
    probe_start = time.perf_counter()
    try:
        async with concurrency_manager.acquire(url, timeout=45.0, request_id=request_id, substage="probe"):
            best_url, probe_time = await url_prober.probe(url)
        url = best_url
    except URLNotReachable as e:
        log_msg = e.get_log_message() if hasattr(e, 'get_log_message') else str(e)
        logger.error(f"{ctx_label} ❌ URL inacessível: {url} - {log_msg}")
        return "", [], []
    except Exception as e:
        logger.warning(f"{ctx_label} ⚠️ Erro no probe, usando URL original: {e}")

    # 2. ANALISAR SITE (sob controle de concorrência)
    analysis_start = time.perf_counter()
    async with concurrency_manager.acquire(url, timeout=45.0, request_id=request_id, substage="analyze"):
        site_profile = await site_analyzer.analyze(url, ctx_label=ctx_label)
    analysis_time_ms = (time.perf_counter() - analysis_start) * 1000

    # 3. SELECIONAR ESTRATÉGIAS
    strategies = strategy_selector.select(site_profile)

    # 4. SCRAPE MAIN PAGE (reutilizar HTML do analyzer quando possível)
    main_page, _reuse_reason = _try_reuse_analyzer_html(url, site_profile, strategies)
    if not main_page or not main_page.success:
        main_page, _scrape_reason = await _scrape_main_page(url, strategies, site_profile, ctx_label, request_id)
    
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
) -> ScrapeResult:
    """
    Faz scrape de todas as subpáginas de um site usando heurísticas (sem LLM).

    Returns:
        ScrapeResult com pages e metadados do pipeline.
    """
    overall_start = time.perf_counter()
    phases = {}
    meta = ScrapeResult()

    # 1. ANALYZE DIRETO (sob controle de concorrência)
    t0 = time.perf_counter()
    async with concurrency_manager.acquire(url, timeout=45.0, request_id=request_id, substage="analyze"):
        site_profile = await site_analyzer.analyze(url, ctx_label=ctx_label)
    phases['analyze'] = (time.perf_counter() - t0) * 1000

    used_probe = False
    # 2. SE ANALYZER FALHOU, FALLBACK PARA PROBE (sob controle de concorrência)
    if not site_profile.raw_html or (site_profile.status_code and site_profile.status_code >= 400):
        logger.info(
            f"{ctx_label}📡 Analyzer falhou (html={bool(site_profile.raw_html)}, "
            f"status={site_profile.status_code}), tentando probe..."
        )
        try:
            t0 = time.perf_counter()
            async with concurrency_manager.acquire(url, timeout=45.0, request_id=request_id, substage="probe"):
                best_url, probe_time = await url_prober.probe(url)
            phases['probe'] = (time.perf_counter() - t0) * 1000
            used_probe = True
            if best_url != url:
                url = best_url
                t0 = time.perf_counter()
                async with concurrency_manager.acquire(url, timeout=45.0, request_id=request_id, substage="analyze_retry"):
                    site_profile = await site_analyzer.analyze(url, ctx_label=ctx_label)
                phases['analyze_retry'] = (time.perf_counter() - t0) * 1000
        except URLNotReachable as e:
            log_msg = e.get_log_message() if hasattr(e, 'get_log_message') else str(e)
            logger.error(f"{ctx_label} ❌ URL inacessível: {url} - {log_msg}")
            error_type = getattr(e, 'error_type', None)
            probe_detail = error_type.value if error_type else "unknown"
            meta.main_page_fail_reason = f"probe_{probe_detail}"
            meta.total_time_ms = (time.perf_counter() - overall_start) * 1000
            return meta
        except Exception as e:
            logger.warning(f"{ctx_label} ⚠️ Probe fallback falhou: {e}")

    # 3. SELECIONAR ESTRATÉGIAS
    strategies = strategy_selector.select(site_profile)

    # 4. REUTILIZAR HTML DO ANALYZER COMO MAIN PAGE
    t0 = time.perf_counter()
    main_page, reuse_reason = _try_reuse_analyzer_html(url, site_profile, strategies)
    reused = main_page is not None and main_page.success
    scrape_fail_reason = ""
    if not reused:
        logger.info(
            f"{ctx_label}📄 Reuse falhou ({reuse_reason}, prot={site_profile.protection_type.value}, "
            f"status={site_profile.status_code}), chamando _scrape_main_page..."
        )
        main_page, scrape_fail_reason = await _scrape_main_page(url, strategies, site_profile, ctx_label, request_id)
    phases['main_page'] = (time.perf_counter() - t0) * 1000

    if not main_page or not main_page.success:
        fail_reason = scrape_fail_reason or reuse_reason or "unknown"
        error_diagnosis = _diagnose_scrape_failure(main_page, url)
        elapsed = (time.perf_counter() - overall_start) * 1000
        logger.error(
            f"{ctx_label} ❌ Falha main page {url} ({elapsed:.0f}ms) "
            f"reason={fail_reason} reuse={reuse_reason} phases={phases} - {error_diagnosis['log_message']}"
        )
        meta.main_page_fail_reason = fail_reason
        meta.total_time_ms = elapsed
        return meta

    meta.main_page_ok = True

    # 5. SLOW MODE
    site_response_ms = site_profile.response_time_ms or 0
    slow_mode = site_response_ms > scraper_config.slow_probe_threshold_ms

    if slow_mode:
        concurrency_manager.mark_domain_slow(url)

    per_request_timeout = (
        scraper_config.slow_per_request_timeout
        if slow_mode else
        scraper_config.fast_per_request_timeout
    )

    # 6. FILTRAR E PRIORIZAR LINKS
    filtered_links = filter_non_html_links(set(main_page.links))
    meta.links_in_html = len(main_page.links)
    meta.links_after_filter = len(filtered_links)

    if filtered_links:
        target_subpages = prioritize_links(filtered_links, url)[:max_subpages]
    else:
        target_subpages = []

    meta.links_selected = len(target_subpages)

    logger.info(
        f"{ctx_label}🏁 {url[:60]} | analyze={phases.get('analyze',0):.0f}ms "
        f"{'probe=' + str(int(phases.get('probe',0))) + 'ms ' if used_probe else ''}"
        f"reuse={'✅' if reused else '❌'} main={phases.get('main_page',0):.0f}ms "
        f"TTFB={site_response_ms:.0f}ms slow={'🐢' if slow_mode else '🚀'} "
        f"links={meta.links_in_html}→{meta.links_after_filter}→{meta.links_selected} "
        f"prot={site_profile.protection_type.value}"
    )

    # 7. SCRAPE SUBPAGES EM BATCH
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

    # 8. RESCUE
    rescue_subpages = []
    if main_page and len(main_page.content) < 500 and main_page.links and not subpages:
        logger.info(f"{ctx_label}🆘 RESCUE: Main page tem pouco conteúdo ({len(main_page.content)} chars), tentando subpages")
        rescue_links = prioritize_links(filtered_links, url)[:3]
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

    # 9. CONSOLIDAR RESULTADO COM METADADOS
    all_pages = [main_page] + subpages + rescue_subpages
    all_subpage_results = subpages + rescue_subpages

    meta.pages = all_pages
    meta.subpages_attempted = len(all_subpage_results)
    meta.subpages_ok = sum(1 for p in all_subpage_results if p.success)
    meta.total_time_ms = (time.perf_counter() - overall_start) * 1000

    error_breakdown: dict = {}
    for p in all_subpage_results:
        if not p.success and p.error:
            err = p.error.lower()
            if "timeout" in err and "slot" in err:
                cat = "timeout_slot"
            elif "circuit" in err:
                cat = "circuit_open"
            elif "rate limit" in err:
                cat = "rate_limit"
            else:
                cat = "scrape_fail"
            error_breakdown[cat] = error_breakdown.get(cat, 0) + 1
    meta.subpage_errors = error_breakdown

    ok = sum(1 for p in all_pages if p.success)
    logger.info(
        f"{ctx_label}✅ {url[:50]} | {ok}/{len(all_pages)} ok | "
        f"total={meta.total_time_ms:.0f}ms links={meta.links_in_html}→{meta.links_selected} "
        f"subpages={meta.subpages_ok}/{meta.subpages_attempted} "
        f"errors={meta.subpage_errors}"
    )

    return meta


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
) -> tuple:
    """
    Faz scrape da main page com fallback entre estratégias.
    Returns:
        (ScrapedPage, "") on success, or (None, "fail_reason") on failure.
    """
    main_start = time.perf_counter()
    last_reason = "scrape_unknown"
    strategy_errors = []
    
    for idx, strategy in enumerate(strategies):
        config = strategy_selector.get_strategy_config(strategy)
        
        try:
            async with concurrency_manager.acquire(url, timeout=45.0, request_id=request_id, substage="main_page"):
                page = await _execute_strategy(url, strategy, config, ctx_label)
            
            if page and page.success:
                page.response_time_ms = (time.perf_counter() - main_start) * 1000
                return page, ""
            
            if page and page.content:
                protection = protection_detector.detect(
                    response_body=page.content,
                    status_code=page.status_code
                )
                if protection_detector.is_blocking_protection(protection):
                    rec = protection_detector.get_retry_recommendation(protection)
                    last_reason = f"scrape_blocked_{protection.value}"
                    strategy_errors.append(f"{strategy.value}:blocked_{protection.value}")
                    logger.warning(
                        f"{ctx_label} ⚠️ Proteção {protection.value} detectada. "
                        f"Aguardando {rec['delay_seconds']}s..."
                    )
                    await asyncio.sleep(rec['delay_seconds'])
                else:
                    err_detail = page.error or "no_content"
                    last_reason = f"scrape_error({err_detail[:40]})"
                    strategy_errors.append(f"{strategy.value}:{err_detail[:30]}")
            elif page:
                err_detail = page.error or "empty_response"
                last_reason = f"scrape_proxy_fail({err_detail[:40]})"
                strategy_errors.append(f"{strategy.value}:{err_detail[:30]}")
            else:
                last_reason = "scrape_null_response"
                strategy_errors.append(f"{strategy.value}:null")
                    
        except TimeoutError:
            last_reason = "scrape_concurrency_timeout"
            strategy_errors.append(f"{strategy.value}:concurrency_timeout")
            logger.warning(f"{ctx_label} ⚠️ Estratégia {strategy.value} concurrency timeout")
            continue
        except asyncio.TimeoutError:
            last_reason = "scrape_concurrency_timeout"
            strategy_errors.append(f"{strategy.value}:concurrency_timeout")
            logger.warning(f"{ctx_label} ⚠️ Estratégia {strategy.value} concurrency timeout")
            continue
        except Exception as e:
            last_reason = f"scrape_exception({type(e).__name__})"
            strategy_errors.append(f"{strategy.value}:{type(e).__name__}")
            logger.warning(f"{ctx_label} ⚠️ Estratégia {strategy.value} falhou: {e}")
            continue
    
    logger.error(
        f"{ctx_label} ❌ Todas estratégias falharam para {url} | "
        f"reason={last_reason} | details={strategy_errors}"
    )
    return None, last_reason


async def _execute_strategy(
    url: str,
    strategy: ScrapingStrategy,
    config: dict,
    ctx_label: str = ""
) -> Optional[ScrapedPage]:
    """Executa estratégia de scraping (SEMPRE via proxy)."""
    headers, impersonate = build_headers()

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

        if not text:
            transport_err = cffi_scrape_safe.last_error or "empty_response"
            return ScrapedPage(
                url=url, content="", error=f"proxy_fail:{transport_err}"
            )

        is_cf = is_cloudflare_challenge(text)
        if is_cf:
            return ScrapedPage(
                url=url, content="", error="Cloudflare",
                links=list(links), document_links=list(docs),
                status_code=403
            )

        is_404 = is_soft_404(text)
        if is_404:
            return ScrapedPage(
                url=url, content="", error="Soft 404",
                links=list(links), document_links=list(docs),
                status_code=404
            )

        return ScrapedPage(
            url=url,
            content=text,
            links=list(links),
            document_links=list(docs),
            status_code=200,
        )

    except Exception as e:
        return ScrapedPage(
            url=url,
            content="",
            error=f"scrape_exception:{type(e).__name__}:{str(e)[:50]}"
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
    Cada subpage usa proxy individual (sem shared_session) para evitar
    que uma proxy ruim derrube todas as subpages da empresa.
    """
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
        )
        results.extend(batch_results)
        total_processed += len(batch)

        batch_duration = time.perf_counter() - batch_start
        ok = sum(1 for r in batch_results if r.success)
        logger.info(
            f"{ctx_label}📦 batch {batch_idx+1}/{len(batches)}: "
            f"{ok}/{len(batch)} ok em {batch_duration:.1f}s"
        )

        if batch_idx < len(batches) - 1:
            base_delay = random.uniform(
                scraper_config.batch_min_delay,
                scraper_config.batch_max_delay
            )
            jitter = base_delay + random.gauss(0, base_delay * 0.3)
            await asyncio.sleep(max(0.02, jitter))

    return results


def _is_site_rejection(error: str) -> bool:
    """Retorna True se o erro indica rejeição real do site (não falha de proxy/rede)."""
    if not error:
        return False
    err = error.lower()
    return any(sig in err for sig in (
        "403", "429", "cloudflare", "captcha", "waf", "forbidden", "blocked",
    ))


async def _scrape_batch_parallel(
    urls: List[str],
    main_strategy: ScrapingStrategy,
    effective_timeout: int,
    start_index: int,
    total_urls: int,
    ctx_label: str = "",
    request_id: str = "",
) -> List[ScrapedPage]:
    """
    Processa um batch de URLs em paralelo.
    Cada subpage usa proxy individual + até 2 retries com proxy diferente.
    Circuit breaker só registra falhas reais do site (não falhas de proxy/rede).
    """
    max_retries = scraper_config.subpage_max_retries

    async def scrape_with_retry(i: int, url: str) -> ScrapedPage:
        if i > 0:
            base = scraper_config.intra_batch_delay
            jitter = base * random.uniform(0.5, 2.0) + random.gauss(0, base * 0.2)
            await asyncio.sleep(max(0.01, jitter))

        if is_circuit_open(url):
            return ScrapedPage(url=url, content="", error="Circuit open")

        normalized_url = normalize_url(url)

        for attempt in range(1 + max_retries):
            try:
                if not await domain_rate_limiter.acquire(url, timeout=10.0):
                    return ScrapedPage(url=normalized_url, content="", error="Rate limit timeout")

                async with concurrency_manager.acquire(url, timeout=45.0, request_id=request_id, substage="subpages"):
                    used_proxy = proxy_pool.get_next_proxy()
                    ref = smart_referer(url)
                    headers, impersonate = build_headers(referer=ref)
                    async with AsyncSession(
                        impersonate=impersonate,
                        proxy=used_proxy,
                        timeout=effective_timeout,
                        headers=headers,
                        verify=False
                    ) as session:
                        page = await _scrape_single_subpage(
                            normalized_url, session, effective_timeout, ctx_label
                        )

                    if page.success:
                        record_success(url)
                        if used_proxy:
                            record_proxy_success(used_proxy)
                        return page

                    if used_proxy:
                        record_proxy_failure(used_proxy, page.error or "unknown")

                    if _is_site_rejection(page.error):
                        record_failure(url)
                        return page

                    if attempt < max_retries:
                        await asyncio.sleep(random.uniform(1.0, 2.0))
                        continue

                    return page

            except TimeoutError:
                if attempt < max_retries:
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                    continue
                return ScrapedPage(url=normalized_url, content="", error="Timeout acquiring slot")
            except Exception as e:
                if attempt < max_retries:
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                    continue
                return ScrapedPage(url=normalized_url, content="", error=str(e))

        return ScrapedPage(url=normalized_url, content="", error="Max retries exhausted")

    tasks = [scrape_with_retry(i, url) for i, url in enumerate(urls)]
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


