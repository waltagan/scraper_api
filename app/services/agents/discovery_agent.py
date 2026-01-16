"""
Agente de Discovery - Encontra o site oficial de uma empresa.

Responsável por analisar resultados de busca e identificar o site oficial
de uma empresa brasileira com base em nome fantasia, razão social, CNPJ, etc.
"""

import json
import logging
from typing import Optional, List, Any

from .base_agent import BaseAgent
from app.services.llm_manager import LLMPriority
from app.services.concurrency_manager.config_loader import get_section as get_config

logger = logging.getLogger(__name__)


class DiscoveryAgent(BaseAgent):
    """
    Agente especializado em encontrar sites oficiais de empresas.
    
    Usa prioridade HIGH por padrão pois é crítico para o fluxo
    (bloqueia o scraper até encontrar o site).
    
    v4.2: Timeout agressivo de 15s para fail-fast e retry rápido.
    """
    
    # Timeout e retries configuráveis
    _CFG = get_config("discovery/llm_agents", {}).get("discovery", {})
    DEFAULT_TIMEOUT = _CFG.get("timeout", 20.0)
    DEFAULT_MAX_RETRIES = _CFG.get("max_retries", 2)
    
    SYSTEM_PROMPT = """Você é um especialista em encontrar sites oficiais de empresas brasileiras.

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
    
    def _build_user_prompt(
        self,
        nome_fantasia: str = "",
        razao_social: str = "",
        cnpj: str = "",
        email: str = "",
        municipio: str = "",
        cnaes: List[str] = None,
        search_results: List[dict] = None,
        **kwargs
    ) -> str:
        """
        Constrói prompt com dados da empresa e resultados de busca.
        
        Args:
            nome_fantasia: Nome fantasia da empresa
            razao_social: Razão social
            cnpj: CNPJ
            email: E-mail (pode ajudar a identificar domínio)
            municipio: Cidade/município
            cnaes: Lista de CNAEs (atividades)
            search_results: Resultados de busca do Google
        
        Returns:
            Prompt formatado
        """
        results_text = json.dumps(search_results or [], indent=2, ensure_ascii=False)
        
        return f"""
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
    
    def _parse_response(self, response: str, **kwargs) -> Optional[str]:
        """
        Processa resposta e extrai URL do site oficial.
        
        Args:
            response: Resposta JSON do LLM
        
        Returns:
            URL do site oficial ou None se não encontrado
        """
        try:
            # Limpar markdown se presente
            content = response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            data = json.loads(content)
            
            # Tratar lista
            if isinstance(data, list):
                if len(data) > 0:
                    data = data[0]
                else:
                    return None
            
            # Verificar se encontrou site oficial
            if data.get("site_oficial") == "sim" and data.get("site"):
                site = data.get("site")
                if site and site != "nao_encontrado":
                    logger.debug(f"DiscoveryAgent: Site encontrado - {site}")
                    return site
            
            justificativa = data.get("justificativa", "Sem justificativa")
            logger.debug(f"DiscoveryAgent: Site não encontrado - {justificativa}")
            return None
            
        except json.JSONDecodeError as e:
            logger.warning(f"DiscoveryAgent: Erro ao parsear JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"DiscoveryAgent: Erro ao processar resposta: {e}")
            return None
    
    async def find_website(
        self,
        nome_fantasia: str,
        razao_social: str,
        cnpj: str = "",
        email: str = "",
        municipio: str = "",
        cnaes: List[str] = None,
        search_results: List[dict] = None,
        ctx_label: str = "",
        request_id: str = ""
    ) -> Optional[str]:
        """
        Método principal para encontrar site oficial de uma empresa.
        
        Args:
            nome_fantasia: Nome fantasia da empresa
            razao_social: Razão social
            cnpj: CNPJ
            email: E-mail
            municipio: Cidade/município
            cnaes: Lista de CNAEs
            search_results: Resultados de busca do Google
            ctx_label: Label de contexto para logs
            request_id: ID da requisição
        
        Returns:
            URL do site oficial ou None
        """
        if not search_results:
            logger.warning(f"{ctx_label}DiscoveryAgent: Sem resultados de busca")
            return None
        
        return await self.execute(
            priority=LLMPriority.HIGH,  # Discovery tem prioridade alta
            ctx_label=ctx_label,
            request_id=request_id,
            nome_fantasia=nome_fantasia,
            razao_social=razao_social,
            cnpj=cnpj,
            email=email,
            municipio=municipio,
            cnaes=cnaes,
            search_results=search_results
        )


# Instância singleton
_discovery_agent: Optional[DiscoveryAgent] = None


def get_discovery_agent() -> DiscoveryAgent:
    """Retorna instância singleton do DiscoveryAgent."""
    global _discovery_agent
    if _discovery_agent is None:
        _discovery_agent = DiscoveryAgent()
    return _discovery_agent


