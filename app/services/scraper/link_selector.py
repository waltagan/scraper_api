"""
Seleção inteligente de links para scraping de subpáginas.

REFATORADO: Agora usa LinkSelectorAgent para seleção de links
via llm_manager centralizado.
"""

import time
import logging
from typing import List, Set
from urllib.parse import urlparse

from .constants import (
    DOCUMENT_EXTENSIONS,
    EXCLUDED_EXTENSIONS,
    ASSET_DIRECTORIES,
    HIGH_PRIORITY_KEYWORDS,
    LOW_PRIORITY_KEYWORDS
)

# Usar agente de seleção de links
from app.services.agents import get_link_selector_agent

logger = logging.getLogger(__name__)

# NOTA: Não precisamos de semáforo aqui!
# O controle de concorrência é feito pelo llm_manager que já gerencia:
# - Rate limiting (RPM/TPM)
# - Semáforos por provider
# - Sistema de prioridades
# - Health monitoring


def filter_non_html_links(links: Set[str]) -> Set[str]:
    """
    Filtra links que são arquivos não-HTML.
    Remove documentos, imagens e outros arquivos estáticos.
    """
    filtered = set()
    
    for link in links:
        link = link.strip().rstrip(',')
        if not link:
            continue
            
        parsed = urlparse(link)
        path_lower = parsed.path.lower()
        
        # Excluir documentos
        if any(path_lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
            continue
        
        # Excluir arquivos estáticos
        if any(path_lower.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
            continue
        
        # Excluir imagens em query string
        if any(ext in parsed.query.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']):
            continue
        
        # Excluir diretórios de assets
        if any(dir_name in path_lower for dir_name in ASSET_DIRECTORIES):
            if any(path_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico']):
                continue
        
        filtered.add(link)
    
    return filtered


def prioritize_links(links: Set[str], base_url: str) -> List[str]:
    """
    Prioriza links por relevância usando heurísticas.
    Fallback quando LLM não está disponível.
    
    Returns:
        Lista de links ordenados por prioridade (mais relevantes primeiro)
    """
    scored = []
    
    for link in links:
        link = link.strip().rstrip(',')
        if not link or link.rstrip('/') == base_url.rstrip('/'):
            continue
            
        score = 0
        lower = link.lower()
        
        # Penalizar links de baixa prioridade
        if any(k in lower for k in LOW_PRIORITY_KEYWORDS):
            score -= 100
        
        # Bonificar links de alta prioridade
        if any(k in lower for k in HIGH_PRIORITY_KEYWORDS):
            score += 50
        
        # Penalizar URLs muito profundas
        score -= len(urlparse(link).path.split('/'))
        
        # Bonificar links de paginação (exceto se for blog)
        if any(x in lower for x in ["page", "p=", "pagina", "nav"]):
            if not any(k in lower for k in LOW_PRIORITY_KEYWORDS):
                score += 30

        scored.append((score, link))
    
    # Ordenar por score (maior primeiro) e filtrar muito negativos
    return [l for s, l in sorted(scored, key=lambda x: x[0], reverse=True) if s > -80]


async def select_links_with_llm(
    links: Set[str], 
    base_url: str, 
    max_links: int = 30,
    ctx_label: str = "",
    request_id: str = ""
) -> List[str]:
    """
    Usa LLM para selecionar links mais relevantes para construção de perfil.
    
    REFATORADO: Agora usa LinkSelectorAgent via llm_manager centralizado.
    
    Args:
        links: Conjunto de links encontrados na página
        base_url: URL base do site
        max_links: Número máximo de links a retornar
        ctx_label: Label de contexto para logs
        request_id: ID da requisição
    
    Returns:
        Lista de links selecionados pelo LLM
    """
    start_ts = time.perf_counter()
    
    if not links:
        return []
    
    # Filtrar links não-HTML
    filtered_links = filter_non_html_links(links)
    logger.info(
        f"{ctx_label}Filtrados {len(links) - len(filtered_links)} links não-HTML. "
        f"Restam {len(filtered_links)} links válidos."
    )
    
    if not filtered_links:
        return []
    
    # Se poucos links, retornar todos (sem usar LLM)
    if len(filtered_links) <= max_links:
        duration = time.perf_counter() - start_ts
        logger.info(f"{ctx_label}[PERF] select_links_llm duration={duration:.3f}s strategy=short_circuit")
        return list(filtered_links)
    
    # Chamar agente diretamente - o llm_manager já controla a concorrência
    return await _select_links_with_agent(
        filtered_links, base_url, max_links, ctx_label, start_ts, request_id
    )


async def _select_links_with_agent(
    filtered_links: Set[str],
    base_url: str,
    max_links: int,
    ctx_label: str,
    start_ts: float,
    request_id: str = ""
) -> List[str]:
    """
    Implementação interna usando LinkSelectorAgent.
    """
    link_selector = get_link_selector_agent()
    
    try:
        selected_urls = await link_selector.select_links(
            links=filtered_links,
            base_url=base_url,
            max_links=max_links,
            ctx_label=ctx_label,
            request_id=request_id
        )
        
        if selected_urls:
            duration = time.perf_counter() - start_ts
            logger.info(
                f"{ctx_label}[PERF] select_links_llm duration={duration:.3f}s "
                f"selected={len(selected_urls)} strategy=agent"
            )
            return selected_urls[:max_links]
        
        # LLM retornou vazio - usar fallback
        logger.warning(f"{ctx_label}[LinkSelector] Agente retornou lista vazia, usando fallback heurístico")
        return prioritize_links(filtered_links, base_url)[:max_links]
        
    except Exception as e:
        duration = time.perf_counter() - start_ts
        logger.warning(
            f"{ctx_label}[LinkSelector] Erro no agente após {duration:.2f}s: {e}. "
            f"Usando fallback heurístico"
        )
        return prioritize_links(filtered_links, base_url)[:max_links]
