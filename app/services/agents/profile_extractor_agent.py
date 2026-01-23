"""
Agente de Extração de Perfil - Extrai dados estruturados de conteúdo scraped.

Responsável por analisar conteúdo de sites e extrair informações de perfil
de empresa em formato estruturado.

v8.0: Solução definitiva anti-loop com 4 camadas
v8.2: Balanceamento qualidade + anti-loop (truncamento determinístico)
v9.0: Roteamento fechado + micro-shots cirúrgicos (qualidade máxima)
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
          - Regra dura: serviços NUNCA em products
          - Schema: category_name e service_details.name obrigatórios
          - Micro-shots para fixação rápida
    
    Usa prioridade NORMAL por padrão pois roda após Discovery e LinkSelector.
    """
    
    # Timeout e retries configuráveis via app/configs/llm_agents.json
    _CFG = get_config("profile/llm_agents", {}).get("profile_extractor", {})
    DEFAULT_TIMEOUT = _CFG.get("timeout", 120.0)
    DEFAULT_MAX_RETRIES = _CFG.get("max_retries", 3)
    
    # Parâmetros otimizados para structured output (balanceado qualidade + anti-loop)
    # v8.2: Penalidades reduzidas para evitar sub-preenchimento e colapso para []
    # v9.0: Mantido (foco no prompt + schema para qualidade)
    DEFAULT_TEMPERATURE: float = 0.1         # 0.1 reduz loops (0.0 aumenta risco em catálogos)
    DEFAULT_PRESENCE_PENALTY: float = 0.15   # v8.2: Reduzido de 0.3 → 0.15 (evita sub-preenchimento)
    DEFAULT_FREQUENCY_PENALTY: float = 0.20  # v8.2: Reduzido de 0.4 → 0.20 (evita colapso para [])
    DEFAULT_SEED: int = 42                   # Reprodutibilidade
    
    # =========================================================================
    # SYSTEM_PROMPT v9.0 - Roteamento fechado + micro-shots cirúrgicos
    # =========================================================================
    # ATUALIZAÇÃO v9.0: Prompt mais curto e cirúrgico para máxima qualidade
    # - Roteamento fechado: serviços NUNCA em products (regra dura)
    # - Micro-shots específicos: services≠products, sem objeto vazio, locations≠phones, client_list só nomes
    # - Evidência mínima para campos sensíveis
    # - Mantém anti-loop e truncamento determinístico
    # - Schema v9.0: category_name e service_details.name obrigatórios (não-null)
    # =========================================================================
    
    SYSTEM_PROMPT = """Você é um extrator de dados B2B. Gere APENAS um JSON válido.
A resposta deve começar com `{` e terminar com `}`.
Proibido markdown, explicações, texto extra.

## 1) Evidência e anti-alucinação (duro)
Preencha valores SOMENTE quando houver evidência explícita no texto fornecido.
Se não houver evidência:
- strings: null
- listas: []

Proibido inventar: clientes, certificações, prêmios, parcerias, produtos, números, datas, métricas.

## 2) Idioma
Saída em Português (Brasil). Manter em inglês apenas termos técnicos globais e nomes próprios.

## 3) Roteamento fechado (evita troca de campos)
- identity.*: nome, CNPJ, slogan, descrição institucional, ano, faixa funcionários.
- contact.*: emails, telefones, site, linkedin, endereço, locations (cidades/estados/unidades).
- offerings.services: atividades/serviços (portaria, limpeza, recepção, segurança, etc.).
- offerings.service_details: detalhes reais (quando houver metodologia/entregáveis/como funciona).
- offerings.products: SOMENTE produtos nomeados (modelo/código/versão/medida/marca+modelo).
- offerings.product_categories: SOMENTE quando houver categoria nomeável + itens válidos.
- team.*: cargos/funções/equipe explicitamente descritos (ex.: "profissionais que disponibilizamos: ...").
- reputation.*: prova social da empresa (certificações, prêmios, parcerias, clientes, cases).

**REGRA CRÍTICA: serviço/atividade NUNCA pode ir em offerings.products.**

## 4) Anti-repetição (obrigatório)
Em TODAS as listas: valores estritamente únicos, manter só a primeira ocorrência.

Se detectar padrão repetitivo durante a geração, interrompa a lista e mantenha apenas os primeiros itens únicos.

## 5) Products e Product Categories (anti-loop forte)
Produto válido exige identificador claro (modelo/código/versão/medida/marca+modelo).

- Se NÃO houver produtos nomeados:
  - offerings.products = []
  - offerings.product_categories = []

Product categories:
- PROIBIDO criar categoria sem category_name válido (não pode ser null).
- PROIBIDO criar categoria sem item válido.
- Para items genéricos ("RCA", "P2", "P10", "XLR"):
  - listar cada termo no máximo 1 vez
  - NÃO combinar ("2 RCA + 2 RCA" etc.)
  - NÃO expandir variações mínimas

## 6) Clientes (prioridade alta, mas com evidência mínima)
Preencher reputation.client_list SOMENTE se houver nomes próprios explícitos em seção/trecho do tipo:
"CLIENTES", "Nossos clientes", "Quem confia", "Projetos realizados", "Cases", "Algumas obras executadas".

Depoimentos sem nomes ⇒ client_list = [].

Ignore placeholders/redações como `<NAME>`, `<EMAIL>`, "(redacted)": isso NÃO é evidência.

## 7) service_details (anti-vazio)
Se não houver detalhe real de serviços, service_details deve ser [].
PROIBIDO inserir objeto de service_details com todos os campos nulos/vazios.
Se criar objeto de service_details, name é OBRIGATÓRIO (não pode ser null).

## 8) locations (anti-erro)
contact.locations: somente cidades/estados/unidades/endereço.
PROIBIDO incluir telefone ou email em locations.

## Micro-shots (fixação rápida)

### SHOT 1 — Serviços ≠ Produtos
Entrada:
"Serviços: Portaria, Limpeza e Conservação, Recepção"
Saída:
"services": ["Portaria", "Limpeza e Conservação", "Recepção"],
"products": [],
"product_categories": []

### SHOT 2 — Sem detalhe => sem objeto vazio
Entrada:
"Serviços: Portaria e Recepção" (sem explicar como funciona)
Saída:
"service_details": []

### SHOT 3 — Locations ≠ Phones/Emails
Entrada:
"Matriz RJ: Rua X... / Tel: (21) 0000-0000"
Saída:
"phones": ["(21) 0000-0000"],
"locations": ["RJ"],
"headquarters_address": "Rua X..."

### SHOT 4 — Clientes só com nomes explícitos
Entrada:
"Depoimentos: 'Ótimo serviço...'"
Saída:
"client_list": []

Agora gere o JSON exatamente no schema fornecido pelo usuário.
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
        Constrói prompt com conteúdo para análise.
        
        v9.0: Schema incluído para guiar roteamento e constraints
        
        Args:
            content: Conteúdo scraped para análise
        
        Returns:
            Prompt formatado com schema JSON
        """
        # Incluir schema JSON completo para guiar o modelo
        schema = _get_company_profile_schema()
        
        # Formatar schema de forma legível
        import json
        schema_str = json.dumps(schema, indent=2, ensure_ascii=False)
        
        return f"""Extraia o perfil completo desta empresa:

{content}

---

Gere o JSON exatamente no seguinte schema:

{schema_str}"""
    
    def _parse_response(self, response: str, **kwargs) -> CompanyProfile:
        """
        Processa resposta e cria CompanyProfile.
        
        v8.0: Com structured output via XGrammar, o JSON é garantido válido.
              Pós-processamento robusto aplica deduplicação determinística.
        v9.0: Schema com constraints não-null reduz erros estruturais
        
        Args:
            response: Resposta JSON do LLM
        
        Returns:
            CompanyProfile com dados extraídos
        """
        try:
            content = response.strip()
            
            # Limpar markdown (caso provider não suporte structured output)
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Com structured output, JSON deve ser válido na primeira tentativa
            data = None
            
            # Tentativa 1: Parse direto (esperado funcionar com XGrammar)
            try:
                data = json.loads(content)
                logger.debug("ProfileExtractorAgent: JSON parseado com sucesso (structured output)")
            except json.JSONDecodeError as e:
                # Structured output falhou - pode ser provider sem suporte
                logger.warning(
                    f"ProfileExtractorAgent: JSON inválido apesar de structured output: {e}. "
                    f"Primeiros 200 chars: {content[:200]}"
                )
                
                # Tentativa 2: json_repair como fallback
                try:
                    data = json_repair.loads(content)
                    logger.info("ProfileExtractorAgent: JSON reparado com sucesso")
                except Exception as repair_error:
                    logger.error(f"ProfileExtractorAgent: Falha crítica no parse JSON: {repair_error}")
                    return CompanyProfile()
            
            # Normalizar estrutura
            if isinstance(data, list):
                data = data[0] if data and isinstance(data[0], dict) else {}
            if not isinstance(data, dict):
                logger.warning(f"ProfileExtractorAgent: Resposta não é dict, tipo: {type(data)}")
                data = {}
            
            # Normalizar resposta
            data = self._normalize_response(data)
            
            # Criar perfil usando validação Pydantic
            try:
                # model_validate é mais robusto que **kwargs
                return CompanyProfile.model_validate(data)
            except Exception as e:
                logger.warning(f"ProfileExtractorAgent: Validação Pydantic falhou: {e}, usando fallback")
                # Fallback: construtor direto
                try:
                    return CompanyProfile(**data)
                except Exception as fallback_error:
                    logger.error(f"ProfileExtractorAgent: Fallback também falhou: {fallback_error}")
                    return CompanyProfile()
                
        except Exception as e:
            logger.error(f"ProfileExtractorAgent: Erro ao processar resposta: {e}")
            return CompanyProfile()
    
    def _deduplicate_and_filter_lists(self, data: dict) -> dict:
        """
        Pós-processamento robusto: deduplicação + filtro anti-template.
        
        v8.0: Não depende de uniqueItems (pode ser ignorado pelo XGrammar)
        
        Args:
            data: Dados extraídos pelo LLM
        
        Returns:
            Dados com listas deduplicadas e filtradas
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
        
        def filter_template_items(items: list, max_items: int = 80) -> list:
            """
            Filtro anti-template: detecta e remove itens com mesmo molde repetido.
            
            Hard cap: máximo 80 itens por categoria (alinhado com PROMPT v8.2)
            Anti-template: se 5 itens seguidos compartilham mesmo prefixo/padrão,
            manter apenas os primeiros 5 únicos desse molde.
            """
            if not items or len(items) <= 5:
                return items[:max_items]
            
            filtered = []
            pattern_counts = {}
            
            for item in items:
                if len(filtered) >= max_items:
                    break
                
                # Extrair "molde" do item (primeiras 2-3 palavras)
                words = item.split()[:3]
                pattern = ' '.join(words) if len(words) >= 2 else item[:20]
                
                # Contar ocorrências desse padrão
                pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
                
                # Se padrão aparece > 5 vezes, parar de adicionar variações dele
                if pattern_counts[pattern] <= 5:
                    filtered.append(item)
            
            return filtered
        
        # Processar offerings (crítico)
        if 'offerings' in data and isinstance(data['offerings'], dict):
            offerings = data['offerings']
            
            # Deduplicate products
            if 'products' in offerings and isinstance(offerings['products'], list):
                offerings['products'] = deduplicate_list(offerings['products'])
            
            # Deduplicate services
            if 'services' in offerings and isinstance(offerings['services'], list):
                offerings['services'] = deduplicate_list(offerings['services'])
            
            # Deduplicate + filter product_categories[].items (CRÍTICO)
            if 'product_categories' in offerings and isinstance(offerings['product_categories'], list):
                for category in offerings['product_categories']:
                    if isinstance(category, dict) and 'items' in category:
                        # Passo 1: Deduplicate
                        category['items'] = deduplicate_list(category['items'])
                        # Passo 2: Filter anti-template (hard cap 80, alinhado com PROMPT v8.2)
                        category['items'] = filter_template_items(category['items'], max_items=80)
            
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
