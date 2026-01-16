# Endpoint: POST /v2/encontrar_site

## Visão Geral

O endpoint `/v2/encontrar_site` é responsável por analisar os resultados de busca do Serper e identificar o site oficial de uma empresa usando LLM (Large Language Model). É o segundo passo no pipeline de descoberta.

---

## Informações Básicas

| Propriedade | Valor |
|-------------|-------|
| **URL** | `POST /v2/encontrar_site` |
| **Tag** | `v2-discovery` |
| **Autenticação** | Não requerida (endpoint interno) |
| **Content-Type** | `application/json` |

---

## Request

### Schema: `DiscoveryRequest`

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

### Schema: `DiscoveryResponse`

```json
{
  "success": true,
  "discovery_id": 456,
  "website_url": "https://www.empresa.com.br",
  "discovery_status": "found",
  "confidence_score": 0.95
}
```

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `success` | boolean | Indica se a operação foi bem-sucedida |
| `discovery_id` | int \| null | ID do registro salvo na tabela `website_discovery` |
| `website_url` | string \| null | URL do site encontrado (null se não encontrado) |
| `discovery_status` | string | Status: `found`, `not_found`, ou `error` |
| `confidence_score` | float \| null | Score de confiança (0.0 a 1.0) |

---

## Fluxo de Execução

```
┌─────────────────────────────────────────────────────────────────┐
│                POST /v2/encontrar_site                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. db_service.get_serper_results()                              │
│     - Busca resultados Serper mais recentes                      │
│     - Retorna razao_social, nome_fantasia, municipio, results    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. _filter_search_results()                                     │
│     - Remove domínios na blacklist                               │
│     - Filtra redes sociais e agregadores                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. DiscoveryAgent.find_website()                                │
│     - LLM analisa resultados de busca                            │
│     - Compara domínios com nome da empresa                       │
│     - Retorna URL ou None                                        │
│     - Phoenix Tracing para observabilidade                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. db_service.save_discovery()                                  │
│     - Salva na tabela: website_discovery                         │
│     - Campos: website_url, discovery_status, confidence_score    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. Retorna DiscoveryResponse                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Funções Chamadas (Call Stack)

### 1. `encontrar_site()` - Endpoint Principal
**Arquivo:** `app/api/v2/encontrar_site.py`

Orquestra todo o fluxo de descoberta de site.

### 2. `db_service.get_serper_results()` - Busca Resultados
**Arquivo:** `app/services/database_service.py`

Recupera os resultados Serper mais recentes para o CNPJ.

### 3. `_filter_search_results()` - Filtragem
**Arquivo:** `app/services/discovery/discovery_service.py`

Remove domínios irrelevantes:
- Redes sociais (facebook, instagram, linkedin, twitter)
- Agregadores (cnpj.biz, econodata, telelistas)
- Marketplaces (mercadolivre, shopee, olx)

### 4. `DiscoveryAgent.find_website()` - Análise LLM
**Arquivo:** `app/services/agents/discovery_agent.py`

Usa LLM para identificar o site oficial:
- Compara domínio com nome da empresa
- Analisa snippets de busca
- Retorna URL com maior probabilidade

### 5. `db_service.save_discovery()` - Persistência
**Arquivo:** `app/services/database_service.py`

Salva resultado da descoberta no banco de dados.

---

## DiscoveryAgent - Detalhes

### System Prompt

O agente usa um prompt especializado para identificação de sites oficiais:

```
Você é um especialista em encontrar sites oficiais de empresas brasileiras.

# REGRA DE OURO (OBRIGATÓRIA)
Se o DOMÍNIO contém o NOME da empresa (mesmo que junto ou abreviado), ACEITE IMEDIATAMENTE.
Remova espaços e compare: "AR ENGENHARIA" → "arengenharia" → domínio "arengenharia.eng.br" = ✅ MATCH

# PROCESSO DE DECISÃO
1. Remover diretórios e redes sociais (blacklist)
2. Para cada URL, extrair domínio e comparar com nome
3. Se múltiplos matches, escolher o primeiro (mais bem ranqueado)
```

### Formato de Resposta (JSON)

```json
{
  "site": "URL_DO_SITE ou nao_encontrado",
  "site_oficial": "sim ou nao",
  "justificativa": "Breve explicação"
}
```

---

## Configurações

### Arquivo: `app/configs/discovery/llm_agents.json`

```json
{
  "discovery": {
    "timeout": 50.0,
    "max_retries": 1
  }
}
```

### Descrição das Configurações

| Parâmetro | Valor | Descrição | Impacto ao Aumentar | Impacto ao Diminuir |
|-----------|-------|-----------|---------------------|---------------------|
| `timeout` | 50.0 | Timeout da chamada LLM (segundos) | Mais tolerância para LLMs lentos | Fail-fast, menos latência |
| `max_retries` | 1 | Retentativas após falha | Mais resiliência | Fail-fast |

### Arquivo: `app/configs/discovery/discovery.json`

```json
{
  "timeout": 70.0,
  "max_retries": 2,
  "serper_num_results": 25
}
```

| Parâmetro | Valor | Descrição | Impacto ao Aumentar | Impacto ao Diminuir |
|-----------|-------|-----------|---------------------|---------------------|
| `timeout` | 70.0 | Timeout total do discovery (segundos) | Mais tempo para análise completa | Resposta mais rápida, pode falhar |
| `max_retries` | 2 | Retentativas do fluxo completo | Mais chances de sucesso | Menos latência |
| `serper_num_results` | 25 | Resultados do Serper a analisar | Mais opções, mais contexto | Análise mais rápida |

---

## Blacklist de Domínios

O sistema filtra automaticamente os seguintes tipos de domínios:

### Redes Sociais
- facebook.com, instagram.com, linkedin.com
- twitter.com, x.com, youtube.com, tiktok.com

### Agregadores de Dados
- cnpj.biz, econodata.com.br, telelistas.net
- apontador.com.br, solutudo.com.br

### Marketplaces
- mercadolivre.com.br, shopee.com.br, olx.com.br

---

## Banco de Dados

### Tabela: `website_discovery`

```sql
CREATE TABLE website_discovery (
    id SERIAL PRIMARY KEY,
    cnpj_basico VARCHAR(8) NOT NULL UNIQUE,
    serper_id INTEGER REFERENCES serper_results(id),
    website_url TEXT,
    discovery_status VARCHAR(20) NOT NULL,
    confidence_score FLOAT,
    llm_reasoning TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## Códigos de Erro

| Código HTTP | Descrição | Causa |
|-------------|-----------|-------|
| 200 | Sucesso | Descoberta realizada (site encontrado ou não) |
| 500 | Erro interno | Falha no LLM ou no banco de dados |

---

## Status de Descoberta

| Status | Descrição |
|--------|-----------|
| `found` | Site oficial identificado com sucesso |
| `not_found` | Nenhum site oficial encontrado |
| `error` | Erro durante o processamento |

---

## Exemplos de Uso

### Request
```bash
curl -X POST "http://localhost:8000/v2/encontrar_site" \
  -H "Content-Type: application/json" \
  -d '{
    "cnpj_basico": "12345678"
  }'
```

### Response (Site Encontrado)
```json
{
  "success": true,
  "discovery_id": 789,
  "website_url": "https://www.exemplo.com.br",
  "discovery_status": "found",
  "confidence_score": 0.9
}
```

### Response (Site Não Encontrado)
```json
{
  "success": true,
  "discovery_id": 790,
  "website_url": null,
  "discovery_status": "not_found",
  "confidence_score": null
}
```

---

## Diagrama de Sequência

```
Cliente         Endpoint        Database       FilterService    DiscoveryAgent      LLM
   │                │               │               │                │              │
   │─POST ──────────▶│               │               │                │              │
   │                │               │               │                │              │
   │                │─get_serper()──▶│               │                │              │
   │                │◀──results──────│               │                │              │
   │                │               │               │                │              │
   │                │────filter()───────────────────▶│                │              │
   │                │◀──filtered────────────────────│                │              │
   │                │               │               │                │              │
   │                │───────────find_website()──────────────────────▶│              │
   │                │               │               │                │──prompt──────▶│
   │                │               │               │                │◀──response───│
   │                │◀──────────────website_url─────────────────────│              │
   │                │               │               │                │              │
   │                │─save_discovery()─▶│               │                │              │
   │                │◀──discovery_id────│               │                │              │
   │                │               │               │                │              │
   │◀──Response─────│               │               │                │              │
```

---

## Phoenix Tracing

O endpoint usa Phoenix Tracing para observabilidade:

```python
async with trace_llm_call("discovery-llm", "find_website") as span:
    if span:
        span.set_attribute("cnpj_basico", request.cnpj_basico)
        span.set_attribute("nome_fantasia", nome_fantasia)
        span.set_attribute("results_count", len(filtered_results))
        # ... executa LLM ...
        span.set_attribute("website_found", website_url is not None)
```

---

## Confidence Score

O sistema calcula um score de confiança baseado em heurísticas:

| Cenário | Score |
|---------|-------|
| Site encontrado pelo LLM | 0.9 |
| Site não encontrado | null |
| Erro durante processamento | null |

---

## Pré-requisitos

Antes de chamar este endpoint, é necessário:

1. **Dados Serper**: Executar `POST /v2/serper` para o mesmo CNPJ

---

## Próximo Passo no Pipeline

Após identificar o site oficial, o próximo endpoint a ser chamado é:

**`POST /v2/scrape`** - Faz scraping do site e extrai conteúdo estruturado.

