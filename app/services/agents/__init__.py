"""
Módulo de Agentes LLM v1.0

Contém agentes especializados para diferentes tarefas que utilizam LLM.
Cada agente encapsula seu prompt e lógica de processamento de resposta.

Agentes disponíveis:
- DiscoveryAgent: Encontra o site oficial de uma empresa
- LinkSelectorAgent: Seleciona links mais relevantes para scraping
- ProfileExtractorAgent: Extrai dados estruturados de conteúdo scraped
"""

from .base_agent import BaseAgent
from .discovery_agent import DiscoveryAgent, get_discovery_agent
from .link_selector_agent import LinkSelectorAgent, get_link_selector_agent
from .profile_extractor_agent import ProfileExtractorAgent, get_profile_extractor_agent

__all__ = [
    # Base
    'BaseAgent',
    
    # Discovery
    'DiscoveryAgent',
    'get_discovery_agent',
    
    # Link Selector
    'LinkSelectorAgent',
    'get_link_selector_agent',
    
    # Profile Extractor
    'ProfileExtractorAgent',
    'get_profile_extractor_agent',
]


