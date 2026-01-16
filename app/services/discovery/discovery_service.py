"""
Serviço de Discovery v4.1 - Descoberta de sites oficiais de empresas.

Usa exclusivamente a API Serper para buscas no Google.

Managers de infraestrutura:
- SerperManager: Rate limiting, retry, connection pooling
- SearchCache: Cache de buscas recentes

A lógica de negócio permanece neste arquivo.
"""

import asyncio
import logging
import json
import time
import urllib.parse
from typing import Optional, List, Dict, Tuple

from app.core.config import settings
from app.services.agents import get_discovery_agent
from app.services.concurrency_manager.config_loader import get_section as get_config

# Importar managers de infraestrutura
from app.services.discovery_manager import (
    serper_manager,
    search_cache,
)

logger = logging.getLogger(__name__)

# --- CONFIGURAÇÃO DE DISCOVERY ---
_DISCOVERY_CFG = get_config("discovery/discovery", {})
DISCOVERY_TIMEOUT = _DISCOVERY_CFG.get("timeout", 60.0)
DISCOVERY_MAX_RETRIES = _DISCOVERY_CFG.get("max_retries", 3)
SERPER_NUM_RESULTS = _DISCOVERY_CFG.get("serper_num_results", 10)


# --- BLACKLIST DE DOMÍNIOS ---
BLACKLIST_DOMAINS = {
    # Sites de dados empresariais
    "econodata.com.br", "cnpj.biz", "cnpja.com", "cnpj.info", "cnpjs.rocks",
    "casadosdados.com.br", "empresascnpj.com", "consultacnpj.com",
    "informecadastral.com.br", "cadastroempresa.com.br", "transparencia.cc",
    "listamais.com.br", "solutudo.com.br", "telelistas.net", "apontador.com.br",
    "guiamais.com.br", "construtora.net.br", "b2bleads.com.br",
    "empresas.serasaexperian.com.br", "jusbrasil.com.br", "jusdados.com",
    # Redes sociais
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com",
    "twitter.com", "x.com", "tiktok.com", "pinterest.com", "threads.net",
    # Marketplaces
    "mercadolivre.com.br", "shopee.com.br", "olx.com.br", "amazon.com.br",
    "magazineluiza.com.br", "americanas.com.br",
    # Outros
    "translate.google.com", "webcache.googleusercontent.com",
}


def is_blacklisted_domain(url: str) -> bool:
    """Verifica se a URL pertence a um domínio na blacklist."""
    if not url:
        return False
    
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()
        
        for prefix in ('www.', 'm.', 'mobile.'):
            if domain.startswith(prefix):
                domain = domain[len(prefix):]
        
        for blacklisted in BLACKLIST_DOMAINS:
            if domain == blacklisted or domain.endswith('.' + blacklisted):
                return True
        
        return False
        
    except Exception:
        return False


async def search_google_serper(query: str, num_results: int = 100, request_id: str = "") -> Tuple[List[Dict[str, str]], int]:
    """
    Realiza busca no Google usando API Serper.
    
    Features via SerperManager:
    - Cache de resultados (evita chamadas repetidas)
    - Rate limiting (controla concorrência)
    - Retry automático com backoff exponencial
    - Connection pooling HTTP/2
    
    Args:
        query: Termo de busca
        num_results: Número máximo de resultados
        request_id: ID da requisição
        
    Returns:
        Tuple de (lista de dicts com title, link, snippet, número de retries)
    """
    # 1. Verificar cache
    cached_results = await search_cache.get(query, num_results)
    if cached_results is not None:
        logger.debug(f"🔍 Serper (cache hit): {query[:30]}...")
        return cached_results, 0  # Cache hit = 0 retries
    
    # 2. Buscar via Serper API
    results, retries = await serper_manager.search(query, num_results, request_id=request_id)
    
    # 3. Armazenar em cache se houve resultados
    if results:
        await search_cache.set(query, results, num_results)
    
    return results, retries


async def close_serper_client():
    """Fecha o cliente HTTP global (chamar no shutdown da aplicação)."""
    await serper_manager.close()
    logger.info("🌐 Discovery: Cliente HTTP fechado")


def _build_search_queries(
    razao_social: str,
    nome_fantasia: str,
    municipio: str
) -> List[str]:
    """
    Constrói queries de busca otimizadas.
    
    Queries (máximo 2):
    - Q1: Nome Fantasia + cidade (se existir)
    - Q2: Razão Social + cidade (se existir)
    """
    queries = []
    
    nf = nome_fantasia.strip() if nome_fantasia else ""
    rs = razao_social.strip() if razao_social else ""
    city = municipio.strip() if municipio else ""
    
    # Q1: Nome Fantasia + Municipio
    if nf:
        q1 = f'{nf} {city} site oficial'.strip()
        queries.append(q1)
    
    # Q2: Razão Social + Municipio (apenas se diferente)
    clean_rs = ""
    if rs:
        clean_rs = rs.replace(" LTDA", "").replace(" S.A.", "").replace(" EIRELI", "")
        clean_rs = clean_rs.replace(" ME", "").replace(" EPP", "").replace(" S/A", "").strip()
    
    if clean_rs:
        q2 = f'{clean_rs} {city} site oficial'.strip()
        if not nf or clean_rs.upper() != nf.upper():
            queries.append(q2)
    
    return queries


def _filter_search_results(
    results: List[Dict[str, str]],
    ctx_label: str = ""
) -> List[Dict[str, str]]:
    """Filtra resultados de busca removendo domínios da blacklist."""
    filtered = []
    blacklisted_count = 0
    seen_links = set()
    
    for r in results:
        link = r.get('link', '')
        
        # Deduplicar
        if link in seen_links:
            continue
        seen_links.add(link)
        
        # Verificar blacklist
        if is_blacklisted_domain(link):
            blacklisted_count += 1
            continue
        
        filtered.append(r)
    
    if blacklisted_count > 0:
        logger.debug(f"{ctx_label}🚫 {blacklisted_count} resultados filtrados (blacklist)")
    
    return filtered


async def find_company_website(
    razao_social: str,
    nome_fantasia: str,
    cnpj: str,
    email: Optional[str] = None,
    municipio: Optional[str] = None,
    cnaes: Optional[List[str]] = None,
    ctx_label: str = "",
    request_id: str = ""
) -> Optional[str]:
    """
    Orquestra a descoberta do site oficial da empresa.

    Fluxo:
    1. Construir queries de busca
    2. Executar buscas em paralelo (via Serper API)
    3. Filtrar resultados (blacklist)
    4. Usar DiscoveryAgent para análise

    Args:
        razao_social: Razão social da empresa
        nome_fantasia: Nome fantasia
        cnpj: CNPJ da empresa
        email: Email (opcional, usado para validação cruzada)
        municipio: Cidade
        cnaes: Lista de CNAEs
        ctx_label: Label para logging

    Returns:
        URL do site oficial ou None
    """
    # 1. CONSTRUIR QUERIES
    queries = _build_search_queries(razao_social, nome_fantasia, municipio or "")

    if not queries:
        logger.warning(f"{ctx_label}⚠️ Sem Nome Fantasia ou Razão Social para busca.")
        return None

    # 2. EXECUTAR BUSCAS EM PARALELO
    all_results = []
    serper_start = time.time()
    total_retries = 0
    
    search_tasks = [search_google_serper(q, num_results=SERPER_NUM_RESULTS, request_id=request_id) for q in queries]
    query_results = await asyncio.gather(*search_tasks, return_exceptions=True)
    
    serper_duration = (time.time() - serper_start) * 1000
    
    failed_queries = 0
    for i, query_result in enumerate(query_results):
        if isinstance(query_result, Exception):
            logger.warning(f"{ctx_label}⚠️ Query {i+1} falhou: {query_result}")
            failed_queries += 1
            continue
        
        # query_result é uma tupla (results, retries)
        if isinstance(query_result, tuple) and len(query_result) == 2:
            results, retries = query_result
            all_results.extend(results)
            total_retries += retries
        else:
            # Fallback para compatibilidade
            all_results.extend(query_result if isinstance(query_result, list) else [])
    
    # 3. FILTRAR RESULTADOS
    filtered_results = _filter_search_results(all_results, ctx_label)

    if not filtered_results:
        logger.warning(f"{ctx_label}⚠️ Nenhum resultado encontrado após filtros.")
        return None

    # 4. USAR DISCOVERY AGENT PARA ANÁLISE
    discovery_agent = get_discovery_agent()
    agent_start = time.time()

    try:
        site = await discovery_agent.find_website(
            nome_fantasia=nome_fantasia,
            razao_social=razao_social,
            cnpj=cnpj,
            email=email,
            municipio=municipio,
            cnaes=cnaes,
            search_results=filtered_results,
            ctx_label=ctx_label,
            request_id=request_id
        )

        agent_duration = (time.time() - agent_start) * 1000

        if not site:
            logger.warning(f"{ctx_label}Site não encontrado pelo agente")

        return site

    except Exception as e:
        agent_duration = (time.time() - agent_start) * 1000
        logger.error(f"{ctx_label}❌ Erro no DiscoveryAgent: {e}")
        return None


def get_discovery_status() -> dict:
    """Retorna status dos componentes de discovery."""
    return {
        "serper": serper_manager.get_status(),
        "cache": search_cache.get_status(),
    }
