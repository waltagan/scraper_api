# Endpoint: POST /v2/serper

## Visão Geral

O endpoint `/v2/serper` é responsável por realizar buscas no Google via API Serper para encontrar informações sobre uma empresa. É o primeiro passo no pipeline de descoberta de sites oficiais.

---

## Informações Básicas

| Propriedade | Valor |
|-------------|-------|
| **URL** | `POST /v2/serper` |
| **Tag** | `v2-serper` |
| **Autenticação** | Não requerida (endpoint interno) |
| **Content-Type** | `application/json` |

---

## Request

### Schema: `SerperRequest`

```json
{
  "cnpj_basico": "12345678",
  "razao_social": "Empresa Exemplo LTDA",
  "nome_fantasia": "Exemplo",
  "municipio": "São Paulo"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `cnpj_basico` | string(8) | ✅ Sim | CNPJ básico da empresa (8 primeiros dígitos) |
| `razao_social` | string | ❌ Não | Razão social da empresa |
| `nome_fantasia` | string | ❌ Não | Nome fantasia da empresa |
| `municipio` | string | ❌ Não | Município da empresa |

---

## Response

### Schema: `SerperResponse`

```json
{
  "success": true,
  "serper_id": 123,
  "results_count": 10,
  "query_used": "Exemplo São Paulo site oficial"
}
```

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `success` | boolean | Indica se a operação foi bem-sucedida |
| `serper_id` | int \| null | ID do registro salvo na tabela `serper_results` |
| `results_count` | int | Número de resultados retornados pela busca |
| `query_used` | string | Query efetivamente utilizada na busca |

---

## Fluxo de Execução

```
┌─────────────────────────────────────────────────────────────────┐
│                    POST /v2/serper                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. _build_search_query()                                        │
│     - Prioridade 1: Nome Fantasia + Município + "site oficial"   │
│     - Prioridade 2: Razão Social limpa + Município               │
│     - Limpa sufixos: LTDA, S.A., EIRELI, ME, EPP, S/A            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. serper_manager.search()                                      │
│     - Rate limiting: TokenBucketRateLimiter                      │
│     - Connection pooling: HTTP/2 com max_concurrent conexões     │
│     - Retry automático com backoff exponencial                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. db_service.save_serper_results()                             │
│     - Salva na tabela: serper_results                            │
│     - Campos: cnpj_basico, results_json (JSONB), query_used      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. Retorna SerperResponse                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Funções Chamadas (Call Stack)

### 1. `buscar_serper()` - Endpoint Principal
**Arquivo:** `app/api/v2/serper.py`

Orquestra todo o fluxo de busca.

### 2. `_build_search_query()` - Construção da Query
**Arquivo:** `app/api/v2/serper.py`

Constrói a query de busca otimizada:
- Remove sufixos corporativos (LTDA, S.A., etc.)
- Prioriza Nome Fantasia sobre Razão Social
- Adiciona município para contexto geográfico
- Sufixo "site oficial" para melhorar relevância

### 3. `serper_manager.search()` - Execução da Busca
**Arquivo:** `app/services/discovery_manager/serper_manager.py`

Gerencia a comunicação com a API Serper:
- Controle de rate limiting
- Connection pooling
- Retry com backoff exponencial
- Tratamento de erros (429, 5xx)

### 4. `db_service.save_serper_results()` - Persistência
**Arquivo:** `app/services/database_service.py`

Salva resultados no banco de dados PostgreSQL.

---

## Configurações

### Arquivo: `app/configs/discovery/serper.json`

```json
{
  "rate_per_second": 190.0,
  "max_burst": 170,
  "max_concurrent": 400,
  "request_timeout": 5.0,
  "connect_timeout": 3.0,
  "max_retries": 1,
  "retry_base_delay": 0.3,
  "retry_max_delay": 1.0,
  "rate_limiter_timeout": 10.0,
  "rate_limiter_retry_timeout": 5.0,
  "connection_semaphore_timeout": 10.0
}
```

### Descrição das Configurações

| Parâmetro | Valor | Descrição | Impacto ao Aumentar | Impacto ao Diminuir |
|-----------|-------|-----------|---------------------|---------------------|
| `rate_per_second` | 190.0 | Taxa máxima de requisições/segundo | Mais requisições, risco de 429 | Menos throughput, mais seguro |
| `max_burst` | 170 | Máximo de requisições em burst | Picos maiores permitidos | Fluxo mais nivelado |
| `max_concurrent` | 400 | Conexões HTTP simultâneas | Mais paralelismo | Menos carga no sistema |
| `request_timeout` | 5.0 | Timeout de leitura (segundos) | Espera mais por resposta | Fail-fast, libera recursos |
| `connect_timeout` | 3.0 | Timeout de conexão (segundos) | Mais tolerância a rede lenta | Detecta problemas mais rápido |
| `max_retries` | 1 | Tentativas após falha | Mais resiliência, mais latência | Fail-fast |
| `retry_base_delay` | 0.3 | Delay base para retry (segundos) | Mais tempo entre retries | Retries mais rápidos |
| `retry_max_delay` | 1.0 | Delay máximo para retry (segundos) | Backoff mais longo | Retries mais agressivos |
| `rate_limiter_timeout` | 10.0 | Timeout para adquirir rate limit | Mais tolerância em filas | Fail-fast em congestionamento |
| `connection_semaphore_timeout` | 10.0 | Timeout para slot de conexão | Mais espera por conexão | Falha rápida sem slots |

---

## Variáveis de Ambiente

| Variável | Descrição | Obrigatória |
|----------|-----------|-------------|
| `SERPER_API_KEY` | Chave de API do Serper | ✅ Sim |

---

## Banco de Dados

### Tabela: `serper_results`

```sql
CREATE TABLE serper_results (
    id SERIAL PRIMARY KEY,
    cnpj_basico VARCHAR(8) NOT NULL,
    company_name VARCHAR(500),
    razao_social VARCHAR(500),
    nome_fantasia VARCHAR(500),
    municipio VARCHAR(200),
    results_json JSONB NOT NULL,
    results_count INTEGER NOT NULL,
    query_used TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Códigos de Erro

| Código HTTP | Descrição | Causa |
|-------------|-----------|-------|
| 200 | Sucesso | Busca realizada com sucesso |
| 500 | Erro interno | Falha na API Serper ou no banco de dados |

---

## Exemplos de Uso

### Request
```bash
curl -X POST "http://localhost:8000/v2/serper" \
  -H "Content-Type: application/json" \
  -d '{
    "cnpj_basico": "12345678",
    "razao_social": "Empresa Exemplo LTDA",
    "nome_fantasia": "Exemplo",
    "municipio": "São Paulo"
  }'
```

### Response (Sucesso)
```json
{
  "success": true,
  "serper_id": 456,
  "results_count": 10,
  "query_used": "Exemplo São Paulo site oficial"
}
```

### Response (Sem Resultados)
```json
{
  "success": true,
  "serper_id": 457,
  "results_count": 0,
  "query_used": "Empresa Desconhecida site oficial"
}
```

---

## Métricas e Monitoramento

O `SerperManager` expõe métricas via `get_status()`:

```python
{
    "total_requests": 1000,
    "successful_requests": 985,
    "failed_requests": 15,
    "rate_limited_requests": 5,
    "success_rate": "98.5%",
    "avg_latency_ms": 250.5,
    "rate_limiter": { ... },
    "semaphore": {
        "max": 400,
        "available": 350,
        "used": 50,
        "utilization": 12.5
    },
    "config": { ... }
}
```

---

## Diagrama de Sequência

```
Cliente          Endpoint         SerperManager      API Serper       Database
   │                 │                  │                │               │
   │─POST /v2/serper─▶│                  │                │               │
   │                 │                  │                │               │
   │                 │─build_query()───▶│                │               │
   │                 │◀────query────────│                │               │
   │                 │                  │                │               │
   │                 │──────search()────▶│                │               │
   │                 │                  │─rate_limit()──▶│               │
   │                 │                  │◀──token────────│               │
   │                 │                  │                │               │
   │                 │                  │───POST /search─▶│               │
   │                 │                  │◀──results──────│               │
   │                 │◀────results──────│                │               │
   │                 │                  │                │               │
   │                 │────save_results()──────────────────────────────────▶│
   │                 │◀───────────────────────────────────serper_id───────│
   │                 │                  │                │               │
   │◀──Response──────│                  │                │               │
   │                 │                  │                │               │
```

---

## Considerações de Performance

1. **Rate Limiting**: A API Serper tem limite de 200 req/s. O sistema usa 190 req/s como margem de segurança.

2. **Connection Pooling**: HTTP/2 com até 400 conexões simultâneas para maximizar throughput.

3. **Caching**: Resultados são salvos no banco para evitar buscas duplicadas.

4. **Timeout Agressivo**: 5s de timeout garante fail-fast e libera recursos.

---

## Próximo Passo no Pipeline

Após salvar os resultados Serper, o próximo endpoint a ser chamado é:

**`POST /v2/encontrar_site`** - Usa LLM para analisar os resultados e identificar o site oficial.

