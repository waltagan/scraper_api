import asyncio
import logging
import json
import urllib.parse
import random
import httpx
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

# crawl4ai removido - alto consumo de memória (PRD v2.0)
# Função search_google agora usa Serper como fallback
HAS_CRAWL4AI = False

from app.core.config import settings
from app.core.proxy import proxy_manager
from app.services.llm.provider_manager import provider_manager
from app.services.llm.health_monitor import health_monitor, FailureType
from app.services.llm.queue_manager import create_queue_manager

logger = logging.getLogger(__name__)

# --- CONFIGURAÇÃO DE DISCOVERY ---
DISCOVERY_TIMEOUT = 60.0  # Timeout para chamadas LLM de discovery (aumentado para produção)
DISCOVERY_MAX_RETRIES = 3  # Número máximo de tentativas
DISCOVERY_BACKOFF_BASE = 2  # Base para backoff exponencial (segundos)
DISCOVERY_BACKOFF_MAX = 16  # Máximo de backoff (segundos)

# --- CONFIGURAÇÃO DO SERPER API ---
# Rate Limit oficial: 300 queries/segundo
# Porém, limitamos concorrência local para evitar exaustão de conexões
SERPER_CONCURRENT_LIMIT = 200  # conexões simultâneas máximas (limitação local, não da API)
SERPER_REQUEST_TIMEOUT = 15.0  # timeout por request (segundos)
SERPER_CONNECT_TIMEOUT = 5.0   # timeout para estabelecer conexão (segundos)
SERPER_MAX_RETRIES = 3         # tentativas máximas por request
SERPER_RETRY_BASE_DELAY = 1.0  # delay base para backoff exponencial (segundos)
SERPER_RETRY_MAX_DELAY = 10.0  # delay máximo para backoff (segundos)

# Semáforo global para controle de concorrência do Serper
_serper_semaphore: Optional[asyncio.Semaphore] = None
_serper_lock = asyncio.Lock()

# Cliente HTTP global com connection pooling
_serper_client: Optional[httpx.AsyncClient] = None
_serper_client_lock = asyncio.Lock()


async def get_serper_semaphore() -> asyncio.Semaphore:
    """Retorna o semáforo global do Serper (lazy initialization)."""
    global _serper_semaphore
    async with _serper_lock:
        if _serper_semaphore is None:
            _serper_semaphore = asyncio.Semaphore(SERPER_CONCURRENT_LIMIT)
    return _serper_semaphore


async def get_serper_client() -> httpx.AsyncClient:
    """
    Retorna cliente HTTP global com connection pooling.
    
    Connection pooling evita criar/destruir conexões a cada request,
    o que era a causa dos erros de conexão em batch de 500 empresas.
    """
    global _serper_client
    async with _serper_client_lock:
        if _serper_client is None or _serper_client.is_closed:
            _serper_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=SERPER_CONNECT_TIMEOUT,
                    read=SERPER_REQUEST_TIMEOUT,
                    write=SERPER_REQUEST_TIMEOUT,
                    pool=SERPER_REQUEST_TIMEOUT
                ),
                limits=httpx.Limits(
                    max_keepalive_connections=50,
                    max_connections=SERPER_CONCURRENT_LIMIT,
                    keepalive_expiry=30.0
                ),
                http2=True  # HTTP/2 para melhor performance
            )
            logger.info(f"🌐 Serper: Cliente HTTP criado (pool={SERPER_CONCURRENT_LIMIT}, http2=True)")
    return _serper_client


async def close_serper_client():
    """Fecha o cliente HTTP global (chamar no shutdown da aplicação)."""
    global _serper_client
    async with _serper_client_lock:
        if _serper_client and not _serper_client.is_closed:
            await _serper_client.aclose()
            _serper_client = None
            logger.info("🌐 Serper: Cliente HTTP fechado")


# --- BLACKLIST DE DOMÍNIOS (Pré-filtro antes da LLM) ---
# Domínios que NUNCA devem ser enviados para análise da LLM
BLACKLIST_DOMAINS = {
    # Diretórios Empresariais e Agregadores de CNPJ (alta frequência nos resultados)
    "econodata.com.br",
    "cnpj.biz",
    "cnpja.com",
    "cnpj.info",
    "cnpjs.rocks",
    "casadosdados.com.br",
    "empresascnpj.com",
    "consultacnpj.com",
    "informecadastral.com.br",
    "cadastroempresa.com.br",
    "transparencia.cc",
    "listamais.com.br",
    "solutudo.com.br",
    "telelistas.net",
    "apontador.com.br",
    "guiamais.com.br",
    "construtora.net.br",
    "b2bleads.com.br",
    "empresas.serasaexperian.com.br",
    "jusbrasil.com.br",
    "jusdados.com",
    
    # Redes Sociais
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "pinterest.com",
    "threads.net",
    
    # Marketplaces
    "mercadolivre.com.br",
    "shopee.com.br",
    "olx.com.br",
    "amazon.com.br",
    "magazineluiza.com.br",
    "americanas.com.br",
    
    # Google Services (tradutor, cache, etc)
    "translate.google.com",
    "webcache.googleusercontent.com",
}


def is_blacklisted_domain(url: str) -> bool:
    """
    Verifica se a URL pertence a um domínio na blacklist.
    Retorna True se deve ser filtrado (não enviar para LLM).
    """
    if not url:
        return False
    
    try:
        # Normaliza URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove prefixos comuns
        for prefix in ('www.', 'm.', 'mobile.'):
            if domain.startswith(prefix):
                domain = domain[len(prefix):]
        
        # Verifica match exato ou subdomínio
        for blacklisted in BLACKLIST_DOMAINS:
            if domain == blacklisted or domain.endswith('.' + blacklisted):
                return True
        
        return False
        
    except Exception:
        return False



DISCOVERY_PROMPT = """Você é um especialista em encontrar sites oficiais de empresas brasileiras.

# TAREFA
Analise os resultados de busca e identifique o site OFICIAL da empresa.

# REGRA DE OURO (OBRIGATÓRIA - SIGA SEMPRE)
Se o DOMÍNIO contém o NOME da empresa (mesmo que junto ou abreviado), ACEITE IMEDIATAMENTE.
Remova espaços e compare: "AR ENGENHARIA" → "arengenharia" → domínio "arengenharia.eng.br" = ✅ MATCH

EXEMPLOS DE MATCH (TODOS devem ser ACEITOS):
- "12M" → "12m.com.br" ✅
- "AR ENGENHARIA" → "arengenharia.eng.br" ✅ (nome sem espaços = domínio)
- "CONSTRUTORA CESAR" → "construtoracesar.com.br" ✅ (nome completo no domínio)
- "ASST Serviços" → "asst.com.br" ✅ (sigla no domínio)
- "CIMMAA Metalmecanica" → "cimmaa.com.br" ✅ (nome principal no domínio)
- "Alianza Manutenção" → "allianzautomacao.com.br" ✅ (variação ortográfica)
- "4M Engenharia" → "4mengenharia.com.br" ✅

# PROCESSO DE DECISÃO

## PASSO 1: Remover diretórios e redes sociais
IGNORE completamente URLs contendo: facebook, instagram, linkedin, youtube, twitter, x.com, tiktok, cnpj.biz, econodata, telelistas, apontador, solutudo, mercadolivre, shopee, olx

## PASSO 2: Para cada URL restante, faça o match
1. Extraia o domínio (ex: "arengenharia.eng.br")
2. Remova sufixos (.com.br, .eng.br, etc) → "arengenharia"
3. Compare com Nome Fantasia SEM ESPAÇOS → "arengenharia"
4. Se são iguais ou muito similares → ACEITE IMEDIATAMENTE

## PASSO 3: Se múltiplos matches, escolha o primeiro (mais bem ranqueado)

# IMPORTANTE
- NÃO exija que o snippet confirme o site - snippets do Google são frequentemente ERRADOS
- NÃO rejeite um site só porque o título não é idêntico ao nome da empresa
- Se o domínio contém o nome, ACEITE - não há necessidade de mais evidências

# RESPOSTA (JSON obrigatório)
```json
{
  "site": "URL_DO_SITE ou nao_encontrado",
  "site_oficial": "sim ou nao",
  "justificativa": "Breve explicação"
}
```
"""
    
    # import httpx  <-- Removido, já está no topo


async def search_google_serper(query: str, num_results: int = 100) -> List[Dict[str, str]]:
    """
    Realiza uma busca no Google usando a API Serper.dev.
    
    Melhorias v2.1:
    - Connection pooling (cliente HTTP global)
    - Retry com backoff exponencial
    - Logging detalhado de erros (tipo + mensagem)
    - Controle de concorrência local
    """
    if not settings.SERPER_API_KEY:
        logger.warning("⚠️ SERPER_API_KEY não configurada.")
        return await search_google(query, num_results)

    # Obter semáforo de concorrência
    semaphore = await get_serper_semaphore()
    
    async with semaphore:
        logger.debug(f"🔎 Serper query: {query[:50]}...")
        
        url = "https://google.serper.dev/search"
        payload = json.dumps({
            "q": query,
            "num": num_results,
            "gl": "br",
            "hl": "pt-br"
        })
        headers = {
            'X-API-KEY': settings.SERPER_API_KEY,
            'Content-Type': 'application/json'
        }

        # Obter cliente HTTP com connection pooling
        client = await get_serper_client()
        
        last_error = None
        last_error_type = None
        
        for attempt in range(SERPER_MAX_RETRIES):
            try:
                # Calcular delay de backoff (0 na primeira tentativa)
                if attempt > 0:
                    delay = min(
                        SERPER_RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.5),
                        SERPER_RETRY_MAX_DELAY
                    )
                    logger.debug(f"🔄 Serper retry {attempt + 1}/{SERPER_MAX_RETRIES} após {delay:.1f}s")
                    await asyncio.sleep(delay)
                
                response = await client.post(url, headers=headers, content=payload)
                
                # Rate limit - fazer backoff e retry
                if response.status_code == 429:
                    logger.warning(f"⚠️ Serper rate limit (429), tentativa {attempt + 1}/{SERPER_MAX_RETRIES}")
                    last_error = "Rate limit (429)"
                    last_error_type = "RateLimit"
                    continue
                
                # Erro de servidor - pode ser temporário
                if response.status_code >= 500:
                    logger.warning(f"⚠️ Serper server error ({response.status_code}), tentativa {attempt + 1}/{SERPER_MAX_RETRIES}")
                    last_error = f"Server error ({response.status_code})"
                    last_error_type = "ServerError"
                    continue
                
                # Erro de cliente (4xx exceto 429) - não faz retry
                if response.status_code >= 400:
                    logger.error(f"❌ Serper client error: {response.status_code}")
                    return []
                
                # Sucesso
                data = response.json()
                organic_results = data.get("organic", [])
                
                results = []
                for item in organic_results:
                    results.append({
                        "title": item.get("title"),
                        "link": item.get("link"),
                        "snippet": item.get("snippet", "")
                    })
                
                logger.debug(f"✅ Serper: {len(results)} resultados")
                return results
                
            except httpx.TimeoutException as e:
                last_error_type = "Timeout"
                last_error = f"timeout após {SERPER_REQUEST_TIMEOUT}s"
                logger.warning(f"⚠️ Serper {last_error_type}: {last_error}, tentativa {attempt + 1}/{SERPER_MAX_RETRIES}")
                
            except httpx.ConnectError as e:
                last_error_type = "ConnectError"
                last_error = str(e) if str(e) else "falha ao conectar"
                logger.warning(f"⚠️ Serper {last_error_type}: {last_error}, tentativa {attempt + 1}/{SERPER_MAX_RETRIES}")
                
            except httpx.PoolTimeout as e:
                last_error_type = "PoolTimeout"
                last_error = "pool de conexões esgotado"
                logger.warning(f"⚠️ Serper {last_error_type}: {last_error}, tentativa {attempt + 1}/{SERPER_MAX_RETRIES}")
                
            except httpx.HTTPStatusError as e:
                last_error_type = "HTTPStatusError"
                last_error = f"status {e.response.status_code}"
                logger.warning(f"⚠️ Serper {last_error_type}: {last_error}, tentativa {attempt + 1}/{SERPER_MAX_RETRIES}")
                
            except Exception as e:
                # Captura qualquer outra exceção com tipo explícito
                last_error_type = type(e).__name__
                last_error = str(e) if str(e) else "erro desconhecido"
                logger.warning(f"⚠️ Serper {last_error_type}: {last_error}, tentativa {attempt + 1}/{SERPER_MAX_RETRIES}")
        
        # Todas as tentativas falharam
        logger.error(f"❌ Serper falhou após {SERPER_MAX_RETRIES} tentativas: [{last_error_type}] {last_error}")
        return []

async def search_google(query: str, num_results: int = 10) -> List[Dict[str, str]]:
    """
    Realiza uma busca no Google.
    
    NOTA v2.0: crawl4ai foi removido por alto consumo de memória.
    Esta função agora retorna lista vazia - use search_google_serper como principal.
    """
    logger.warning(
        "⚠️ search_google: crawl4ai não disponível (PRD v2.0). "
        "Use search_google_serper como método principal de busca."
    )
    
    # Fallback: tentar busca simples via httpx (sem browser)
    try:
        import httpx
        
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded_query}&hl=pt-BR&num={num_results}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pt-BR,pt;q=0.9"
        }
        
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code != 200:
                logger.warning(f"search_google: Status {response.status_code}")
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for script in soup(["script", "style"]):
                script.decompose()
            
            results = []
            results_found = False
            possible_selectors = ['div.g', 'div.MjjYud', 'div.tF2Cxc']
            
            for selector in possible_selectors:
                items = soup.select(selector)
                if items:
                    for item in items:
                        h3 = item.find('h3')
                        a = item.find('a', href=True)
                        
                        if h3 and a:
                            link = a['href']
                            title = h3.get_text(strip=True)
                            container_text = item.get_text(separator=' ', strip=True)
                            snippet = container_text.replace(title, '', 1).strip()
                            snippet = snippet.replace(link, '')
                            
                            if link.startswith('http') and 'google.com' not in link:
                                results.append({
                                    "title": title,
                                    "link": link,
                                    "snippet": snippet[:400]
                                })
                                results_found = True
                    
                    if results_found:
                        break

            # Fallback Agressivo
            if not results_found:
                logger.warning("⚠️ Seletores específicos falharam. Usando extração por proximidade.")
                # Procura todos h3 (que geralmente são títulos)
                all_h3 = soup.find_all('h3')
                for h3 in all_h3:
                    # O link costuma ser o pai ou vizinho
                    parent_a = h3.find_parent('a', href=True)
                    if not parent_a:
                        # Às vezes o h3 está dentro do a, ou o a está logo antes
                        continue
                        
                    link = parent_a['href']
                    title = h3.get_text(strip=True)
                    
                    if not link.startswith('http') or 'google.com' in link:
                        continue

                    # Tenta pegar o snippet: texto no elemento pai do link (container do resultado)
                    container = parent_a.find_parent('div')
                    snippet = ""
                    if container:
                        full_text = container.get_text(separator=' ', strip=True)
                        snippet = full_text.replace(title, '', 1).replace(link, '').strip()
                    
                    results.append({
                        "title": title,
                        "link": link,
                        "snippet": snippet[:400]
                    })
                        
    except Exception as e:
        logger.error(f"❌ Erro na execução da busca: {e}")
        return []

    logger.info(f"✅ Encontrados {len(results)} resultados na busca.")
    return results

async def find_company_website(
    razao_social: str, 
    nome_fantasia: str, 
    cnpj: str,
    email: Optional[str] = None,
    municipio: Optional[str] = None,
    cnaes: Optional[List[str]] = None,
    ctx_label: str = ""
) -> Optional[str]:
    """
    Orquestra a descoberta do site oficial da empresa.
    
    Queries otimizadas (máximo 2):
    - Q1: Nome Fantasia + cidade (se existir)
    - Q2: Razão Social + cidade (se existir)
    
    Se tiver apenas um dado, faz apenas uma query.
    """
    queries = []
    
    nf = nome_fantasia.strip() if nome_fantasia else ""
    rs = razao_social.strip() if razao_social else ""
    city = municipio.strip() if municipio else ""
    
    # Q1: Nome Fantasia + Municipio
    if nf:
        q1 = f'{nf} {city} site oficial'.strip()
        queries.append(q1)
        logger.debug(f"{ctx_label}📝 Q1: {q1}")
    
    # Q2: Razão Social + Municipio (apenas se diferente do nome fantasia)
    if rs:
        # Limpar sufixos jurídicos
        clean_rs = rs.replace(" LTDA", "").replace(" S.A.", "").replace(" EIRELI", "")
        clean_rs = clean_rs.replace(" ME", "").replace(" EPP", "").replace(" S/A", "").strip()
        
    # Só adiciona Q2 se for diferente de Q1
    q2 = f'{clean_rs} {city} site oficial'.strip()
    if not nf or clean_rs.upper() != nf.upper():
        queries.append(q2)
        logger.debug(f"{ctx_label}📝 Q2: {q2}")

    # Q3: Busca por CNPJ (pode revelar site no rodapé ou página de contato)
    if cnpj:
        q3 = f'"{cnpj}" site'.strip()
        queries.append(q3)
        logger.debug(f"{ctx_label}📝 Q3: {q3}")
    
    # Se não gerou queries (input vazio), retorna
    if not queries:
        logger.warning(f"{ctx_label}⚠️ Sem Nome Fantasia ou Razão Social para busca.")
        return None
    
    logger.info(f"{ctx_label}🔍 Discovery: {len(queries)} query(s) para {nf or rs}")

    # ESTRATÉGIA EXTRA: Validação de E-mail (Apenas Log)
    # Se tiver email corporativo, logamos para debug, mas não forçamos busca específica.
    if email and "@" in email:
        domain_part = email.split("@")[1].lower().strip()
        generic_domains = [
            "gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "yahoo.com.br", 
            "uol.com.br", "bol.com.br", "terra.com.br", "ig.com.br", "icloud.com", "me.com"
        ]
        if domain_part not in generic_domains and "." in domain_part:
            logger.info(f"{ctx_label}📧 Domínio de email disponível para validação cruzada: {domain_part}")

    # Executar buscas (sequencial para evitar rate limit agressivo)
    all_results = []
    seen_links = set()
    filtered_count = 0
    
    # Executar queries em ordem de prioridade
    
    for q in queries:
        res = await search_google_serper(q)
        for r in res:
            link = r.get('link', '')
            if link not in seen_links:
                # Pré-filtro: remover domínios da blacklist antes de enviar para LLM
                if is_blacklisted_domain(link):
                    filtered_count += 1
                    continue
                all_results.append(r)
                seen_links.add(link)
    
    if filtered_count > 0:
        logger.debug(f"{ctx_label}🚫 {filtered_count} resultados filtrados (blacklist)")
    
    if not all_results:
        logger.warning(f"{ctx_label}⚠️ Nenhum resultado encontrado no Google após múltiplas buscas.")
        return None
        
    # Logar resultados consolidados para debug
    logger.info(f"{ctx_label}🔍 Resultados consolidados enviados para IA ({len(all_results)} itens)")
    logger.debug(json.dumps(all_results, indent=2, ensure_ascii=False))

    # 3. Analisar com LLM (com load balancing e retry)
    results_text = json.dumps(all_results, indent=2, ensure_ascii=False)
    
    user_content = f"""
    Dados da Empresa:
    - Nome Fantasia: {nome_fantasia or 'Não informado'}
    - Razão Social: {razao_social or 'Não informado'}
    - CNPJ: {cnpj or 'Não informado'}
    - E-mail: {email or 'Não informado'}
    - Município: {municipio or 'Não informado'}
    - CNAEs (Atividades): {', '.join(cnaes) if cnaes else 'Não informado'}
    
    Resultados da Busca (Consolidados):
    {results_text}
    """
    
    # Retry com backoff exponencial e load balancing WEIGHTED
    last_error = None
    providers_tried = []
    
    # Criar queue_manager para usar weighted selection
    queue_manager = create_queue_manager(
        providers=provider_manager.available_providers,
        priorities=provider_manager.provider_weights  # Usar WEIGHTS ao invés de priorities
    )
    
    for attempt in range(DISCOVERY_MAX_RETRIES):
        # NOVO: Usar weighted selection para distribuir carga proporcionalmente
        selected_provider = queue_manager.get_weighted_provider(
            exclude=providers_tried,
            weights=provider_manager.provider_weights
        )
        
        if not selected_provider:
            logger.error(f"{ctx_label}❌ Nenhum provider LLM disponível")
            continue
        
        providers_tried.append(selected_provider)
        
        # Calcular backoff para retry (0 na primeira tentativa)
        if attempt > 0:
            backoff = min(DISCOVERY_BACKOFF_BASE ** attempt + random.uniform(0, 1), DISCOVERY_BACKOFF_MAX)
            logger.debug(f"{ctx_label}🔄 Discovery retry {attempt + 1}/{DISCOVERY_MAX_RETRIES} após {backoff:.1f}s")
            await asyncio.sleep(backoff)
        
        try:
            start_time = asyncio.get_event_loop().time()
            
            messages = [
                            {"role": "system", "content": DISCOVERY_PROMPT},
                            {"role": "user", "content": user_content}
            ]
            
            content, latency_ms = await provider_manager.call(
                provider=selected_provider,
                messages=messages,
                timeout=DISCOVERY_TIMEOUT,
                response_format={"type": "json_object"},
                ctx_label=ctx_label
            )
            
            duration = asyncio.get_event_loop().time() - start_time
            logger.info(f"{ctx_label}🧠 Decisão do LLM ({selected_provider}): {content}")
            
            # Registrar sucesso
            health_monitor.record_success(selected_provider, latency_ms)
            
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Tentar limpar markdown se houver
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                    data = json.loads(content)
                else:
                    raise

            # Tratamento para caso a IA retorne uma lista em vez de um objeto
            if isinstance(data, list):
                if len(data) > 0:
                    data = data[0]
                else:
                    logger.warning("⚠️ IA retornou lista vazia.")
                    return None
            
            if data.get("site_oficial") == "sim" and data.get("site") and data.get("site") != "nao_encontrado":
                return data.get("site")
            else:
                logger.debug(f"{ctx_label}Site não encontrado. Justificativa: {data.get('justificativa')}")
                return None
            
        except asyncio.TimeoutError:
            duration = (asyncio.get_event_loop().time() - start_time) * 1000 if 'start_time' in dir() else DISCOVERY_TIMEOUT * 1000
            health_monitor.record_failure(selected_provider, FailureType.TIMEOUT, duration)
            logger.warning(f"{ctx_label}⚠️ Timeout na análise do LLM ({selected_provider}) para descoberta de site ({DISCOVERY_TIMEOUT}s). "
                          f"Tentativa {attempt + 1}/{DISCOVERY_MAX_RETRIES}")
            last_error = "timeout"
            continue  # Tentar novamente com outro provedor
            
        except Exception as e:
            duration = (asyncio.get_event_loop().time() - start_time) * 1000 if 'start_time' in dir() else 0
            health_monitor.record_failure(selected_provider, FailureType.ERROR, duration)
            logger.warning(f"{ctx_label}⚠️ Erro na análise do LLM ({selected_provider}): {e}. "
                          f"Tentativa {attempt + 1}/{DISCOVERY_MAX_RETRIES}")
            last_error = str(e)
            continue  # Tentar novamente com outro provedor
    
    # Todas as tentativas falharam
    logger.error(f"{ctx_label}❌ Erro na análise do LLM para descoberta de site após {DISCOVERY_MAX_RETRIES} tentativas. "
                f"Último erro: {last_error}")
    return None
