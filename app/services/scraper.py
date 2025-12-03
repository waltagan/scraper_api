import asyncio
import subprocess
import random
import logging
import time
from typing import List, Tuple, Set, Optional
from urllib.parse import urljoin, urlparse, quote, unquote
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession, RequestsError
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, BrowserConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from tenacity import retry, stop_after_attempt, wait_fixed, wait_exponential, retry_if_exception_type, before_sleep_log, RetryError
from app.core.proxy import proxy_manager

# Playwright error imports para tratamento específico
try:
    from playwright._impl._errors import TargetClosedError, TimeoutError as PlaywrightTimeout
except ImportError:
    # Fallback se os tipos não estiverem disponíveis
    TargetClosedError = Exception
    PlaywrightTimeout = Exception

# Configurar logger
logger = logging.getLogger(__name__)

# --- SCRAPER CONFIGURATION ---
# Parâmetros configuráveis dinamicamente para otimização
# Configuração otimizada para velocidade agressiva (Round 4 Benchmark)
_scraper_config = {
    'playwright_semaphore_limit': 40,
    'circuit_breaker_threshold': 2,
    'page_timeout': 10000,
    'md_threshold': 0.6,
    'min_word_threshold': 4,
    'chunk_size': 20,
    'chunk_semaphore_limit': 50,
    'session_timeout': 5
}

# Global semaphore to limit concurrent Playwright instances
# Prevents resource exhaustion and browser crashes
playwright_semaphore = asyncio.Semaphore(_scraper_config['playwright_semaphore_limit'])

# --- CIRCUIT BREAKER ---
# Dicionário global para rastrear falhas consecutivas por domínio
# Chave: domínio (netloc), Valor: contador de falhas
domain_failures = {}
# Limite de falhas para abrir o circuito
CIRCUIT_BREAKER_THRESHOLD = _scraper_config['circuit_breaker_threshold']

def configure_scraper_params(
    playwright_semaphore_limit: int = 10,
    circuit_breaker_threshold: int = 5,
    page_timeout: int = 60000,
    md_threshold: float = 0.35,
    min_word_threshold: int = 5,
    chunk_size: int = 3,
    chunk_semaphore_limit: int = 30,
    session_timeout: int = 15
):
    """
    Configura dinamicamente os parâmetros do scraper para otimização.

    Args:
        playwright_semaphore_limit: Limite de instâncias Playwright concorrentes
        circuit_breaker_threshold: Limite de falhas para ativar circuit breaker
        page_timeout: Timeout da página em ms
        md_threshold: Threshold do markdown generator
        min_word_threshold: Threshold mínimo de palavras
        chunk_size: Tamanho dos chunks para processamento paralelo
        chunk_semaphore_limit: Limite do semáforo de chunks
        session_timeout: Timeout das sessões em segundos
    """
    global _scraper_config, playwright_semaphore, CIRCUIT_BREAKER_THRESHOLD

    # Atualizar configuração global
    _scraper_config.update({
        'playwright_semaphore_limit': playwright_semaphore_limit,
        'circuit_breaker_threshold': circuit_breaker_threshold,
        'page_timeout': page_timeout,
        'md_threshold': md_threshold,
        'min_word_threshold': min_word_threshold,
        'chunk_size': chunk_size,
        'chunk_semaphore_limit': chunk_semaphore_limit,
        'session_timeout': session_timeout
    })

    # Recriar semáforos com novos limites
    playwright_semaphore = asyncio.Semaphore(playwright_semaphore_limit)
    CIRCUIT_BREAKER_THRESHOLD = circuit_breaker_threshold

    # Resetar circuit breaker
    domain_failures.clear()

    logger.info(f"🔧 Scraper reconfigurado: semaphore={playwright_semaphore_limit}, "
                f"circuit_breaker={circuit_breaker_threshold}, page_timeout={page_timeout}, "
                f"md_threshold={md_threshold}, min_word_threshold={min_word_threshold}, "
                f"chunk_size={chunk_size}, chunk_semaphore={chunk_semaphore_limit}, "
                f"session_timeout={session_timeout}")
# Tempo de reset do circuito (não implementado full, apenas reset manual ou restart)

def _get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except:
        return "unknown"

def _record_failure(url: str):
    domain = _get_domain(url)
    domain_failures[domain] = domain_failures.get(domain, 0) + 1
    if domain_failures[domain] >= CIRCUIT_BREAKER_THRESHOLD:
        logger.warning(f"🔌 CIRCUIT BREAKER ABERTO para {domain} após {domain_failures[domain]} falhas consecutivas")

def _record_success(url: str):
    domain = _get_domain(url)
    if domain in domain_failures:
        # Resetar contador em caso de sucesso (Half-Open logic simplificada)
        domain_failures[domain] = 0

def _is_circuit_open(url: str) -> bool:
    domain = _get_domain(url)
    return domain_failures.get(domain, 0) >= CIRCUIT_BREAKER_THRESHOLD

@retry(
    retry=retry_if_exception_type((TargetClosedError, PlaywrightTimeout)),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(2),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
async def _playwright_scrape_with_retry(url: str, proxy: Optional[str]) -> Tuple[str, Set[str], Set[str]]:
    """
    Wrapper com retry para chamadas do Playwright.
    Tenta 2x com backoff exponencial antes de desistir.
    Registra tempo total da navegação Playwright.
    """
    start_ts = time.perf_counter()
    # Ajustar filtro para ser menos agressivo e preservar mais conteúdo
    # threshold menor = menos agressivo (mantém mais conteúdo)
    # min_word_threshold menor = aceita textos menores
    md_generator = DefaultMarkdownGenerator(content_filter=PruningContentFilter(
        threshold=_scraper_config['md_threshold'],
        min_word_threshold=_scraper_config['min_word_threshold']
    ))
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        exclude_external_images=True,
        markdown_generator=md_generator,
        page_timeout=_scraper_config['page_timeout']
    )
    browser_config = BrowserConfig(
        browser_type="chromium", 
        headless=True, 
        proxy_config=proxy, 
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    
    crawler = None
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config, magic=True)
            
            if not result.success or not result.markdown or len(result.markdown) < 200:
                raise Exception("Playwright failed or content too short")
            
            # Extrair links de Markdown E HTML para garantir cobertura total
            # Markdown falha em links de imagem (nested brackets) -> HTML resolve
            pdfs_md, links_md = _extract_links(result.markdown, url)
            pdfs_html, links_html = _extract_links_html(result.html, url)
            
            # Combinar resultados (união de sets)
            pdfs = pdfs_md | pdfs_html
            links = links_md | links_html
            
            duration = time.perf_counter() - start_ts
            logger.info(
                f"[PERF] scraper step=playwright_main url={url} "
                f"duration={duration:.3f}s markdown_chars={len(result.markdown)} "
                f"pdfs={len(pdfs)} links={len(links)}"
            )
            return result.markdown, pdfs, links
            
    finally:
        # ✅ CORREÇÃO 4: Garantir cleanup adequado
        if crawler is not None:
            try:
                await crawler.close()
            except:
                pass  # Já foi fechado ou erro ao fechar

async def scrape_url(url: str, max_subpages: int = 100) -> Tuple[str, List[str], List[str]]:
    """
    High-performance scraper with IP Rotation and Parallelism.
    Strategy:
    1. Main Page: Playwright (JS support) with fresh proxy.
    2. Subpages: Parallel Curl Impersonation tasks (max concurrency 10) with unique IPs.
    Registra métricas de tempo por etapa (main, seleção de links, subpáginas).
    """
    overall_start = time.perf_counter()
    aggregated_markdown = []
    all_pdf_links = set()
    visited_urls = []

    # --- 1. SCRAPE MAIN PAGE (Playwright) ---
    # ✅ CORREÇÃO 3: Usar semaphore para limitar concorrência
    main_start = time.perf_counter()
    async with playwright_semaphore:
        print(f"[Scraper] Processing Main: {url}")
        main_proxy = await proxy_manager.get_next_proxy()
        
        try:
            # ✅ CORREÇÃO 5: Usar função com retry automático
            markdown, pdfs, links = await _playwright_scrape_with_retry(url, main_proxy)
            
            visited_urls.append(url)
            aggregated_markdown.append(f"--- PAGE START: {url} ---\n{markdown}\n--- PAGE END ---\n")
            all_pdf_links.update(pdfs)
            
        except TargetClosedError as e:
            # ✅ CORREÇÃO 2: Tratamento específico de TargetClosedError
            logger.warning(f"[Main] Playwright browser closed unexpectedly: {e}. Using Curl fallback.")
            text, pdfs, links = await _system_curl_scrape(url, await proxy_manager.get_next_proxy())
            if text:
                visited_urls.append(url)
                aggregated_markdown.append(f"--- PAGE START: {url} ---\n{text}\n--- PAGE END ---\n")
                all_pdf_links.update(pdfs)
            else:
                return "", [], []
                
        except (PlaywrightTimeout, asyncio.TimeoutError) as e:
            # ✅ CORREÇÃO 2: Tratamento específico de timeout
            logger.warning(f"[Main] Playwright timeout: {e}. Using Curl fallback.")
            text, pdfs, links = await _system_curl_scrape(url, await proxy_manager.get_next_proxy())
            if text:
                visited_urls.append(url)
                aggregated_markdown.append(f"--- PAGE START: {url} ---\n{text}\n--- PAGE END ---\n")
                all_pdf_links.update(pdfs)
            else:
                return "", [], []
                
        except Exception as e:
            # ✅ CORREÇÃO 2: Catch-all com fallback
            logger.error(f"[Main] Playwright failed: {e}. Trying System Curl Fallback.")
            text, pdfs, links = await _system_curl_scrape(url, await proxy_manager.get_next_proxy())
            if text:
                visited_urls.append(url)
                aggregated_markdown.append(f"--- PAGE START: {url} ---\n{text}\n--- PAGE END ---\n")
                all_pdf_links.update(pdfs)
            else:
                # TENTATIVA FINAL: Smart URL Retry (Adicionar/Remover www)
                # Resolve problemas como deltaaut.com vs www.deltaaut.com se o DNS falhar
                parsed = urlparse(url)
                new_netloc = None
                if parsed.netloc.startswith("www."):
                    new_netloc = parsed.netloc[4:]
                else:
                    new_netloc = f"www.{parsed.netloc}"
                
                if new_netloc:
                    new_url = parsed._replace(netloc=new_netloc).geturl()
                    logger.warning(f"[Main] Falha total em {url}. Tentando variação: {new_url}")
                    text, pdfs, links = await _system_curl_scrape(new_url, await proxy_manager.get_next_proxy())
                    if text:
                        visited_urls.append(new_url) # Registrar a URL que funcionou
                        aggregated_markdown.append(f"--- PAGE START: {new_url} ---\n{text}\n--- PAGE END ---\n")
                        all_pdf_links.update(pdfs)
                        # Atualizar URL base para seleção de links subsequente
                        url = new_url 
                    else:
                        return "", [], []
                else:
                    return "", [], []

    main_duration = time.perf_counter() - main_start
    logger.info(
        f"[PERF] scraper step=main_page url={url} "
        f"duration={main_duration:.3f}s pages=1 pdfs={len(all_pdf_links)} links={len(links)}"
    )

    # --- 2. SCRAPE SUBPAGES (Parallel + Rotation) ---
    # Usar LLM para seleção inteligente de links (muito melhor que regras hardcoded!)
    logger.info(f"[Scraper] Encontrados {len(links)} links. Usando LLM para selecionar os mais relevantes...")
    target_subpages = await _select_links_with_llm(links, url, max_links=max_subpages)
    
    if target_subpages:
        subpages_start = time.perf_counter()
        print(f"[Scraper] Processing {len(target_subpages)} subpages with Parallel IP Rotation & Session Reuse")
        
        # Semaphore to limit concurrency (avoid overwhelming proxy provider or local resources)
        sem = asyncio.Semaphore(10) 
        
        # Agrupar subpáginas para processamento em lote (tentativa de Session Reuse)
        # Como o código original processa em paralelo individualmente, vamos manter a estrutura
        # mas injetar a lógica de sessão persistente DENTRO da task se possível, 
        # ou melhor: usar um gerenciador de sessão que reutiliza sessões por proxy.
        #
        # DADO A ESTRUTURA ATUAL de tasks independentes, o melhor é:
        # Tentar usar uma sessão "Sticky" por Batch de URLs se formos reestruturar,
        # MAS para manter a compatibilidade com o fluxo atual:
        # Vamos criar um pool de sessões ou simplesmente permitir que o scrape_subpage crie uma sessão
        # e tente reusá-la se falhar e precisar de retry? Não, o retry troca de proxy.
        #
        # ESTRATÉGIA CORRIGIDA PARA KEEP-ALIVE:
        # O Keep-Alive só funciona se fizermos múltiplas requisições COM O MESMO PROXY.
        # O modelo atual (Task Paralela -> Pega Proxy -> Faz 1 Request) mata o Keep-Alive.
        #
        # MUDANÇA: Agrupar URLs por "Lote de Proxy".
        # Vamos dividir as URLs em chunks de 5. Para cada chunk, pegamos 1 proxy e usamos 1 sessão.
        
        # 1. Agrupar URLs em chunks
        # Reduzir tamanho do chunk para minimizar Head-of-Line Blocking (uma URL lenta travar as outras do mesmo proxy)
        chunk_size = _scraper_config['chunk_size']
        url_chunks = [target_subpages[i:i + chunk_size] for i in range(0, len(target_subpages), chunk_size)]
        
        async def scrape_chunk(urls_chunk):
            chunk_results = []
            # Obter proxy e criar sessão para este chunk
            chunk_proxy = await proxy_manager.get_next_proxy()
            
            # Usar Context Manager para garantir fechamento da sessão
            try:
                # Timeout reduzido para ser mais agressivo (15s total para o chunk não ficar preso)
                # O "Fail Fast" real acontece na conexão.
                async with AsyncSession(
                    impersonate="chrome120",
                    proxy=chunk_proxy,
                    timeout=_scraper_config['session_timeout'],
                    verify=False
                ) as session:
                    
                    for sub_url in urls_chunk:
                        # Verificar Circuit Breaker antes de processar
                        if _is_circuit_open(sub_url):
                            logger.warning(f"🔌 [CircuitBreaker] Pulando {sub_url} devido a falhas excessivas no domínio")
                            chunk_results.append(None)
                            continue

                        # Normalizar URL
                        normalized_url = _normalize_url(sub_url)
                        
                        # Tentativa com a sessão persistente (Keep-Alive Reuse)
                        try:
                            logger.debug(f"[Sub] Processando {normalized_url} com sessão persistente...")
                            text, pdfs, _ = await _cffi_scrape(normalized_url, proxy=None, session=session) # Proxy já na sessão
                            
                            if text and len(text) >= 100:
                                logger.info(f"[Sub] ✅ Success (Keep-Alive): {normalized_url} ({len(text)} chars)")
                                _record_success(normalized_url)
                                chunk_results.append((normalized_url, text, pdfs))
                                continue # Sucesso, vai para próxima URL do chunk
                            
                            # Se falhou ou conteúdo pequeno com a sessão atual, marcar falha
                            # E tentar fallback isolado (Curl System)
                            logger.warning(f"[Sub] ⚠️ Falha/Pequeno com CFFI Session em {normalized_url}. Tentando Curl Fallback...")
                            _record_failure(normalized_url)
                            
                        except Exception as e:
                            logger.warning(f"[Sub] ❌ Erro CFFI Session em {normalized_url}: {e}")
                            _record_failure(normalized_url)
                        
                        # Fallback: System Curl (Isolated)
                        # Só tenta curl se o CFFI falhou. O Curl não usa a sessão CFFI.
                        # Usa o mesmo proxy do chunk para aproveitar (ou tentar novo? melhor novo se o proxy for o problema)
                        # Vamos tentar com NOVO proxy no fallback para maximizar chance
                        try:
                            fallback_proxy = await proxy_manager.get_next_proxy()
                            text, pdfs, _ = await _system_curl_scrape(normalized_url, fallback_proxy)
                            
                            if text and len(text) >= 100:
                                logger.info(f"[Sub] ✅ Success (Curl Fallback): {normalized_url}")
                                _record_success(normalized_url)
                                chunk_results.append((normalized_url, text, pdfs))
                            else:
                                logger.warning(f"[Sub] ❌ Falha total em {normalized_url} (CFFI+Curl)")
                                _record_failure(normalized_url)
                                chunk_results.append(None)
                        except Exception as e:
                            logger.error(f"[Sub] ❌ Erro Curl Fallback em {normalized_url}: {e}")
                            _record_failure(normalized_url)
                            chunk_results.append(None)
                            
            except Exception as e_session:
                logger.error(f"[Chunk] ❌ Erro fatal na sessão do chunk (Proxy: {chunk_proxy}): {e_session}")
                # Se a sessão caiu (proxy morreu), todo o chunk falha neste design simples
                # Idealmente retentaria as URLs restantes, mas por simplicidade/performance falhamos o lote
                for _ in range(len(urls_chunk) - len(chunk_results)):
                    chunk_results.append(None)
                    
            return chunk_results

        # Launch parallel chunks
        # Aumentar drasticamente o paralelismo de chunks
        # Antes: 5 chunks (25 URLs max). Agora: 30 chunks (30 * 3 = 90 URLs max)
        # Isso aproxima a performance da V2 (fire-and-forget) mantendo a estabilidade da sessão/proxy da V3
        chunk_sem = asyncio.Semaphore(_scraper_config['chunk_semaphore_limit']) 
        
        async def scrape_chunk_wrapper(chunk):
            async with chunk_sem:
                return await scrape_chunk(chunk)

        tasks = [scrape_chunk_wrapper(chunk) for chunk in url_chunks]
        results_of_chunks = await asyncio.gather(*tasks)
        
        # Flatten results
        results = []
        for chunk_res in results_of_chunks:
            results.extend(chunk_res)

        success_subpages = 0
        for res in results:
            if res:
                sub_url, text, pdfs = res
                visited_urls.append(sub_url)
                aggregated_markdown.append(f"--- PAGE START: {sub_url} ---\n{text}\n--- PAGE END ---\n")
                all_pdf_links.update(pdfs)
                success_subpages += 1

        subpages_duration = time.perf_counter() - subpages_start
        logger.info(
            f"[PERF] scraper step=subpages url={url} "
            f"duration={subpages_duration:.3f}s subpages_requested={len(target_subpages)} "
            f"subpages_ok={success_subpages}"
        )

    total_duration = time.perf_counter() - overall_start
    logger.info(
        f"[PERF] scraper step=total url={url} "
        f"duration={total_duration:.3f}s pages={len(visited_urls)} pdfs={len(all_pdf_links)}"
    )
    return "\n".join(aggregated_markdown), list(all_pdf_links), visited_urls

# --- HELPERS ---

def _normalize_url(url: str) -> str:
    """
    Normaliza URL para lidar com caracteres especiais e encoding.
    Preserva a estrutura da URL mas garante que caracteres especiais sejam codificados corretamente.
    Remove fragmentos malformados que podem aparecer quando o título do link markdown é incluído na URL.
    """
    try:
        # Primeiro, limpar a URL removendo espaços e caracteres problemáticos no início/fim
        url = url.strip()
        
        # Se a URL contém espaços ou aspas, pode ser um problema de parsing
        # Remover aspas e espaços extras
        if url.startswith('"') and url.endswith('"'):
            url = url[1:-1]
        if url.startswith("'") and url.endswith("'"):
            url = url[1:-1]
        url = url.strip()
        
        parsed = urlparse(url)
        
        # Limpar o path removendo partes problemáticas como %20%22 (espaço + aspas codificadas)
        # Esses fragmentos geralmente aparecem quando o título do link markdown é incluído na URL
        path = parsed.path
        if '%20%22' in path or '%22' in path:
            # Encontrar onde começa o fragmento problemático e remover tudo após ele
            problematic_markers = ['%20%22', '%22']
            for marker in problematic_markers:
                if marker in path:
                    # Remover tudo após o marcador problemático
                    path = path[:path.index(marker)]
                    break
        
        # Se o path ainda não está codificado corretamente, codificar
        if '%' not in path:
            # Separar path em partes e codificar cada parte
            path_parts = path.split('/')
            encoded_parts = [quote(part, safe='') if part else part for part in path_parts]
            path = '/'.join(encoded_parts)
        
        # Limpar query string também
        query = parsed.query
        if query:
            # Remover fragmentos problemáticos da query
            if '%20%22' in query or '%22' in query:
                query = query.split('%20%22')[0].split('%22')[0]
            if query and '%' not in query:
                # Codificar query string se necessário
                query_parts = query.split('&')
                encoded_query_parts = []
                for part in query_parts:
                    if '=' in part:
                        key, value = part.split('=', 1)
                        encoded_query_parts.append(f"{quote(key, safe='')}={quote(value, safe='')}")
                    else:
                        encoded_query_parts.append(quote(part, safe=''))
                query = '&'.join(encoded_query_parts)
        
        # Reconstruir URL (sem fragment, que pode conter dados problemáticos)
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        if query:
            normalized += f"?{query}"
        # Não incluir fragment para evitar problemas com títulos de links markdown
        
        return normalized
    except Exception as e:
        logger.warning(f"Erro ao normalizar URL {url}: {e}, usando URL original")
        return url

@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def _cffi_scrape(url: str, proxy: Optional[str]) -> Tuple[str, Set[str], Set[str]]:
    start_ts = time.perf_counter()
    try:
        async with AsyncSession(impersonate="chrome120", proxy=proxy, timeout=25) as s:
            resp = await s.get(url)
            if resp.status_code != 200:
                raise Exception(f"Status {resp.status_code}")
            text, pdfs, links = _parse_html(resp.text, url)
            duration = time.perf_counter() - start_ts
            logger.debug(
                f"[PERF] scraper step=cffi_subpage url={url} "
                f"duration={duration:.3f}s text_chars={len(text)} pdfs={len(pdfs)} links={len(links)}"
            )
            return text, pdfs, links
    except Exception as e: 
        duration = time.perf_counter() - start_ts
        logger.debug(
            f"[PERF] scraper step=cffi_subpage_fail url={url} "
            f"duration={duration:.3f}s error={type(e).__name__}"
        )
        raise

# Wrapper to handle the retry exception and return empty tuple on final failure
async def _cffi_scrape_safe(url: str, proxy: Optional[str]) -> Tuple[str, Set[str], Set[str]]:
    try:
        return await _cffi_scrape(url, proxy)
    except:
        return "", set(), set()

@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def _system_curl_scrape(url: str, proxy: Optional[str]) -> Tuple[str, Set[str], Set[str]]:
    start_ts = time.perf_counter()
    try:
        cmd = ["curl", "-L", "-k", "-s"]
        if proxy: cmd.extend(["-x", proxy])
        cmd.extend(["-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36", url])
        
        res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=35)
        if res.returncode != 0 or not res.stdout:
            raise Exception("Curl Failed")
        text, pdfs, links = _parse_html(res.stdout, url)
        duration = time.perf_counter() - start_ts
        logger.debug(
            f"[PERF] scraper step=system_curl url={url} "
            f"duration={duration:.3f}s text_chars={len(text)} pdfs={len(pdfs)} links={len(links)}"
        )
        return text, pdfs, links
    except Exception as e: 
        duration = time.perf_counter() - start_ts
        logger.debug(
            f"[PERF] scraper step=system_curl_fail url={url} "
            f"duration={duration:.3f}s error={type(e).__name__}"
        )
        raise

# Wrapper for safe execution
async def _system_curl_scrape_safe(url: str, proxy: Optional[str]) -> Tuple[str, Set[str], Set[str]]:
    try:
        return await _system_curl_scrape(url, proxy)
    except:
        return "", set(), set()

# Note: Update calls in scrape_subpage to use _safe versions if we want to suppress errors after retries
# However, the original code already has try/except blocks inside _cffi_scrape. 
# To use tenacity effectively, we need to remove the internal try/except catch-all and let tenacity catch it.
# BUT, _cffi_scrape is called by scrape_subpage which expects a return value.
# Refactoring _cffi_scrape to raise exception for tenacity, then catching it in the safe wrapper is best.
# Let's revert to the pattern: Decorator on the Logic, Safe Wrapper for the Caller.

# Redefining _cffi_scrape without the broad try/except, but with specific logic
# REMOVIDO @retry AQUI pois o retry é gerenciado no loop principal com rotação de proxy
# E agora suporta reutilização de sessão
async def _cffi_scrape_logic(url: str, session: Optional[AsyncSession] = None, proxy: Optional[str] = None) -> Tuple[str, Set[str], Set[str]]:
    # Timeout segregado: 5s para conectar (fail fast no proxy), 30s para ler (paciência com servidor)
    # Requer curl_cffi >= 0.6.0b6 para suportar tuple/RequestsTimeout, ou apenas float
    # Vamos usar float simples se a versão não suportar, mas idealmente seria tuple
    # Por segurança e compatibilidade, vamos usar timeout total de 30s, mas confiar que
    # o proxy manager nos dá proxies bons, e se falhar no connect, falha rápido.
    # Mas para implementar o "Fail Fast" no connect, o ideal é o split.
    # Assumindo suporte a tuple (connect, read) ou configurando na session.
    
    # Se sessão fornecida, usar ela (Keep-Alive!)
    if session:
        # Nota: curl_cffi não permite trocar proxy de sessão existente facilmente sem criar nova connection pool
        # Então assumimos que a session já está configurada com o proxy correto ou sem proxy
        resp = await session.get(url)
    else:
        # Fallback: criar nova sessão (sem reuse) - comportamento antigo
        # Usar timeout dividido se possível, ou 30s total
        # Mas para garantir o "fail fast" de proxy, precisamos de connect curto.
        # Implementação segura: 25s total, mas connect implícito do libcurl é geralmente ~30s.
        # Vamos tentar forçar via argumento se a lib suportar, senão 25s total.
        timeout_cfg = 25
        async with AsyncSession(impersonate="chrome120", proxy=proxy, timeout=timeout_cfg) as s:
            resp = await s.get(url)
            
    if resp.status_code != 200: 
        raise Exception(f"Status {resp.status_code}")
    
    return _parse_html(resp.text, url)

async def _cffi_scrape(url: str, proxy: Optional[str], session: Optional[AsyncSession] = None) -> Tuple[str, Set[str], Set[str]]:
    try:
        return await _cffi_scrape_logic(url, session=session, proxy=proxy)
    except Exception as e:
        logger.debug(f"[CFFI] Erro ao fazer scrape de {url}: {type(e).__name__}: {str(e)}")
        # Propagar erro para permitir que o retry loop troque de proxy
        raise e

@retry(stop=stop_after_attempt(1), wait=wait_fixed(0))
async def _system_curl_scrape_logic(url: str, proxy: Optional[str]) -> Tuple[str, Set[str], Set[str]]:
    cmd = ["curl", "-L", "-k", "-s", "--max-time", "6"] # Timeout ultra agressivo de 6s
    if proxy: cmd.extend(["-x", proxy])
    cmd.extend(["-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36", url])
    
    res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=10) # Timeout do subprocess um pouco maior que o do curl
    if res.returncode != 0 or not res.stdout: raise Exception("Curl Failed")
    return _parse_html(res.stdout, url)

async def _system_curl_scrape(url: str, proxy: Optional[str]) -> Tuple[str, Set[str], Set[str]]:
    try:
        return await _system_curl_scrape_logic(url, proxy)
    except Exception as e:
        logger.debug(f"[SystemCurl] Erro ao fazer scrape de {url}: {type(e).__name__}: {str(e)}")
        return "", set(), set()


def _parse_html(html: str, url: str) -> Tuple[str, Set[str], Set[str]]:
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(["script", "style", "nav", "footer", "svg"]): tag.extract()
        text = soup.get_text(separator='\n\n')
        clean = '\n'.join(l.strip() for l in text.splitlines() if l.strip())
        return clean, *_extract_links_html(str(soup), url)
    except: return "", set(), set()

def _extract_links_html(html: str, base_url: str) -> Tuple[Set[str], Set[str]]:
    """
    Extrai links HTML e documentos (PDFs, Word, PowerPoint).
    Retorna: (documentos_importantes, links_internos_html)
    """
    documents, internal = set(), set()
    try:
        soup = BeautifulSoup(html, 'html.parser')
        base_domain = urlparse(base_url).netloc
        
        # Documentos importantes que devem ser processados
        DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}
        
        # Extensões de arquivos que NÃO devem ser coletados como páginas HTML
        EXCLUDED_EXTENSIONS = {
            # Imagens
            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.tiff',
            # Arquivos não-documentos
            '.zip', '.rar', '.tar', '.gz', '.xls', '.xlsx', '.csv', '.txt', '.xml', '.json', '.js', '.css',
            # Mídia
            '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.webm',
            # Outros
            '.woff', '.woff2', '.ttf', '.eot', '.otf'
        }
        
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            
            # IGNORAR ÂNCORAS PURAS E JAVASCRIPT
            if href.startswith('#') or href.lower().startswith('javascript:'):
                continue
                
            full = urljoin(base_url, href)
            
            # IGNORAR ÂNCORAS NA MESMA PÁGINA (ex: base_url/#contato)
            # Removemos a âncora para comparar
            if '#' in full:
                full_no_frag = full.split('#')[0]
                base_no_frag = base_url.split('#')[0]
                if full_no_frag == base_no_frag:
                    continue

            parsed = urlparse(full)
            path_lower = parsed.path.lower()
            
            # Verificar se é documento importante (PDF, Word, PowerPoint)
            if any(path_lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
                documents.add(full)
            # Verificar se é arquivo excluído (imagem, arquivo, etc)
            elif any(path_lower.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
                continue  # Ignorar imagens e outros arquivos
            # Verificar se é link interno válido
            elif parsed.netloc == base_domain:
                # Filtrar também query strings com extensões de imagem
                if not any(ext in parsed.query.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']):
                    internal.add(full)
    except: pass
    return documents, internal

def _extract_links(markdown: str, base_url: str) -> Tuple[Set[str], Set[str]]:
    """Extrair links de markdown formatado"""
    import re
    documents = set()
    internal = set()
    base_domain = urlparse(base_url).netloc
    
    # Documentos importantes que devem ser processados
    DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}
    
    # Extensões de arquivos que NÃO devem ser coletados como páginas HTML
    EXCLUDED_EXTENSIONS = {
        # Imagens
        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.tiff',
        # Arquivos não-documentos
        '.zip', '.rar', '.tar', '.gz', '.xls', '.xlsx', '.csv', '.txt', '.xml', '.json', '.js', '.css',
        # Mídia
        '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.webm',
        # Outros
        '.woff', '.woff2', '.ttf', '.eot', '.otf'
    }
    
    # Regex para links markdown: [texto](url) ou [texto](url "título")
    # O título opcional após a URL deve ser ignorado
    pattern = r'\[([^\]]+)\]\(([^\)"\s]+)(?:\s+"[^"]*")?\)'
    matches = re.findall(pattern, markdown)
    
    for text, url in matches:
        # Limpar a URL removendo espaços e aspas extras
        url = url.strip().strip('"').strip("'")
        full_url = urljoin(base_url, url)
        parsed = urlparse(full_url)
        path_lower = parsed.path.lower()
        
        # Verificar se é documento importante (PDF, Word, PowerPoint)
        if any(path_lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
            documents.add(full_url)
        # Verificar se é arquivo excluído (imagem, arquivo, etc)
        elif any(path_lower.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
            continue  # Ignorar imagens e outros arquivos
        elif parsed.netloc == base_domain:
            # Filtrar também query strings com extensões de imagem
            if not any(ext in parsed.query.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']):
                internal.add(full_url)
    
    return documents, internal

def _prioritize_links(links: Set[str], base_url: str) -> List[str]:
    # Expanded keyword list for richer profiles
    high = [
        # Core
        "quem-somos", "sobre", "institucional",
        # Offerings (MELHORADO - adicionado catálogo)
        "portfolio", "produto", "servico", "solucoes", "atuacao", "tecnologia",
        "catalogo", "catalogo-digital", "catalogo-online", "produtos", "servicos",
        # Trust & Proof (NEW)
        "clientes", "cases", "projetos", "obras", "certificacoes", "premios", "parceiros",
        # Team & Contact (NEW)
        "equipe", "time", "lideranca", "contato", "fale-conosco", "unidades"
    ]
    
    low = ["login", "signin", "cart", "policy", "blog", "news", "politica-privacidade", "termos"]
    
    scored = []
    for l in links:
        if l.rstrip('/') == base_url.rstrip('/'): continue
        s = 0
        lower = l.lower()
        
        if any(k in lower for k in low): s -= 100
        if any(k in lower for k in high): s += 50
        
        # Penalize deep nesting (often less relevant blog posts or detailed product specs)
        s -= len(urlparse(l).path.split('/'))
        
        # Boost for pagination if it looks like a list (often contains products/projects)
        # Fix for sites like EDJUNIOR where content is in page_1, page_2
        if any(x in lower for x in ["page", "p=", "pagina", "nav"]):
             # Apenas boost se não for um link explicitamente "low" (login, cart, etc)
             if not any(k in lower for k in low):
                s += 30

        scored.append((s, l))
        
    return [l for s, l in sorted(scored, key=lambda x: x[0], reverse=True) if s > -80]

def _filter_non_html_links(links: Set[str]) -> Set[str]:
    """
    Filtra links que são imagens, arquivos ou outros recursos não-HTML.
    IMPORTANTE: NÃO filtra documentos importantes (PDF, Word, PowerPoint) - eles são processados separadamente.
    """
    # Documentos importantes que NÃO devem ser filtrados (são processados separadamente)
    DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}
    
    EXCLUDED_EXTENSIONS = {
        # Imagens
        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.tiff',
        # Arquivos não-documentos
        '.zip', '.rar', '.tar', '.gz', '.xls', '.xlsx', '.csv', '.txt', '.xml', '.json', '.js', '.css',
        # Mídia
        '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.webm',
        # Outros
        '.woff', '.woff2', '.ttf', '.eot', '.otf'
    }
    
    filtered = set()
    for link in links:
        parsed = urlparse(link)
        path_lower = parsed.path.lower()
        
        # IMPORTANTE: Documentos (PDF, Word, PowerPoint) NÃO devem ser filtrados aqui
        # Eles são processados separadamente e não devem aparecer como links HTML
        if any(path_lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
            continue  # Documentos são coletados separadamente, não como links HTML
        
        # Verificar extensão no path
        if any(path_lower.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
            continue
        
        # Verificar extensão na query string
        if any(ext in parsed.query.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']):
            continue
        
        # Verificar se o path contém diretórios de assets/imagens comuns
        if any(dir_name in path_lower for dir_name in ['/wp-content/uploads/', '/assets/', '/images/', '/img/', '/static/', '/media/']):
            # Se está em diretório de assets, verificar se tem extensão de imagem
            if any(path_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico']):
                continue
        
        # Incluir o link (não é arquivo excluído)
        filtered.add(link)
    
    return filtered

async def _select_links_with_llm(links: Set[str], base_url: str, max_links: int = 30) -> List[str]:
    """
    Usa LLM para selecionar os links mais relevantes para completar o perfil da empresa.
    Muito mais inteligente que regras hardcoded!
    Registra tempo total gasto na seleção com LLM ou fallback.
    """
    start_ts = time.perf_counter()
    if not links or len(links) == 0:
        duration = time.perf_counter() - start_ts
        logger.info(
            f"[PERF] scraper step=select_links_llm base_url={base_url} "
            f"duration={duration:.3f}s reason=no_links"
        )
        return []
    
    # FILTRAR PRIMEIRO: Remover imagens e arquivos não-HTML
    filtered_links = _filter_non_html_links(links)
    logger.info(f"Filtrados {len(links) - len(filtered_links)} links não-HTML (imagens, arquivos, etc). Restam {len(filtered_links)} links válidos.")
    
    if not filtered_links:
        duration = time.perf_counter() - start_ts
        logger.info(
            f"[PERF] scraper step=select_links_llm base_url={base_url} "
            f"duration={duration:.3f}s reason=no_filtered_links"
        )
        return []
    
    # Se tiver poucos links após filtro, retornar todos
    if len(filtered_links) <= max_links:
        duration = time.perf_counter() - start_ts
        logger.info(
            f"[PERF] scraper step=select_links_llm base_url={base_url} "
            f"duration={duration:.3f}s selected={len(filtered_links)} total_candidates={len(links)} "
            f"strategy=short_circuit"
        )
        return list(filtered_links)
    
    # Importar aqui para evitar dependência circular
    from openai import AsyncOpenAI
    from app.core.config import settings
    import json
    
    # Preparar cliente LLM
    client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
    
    # Criar prompt com contexto do schema
    links_list = "\n".join([f"{i+1}. {url}" for i, url in enumerate(sorted(filtered_links))])
    
    prompt = f"""Você é um especialista em análise de websites B2B.

CONTEXTO: Estamos coletando dados para criar um perfil completo de empresa com os seguintes campos:

**IDENTITY**: Nome da empresa, CNPJ, tagline, descrição, ano de fundação, número de funcionários
**CLASSIFICATION**: Indústria, modelo de negócio (B2B/B2C), público-alvo, cobertura geográfica
**TEAM**: Tamanho da equipe, cargos-chave, certificações do time
**OFFERINGS**: Produtos, categorias de produtos, serviços, detalhes de serviços, modelos de engajamento, diferenciais
**REPUTATION**: Certificações, prêmios, parcerias, lista de clientes, cases de sucesso
**CONTACT**: E-mails, telefones, LinkedIn, endereço, localizações

TAREFA: Selecione os {max_links} links MAIS RELEVANTES da lista abaixo que provavelmente contêm informações para preencher esses campos. Priorize:
1. Páginas "Sobre", "Quem Somos", "Institucional"
2. Páginas de Produtos/Serviços/Soluções/Catálogos
3. Páginas de Cases, Clientes, Projetos
4. Páginas de Contato, Equipe, Localizações
5. Páginas de Certificações, Prêmios, Parcerias

IMPORTANTE: 
- PRIORIZE páginas com palavras como "catalogo", "catalogo-digital", "portfolio", "produtos", "servicos"
- considere páginas com extensões antigas (.asp, .aspx, .cfm) como conteúdo válido e relevante.
- CASO ESPECIAL: Se o site usar navegação numerada (ex: page_1, page_2, p=12) ou genérica para listar portfólio/produtos, VOCÊ DEVE INCLUIR esses links.
- EVITE: Blogs (exceto se for a única fonte de cases), notícias datadas, políticas de privacidade, login, carrinho, termos de uso
- EVITE: Links que parecem ser imagens ou arquivos (já foram filtrados, mas seja cuidadoso)

LISTA DE LINKS DO SITE {base_url}:
{links_list}

Responda APENAS com um JSON array contendo os números dos links selecionados (ex: [1, 3, 5, 7, ...]):
"""

    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "Você é um assistente especializado em análise de websites B2B. Responda sempre em JSON válido."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content.strip()
        
        # Parse do JSON
        try:
            result = json.loads(content)
            # Pode vir como {"links": [1,2,3]} ou {"selected": [1,2,3]} ou direto [1,2,3]
            if isinstance(result, list):
                selected_indices = result
            elif "links" in result:
                selected_indices = result["links"]
            elif "selected" in result:
                selected_indices = result["selected"]
            elif "indices" in result:
                selected_indices = result["indices"]
            else:
                # Pegar o primeiro array que encontrar
                for value in result.values():
                    if isinstance(value, list):
                        selected_indices = value
                        break
                else:
                    selected_indices = []
        except:
            # Se falhar no parse, usar estratégia de fallback (priorização básica)
            logger.warning("LLM não retornou JSON válido, usando fallback")
            duration = time.perf_counter() - start_ts
            prioritized = _prioritize_links(filtered_links, base_url)[:max_links]
            logger.info(
                f"[PERF] scraper step=select_links_llm base_url={base_url} "
                f"duration={duration:.3f}s selected={len(prioritized)} total_candidates={len(links)} "
                f"strategy=fallback_prioritize"
            )
            return prioritized
        
        # Converter índices para URLs
        sorted_links = sorted(filtered_links)
        selected_urls = []
        for idx in selected_indices:
            if 1 <= idx <= len(sorted_links):
                selected_urls.append(sorted_links[idx - 1])
        
        duration = time.perf_counter() - start_ts
        logger.info(
            f"[PERF] scraper step=select_links_llm base_url={base_url} "
            f"duration={duration:.3f}s selected={len(selected_urls)} total_candidates={len(links)} "
            f"strategy=llm"
        )
        logger.info(f"LLM selecionou {len(selected_urls)} de {len(filtered_links)} links válidos (de {len(links)} totais)")
        return selected_urls[:max_links]
        
    except Exception as e:
        logger.error(f"Erro ao usar LLM para selecionar links: {e}")
        # Fallback para estratégia baseada em regras
        duration = time.perf_counter() - start_ts
        prioritized = _prioritize_links(links, base_url)[:max_links]
        logger.info(
            f"[PERF] scraper step=select_links_llm base_url={base_url} "
            f"duration={duration:.3f}s selected={len(prioritized)} total_candidates={len(links)} "
            f"strategy=error_fallback_prioritize"
        )
        return prioritized
