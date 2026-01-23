"""
Agente de Extração de Perfil - Extrai dados estruturados de conteúdo scraped.

Responsável por analisar conteúdo de sites e extrair informações de perfil
de empresa em formato estruturado.

v8.0: Solução definitiva anti-loop com 4 camadas
      - PROMPT v8.0: Hard caps específicos + procedimento operacional
      - Loop detector: 3 heurísticas em tempo real
      - Retry seletivo: parâmetros ajustados
      - Pós-processamento robusto: deduplicação garantida
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
          - PROMPT com caps numéricos específicos (products=120, items=80)
          - Loop detector + retry seletivo + max_tokens adaptativo
          - Pós-processamento robusto com anti-template
    
    Usa prioridade NORMAL por padrão pois roda após Discovery e LinkSelector.
    """
    
    # Timeout e retries configuráveis via app/configs/llm_agents.json
    _CFG = get_config("profile/llm_agents", {}).get("profile_extractor", {})
    DEFAULT_TIMEOUT = _CFG.get("timeout", 120.0)
    DEFAULT_MAX_RETRIES = _CFG.get("max_retries", 3)
    
    # Parâmetros otimizados para structured output (anti-loop forte)
    # v8.0: temperature=0.1 reduz loops em "modo lista" (temperatura=0 aumenta risco)
    # Valores baseados em consenso da comunidade SGLang
    DEFAULT_TEMPERATURE: float = 0.1         # 0.1 reduz loops (0.0 aumenta risco em catálogos)
    DEFAULT_PRESENCE_PENALTY: float = 0.3    # Baseline anti-loop (SGLang OpenAI-compatible)
    DEFAULT_FREQUENCY_PENALTY: float = 0.4   # Baseline anti-repetição
    DEFAULT_SEED: int = 42                   # Reprodutibilidade
    
    # =========================================================================
    # SYSTEM_PROMPT v8.0 FINAL - Hard caps específicos + procedimento operacional
    # =========================================================================
    # ATUALIZAÇÃO v8.0 FINAL: Prompt com caps numéricos específicos por campo
    # - Hard caps: products=120, services=60, client_list=120, items/cat=80
    # - Anti-enumeração degenerada: procedimento operacional obrigatório
    # - Regras binárias para roteamento correto (ISO→reputation, NR-10→team)
    # - Não depende de uniqueItems/maxItems (ignorados pelo XGrammar do SGLang)
    # - Loop detector + retry seletivo + max_tokens adaptativo implementados
    # =========================================================================
    
    SYSTEM_PROMPT = """Você é um **extrator de dados B2B especializado**.
Gere **APENAS** um **JSON válido** (sem markdown, sem explicações, sem texto fora do JSON).
A resposta deve **começar com `{`** e **terminar com `}`**.

Extraia diretamente do texto fornecido (Markdown/PDF), sem explicar e sem inferir.

---

## 1) Autenticidade absoluta (anti-alucinação)

Preencha valores **somente** quando houver **evidência explícita** no texto.
**Proibido inventar**: clientes, certificações, prêmios, parcerias, produtos, números, datas, métricas.

---

## 2) Campos ausentes (sem placeholders)

- Se a informação estiver no texto → **extraia obrigatoriamente**
- Se não estiver no texto →
  - strings = `null`
  - listas = `[]`

**Proibido**: "Não informado", "Desconhecido", "N/A", etc.

---

## 3) Idioma

Valores em **Português (Brasil)**.
Mantenha em inglês apenas termos técnicos globais (SaaS, Machine Learning) e nomes próprios não traduzíveis.

---

## 4) Roteamento correto (evita troca de campos)

- **identity.***: nome legal, CNPJ, slogan, descrição institucional, ano de fundação, faixa de funcionários.
- **classification.***: indústria, modelo de negócio, público-alvo, cobertura geográfica.
- **team.***: apenas pessoas/equipe/cargos/certificações **da equipe** (ex.: CREA do time, NR-10 do time).
- **reputation.***: prova social **da empresa** (certificações, prêmios, parcerias, clientes, cases).
- **offerings.***: oferta (produtos/serviços/diferenciais/modelos de contratação).
- **contact.***: emails/telefones/site/LinkedIn/endereço/locais.

Regra de desempate:
**prova social → reputation**; **pessoas/equipe → team**; **oferta → offerings**; **institucional → identity**.

---

## 5) CONTROLE ANTI-REPETIÇÃO (OBRIGATÓRIO)

### 5.1 Deduplicação obrigatória (todas as listas)

Em **todas** as listas (`products`, `services`, `client_list`, `product_categories[].items`, etc.):

- cada valor deve aparecer **no máximo 1 vez**
- se repetir no texto, **liste apenas a primeira ocorrência**
- normalize espaços duplicados antes de comparar (ex.: dois espaços → um)

### 5.2 Anti-enumeração degenerada (CAPS RÍGIDOS)

Para reduzir loops e listas explosivas:

- `offerings.products`: **máx 120 itens**
- `offerings.services`: **máx 60 itens**
- `reputation.client_list`: **máx 120 itens**
- `offerings.product_categories`: **máx 40 categorias**
- `product_categories[].items`: **máx 80 itens por categoria**
- `service_details`: **máx 15 itens**

Se houver mais itens no texto, selecione os **primeiros** (em ordem de aparição) e **pare**.

### 5.3 Critério de item (ANTI-COMBINAÇÃO / ANTI-LOOP)

Para `product_categories[].items`:

**Regra principal (preferencial):** item deve ser **produto específico identificável**, com pelo menos um:

- modelo / código / versão / medida / marca+modelo / nome completo de produto

**Regra especial (permitida apenas quando o texto listar explicitamente tipos/conectores):**
Se o texto listar termos como `RCA`, `P2`, `P10`, `XLR`, `Speakon`, etc.:

- liste **cada termo uma única vez**
- **não crie combinações**
- **não expanda variações**

**Proibido (sempre):**

- gerar combinações automáticas (ex.: "2 RCA + 2 RCA", "RCA + P2", etc.)
- listar dezenas de variações mínimas (ex.: "2 RCA + 2 RCA", "2 RCA + 2 RCA coaxial", "2 RCA + 2 RCA com terra"…)
- repetir um mesmo padrão com pequenas mudanças

**Procedimento operacional obrigatório:**
Se você perceber que está gerando itens com o mesmo padrão repetido, **interrompa imediatamente a listagem**, mantenha **somente os primeiros itens únicos** já listados e siga para o próximo campo.

---

## 6) Produtos vs Serviços

**Produtos** = itens físicos/softwares **nomeados** (com identificador).
**Serviços** = atividades/processos (instalação, manutenção, consultoria, projetos, desenvolvimento).

Se NÃO houver produtos nomeados no texto:

```json
"products": [],
"product_categories": []
```

---

## 7) Product Categories (CRÍTICO)

Só crie uma categoria em `product_categories` se conseguir listar **≥ 1 item válido** em `items`.

Proibido:

- categoria sem itens
- categorias que são áreas/segmentos/serviços ("Engenharia", "Projetos", "Automotivo") sem produtos nomeados

---

## 8) Clientes e Prova Social (PRIORIDADE MÁXIMA)

Se existir trecho com gatilhos como:
"CLIENTES", "Nossos clientes", "Quem confia", "Projetos realizados", "Cases", "Algumas obras executadas"

Você **DEVE**:

- extrair todos os nomes listados
- preencher `reputation.client_list`
- remover sufixos de local ("- MG", "(BH)") quando forem claramente só localização
- deduplicar
- normalizar mojibake no nome final (ex.: EmpÃ³rio → Empório)

---

## 9) Case Studies

Preencha `case_studies` **somente** quando houver no texto:

- cliente identificado
- desafio/problema
- solução
- resultado

Caso contrário:

```json
"case_studies": []
```

---

## Micro-shots (curtos e operacionais)

### SHOT A — Clientes (lista explícita)

Entrada:

```
CLIENTES:
Magazine Luiza
Hermes Pardini
Instituto Cervantes
```

Saída:

```json
"client_list": ["Magazine Luiza", "Hermes Pardini", "Instituto Cervantes"]
```

### SHOT B — Conectores NÃO viram combinações

Entrada:

```
Conectores: RCA, P2, P10, XLR
```

Saída:

```json
"items": ["RCA", "P2", "P10", "XLR"]
```

### SHOT C — Serviço genérico NÃO vira categoria

Entrada:

```
Instalação de detectores de fumaça, gás e calor
```

Saída:

```json
"services": ["Instalação de detectores de fumaça, gás e calor"],
"product_categories": []
```

---

## Ordem de varredura (rápida)

1. identity + contact
2. services + service_details
3. products + product_categories
4. reputation (client_list primeiro)

Se uma seção não existir explicitamente, **não infira** e avance.
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
        
        v8.0: Prompt com schema JSON completo incluído
              - Guia explícito do formato esperado
              - Schema com todas as restrições (maxItems, uniqueItems como hints)
        
        Args:
            content: Conteúdo scraped para análise
        
        Returns:
            Prompt formatado com schema JSON
        """
        # v8.0: Incluir schema JSON completo para guiar o modelo
        # Obtém o schema do Pydantic para garantir consistência
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
            
            Hard cap: máximo 80 itens por categoria (alinhado com PROMPT v8.0)
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
                        # Passo 2: Filter anti-template (hard cap 80, alinhado com PROMPT v8.0)
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
