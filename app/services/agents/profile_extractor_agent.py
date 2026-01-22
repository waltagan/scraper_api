"""
Agente de Extração de Perfil - Extrai dados estruturados de conteúdo scraped.

Responsável por analisar conteúdo de sites e extrair informações de perfil
de empresa em formato estruturado.

v4.0: Suporte a Structured Output via SGLang/XGrammar
      - Usa json_schema do Pydantic para garantir JSON válido
      - XGrammar garante aderência ao schema durante geração
      - Fallback para json_repair se necessário
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
    
    v4.0: Otimizado para SGLang com Qwen2.5-3B-Instruct
          - Usa json_schema via XGrammar para garantir JSON válido
          - Temperature 0.0 para output determinístico
          - Schema baseado no modelo Pydantic CompanyProfile
    
    Usa prioridade NORMAL por padrão pois roda após Discovery e LinkSelector.
    """
    
    # Timeout e retries configuráveis via app/configs/llm_agents.json
    _CFG = get_config("profile/llm_agents", {}).get("profile_extractor", {})
    DEFAULT_TIMEOUT = _CFG.get("timeout", 90.0)
    DEFAULT_MAX_RETRIES = _CFG.get("max_retries", 2)
    
    # Temperature otimizada para structured output (determinístico)
    DEFAULT_TEMPERATURE: float = 0.0
    
    # =========================================================================
    # SYSTEM_PROMPT v4.0 - Versão com regras estritas e micro-shots
    # =========================================================================
    # ATUALIZAÇÃO: Prompt redesenhado com foco em autenticidade absoluta,
    # regras estritas para product_categories, priorização de clientes/prova social
    # e exemplos práticos (micro-shots). XGrammar garante JSON válido via json_schema.
    # =========================================================================
    
    SYSTEM_PROMPT = """Você é um extrator de dados B2B especializado.

Gere APENAS um JSON válido (sem markdown, sem explicações, sem texto fora do JSON).
A resposta deve começar com { e terminar com }.

Extraia diretamente, sem explicar, sem planejar em etapas internas, sem resumir o texto.

---

## Regras Fundamentais

### 1) Autenticidade absoluta
Preencha valores somente quando houver evidência explícita no texto fornecido.
Nunca invente clientes, certificações, prêmios, parcerias, produtos, números, datas ou métricas.

### 2) Campos ausentes
- Se a informação estiver no texto → extraia obrigatoriamente
- Se não estiver no texto:
  - campos string = `null`
  - listas = `[]`

Nunca use textos como "Não informado", "Não especificado", "Desconhecido".

### 3) Idioma
Valores em Português (Brasil).
Mantenha em inglês apenas termos técnicos globais e nomes próprios não traduzíveis.

### 4) Produtos vs Serviços

**Produtos:**
- itens físicos ou softwares nomeados (produto, modelo, linha, SKU, versão)

**Serviços:**
- atividades (instalação, manutenção, consultoria, projetos, desenvolvimento)

### 5) Product Categories (CRÍTICO)

- Crie categoria em `product_categories` somente se houver ≥ 1 item específico em `items`
- `items` devem ser nomes/modelos/linhas identificáveis

Proibido:
- categoria sem itens
- itens genéricos ("detector", "moldes", "sprinklers")
- áreas ("Engenharia", "Projetos") como categoria

Se não houver produtos específicos:
- `"products": []`
- `"product_categories": []`

### 6) Clientes e Prova Social (PRIORIDADE MÁXIMA)

Se existir trecho com:
"CLIENTES", "Nossos clientes", "Algumas obras executadas", "Quem confia", "Projetos realizados", "Cases"

Você DEVE:
- extrair todos os nomes listados
- preencher `reputation.client_list`
- remover locais e sufixos ("– MG", "(BH)")
- deduplicar

Normalize encoding apenas nos nomes extraídos (ex.: EmpÃ³rio → Empório).

### 7) Case Studies

Preencha `case_studies` somente quando existir:
- cliente identificado
- solução descrita
- resultado descrito

Caso contrário:
```json
"case_studies": []
```

---

## Micro-Shots Essenciais

### SHOT A — Clientes (lista explícita)

**Entrada:**
```
CLIENTES / Algumas obras executadas:
Magazine Luiza
Hermes Pardini
Instituto Cervantes
```

**Saída:**
```json
"client_list": ["Magazine Luiza", "Hermes Pardini", "Instituto Cervantes"]
```

### SHOT B — Serviço genérico NÃO vira categoria

**Entrada:**
```
Instalação de detectores de fumaça, gás e calor
```

**Saída mínima correta:**
```json
"services": ["Instalação de detectores de fumaça, gás e calor"],
"product_categories": []
```

### SHOT C — Categoria só com item específico

**Entrada:**
```
Produtos: Ionizador AquaZon X200; Sistema Acquazon Pro 3.1
```

**Saída:**
```json
"product_categories": [
  {"category_name": "Ionizadores", "items": ["Ionizador AquaZon X200"]},
  {"category_name": "Sistemas Acquazon", "items": ["Sistema Acquazon Pro 3.1"]}
]
```

---

## Ordem de Varredura (curta e eficiente)

1. **Identity + Contact**
2. **Services + Service details**
3. **Products / Categories**
4. **Reputation (client_list primeiro)**

Se uma seção não existir explicitamente no texto, não procure inferir e avance para a próxima.

---

## Schema JSON Final

Retorne EXATAMENTE este formato (sem markdown, apenas o JSON puro):

{
  "identity": {
    "company_name": "string",
    "cnpj": "string",
    "tagline": "string",
    "description": "string",
    "founding_year": "string",
    "employee_count_range": "string"
  },
  "classification": {
    "industry": "string",
    "business_model": "string",
    "target_audience": "string",
    "geographic_coverage": "string"
  },
  "team": {
    "size_range": "string",
    "key_roles": ["string"],
    "team_certifications": ["string"]
  },
  "offerings": {
    "products": ["string"],
    "product_categories": [
      {
        "category_name": "string",
        "items": ["string"]
      }
    ],
    "services": ["string"],
    "service_details": [
      {
        "name": "string",
        "description": "string",
        "methodology": "string",
        "deliverables": ["string"],
        "ideal_client_profile": "string"
      }
    ],
    "engagement_models": ["string"],
    "key_differentiators": ["string"]
  },
  "reputation": {
    "certifications": ["string"],
    "awards": ["string"],
    "partnerships": ["string"],
    "client_list": ["string"],
    "case_studies": [
      {
        "title": "string",
        "client_name": "string",
        "industry": "string",
        "challenge": "string",
        "solution": "string",
        "outcome": "string"
      }
    ]
  },
  "contact": {
    "emails": ["string"],
    "phones": ["string"],
    "linkedin_url": "string",
    "website_url": "string",
    "headquarters_address": "string",
    "locations": ["string"]
  }
}"""
    
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
        
        v4.0: Prompt otimizado para structured output
              - Direto ao ponto (XGrammar garante formato)
              - Foco na tarefa de extração
        
        Args:
            content: Conteúdo scraped para análise
        
        Returns:
            Prompt formatado
        """
        # v4.0: Com structured output, prompt pode ser mais direto
        # XGrammar garante o formato JSON, focamos na extração
        return f"""Extraia o perfil completo desta empresa:

{content}"""
    
    def _parse_response(self, response: str, **kwargs) -> CompanyProfile:
        """
        Processa resposta e cria CompanyProfile.
        
        v4.0: Com structured output via XGrammar, o JSON é garantido válido.
              O parsing é simplificado e mais robusto.
        
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
    
    def _normalize_response(self, data: dict) -> dict:
        """
        Normaliza a resposta do LLM para o formato esperado.
        
        Args:
            data: Dados extraídos pelo LLM
        
        Returns:
            Dados normalizados
        """
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
            return await self.execute(
                priority=LLMPriority.NORMAL,  # Profile usa prioridade normal
                timeout=self.DEFAULT_TIMEOUT,
                max_retries=self.DEFAULT_MAX_RETRIES,
                ctx_label=ctx_label,
                request_id=request_id,
                content=content
            )
        except Exception as e:
            logger.error(f"{ctx_label}ProfileExtractorAgent: Erro na extração: {e}")
            return CompanyProfile()


# Instância singleton
_profile_extractor_agent: Optional[ProfileExtractorAgent] = None


def get_profile_extractor_agent() -> ProfileExtractorAgent:
    """Retorna instância singleton do ProfileExtractorAgent."""
    global _profile_extractor_agent
    if _profile_extractor_agent is None:
        _profile_extractor_agent = ProfileExtractorAgent()
    return _profile_extractor_agent

