"""
Serviço principal de scraping v2.0.
Orquestra todo o processo de scrape com adaptação automática.
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

from app.core.proxy import proxy_manager
from app.services.learning import (
    failure_tracker, FailureModule, FailureType,
    site_knowledge, adaptive_config
)
from .models import (
    SiteProfile, ScrapedContent, ScrapedPage, ScrapingStrategy
)
from .constants import scraper_config, DEFAULT_HEADERS, FAST_TRACK_CONFIG, RETRY_TRACK_CONFIG
from .circuit_breaker import record_failure, record_success, is_circuit_open
from .http_client import cffi_scrape, cffi_scrape_safe, system_curl_scrape
from .html_parser import is_cloudflare_challenge, is_soft_404, normalize_url
from .link_selector import select_links_with_llm
from .site_analyzer import site_analyzer
from .protection_detector import protection_detector, ProtectionType
from .strategy_selector import strategy_selector
from .url_prober import url_prober, URLNotReachable

logger = logging.getLogger(__name__)

# Controle de concorrência por domínio e saúde de proxies
_domain_semaphores = {}
_proxy_failures = {}
_proxy_quarantine_until = {}
_PROXY_QUARANTINE_SECONDS = 300


def _get_domain_semaphore(host: str) -> asyncio.Semaphore:
    """Retorna o semáforo por domínio para limitar paralelismo no mesmo host."""
    limit = max(1, scraper_config.per_domain_limit)
    if host not in _domain_semaphores:
        _domain_semaphores[host] = asyncio.Semaphore(limit)
    return _domain_semaphores[host]


def _proxy_is_quarantined(proxy: str) -> bool:
    until = _proxy_quarantine_until.get(proxy)
    return until is not None and until > time.time()


def _record_proxy_failure(proxy: str, ctx_label: str = ""):
    _proxy_failures[proxy] = _proxy_failures.get(proxy, 0) + 1
    if _proxy_failures[proxy] >= scraper_config.proxy_max_failures:
        _proxy_quarantine_until[proxy] = time.time() + _PROXY_QUARANTINE_SECONDS
        logger.debug(f"{ctx_label} [Proxy] Quarentena aplicada ao proxy {proxy}")


def _record_proxy_success(proxy: str):
    _proxy_failures[proxy] = 0
    _proxy_quarantine_until.pop(proxy, None)


async def _test_proxy_latency(proxy_url: str) -> Tuple[float, bool]:
    """Testa conexão TCP básica ao host do proxy para medir latência."""
    try:
        parsed = urlparse(proxy_url if "://" in proxy_url else f"http://{proxy_url}")
        host = parsed.hostname
        port = parsed.port or 80
        start = time.perf_counter()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=5.0
        )
        writer.close()
        await writer.wait_closed()
        latency_ms = (time.perf_counter() - start) * 1000
        return latency_ms, True
    except Exception:
        return 0, False


async def _get_healthy_proxy(max_attempts: int = 3) -> Optional[str]:
    """
    Obtém um proxy saudável:
    - Pula proxies em quarentena
    - Mede latência e recusa se > limiar
    - Quarentena após repetidas falhas
    """
    for _ in range(max_attempts):
        proxy = await proxy_manager.get_next_proxy()
        if not proxy:
            continue
        if _proxy_is_quarantined(proxy):
            continue
        latency, ok = await _test_proxy_latency(proxy)
        if ok and latency <= scraper_config.proxy_max_latency_ms:
            _record_proxy_success(proxy)
            return proxy
        _record_proxy_failure(proxy)
    return None

# User-Agents para rotação
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


async def scrape_url(url: str, max_subpages: int = 100, ctx_label: str = "") -> Tuple[str, List[str], List[str]]:
    """
    Scraper adaptativo v2.0 com Learning Engine.
    
    Fluxo:
    1. Consultar conhecimento prévio do site
    2. Probe URL (encontrar melhor variação)
    3. Analisar site (detectar proteção e tipo)
    4. Selecionar estratégia (considerando conhecimento prévio)
    5. Scrape main page com fallback
    6. Extrair e selecionar links
    7. Scrape subpages em paralelo
    8. Consolidar e registrar aprendizado
    
    Returns:
        Tuple de (texto_agregado, lista_documentos, urls_visitadas)
    """
    overall_start = time.perf_counter()
    
    # 0. CONSULTAR CONHECIMENTO PRÉVIO OU USAR APRENDIZADO GLOBAL
    site_profile_known = site_knowledge.get_profile(url)
    
    if site_profile_known and site_profile_known.total_attempts > 0:
        # Site já conhecido - usar conhecimento específico
        known_strategy = site_profile_known.best_strategy
        known_protection = site_profile_known.protection_type
        logger.info(f"{ctx_label} 📚 Conhecimento específico: proteção={known_protection}, estratégia={known_strategy}")
    else:
        # Site NOVO - usar aprendizado global dos padrões
        known_strategy = adaptive_config.get_default_strategy_for_new_site()
        known_protection = "none"
        if known_strategy != "standard":
            logger.info(f"{ctx_label} 🧠 Usando aprendizado global: estratégia={known_strategy} (baseado em padrões)")
    
    # 1. PROBE URL
    try:
        best_url, probe_time = await url_prober.probe(url)
        logger.info(f"{ctx_label} 🎯 URL selecionada: {best_url} ({probe_time:.0f}ms)")
        url = best_url
    except URLNotReachable as e:
        logger.error(f"{ctx_label} ❌ URL inacessível: {url} - {e}")
        failure_tracker.record_failure(
            module=FailureModule.SCRAPER,
            error_type=FailureType.CONNECTION_ERROR,
            url=url,
            error_message=str(e),
            duration_ms=(time.perf_counter() - overall_start) * 1000
        )
        return "", [], []
    except Exception as e:
        logger.warning(f"{ctx_label} ⚠️ Erro no probe, usando URL original: {e}")
    
    # 2. ANALISAR SITE
    analysis_start = time.perf_counter()
    site_profile = await site_analyzer.analyze(url, ctx_label=ctx_label)
    analysis_time_ms = (time.perf_counter() - analysis_start) * 1000
    
    # 3. SELECIONAR ESTRATÉGIAS (priorizar conhecimento prévio)
    strategies = strategy_selector.select(site_profile)
    
    # Se temos conhecimento prévio de uma estratégia melhor, priorizá-la
    if known_strategy != "standard":
        try:
            known_strat_enum = ScrapingStrategy(known_strategy)
            if known_strat_enum in strategies:
                strategies.remove(known_strat_enum)
            strategies.insert(0, known_strat_enum)
            logger.info(f"{ctx_label} 📋 Estratégias (priorizando aprendizado): {[s.value for s in strategies]}")
        except ValueError:
            logger.info(f"{ctx_label} 📋 Estratégias: {[s.value for s in strategies]}")
    else:
        logger.info(f"{ctx_label} 📋 Estratégias: {[s.value for s in strategies]}")
    
    # 4. SCRAPE MAIN PAGE
    main_page = await _scrape_main_page(url, strategies, site_profile, ctx_label)
    
    if not main_page or not main_page.success:
        logger.error(f"{ctx_label} ❌ Falha ao obter main page de {url}")
        failure_tracker.record_failure(
            module=FailureModule.SCRAPER,
            error_type=_classify_error(main_page.error if main_page else "unknown"),
            url=url,
            error_message=main_page.error if main_page else "No content",
            context={"site_type": site_profile.site_type.value if site_profile else "unknown"},
            strategy_used=str(strategies[0].value) if strategies else "",
            duration_ms=(time.perf_counter() - overall_start) * 1000
        )
        site_knowledge.record_failure(url, main_page.error if main_page else "unknown")
        return "", [], []
    
    # 5. CONFIGURAÇÃO DE PERFORMANCE
    probe_ms = probe_time if 'probe_time' in locals() else 0
    main_ms = getattr(main_page, "response_time_ms", 0) or 0
    slow_mode = (
        (probe_ms and probe_ms > scraper_config.slow_probe_threshold_ms) or
        (analysis_time_ms > scraper_config.slow_main_threshold_ms) or
        (main_ms > scraper_config.slow_main_threshold_ms)
    )
    
    # Ajustar timeout e concorrência baseada na lentidão do site
    per_request_timeout = (
        scraper_config.slow_per_request_timeout
        if slow_mode else
        scraper_config.fast_per_request_timeout
    )
    
    # 6. SELECIONAR SUBPÁGINAS RELEVANTES
    # Sempre buscar subpáginas relevantes para compor perfil completo
    target_subpages = await select_links_with_llm(
        set(main_page.links), url, max_links=max_subpages, ctx_label=ctx_label
    )
    
    # 7. SCRAPE SUBPAGES
    subpages = []
    if target_subpages:
        # Definir limite seguro de subpáginas se necessário
        effective_cap = scraper_config.slow_subpage_cap if slow_mode else max_subpages
        # Ignorar cap agressivo do slow mode se for muito baixo (ex: < 5) para garantir qualidade
        if effective_cap < 5: 
            effective_cap = 10

        subpages = await _scrape_subpages_adaptive(
            target_subpages, 
            main_page.strategy_used,
            site_profile,
            slow_mode=slow_mode,
            subpage_cap=effective_cap,
            per_request_timeout=per_request_timeout,
            ctx_label=ctx_label
        )
    
    # 8. CONSOLIDAR
    content = ScrapedContent(
        main_url=url,
        main_page=main_page,
        subpages=subpages,
        total_time_ms=(time.perf_counter() - overall_start) * 1000,
        strategies_tried=strategies
    )
    
    total_duration = time.perf_counter() - overall_start
    total_duration_ms = total_duration * 1000
    
    # 9. REGISTRAR APRENDIZADO
    if content.success_rate > 0.5:
        site_knowledge.record_success(
            url, 
            response_time_ms=total_duration_ms,
            strategy_used=main_page.strategy_used.value if main_page.strategy_used else "standard"
        )
        # Atualizar proteção conhecida se detectada
        if site_profile and site_profile.protection_type.value != "none":
            site_knowledge.update_profile(
                url,
                protection_type=site_profile.protection_type.value
            )
    
    logger.info(
        f"{ctx_label} [PERF] scrape_url total={total_duration:.3f}s "
        f"pages={len(content.visited_urls)} success_rate={content.success_rate:.1%}"
    )
    
    return content.aggregated_content, content.all_document_links, content.visited_urls


async def scrape_batch_hybrid(urls: List[str], max_subpages: int = 100) -> List[Tuple[str, List[str], List[str]]]:
    """
    Processa um lote de URLs usando a estratégia Híbrida (Fast Path + Retry Path).
    
    Fase 1 (Fast Track): Processa todas URLs com timeout curto e alta concorrência.
    Fase 2 (Retry Track): Reprocessa falhas com timeout longo e limites estritos.
    """
    logger.info(f"🚀 Iniciando scrape híbrido para {len(urls)} URLs")
    results = {}
    failed_urls = []
    
    # --- FASE 1: FAST TRACK ---
    logger.info("⚡ FAST TRACK: Iniciando processamento rápido...")
    scraper_config.update(**FAST_TRACK_CONFIG)
    
    # Usar concorrência alta para Fast Track (ex: 60)
    fast_sem = asyncio.Semaphore(60)
    fast_timeout = 35.0
    
    async def fast_scrape(url):
        async with fast_sem:
            try:
                # Envolver scrape_url com timeout curto
                return await asyncio.wait_for(scrape_url(url, max_subpages), timeout=fast_timeout)
            except Exception as e:
                return e

    tasks = [fast_scrape(url) for url in urls]
    fast_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for url, res in zip(urls, fast_results):
        # Verificar se houve sucesso (conteúdo retornado)
        if isinstance(res, Exception) or not res or (isinstance(res, tuple) and not res[0]):
            failed_urls.append(url)
        else:
            results[url] = res
            
    logger.info(f"⚡ FAST TRACK Concluído: {len(results)} sucessos, {len(failed_urls)} falhas")
    
    if not failed_urls:
        return [results.get(url, ("", [], [])) for url in urls]
    
    # --- FASE 2: RETRY TRACK ---
    logger.info(f"🐢 RETRY TRACK: Reprocessando {len(failed_urls)} falhas...")
    scraper_config.update(**RETRY_TRACK_CONFIG)
    
    # Resetar circuit breaker para dar nova chance
    from .circuit_breaker import _domain_failures
    _domain_failures.clear()
    
    # Usar concorrência baixa para Retry Track (ex: 5)
    retry_sem = asyncio.Semaphore(5)
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
    
    logger.info(f"🐢 RETRY TRACK Concluído: {success_retry}/{len(failed_urls)} recuperados")
    
    # Ordenar resultados na ordem original
    final_output = [results.get(url, ("", [], [])) for url in urls]
    return final_output


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


async def _scrape_main_page(
    url: str, 
    strategies: List[ScrapingStrategy],
    site_profile: SiteProfile,
    ctx_label: str = ""
) -> Optional[ScrapedPage]:
    """
    Faz scrape da main page com fallback entre estratégias.
    Simplificado: Removeu lógica de 'Rescue Mode' para conteúdo insuficiente.
    """
    main_start = time.perf_counter()
    
    for strategy in strategies:
        config = strategy_selector.get_strategy_config(strategy)
        logger.info(f"{ctx_label} 🔄 Tentando estratégia {strategy.value} para main page")
        
        try:
            page = await _execute_strategy(url, strategy, config)
            
            if page and page.success:
                page.response_time_ms = (time.perf_counter() - main_start) * 1000
                logger.info(
                    f"{ctx_label} ✅ Main page OK com {strategy.value}: "
                    f"{len(page.content or '')} chars, {len(page.links)} links"
                )
                return page
            
            # Verificar se é proteção que bloqueia
            if page and page.content:
                protection = protection_detector.detect(
                    response_body=page.content,
                    status_code=page.status_code
                )
                if protection_detector.is_blocking_protection(protection):
                    rec = protection_detector.get_retry_recommendation(protection)
                    logger.warning(
                        f"{ctx_label} ⚠️ Proteção {protection.value} detectada. "
                        f"Aguardando {rec['delay_seconds']}s..."
                    )
                    await asyncio.sleep(rec['delay_seconds'])
                    
        except Exception as e:
            logger.warning(f"{ctx_label} ⚠️ Estratégia {strategy.value} falhou: {e}")
            continue
    
    logger.error(f"{ctx_label} ❌ Todas estratégias falharam para {url}")
    return None


async def _execute_strategy(
    url: str, 
    strategy: ScrapingStrategy, 
    config: dict
) -> Optional[ScrapedPage]:
    """Executa uma estratégia específica de scraping."""
    headers = DEFAULT_HEADERS.copy()
    
    # Rotação de User-Agent se configurado
    if config.get("rotate_ua"):
        headers["User-Agent"] = random.choice(USER_AGENTS)
    
    # Proxy se configurado
    proxy = None
    if config.get("use_proxy"):
        proxy = await _get_healthy_proxy()
        if config.get("rotate_proxy"):
            # Tentar múltiplos proxies
            for _ in range(3):
                try:
                    page = await _do_scrape(url, proxy, headers, config["timeout"])
                    if page.success:
                        page.strategy_used = strategy
                        return page
                except:
                    proxy = await _get_healthy_proxy()
    
    # Executar scrape
    page = await _do_scrape(url, proxy, headers, config["timeout"])
    page.strategy_used = strategy
    return page


async def _do_scrape(
    url: str, 
    proxy: Optional[str], 
    headers: dict,
    timeout: int
) -> ScrapedPage:
    """Executa o scrape real."""
    try:
        text, docs, links = await cffi_scrape_safe(url, proxy)
        
        # Verificar qualidade do conteúdo
        if not text or len(text) < 100:
            # Fallback para system curl
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


async def _scrape_subpages_adaptive(
    target_subpages: List[str],
    main_strategy: ScrapingStrategy,
    site_profile: SiteProfile,
    slow_mode: bool = False,
    subpage_cap: Optional[int] = None,
    per_request_timeout: Optional[int] = None,
    ctx_label: str = ""
) -> List[ScrapedPage]:
    """
    Faz scrape das subpáginas usando BATCH SCRAPING.
    
    Estratégia híbrida que equilibra velocidade e confiabilidade:
    - Processa em mini-batches paralelos (3-5 páginas por vez)
    - Delays aleatórios entre batches (3-7s)
    - Simula navegação humana natural
    - 3-5x mais rápido que sequencial puro
    """
    subpages_start = time.perf_counter()
    logger.info(f"{ctx_label} [Scraper] Processing {len(target_subpages)} subpages (batch mode: {scraper_config.batch_size} per batch)")
    
    # Limitar quantidade de subpáginas se necessário
    if subpage_cap:
        target_subpages = target_subpages[:subpage_cap]
    
    # Usar estratégia batch para equilíbrio entre velocidade e confiabilidade
    results = await _scrape_subpages_sequential(
        target_subpages,
        main_strategy,
        per_request_timeout,
        ctx_label
    )

    success_count = sum(1 for p in results if p.success)
    subpages_duration = time.perf_counter() - subpages_start
    logger.info(
        f"{ctx_label} [PERF] subpages duration={subpages_duration:.3f}s "
        f"requested={len(target_subpages)} ok={success_count}"
    )
    
    return results


async def _scrape_subpages_sequential(
    target_subpages: List[str],
    main_strategy: ScrapingStrategy,
    per_request_timeout: Optional[int] = None,
    ctx_label: str = ""
) -> List[ScrapedPage]:
    """
    Faz scrape das subpáginas usando BATCH SCRAPING (meio termo entre sequencial e paralelo).
    
    Estratégia:
    - Processa páginas em mini-batches (3-5 por vez)
    - Delay aleatório entre batches (3-7s) para simular navegação humana
    - Usa mesmo proxy/sessão dentro do batch
    - Evita detecção de bot mantendo controle de taxa
    
    Benefícios:
    - 3-5x mais rápido que sequencial puro
    - Não sobrecarrega o servidor
    - Simula comportamento humano (navegação em abas)
    - Baixo risco de bloqueio
    """
    import random
    
    config = strategy_selector.get_strategy_config(main_strategy)
    effective_timeout = per_request_timeout or config["timeout"]
    
    results = []
    
    # Obter um proxy saudável para usar em todas as requisições
    shared_proxy = await _get_healthy_proxy()
    logger.info(f"{ctx_label} [Scraper] Using batch scraping mode (batch_size={scraper_config.batch_size})")
    
    # Dividir em batches
    batch_size = scraper_config.batch_size
    batches = [target_subpages[i:i + batch_size] for i in range(0, len(target_subpages), batch_size)]
    
    total_processed = 0
    
    for batch_idx, batch in enumerate(batches):
        batch_start = time.perf_counter()
        
        # Processar batch em paralelo (dentro do batch)
        batch_results = await _scrape_batch_parallel(
            batch, 
            main_strategy, 
            shared_proxy, 
            effective_timeout,
            total_processed,
            len(target_subpages),
            ctx_label
        )
        results.extend(batch_results)
        total_processed += len(batch)
        
        batch_duration = time.perf_counter() - batch_start
        
        # Delay entre batches (exceto após o último)
        if batch_idx < len(batches) - 1:
            # Delay aleatório para simular comportamento humano
            delay = random.uniform(
                scraper_config.batch_min_delay, 
                scraper_config.batch_max_delay
            )
            logger.debug(
                f"{ctx_label} [Batch {batch_idx+1}/{len(batches)}] "
                f"Concluído em {batch_duration:.1f}s. "
                f"Aguardando {delay:.1f}s antes do próximo batch..."
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
    ctx_label: str = ""
) -> List[ScrapedPage]:
    """
    Processa um batch de URLs em paralelo com delays internos.
    """
    config = strategy_selector.get_strategy_config(main_strategy)
    results = []
    
    async def scrape_with_delay(i: int, url: str) -> ScrapedPage:
        """Scrape uma URL com delay interno ao batch."""
        # Delay proporcional à posição no batch (para não disparar todos de uma vez)
        if i > 0:
            await asyncio.sleep(scraper_config.intra_batch_delay * i)
        
        # Verificar circuit breaker
        if is_circuit_open(url):
            return ScrapedPage(url=url, content="", error="Circuit open")
        
        normalized_url = normalize_url(url)
        global_index = start_index + i + 1
        
        try:
            logger.debug(f"{ctx_label} [Batch] {global_index}/{total_urls}: {normalized_url[:60]}")
            
            # Tentar com cffi primeiro
            if HAS_CURL_CFFI and AsyncSession:
                try:
                    async with AsyncSession(
                        impersonate="chrome120",
                        proxy=shared_proxy,
                        timeout=effective_timeout,
                        verify=False
                    ) as session:
                        page = await _scrape_single_subpage(
                            normalized_url, session, config, effective_timeout, ctx_label
                        )
                        if page.success:
                            logger.info(f"{ctx_label}    ✅ [{global_index}/{total_urls}] {normalized_url[:50]} ({len(page.content)} chars)")
                        else:
                            logger.debug(f"{ctx_label}    ⚠️ [{global_index}/{total_urls}] {normalized_url[:50]} - {page.error}")
                        return page
                except Exception as e:
                    logger.debug(f"{ctx_label}    cffi failed, trying fallback: {e}")
            
            # Fallback para system_curl
            page = await _scrape_single_subpage_fallback(
                normalized_url, shared_proxy, effective_timeout, ctx_label
            )
            
            if page.success:
                logger.info(f"{ctx_label}    ✅ [{global_index}/{total_urls}] {normalized_url[:50]} ({len(page.content)} chars)")
            else:
                logger.debug(f"{ctx_label}    ⚠️ [{global_index}/{total_urls}] {normalized_url[:50]} - {page.error}")
            
            return page
                
        except Exception as e:
            logger.warning(f"{ctx_label}    ❌ [{global_index}/{total_urls}] {normalized_url[:50]} - {e}")
            return ScrapedPage(url=normalized_url, content="", error=str(e))
    
    # Processar todas URLs do batch em paralelo
    tasks = [scrape_with_delay(i, url) for i, url in enumerate(urls)]
    results = await asyncio.gather(*tasks)
    
    return results


async def _scrape_subpages_parallel(
    target_subpages: List[str],
    main_strategy: ScrapingStrategy,
    site_profile: SiteProfile,
    slow_mode: bool = False,
    subpage_cap: Optional[int] = None,
    per_request_timeout: Optional[int] = None
) -> List[ScrapedPage]:
    """
    Faz scrape das subpáginas em PARALELO (versão antiga, mantida para referência).
    Mais rápido, porém pode sobrecarregar sites frágeis.
    """
    # Limitar quantidade de subpáginas se necessário
    if subpage_cap:
        target_subpages = target_subpages[:subpage_cap]
    
    chunk_size = scraper_config.chunk_size
    url_chunks = [target_subpages[i:i + chunk_size] for i in range(0, len(target_subpages), chunk_size)]
    
    chunk_limit = (
        scraper_config.slow_chunk_semaphore_limit if slow_mode
        else scraper_config.chunk_semaphore_limit
    )
    chunk_sem = asyncio.Semaphore(chunk_limit)
    
    async def scrape_chunk_wrapper(chunk):
        async with chunk_sem:
            return await _scrape_chunk_adaptive(
                chunk, main_strategy, slow_mode=slow_mode, per_request_timeout=per_request_timeout
            )

    tasks = [scrape_chunk_wrapper(chunk) for chunk in url_chunks]
    results_of_chunks = await asyncio.gather(*tasks)
    
    results = []
    for chunk_res in results_of_chunks:
        results.extend(chunk_res)
    
    return results


async def _scrape_chunk_adaptive(
    urls_chunk: List[str],
    main_strategy: ScrapingStrategy,
    slow_mode: bool = False,
    per_request_timeout: Optional[int] = None
) -> List[ScrapedPage]:
    """
    Faz scrape de um chunk de URLs com estratégia adaptativa.
    OTIMIZADO v2: Cada subpágina usa um PROXY DIFERENTE para evitar rate limiting.
    """
    config = strategy_selector.get_strategy_config(main_strategy)
    effective_timeout = per_request_timeout or config["timeout"]
    
    # Filtrar URLs com circuit breaker aberto
    urls_to_process = []
    circuit_open_results = []
    
    for sub_url in urls_chunk:
        if is_circuit_open(sub_url):
            circuit_open_results.append(ScrapedPage(url=sub_url, content="", error="Circuit open"))
        else:
            urls_to_process.append(normalize_url(sub_url))
    
    if not urls_to_process:
        return circuit_open_results
    
    # Semáforo interno para limitar paralelismo (evita sobrecarga)
    internal_limit = (
        scraper_config.slow_chunk_internal_limit if slow_mode
        else scraper_config.fast_chunk_internal_limit
    )
    chunk_internal_sem = asyncio.Semaphore(internal_limit)
    
    async def scrape_with_individual_proxy(url: str) -> ScrapedPage:
        """Scrape uma URL com seu próprio proxy."""
        async with chunk_internal_sem:
            # Limite por domínio
            host = urlparse(url).netloc
            domain_sem = _get_domain_semaphore(host)
            async with domain_sem:
                individual_proxy = await _get_healthy_proxy()
                
            if HAS_CURL_CFFI and AsyncSession:
                try:
                    async with AsyncSession(
                        impersonate="chrome120",
                        proxy=individual_proxy,
                        timeout=effective_timeout,
                        verify=False
                    ) as session:
                        return await _scrape_single_subpage(
                            url, session, config, effective_timeout
                        )
                except Exception:
                    # Fallback para system_curl
                    return await _scrape_single_subpage_fallback(
                        url, individual_proxy, effective_timeout
                    )
            else:
                return await _scrape_single_subpage_fallback(
                    url, individual_proxy, effective_timeout
                )
    
    # Processar todas URLs em paralelo, cada uma com seu proxy
    tasks = [scrape_with_individual_proxy(url) for url in urls_to_process]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Processar resultados
    chunk_results = []
    for url, result in zip(urls_to_process, results):
        if isinstance(result, Exception):
            chunk_results.append(ScrapedPage(url=url, content="", error=str(result)))
    else:
            chunk_results.append(result)
    
    return circuit_open_results + chunk_results


async def _scrape_single_subpage_fallback(
    url: str,
    proxy: Optional[str],
    per_request_timeout: int,
    ctx_label: str = ""
) -> ScrapedPage:
    """Faz scrape usando system_curl quando curl_cffi não está disponível."""
    try:
        text, docs, _ = await asyncio.wait_for(
            system_curl_scrape(url, proxy),
            timeout=per_request_timeout
        )
        
        if not text or len(text) < 100 or is_soft_404(text):
            record_failure(url)
            return ScrapedPage(url=url, content="", error="Empty or soft 404")
        
        record_success(url)
        logger.debug(f"{ctx_label} [Sub] ✅ {url[:60]} ({len(text)} chars)")
        return ScrapedPage(
            url=url,
            content=text,
            document_links=list(docs),
            status_code=200
        )
    except Exception as e:
        record_failure(url)
        return ScrapedPage(url=url, content="", error=str(e))


async def _scrape_single_subpage(
    url: str,
    session: AsyncSession,
    config: dict,
    per_request_timeout: int,
    ctx_label: str = ""
) -> ScrapedPage:
    """Faz scrape de uma única subpágina."""
    try:
        text, docs, _ = await asyncio.wait_for(
            cffi_scrape(url, proxy=None, session=session),
            timeout=per_request_timeout
        )
        
        is_cf = is_cloudflare_challenge(text) if text else False
        
        if not text or len(text) < 100 or is_soft_404(text):
            record_failure(url, is_protection=is_cf)
            
            # Fallback
            fallback_proxy = await _get_healthy_proxy()
            text, docs, _ = await asyncio.wait_for(
                system_curl_scrape(url, fallback_proxy),
                timeout=per_request_timeout
            )
            
            if not text or len(text) < 100 or is_soft_404(text):
                record_failure(url)
                return ScrapedPage(url=url, content="", error="Empty or soft 404")
        
        record_success(url)
        logger.debug(f"{ctx_label} [Sub] ✅ {url[:60]} ({len(text)} chars)")
        
        return ScrapedPage(
            url=url,
            content=text,
            document_links=list(docs),
            status_code=200
        )
        
    except Exception as e:
        record_failure(url)
        return ScrapedPage(url=url, content="", error=str(e))
