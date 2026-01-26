"""
Agente de Extração de Perfil - Extrai dados estruturados de conteúdo scraped.

Responsável por analisar conteúdo de sites e extrair informações de perfil
de empresa em formato estruturado.

v8.0: Solução definitiva anti-loop com 4 camadas
v8.2: Balanceamento qualidade + anti-loop (truncamento determinístico)
v9.0: Roteamento fechado + micro-shots cirúrgicos (qualidade máxima)
v9.1: Caps reduzidos + parâmetros mais estáveis (menos degeneração)
      - presence_penalty = 0.0, frequency_penalty = 0.0
      - temperature = 0.15, top_p = 0.9
      - max_tokens mais conservador (900/1400/2200)
      - Schema sem ser colado no user prompt (reduz contexto)
"""

import json
import logging
from typing import Optional, Any, Dict

import json_repair

from .base_agent import BaseAgent
from app.services.llm_manager import LLMPriority
from app.schemas.profile import CompanyProfile
from app.services.concurrency_manager.config_loader import get_section as get_config

logger = logging.getLogger(__name__)

# Cache do schema JSON para evitar recomputação
_COMPANY_PROFILE_SCHEMA: Optional[Dict[str, Any]] = None


def _get_company_profile_schema() -> Dict[str, Any]:
    """
    Retorna JSON Schema do CompanyProfile para structured output.
    
    Usa cache para evitar recomputação do schema.
    
    Returns:
        Dict com JSON Schema completo do CompanyProfile
    """
    global _COMPANY_PROFILE_SCHEMA
    
    if _COMPANY_PROFILE_SCHEMA is None:
        # Gerar schema a partir do modelo Pydantic
        _COMPANY_PROFILE_SCHEMA = CompanyProfile.model_json_schema()
        logger.info(
            f"ProfileExtractorAgent: Schema JSON gerado "
            f"({len(json.dumps(_COMPANY_PROFILE_SCHEMA))} chars)"
        )
    
    return _COMPANY_PROFILE_SCHEMA


class ProfileExtractorAgent(BaseAgent):
    """
    Agente especializado em extrair perfil de empresa de conteúdo scraped.
    
    v8.0: Solução definitiva anti-loop (não depende de XGrammar)
    v8.2: Balanceamento qualidade + anti-loop
    v9.0: Roteamento fechado + micro-shots cirúrgicos
    v9.1: Parâmetros mais estáveis + schema reduzido
          - Zera presence/frequency (evita sub-preenchimento)
          - Caps menores no schema (menos runaway)
          - User prompt sem schema (economia de tokens)
    
    Usa prioridade NORMAL por padrão pois roda após Discovery e LinkSelector.
    """
    
    # Timeout e retries configuráveis via app/configs/llm_agents.json
    _CFG = get_config("profile/llm_agents", {}).get("profile_extractor", {})
    DEFAULT_TIMEOUT = _CFG.get("timeout", 120.0)
    DEFAULT_MAX_RETRIES = _CFG.get("max_retries", 3)
    
    # Parâmetros otimizados para Qwen3-8B + SGLang Guided Decoding v10.0
    # v10.0: Otimizado para precisão máxima com Guided Decoding
    #       - temperature=0.1 para precisão (Qwen3-8B)
    #       - top_p=0.95 para nucleus sampling otimizado
    #       - repetition_penalty via extra_body (mais efetivo)
    #       - Controle de repetição via schema (uniqueItems + maxItems)
    DEFAULT_TEMPERATURE: float = 0.1         # v10.0: Precisão máxima para Qwen3-8B
    DEFAULT_TOP_P: float = 0.95              # v10.0: Nucleus sampling otimizado
    DEFAULT_PRESENCE_PENALTY: float = 0.0    # v10.0: Zerado (repetition_penalty via extra_body)
    DEFAULT_FREQUENCY_PENALTY: float = 0.0   # v10.0: Zerado (repetition_penalty via extra_body)
    DEFAULT_SEED: int = 42                   # Reprodutibilidade
    
    # =========================================================================
    # SYSTEM_PROMPT v10.0 - XML Structured + Chain-of-Thought
    # =========================================================================
    # v10.0: Refatoração para "LLM como motor de computação estruturada"
    # - Prompts XML estruturados (Qwen3 processa melhor dados estruturados)
    # - Chain-of-Thought para raciocínio explícito
    # - Removidas instruções de formato JSON (SGLang Guided Decoding cuida disso)
    # - Foco em lógica de extração, não em formatação
    # =========================================================================
    
    SYSTEM_PROMPT = """<role>Você é um Analista de Dados B2B Especialista em extração estruturada.</role>

<task>Extrair informações corporativas precisas do conteúdo fornecido em <raw_content>.</task>

<extraction_logic>
1. IDENTIDADE: Extraia o nome comercial e CNPJ (se houver).
2. CLASSIFICAÇÃO: Determine o setor com base no core business.
3. PRODUTOS vs SERVIÇOS: 
   - Produtos: Itens físicos, softwares com SKU, modelos ou versões.
   - Serviços: Consultoria, manutenção, treinamentos.
</extraction_logic>

<constraints>
- Use null para dados não encontrados.
- Mantenha a terminologia técnica original.
- Máxima fidelidade às evidências: não invente clientes ou prêmios.
- Idioma: Português (Brasil), exceto termos técnicos globais.
</constraints>

<reasoning>
Antes de preencher o JSON, identifique mentalmente:
1. Seções de Produtos e Serviços no conteúdo
2. Nomes próprios explícitos (clientes, certificações)
3. Diferenciação clara entre produtos físicos e serviços intangíveis
</reasoning>
"""
    
    def _get_json_schema(self) -> Optional[Dict[str, Any]]:
        """
        Retorna JSON Schema do CompanyProfile para structured output.
        
        SGLang/XGrammar usa este schema para garantir que a saída
        seja um JSON válido conforme a estrutura definida.
        
        Returns:
            Dict com JSON Schema do CompanyProfile
        """
        return _get_company_profile_schema()
    
    def _get_schema_name(self) -> str:
        """
        Retorna nome do schema para identificação.
        
        Returns:
            Nome do schema
        """
        return "company_profile_extraction"
    
    def _build_user_prompt(self, content: str = "", **kwargs) -> str:
        """
        Constrói prompt com conteúdo para análise usando tags XML.
        
        v10.0: XML structured prompts para melhor processamento pelo Qwen3-8B
              - Conteúdo envolto em <raw_content> para estruturação clara
              - Chain-of-Thought implícito via estrutura XML
        
        Args:
            content: Conteúdo scraped para análise
        
        Returns:
            Prompt formatado em XML (sem schema - Guided Decoding cuida disso)
        """
        return f"""<raw_content>
{content}
</raw_content>

<instruction>Extraia o perfil completo desta empresa. Use apenas evidência explícita do conteúdo acima.</instruction>"""
    
    def _parse_response(self, response: str, **kwargs) -> CompanyProfile:
        """
        Processa resposta e cria CompanyProfile.
        
        v10.0: SGLang Guided Decoding garante JSON válido
              - Removidas lógicas de fallback de parsing (não são mais necessárias)
              - Confiança total no Guided Decoding do SGLang
              - Pós-processamento mínimo (apenas normalização)
        
        Args:
            response: Resposta JSON do LLM (garantida válida pelo Guided Decoding)
        
        Returns:
            CompanyProfile com dados extraídos
        """
        try:
            content = response.strip()
            
            # v10.0: SGLang Guided Decoding garante JSON válido
            # Parse direto sem fallbacks defensivos
            try:
                data = json.loads(content)
                logger.debug("ProfileExtractorAgent: JSON parseado (Guided Decoding)")
            except json.JSONDecodeError as e:
                # Isso NÃO deveria acontecer com Guided Decoding
                # Log crítico para investigação
                logger.error(
                    f"ProfileExtractorAgent: JSON inválido apesar de Guided Decoding: {e}. "
                    f"Primeiros 500 chars: {content[:500]}"
                )
                return CompanyProfile()
            
            # Normalizar estrutura (array → dict)
            if isinstance(data, list):
                data = data[0] if data and isinstance(data[0], dict) else {}
            if not isinstance(data, dict):
                logger.warning(f"ProfileExtractorAgent: Resposta não é dict, tipo: {type(data)}")
                data = {}
            
            # Normalizar resposta (validação de tipos e estruturas)
            data = self._normalize_response(data)
            
            # Criar perfil usando validação Pydantic
            try:
                return CompanyProfile.model_validate(data)
            except Exception as e:
                logger.warning(f"ProfileExtractorAgent: Validação Pydantic falhou: {e}")
                # Fallback mínimo: construtor direto
                try:
                    return CompanyProfile(**data)
                except Exception:
                    logger.error(f"ProfileExtractorAgent: Falha crítica na criação do perfil")
                    return CompanyProfile()
                
        except Exception as e:
            logger.error(f"ProfileExtractorAgent: Erro ao processar resposta: {e}")
            return CompanyProfile()
    
    def _deduplicate_and_filter_lists(self, data: dict) -> dict:
        """
        Pós-processamento leve: deduplicação básica (safety net).
        
        v10.0: Guided Decoding + schema constraints devem prevenir duplicatas
              - Mantido apenas como safety net para casos extremos
              - Deduplicação básica (sem filtro anti-template pesado)
        
        Args:
            data: Dados extraídos pelo LLM
        
        Returns:
            Dados com listas deduplicadas (leve)
        """
        if not isinstance(data, dict):
            return data
        
        def deduplicate_list(items: list) -> list:
            """Deduplica lista mantendo ordem da primeira ocorrência."""
            if not items:
                return []
            seen = set()
            unique = []
            for item in items:
                if isinstance(item, str):
                    item_normalized = item.strip().lower()
                    if item_normalized and item_normalized not in seen:
                        seen.add(item_normalized)
                        unique.append(item.strip())
                else:
                    unique.append(item)
            return unique
        
        # v10.0: Removido filter_template_items pesado
        # Guided Decoding + schema constraints devem prevenir loops
        # Apenas deduplicação básica mantida
        
        # Processar offerings (crítico)
        if 'offerings' in data and isinstance(data['offerings'], dict):
            offerings = data['offerings']
            
            # Deduplicate products
            if 'products' in offerings and isinstance(offerings['products'], list):
                offerings['products'] = deduplicate_list(offerings['products'])
            
            # Deduplicate services
            if 'services' in offerings and isinstance(offerings['services'], list):
                offerings['services'] = deduplicate_list(offerings['services'])
            
            # Deduplicate product_categories[].items (leve)
            if 'product_categories' in offerings and isinstance(offerings['product_categories'], list):
                for category in offerings['product_categories']:
                    if isinstance(category, dict) and 'items' in category:
                        # v10.0: Apenas deduplicação básica (schema cuida do resto)
                        category['items'] = deduplicate_list(category['items'])
            
            # Deduplicate engagement_models
            if 'engagement_models' in offerings and isinstance(offerings['engagement_models'], list):
                offerings['engagement_models'] = deduplicate_list(offerings['engagement_models'])
            
            # Deduplicate key_differentiators
            if 'key_differentiators' in offerings and isinstance(offerings['key_differentiators'], list):
                offerings['key_differentiators'] = deduplicate_list(offerings['key_differentiators'])
        
        # Processar reputation (cliente list é crítica)
        if 'reputation' in data and isinstance(data['reputation'], dict):
            reputation = data['reputation']
            
            # Deduplicate client_list
            if 'client_list' in reputation and isinstance(reputation['client_list'], list):
                reputation['client_list'] = deduplicate_list(reputation['client_list'])
            
            # Deduplicate certifications
            if 'certifications' in reputation and isinstance(reputation['certifications'], list):
                reputation['certifications'] = deduplicate_list(reputation['certifications'])
            
            # Deduplicate awards
            if 'awards' in reputation and isinstance(reputation['awards'], list):
                reputation['awards'] = deduplicate_list(reputation['awards'])
            
            # Deduplicate partnerships
            if 'partnerships' in reputation and isinstance(reputation['partnerships'], list):
                reputation['partnerships'] = deduplicate_list(reputation['partnerships'])
        
        # Processar team
        if 'team' in data and isinstance(data['team'], dict):
            team = data['team']
            
            # Deduplicate key_roles
            if 'key_roles' in team and isinstance(team['key_roles'], list):
                team['key_roles'] = deduplicate_list(team['key_roles'])
            
            # Deduplicate team_certifications
            if 'team_certifications' in team and isinstance(team['team_certifications'], list):
                team['team_certifications'] = deduplicate_list(team['team_certifications'])
        
        # Processar contact
        if 'contact' in data and isinstance(data['contact'], dict):
            contact = data['contact']
            
            # Deduplicate emails
            if 'emails' in contact and isinstance(contact['emails'], list):
                contact['emails'] = deduplicate_list(contact['emails'])
            
            # Deduplicate phones
            if 'phones' in contact and isinstance(contact['phones'], list):
                contact['phones'] = deduplicate_list(contact['phones'])
            
            # Deduplicate locations
            if 'locations' in contact and isinstance(contact['locations'], list):
                contact['locations'] = deduplicate_list(contact['locations'])
        
        return data
    
    def _normalize_response(self, data: dict) -> dict:
        """
        Normaliza a resposta do LLM para o formato esperado.
        
        v8.0: Aplica deduplicação robusta antes de normalizar
        v9.1: Caps já são menores no schema
        
        Args:
            data: Dados extraídos pelo LLM
        
        Returns:
            Dados normalizados
        """
        # v8.0: Deduplicação robusta (não depende de uniqueItems no schema)
        data = self._deduplicate_and_filter_lists(data)
        
        # Importar normalizador do módulo profile_builder
        try:
            from app.services.profile_builder.response_normalizer import normalize_llm_response
            return normalize_llm_response(data)
        except ImportError:
            # Fallback se normalizador não disponível
            return data
    
    async def extract_profile(
        self,
        content: str,
        ctx_label: str = "",
        request_id: str = ""
    ) -> CompanyProfile:
        """
        Método principal para extrair perfil de conteúdo.
        
        Args:
            content: Conteúdo scraped para análise
            ctx_label: Label de contexto para logs
            request_id: ID da requisição
        
        Returns:
            CompanyProfile com dados extraídos
        """
        if not content or len(content.strip()) < 100:
            logger.warning(f"{ctx_label}ProfileExtractorAgent: Conteúdo muito curto ou vazio")
            return CompanyProfile()
        
        try:
            logger.info(
                f"{ctx_label}ProfileExtractorAgent: Iniciando extração "
                f"(content_len={len(content)}, request_id={request_id})"
            )
            
            result = await self.execute(
                priority=LLMPriority.NORMAL,  # Profile usa prioridade normal
                timeout=self.DEFAULT_TIMEOUT,
                max_retries=self.DEFAULT_MAX_RETRIES,
                ctx_label=ctx_label,
                request_id=request_id,
                content=content
            )
            
            logger.info(
                f"{ctx_label}ProfileExtractorAgent: Extração concluída "
                f"(empty={result.is_empty() if result else True})"
            )
            
            return result
        except Exception as e:
            logger.error(
                f"{ctx_label}ProfileExtractorAgent: Erro na extração: {e}",
                exc_info=True
            )
            return CompanyProfile()


# Instância singleton
_profile_extractor_agent: Optional[ProfileExtractorAgent] = None


def get_profile_extractor_agent() -> ProfileExtractorAgent:
    """Retorna instância singleton do ProfileExtractorAgent."""
    global _profile_extractor_agent
    if _profile_extractor_agent is None:
        _profile_extractor_agent = ProfileExtractorAgent()
    return _profile_extractor_agent
