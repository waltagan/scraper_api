"""
Agente de Extração de Perfil (versão sem LLM).

Esta implementação foi simplificada para **não realizar nenhuma chamada a LLM**.
Ela existe apenas para manter a compatibilidade com o restante da API enquanto
o novo pipeline de montagem de perfil (sem LLM) é projetado.
"""

import logging
from typing import Optional

from app.schemas.profile import CompanyProfile

logger = logging.getLogger(__name__)


class ProfileExtractorAgent:
    """
    Agente de perfil neutro (sem LLM).

    Importante:
    - Não faz chamadas a serviços de LLM.
    - Serve apenas como stub/placeholder para manter a API funcionando.
    - Pode ser substituído futuramente por um extrator determinístico/regra‑baseado.
    """

    async def extract_profile(
        self,
        content: str,
        ctx_label: str = "",
        request_id: str = ""
    ) -> CompanyProfile:
        """
        Extrai perfil de forma não‑LLM.

        Atualmente, retorna sempre um `CompanyProfile` vazio, apenas logando o uso.
        Isso garante que **nenhuma requisição a LLM** seja feita no fluxo de criação
        de perfil, atendendo ao requisito de desligar completamente essa parte.
        """
        if not content or not content.strip():
            logger.warning(f"{ctx_label}ProfileExtractorAgent: Conteúdo vazio ou muito curto")
            return CompanyProfile()

        logger.info(
            f"{ctx_label}ProfileExtractorAgent: Extração de perfil via LLM desativada "
            f"(content_len={len(content)}, request_id={request_id})"
        )

        # Aqui poderemos, no futuro, implementar um extrator baseado em regras.
        return CompanyProfile()


# Instância singleton
_profile_extractor_agent: Optional[ProfileExtractorAgent] = None


def get_profile_extractor_agent() -> ProfileExtractorAgent:
    """Retorna instância singleton do ProfileExtractorAgent."""
    global _profile_extractor_agent
    if _profile_extractor_agent is None:
        _profile_extractor_agent = ProfileExtractorAgent()
    return _profile_extractor_agent
