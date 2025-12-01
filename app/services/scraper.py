import asyncio
import subprocess
import random
import logging
import time
from typing import List, Tuple, Set, Optional
from urllib.parse import urljoin, urlparse, quote, unquote
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, BrowserConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from tenacity import retry, stop_after_attempt, wait_fixed, wait_exponential, retry_if_exception_type, before_sleep_log
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

# Global semaphore to limit concurrent Playwright instances
# Prevents resource exhaustion and browser crashes
playwright_semaphore = asyncio.Semaphore(10)  # Aumentado para priorizar velocidade

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
    md_generator = DefaultMarkdownGenerator(content_filter=PruningContentFilter(threshold=0.35, min_word_threshold=5))
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS, 
        exclude_external_images=True, 
        markdown_generator=md_generator, 
        page_timeout=60000  # ✅ CORREÇÃO 1: Aumentado de 30s para 60s
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
            
            pdfs, links = _extract_links(result.markdown, url)
            if not links: 
                pdfs, links = _extract_links_html(result.html, url)
            
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
        print(f"[Scraper] Processing {len(target_subpages)} subpages with Parallel IP Rotation")
        
        # Semaphore to limit concurrency (avoid overwhelming proxy provider or local resources)
        sem = asyncio.Semaphore(10) 

        async def scrape_subpage(sub_url):
            async with sem:
                # Normalizar URL para lidar com caracteres especiais
                normalized_url = _normalize_url(sub_url)
                if normalized_url != sub_url:
                    logger.debug(f"[Sub] URL normalizada: {sub_url} -> {normalized_url}")
                
                # Loop de retry com rotação de proxy (Ultra Aggressive)
                MAX_ATTEMPTS = 3
                for attempt in range(MAX_ATTEMPTS):
                    try:
                        # Get fresh proxy for THIS attempt
                        sub_proxy = await proxy_manager.get_next_proxy()
                        
                        logger.debug(f"[Sub] Tentativa {attempt+1}/{MAX_ATTEMPTS} para {normalized_url}")
                        
                        # Try CFFI (fail fast with timeout 6s)
                        text, pdfs, _ = await _cffi_scrape(normalized_url, sub_proxy)
                        
                        # Fallback System Curl if CFFI failed
                        if not text:
                            text, pdfs, _ = await _system_curl_scrape(normalized_url, sub_proxy)
                        
                        if text:
                            # Verificar se o conteúdo é muito pequeno (descartar erros de proxy/captcha que passam como 200)
                            if len(text) < 100: 
                                logger.warning(f"⚠️ [Sub] Conteúdo inválido/muito pequeno ({len(text)} chars) na tentativa {attempt+1}. Tentando próximo proxy...")
                                continue
                                
                            logger.info(f"[Sub] ✅ Success: {normalized_url} ({len(text)} chars)")
                            print(f"[Sub] Success: {normalized_url}")
                            return (normalized_url, text, pdfs)
                        
                        # Se chegou aqui, ambos falharam nesta tentativa
                        logger.debug(f"[Sub] Falha na tentativa {attempt+1} para {normalized_url}. Tentando próximo proxy...")
                        
                    except Exception as e:
                        logger.warning(f"[Sub] Erro na tentativa {attempt+1} para {normalized_url}: {e}")
                        continue

                # Se saiu do loop, todas as tentativas falharam
                logger.warning(f"[Sub] ❌ Failed: {normalized_url} - Todas as {MAX_ATTEMPTS} tentativas falharam")
                print(f"[Sub] Failed: {normalized_url}")
                return None

        # Launch parallel tasks
        tasks = [scrape_subpage(sub) for sub in target_subpages]
        results = await asyncio.gather(*tasks)

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
@retry(stop=stop_after_attempt(1), wait=wait_fixed(0))
async def _cffi_scrape_logic(url: str, proxy: Optional[str]) -> Tuple[str, Set[str], Set[str]]:
    # Timeout ultra agressivo de 6s (fail-fast)
    async with AsyncSession(impersonate="chrome120", proxy=proxy, timeout=6) as s:
        resp = await s.get(url)
        if resp.status_code != 200: raise Exception(f"Status {resp.status_code}")
        return _parse_html(resp.text, url)

async def _cffi_scrape(url: str, proxy: Optional[str]) -> Tuple[str, Set[str], Set[str]]:
    try:
        return await _cffi_scrape_logic(url, proxy)
    except Exception as e:
        logger.debug(f"[CFFI] Erro ao fazer scrape de {url}: {type(e).__name__}: {str(e)}")
        return "", set(), set()

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
- EVITE: Blogs, notícias, políticas de privacidade, login, carrinho, termos de uso
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
