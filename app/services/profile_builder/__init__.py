"""
Módulo Profile Builder v3.0

Responsável por analisar conteúdo scraped e extrair perfis de empresas.

Este módulo contém:
- LLMService: Serviço principal de análise de conteúdo
- Processamento de conteúdo (chunking, normalização, merge)
- Configurações específicas de perfil

Para gerenciamento de chamadas LLM (rate limiting, health monitoring, etc),
use o módulo app.services.llm_manager
"""

"""
Módulo Profile Builder (versão sem LLM).

Antes, este pacote centralizava serviços de LLM (`LLMService`, `provider_caller`,
configurações de modelo etc.) para montagem de perfil. Essa responsabilidade foi
descontinuada: **nenhuma funcionalidade de LLM é mais exposta por aqui**.

Por enquanto, mantemos apenas utilitários puramente determinísticos relacionados
à fusão/normalização de perfis, caso ainda sejam úteis em outros fluxos.
"""

from .profile_merger import merge_profiles
from .response_normalizer import normalize_llm_response

__all__ = [
    'merge_profiles',
    'normalize_llm_response',
]
