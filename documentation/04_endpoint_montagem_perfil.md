# Endpoint: POST /v2/montagem_perfil

## Visão Geral

O endpoint `/v2/montagem_perfil` é responsável por processar os chunks salvos no banco de dados usando LLM para extrair informações estruturadas de perfil da empresa. É o quarto e último passo no pipeline v2.

---

## Informações Básicas

| Propriedade | Valor |
|-------------|-------|
| **URL** | `POST /v2/montagem_perfil` |
| **Tag** | `v2-profile` |
| **Autenticação** | Não requerida (endpoint interno) |
| **Content-Type** | `application/json` |

---

## Request

### Schema: `ProfileRequest`

```json
{
  "cnpj_basico": "12345678"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `cnpj_basico` | string(8) | ✅ Sim | CNPJ básico da empresa (8 primeiros dígitos) |

---

## Response

### Schema: `ProfileResponse`

```json
{
  "success": true,
  "company_id": 789,
  "profile_status": "success",
  "chunks_processed": 15,
  "processing_time_ms": 5432.1
}
```

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `success` | boolean | Indica se a operação foi bem-sucedida |
| `company_id` | int \| null | ID do registro salvo na tabela `company_profile` |
| `profile_status` | string | Status: `success`, `partial`, ou `error` |
| `chunks_processed` | int | Número de chunks processados com sucesso |
| `processing_time_ms` | float | Tempo total de processamento (ms) |

---

## Fluxo de Execução

```
┌─────────────────────────────────────────────────────────────────┐
│                POST /v2/montagem_perfil                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. db_service.get_chunks()                                      │
│     - Busca todos os chunks do CNPJ                              │
│     - Ordenados por chunk_index                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. Processamento Paralelo de Chunks                             │
│     - asyncio.gather() para paralelismo                          │
│     - ProfileExtractorAgent.extract_profile() para cada chunk    │
│     - Phoenix Tracing para cada chamada LLM                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. merge_profiles()                                             │
│     - Consolida múltiplos perfis parciais                        │
│     - Remove duplicatas                                          │
│     - Prioriza informações mais completas                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. db_service.save_profile()                                    │
│     - Salva perfil completo na tabela company_profile            │
│     - Campos normalizados + profile_json (JSONB completo)        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. Retorna ProfileResponse                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Funções Chamadas (Call Stack Detalhado)

### 1. `montar_perfil()` - Endpoint Principal
**Arquivo:** `app/api/v2/montagem_perfil.py`

Orquestra todo o fluxo de extração de perfil.

### 2. `db_service.get_chunks()` - Busca Chunks
**Arquivo:** `app/services/database_service.py`

Recupera todos os chunks do CNPJ ordenados por índice.

### 3. `ProfileExtractorAgent.extract_profile()` - Extração LLM
**Arquivo:** `app/services/agents/profile_extractor_agent.py`

Usa LLM para extrair dados estruturados de cada chunk:
- System prompt especializado
- Output em formato JSON
- Normalização de resposta

### 4. `merge_profiles()` - Consolidação
**Arquivo:** `app/services/profile_builder/profile_merger.py`

Consolida múltiplos perfis parciais:
- Score de completude para escolher base
- Merge de listas (products, services, etc.)
- Deduplicação inteligente
- Concatenação de textos complementares

### 5. `db_service.save_profile()` - Persistência
**Arquivo:** `app/services/database_service.py`

Salva perfil final no banco de dados.

---

## ProfileExtractorAgent - Detalhes

### System Prompt

O agente usa um prompt especializado para extração de dados B2B:

```
Você é um extrator de dados B2B especializado.

INSTRUÇÕES CRÍTICAS:
1. IDIOMA DE SAÍDA: PORTUGUÊS (BRASIL)
2. PRODUTOS vs SERVIÇOS: Distinga claramente
3. LISTAGEM DE PRODUTOS EXAUSTIVA: Extraia TODOS os produtos
4. PROVA SOCIAL: Extraia Case Studies, Clientes, Certificações
5. ENGAJAMENTO: Como eles vendem (Mensalidade? Projeto?)
6. CONSOLIDAÇÃO: Sem duplicatas
```

### Schema de Extração

```json
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
      { "category_name": "string", "items": ["string"] }
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
}
```

---

## Configurações

### Arquivo: `app/configs/profile/llm_agents.json`

```json
{
  "profile_extractor": {
    "timeout": 60.0,
    "max_retries": 1
  }
}
```

| Parâmetro | Valor | Descrição | Impacto ao Aumentar | Impacto ao Diminuir |
|-----------|-------|-----------|---------------------|---------------------|
| `timeout` | 60.0 | Timeout da chamada LLM (segundos) | Mais tolerância para chunks grandes | Fail-fast, menos latência |
| `max_retries` | 1 | Retentativas após falha | Mais resiliência | Fail-fast |

### Arquivo: `app/configs/profile/profile_llm.json`

```json
{
  "max_chunk_tokens": 20000,
  "system_prompt_overhead": 2500,
  "chars_per_token": 3,
  "group_target_tokens": 15000,
  "min_chunk_chars": 500,
  "retry_attempts": 1,
  "retry_min_wait": 1,
  "retry_max_wait": 10,
  "similarity_threshold": 0.3,
  "text_score_divisor": 10
}
```

| Parâmetro | Valor | Descrição | Impacto ao Aumentar | Impacto ao Diminuir |
|-----------|-------|-----------|---------------------|---------------------|
| `max_chunk_tokens` | 20000 | Limite de tokens para LLM | Processa mais conteúdo | Chunks menores, mais seguros |
| `retry_attempts` | 1 | Tentativas LLM | Mais resiliência, mais custo | Fail-fast |
| `retry_min_wait` | 1 | Espera mínima entre retries (s) | Mais espaçado | Mais agressivo |
| `retry_max_wait` | 10 | Espera máxima (s) | Mais tempo | Mais rápido |
| `similarity_threshold` | 0.3 | Corte para deduplicação | Mais rigoroso | Mais permissivo |
| `text_score_divisor` | 10 | Divisor no score de texto | Reduz peso | Aumenta peso |

---

## Merge de Perfis

### Algoritmo de Consolidação

1. **Score de Completude**: Calcula score para cada perfil
2. **Seleção de Base**: Usa perfil mais completo como base
3. **Merge de Seções Simples**: identity, classification, team, contact
4. **Merge de Offerings**: products, services, engagement_models
5. **Merge de Reputation**: certifications, awards, partnerships
6. **Deduplicação**: Remove duplicatas em listas
7. **Limpeza Final**: Remove categorias inválidas

### Exemplo de Merge

```python
# Perfil 1 (Score: 50)
{
  "identity": {"company_name": "Empresa"},
  "offerings": {"products": ["Produto A"]}
}

# Perfil 2 (Score: 80) - Base
{
  "identity": {"company_name": "Empresa LTDA", "description": "..."},
  "offerings": {"products": ["Produto B", "Produto C"]}
}

# Resultado Mergeado
{
  "identity": {"company_name": "Empresa LTDA", "description": "..."},
  "offerings": {"products": ["Produto A", "Produto B", "Produto C"]}
}
```

---

## Banco de Dados

### Tabela: `company_profile`

```sql
CREATE TABLE company_profile (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(500),
    cnpj VARCHAR(14) NOT NULL UNIQUE,
    industry VARCHAR(200),
    business_model VARCHAR(200),
    target_audience VARCHAR(500),
    geographic_coverage VARCHAR(500),
    founding_year INTEGER,
    employee_count_min INTEGER,
    employee_count_max INTEGER,
    headquarters_address TEXT,
    linkedin_url TEXT,
    website_url TEXT,
    profile_json JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## Status de Processamento

| Status | Descrição | Condição |
|--------|-----------|----------|
| `success` | Todos os chunks processados | chunks_processed == total_chunks |
| `partial` | Alguns chunks processados | 0 < chunks_processed < total_chunks |
| `error` | Nenhum chunk processado | chunks_processed == 0 |

---

## Códigos de Erro

| Código HTTP | Descrição | Causa |
|-------------|-----------|-------|
| 200 | Sucesso | Perfil extraído e salvo com sucesso |
| 500 | Erro interno | Falha no LLM ou no banco de dados |

---

## Exemplos de Uso

### Request
```bash
curl -X POST "http://localhost:8000/v2/montagem_perfil" \
  -H "Content-Type: application/json" \
  -d '{
    "cnpj_basico": "12345678"
  }'
```

### Response (Sucesso Total)
```json
{
  "success": true,
  "company_id": 456,
  "profile_status": "success",
  "chunks_processed": 15,
  "processing_time_ms": 8500.5
}
```

### Response (Sucesso Parcial)
```json
{
  "success": true,
  "company_id": 457,
  "profile_status": "partial",
  "chunks_processed": 10,
  "processing_time_ms": 6200.3
}
```

### Response (Sem Chunks)
```json
{
  "success": false,
  "company_id": null,
  "profile_status": "error",
  "chunks_processed": 0,
  "processing_time_ms": 150.0
}
```

---

## Diagrama de Sequência

```
Cliente        Endpoint        Database       ProfileExtractor     Merger         LLM
   │               │               │               │                 │             │
   │─POST ─────────▶│               │               │                 │             │
   │               │               │               │                 │             │
   │               │─get_chunks()──▶│               │                 │             │
   │               │◀──chunks───────│               │                 │             │
   │               │               │               │                 │             │
   │               │   ┌───────────────────────────────────────────────────────────┐
   │               │   │  Para cada chunk (em paralelo):                           │
   │               │   │                                                           │
   │               │   │  │─extract_profile()─▶│                 │             │  │
   │               │   │  │               │    │─────prompt──────────────────▶│  │
   │               │   │  │               │    │◀────json─────────────────────│  │
   │               │   │  │◀──profile─────│    │                 │             │  │
   │               │   └───────────────────────────────────────────────────────────┘
   │               │               │               │                 │             │
   │               │────────────merge_profiles()────────────────────▶│             │
   │               │◀───────────────merged_profile──────────────────│             │
   │               │               │               │                 │             │
   │               │─save_profile()─▶│               │                 │             │
   │               │◀──company_id────│               │                 │             │
   │               │               │               │                 │             │
   │◀──Response────│               │               │                 │             │
```

---

## Phoenix Tracing

O endpoint usa Phoenix Tracing para cada chamada LLM:

```python
async with trace_llm_call("profile-llm", f"extract_profile_chunk_{chunk_idx}") as span:
    if span:
        span.set_attribute("cnpj_basico", request.cnpj_basico)
        span.set_attribute("chunk_index", chunk_idx)
        span.set_attribute("chunk_tokens", chunk_data.get('token_count', 0))
    
    profile = await profile_extractor.extract_profile(...)
    
    if span:
        span.set_attribute("profile_empty", profile.is_empty())
```

---

## Processamento Paralelo

Os chunks são processados em paralelo usando `asyncio.gather`:

```python
profile_tasks = [
    extract_chunk(chunk_data, idx) 
    for idx, chunk_data in enumerate(chunks_data)
]
profiles_results = await asyncio.gather(*profile_tasks, return_exceptions=True)
```

### Benefícios
- Reduz tempo total de processamento
- Aproveita capacidade do LLM
- Erros em um chunk não afetam outros

### Considerações
- Carga no LLM aumenta com número de chunks
- Rate limiting do LLM pode ser atingido
- Memory footprint maior

---

## Limpeza de Dados

### Categorias Inválidas Removidas
- "outras categorias", "outras"
- "marcas", "marca", "geral"
- "diversos", "outros"
- "categorias", "categoria"
- "produtos", "produto"

### Validação de Campos
- Strings vazias são removidas de listas
- Dicts sem campos obrigatórios são filtrados
- URLs são validadas

---

## Pré-requisitos

Antes de chamar este endpoint, é necessário:

1. **Busca Serper**: Executar `POST /v2/serper`
2. **Descoberta de Site**: Executar `POST /v2/encontrar_site`
3. **Scraping**: Executar `POST /v2/scrape`

---

## Resultado Final

O perfil completo é salvo em dois formatos:

1. **Campos Normalizados**: Para queries SQL rápidas
2. **profile_json (JSONB)**: Perfil completo em formato JSON

### Exemplo de Perfil Completo

```json
{
  "identity": {
    "company_name": "Empresa Exemplo LTDA",
    "cnpj": "12.345.678/0001-00",
    "tagline": "Inovação em Tecnologia",
    "description": "Empresa líder em soluções B2B...",
    "founding_year": "2010",
    "employee_count_range": "50-200"
  },
  "classification": {
    "industry": "Tecnologia da Informação",
    "business_model": "SaaS",
    "target_audience": "Empresas de médio e grande porte",
    "geographic_coverage": "Brasil"
  },
  "offerings": {
    "products": ["Produto A", "Produto B"],
    "services": ["Consultoria", "Implementação"],
    "product_categories": [
      {"category_name": "Software", "items": ["ERP", "CRM"]}
    ]
  },
  "reputation": {
    "certifications": ["ISO 9001", "SOC 2"],
    "client_list": ["Cliente 1", "Cliente 2"],
    "case_studies": [...]
  },
  "contact": {
    "emails": ["contato@empresa.com"],
    "phones": ["(11) 1234-5678"],
    "website_url": "https://www.empresa.com.br"
  }
}
```

