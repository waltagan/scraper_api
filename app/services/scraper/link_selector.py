"""
Seleção inteligente de links para scraping de subpáginas.
Usa LLM para priorizar links mais relevantes para construção de perfil.
"""

import json
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

logger = logging.getLogger(__name__)


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
    ctx_label: str = ""
) -> List[str]:
    """
    Usa LLM para selecionar links mais relevantes para construção de perfil.
    
    Args:
        links: Conjunto de links encontrados na página
        base_url: URL base do site
        max_links: Número máximo de links a retornar
        ctx_label: Label de contexto para logs
    
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
    
    # Se poucos links, retornar todos
    if len(filtered_links) <= max_links:
        duration = time.perf_counter() - start_ts
        logger.info(f"{ctx_label}[PERF] select_links_llm duration={duration:.3f}s strategy=short_circuit")
        return list(filtered_links)
    
    # Importar dependências de LLM
    from openai import AsyncOpenAI
    from app.core.config import settings
    
    client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
    links_list = "\n".join([f"{i+1}. {url}" for i, url in enumerate(sorted(filtered_links))])
    
    prompt = f"""Você é um especialista em análise de websites B2B.

CONTEXTO: Estamos coletando dados para criar um perfil completo de empresa com os seguintes campos:

**IDENTITY**: Nome da empresa, CNPJ, tagline, descrição, ano de fundação, número de funcionários
**CLASSIFICATION**: Indústria, modelo de negócio (B2B/B2C), público-alvo, cobertura geográfica
**TEAM**: Tamanho da equipe, cargos-chave, certificações do time
**OFFERINGS**: Produtos, categorias de produtos, serviços, detalhes de serviços, modelos de engajamento, diferenciais
**REPUTATION**: Certificações, prêmios, parcerias, lista de clientes, cases de sucesso
**CONTACT**: E-mails, telefones, LinkedIn, endereço, localizações

TAREFA: Selecione os {max_links} links MAIS RELEVANTES da lista abaixo. Priorize:
1. Páginas "Sobre", "Quem Somos", "Institucional"
2. Páginas de Produtos/Serviços/Soluções/Catálogos
3. Páginas de Cases, Clientes, Projetos
4. Páginas de Contato, Equipe, Localizações
5. Páginas de Certificações, Prêmios, Parcerias

EVITE: Blogs, notícias, políticas de privacidade, login, carrinho, termos de uso

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
        
        try:
            result = json.loads(content)
            if isinstance(result, list):
                selected_indices = result
            elif "links" in result:
                selected_indices = result["links"]
            elif "selected" in result:
                selected_indices = result["selected"]
            elif "indices" in result:
                selected_indices = result["indices"]
            else:
                for value in result.values():
                    if isinstance(value, list):
                        selected_indices = value
                        break
                else:
                    selected_indices = []
        except:
            logger.warning(f"{ctx_label}LLM não retornou JSON válido, usando fallback")
            return prioritize_links(filtered_links, base_url)[:max_links]
        
        sorted_links = sorted(filtered_links)
        selected_urls = []
        for idx in selected_indices:
            try:
                idx_int = int(idx)
                if 1 <= idx_int <= len(sorted_links):
                    selected_urls.append(sorted_links[idx_int - 1])
            except (ValueError, TypeError):
                continue
        
        # Se LLM retornou lista vazia, mas tínhamos links válidos, usar fallback heurístico
        if not selected_urls and filtered_links:
            logger.warning(f"{ctx_label}LLM retornou lista vazia de links, usando fallback heurístico para garantir navegação")
            return prioritize_links(filtered_links, base_url)[:max_links]

        duration = time.perf_counter() - start_ts
        logger.info(f"{ctx_label}[PERF] select_links_llm duration={duration:.3f}s selected={len(selected_urls)} strategy=llm")
        return selected_urls[:max_links]
        
    except Exception as e:
        logger.error(f"{ctx_label}Erro ao usar LLM para selecionar links: {e}")
        return prioritize_links(filtered_links, base_url)[:max_links]

