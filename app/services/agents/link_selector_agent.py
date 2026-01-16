"""
Agente de Seleção de Links - Seleciona links mais relevantes para scraping.

Responsável por analisar uma lista de links e selecionar os mais relevantes
para construção de perfil de empresa.
"""

import json
import logging
from typing import List, Set, Optional

from .base_agent import BaseAgent
from app.services.llm_manager import LLMPriority
from app.services.concurrency_manager.config_loader import get_section as get_config

logger = logging.getLogger(__name__)


class LinkSelectorAgent(BaseAgent):
    """
    Agente especializado em selecionar links relevantes para scraping.
    
    Usa prioridade HIGH por padrão pois é crítico para o fluxo
    (bloqueia o scraper até selecionar os links).
    
    v4.2: Timeout agressivo de 15s para fail-fast.
    """
    
    # Timeout e retries configuráveis
    _CFG = get_config("discovery/llm_agents", {}).get("link_selector", {})
    DEFAULT_TIMEOUT = _CFG.get("timeout", 15.0)
    DEFAULT_MAX_RETRIES = _CFG.get("max_retries", 2)
    
    SYSTEM_PROMPT = """Você é um assistente especializado em análise de websites B2B. Responda sempre em JSON válido."""
    
    def _build_user_prompt(
        self,
        links: List[str] = None,
        base_url: str = "",
        max_links: int = 30,
        **kwargs
    ) -> str:
        """
        Constrói prompt com lista de links para seleção.
        
        Args:
            links: Lista de links para analisar
            base_url: URL base do site
            max_links: Número máximo de links a selecionar
        
        Returns:
            Prompt formatado
        """
        links_list = "\n".join([f"{i+1}. {url}" for i, url in enumerate(sorted(links or []))])
        
        return f"""Você é um especialista em análise de websites B2B.

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
    
    def _parse_response(
        self,
        response: str,
        links: List[str] = None,
        **kwargs
    ) -> List[str]:
        """
        Processa resposta e extrai URLs selecionadas.
        
        Args:
            response: Resposta JSON do LLM
            links: Lista original de links (para mapear índices)
        
        Returns:
            Lista de URLs selecionadas
        """
        links = links or []
        sorted_links = sorted(links)
        
        try:
            result = json.loads(response)
            
            # Extrair lista de índices
            if isinstance(result, list):
                selected_indices = result
            elif "links" in result:
                selected_indices = result["links"]
            elif "selected" in result:
                selected_indices = result["selected"]
            elif "indices" in result:
                selected_indices = result["indices"]
            else:
                # Procurar primeiro array no resultado
                for value in result.values():
                    if isinstance(value, list):
                        selected_indices = value
                        break
                else:
                    selected_indices = []
            
            # Mapear índices para URLs
            selected_urls = []
            for idx in selected_indices:
                try:
                    idx_int = int(idx)
                    if 1 <= idx_int <= len(sorted_links):
                        selected_urls.append(sorted_links[idx_int - 1])
                except (ValueError, TypeError):
                    continue
            
            logger.debug(f"LinkSelectorAgent: Selecionados {len(selected_urls)} links")
            return selected_urls
            
        except json.JSONDecodeError:
            logger.warning("LinkSelectorAgent: LLM não retornou JSON válido")
            return []
        except Exception as e:
            logger.warning(f"LinkSelectorAgent: Erro ao processar resposta: {e}")
            return []
    
    async def select_links(
        self,
        links: Set[str],
        base_url: str,
        max_links: int = 30,
        ctx_label: str = "",
        request_id: str = ""
    ) -> List[str]:
        """
        Método principal para selecionar links relevantes.
        
        Args:
            links: Conjunto de links encontrados na página
            base_url: URL base do site
            max_links: Número máximo de links a retornar
            ctx_label: Label de contexto para logs
            request_id: ID da requisição
        
        Returns:
            Lista de URLs selecionadas
        """
        if not links:
            return []
        
        links_list = list(links)
        
        # Se poucos links, retornar todos
        if len(links_list) <= max_links:
            logger.debug(f"{ctx_label}LinkSelectorAgent: Poucos links ({len(links_list)}), retornando todos")
            return links_list
        
        try:
            selected = await self.execute(
                priority=LLMPriority.HIGH,  # LinkSelector tem prioridade alta
                timeout=self.DEFAULT_TIMEOUT,
                ctx_label=ctx_label,
                request_id=request_id,
                links=links_list,
                base_url=base_url,
                max_links=max_links
            )
            
            if selected:
                return selected[:max_links]
            
            # Fallback se LLM falhou
            logger.warning(f"{ctx_label}LinkSelectorAgent: Usando fallback (primeiros {max_links} links)")
            return links_list[:max_links]
            
        except Exception as e:
            logger.warning(f"{ctx_label}LinkSelectorAgent: Erro na seleção, usando fallback: {e}")
            return links_list[:max_links]


# Instância singleton
_link_selector_agent: Optional[LinkSelectorAgent] = None


def get_link_selector_agent() -> LinkSelectorAgent:
    """Retorna instância singleton do LinkSelectorAgent."""
    global _link_selector_agent
    if _link_selector_agent is None:
        _link_selector_agent = LinkSelectorAgent()
    return _link_selector_agent


