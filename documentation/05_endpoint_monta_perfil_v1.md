# Endpoint: POST /monta_perfil (v1 - Fluxo Completo)

## Visão Geral

O endpoint `/monta_perfil` é o endpoint principal e completo que executa todo o pipeline de extração de perfil em uma única chamada. Diferente dos endpoints v2 que são modulares, este endpoint orquestra automaticamente todas as etapas: discovery, scraping e análise.

---

## Informações Básicas

| Propriedade | Valor |
|-------------|-------|
| **URL** | `POST /monta_perfil` |
| **Autenticação** | ✅ API Key (header `X-API-Key`) |
| **Content-Type** | `application/json` |
| **Timeout** | 300 segundos |

---

## Request

### Schema: `CompanyRequest`

```json
{
  "url": "https://www.empresa.com.br",
  "razao_social": "Empresa Exemplo LTDA",
  "nome_fantasia": "Exemplo",
  "cnpj": "12345678000100",
  "email": "contato@empresa.com",
  "municipio": "São Paulo",
  "cnaes": ["6201-5/00", "6202-3/00"]
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `url` | HttpUrl | ❌ Não* | URL direta do site (pula discovery) |
| `razao_social` | string | ❌ Não* | Razão social da empresa |
| `nome_fantasia` | string | ❌ Não* | Nome fantasia da empresa |
| `cnpj` | string | ❌ Não* | CNPJ completo da empresa |
| `email` | string | ❌ Não | E-mail da empresa (ajuda no discovery) |
| `municipio` | string | ❌ Não | Município da empresa |
| `cnaes` | List[string] | ❌ Não | Lista de CNAEs (atividades) |

> **\*** Deve fornecer `url` OU dados da empresa (`razao_social`, `nome_fantasia`, `cnpj`).

---

## Response

### Schema: `CompanyProfile`

O response é o perfil completo da empresa no formato estruturado.

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
  "team": {
    "size_range": "51-200",
    "key_roles": ["CEO", "CTO", "Gerente de Vendas"],
    "team_certifications": ["PMP", "AWS Certified"]
  },
  "offerings": {
    "products": ["ERP Cloud", "CRM Integrado"],
    "product_categories": [
      {
        "category_name": "Software de Gestão",
        "items": ["ERP Cloud", "CRM", "BI Dashboard"]
      }
    ],
    "services": ["Consultoria", "Implementação", "Suporte"],
    "service_details": [
      {
        "name": "Consultoria em TI",
        "description": "Análise e planejamento de soluções",
        "methodology": "Metodologia ágil",
        "deliverables": ["Relatório técnico", "Roadmap"],
        "ideal_client_profile": "Empresas em transformação digital"
      }
    ],
    "engagement_models": ["Projeto", "Mensalidade", "Consultoria por hora"],
    "key_differentiators": ["Suporte 24/7", "Integração nativa"]
  },
  "reputation": {
    "certifications": ["ISO 9001", "SOC 2 Type II"],
    "awards": ["Prêmio Inovação 2023"],
    "partnerships": ["Microsoft Gold Partner", "AWS Partner"],
    "client_list": ["Empresa A", "Empresa B", "Empresa C"],
    "case_studies": [
      {
        "title": "Transformação Digital na Empresa X",
        "client_name": "Empresa X",
        "industry": "Varejo",
        "challenge": "Sistemas legados desintegrados",
        "solution": "Implementação de ERP Cloud",
        "outcome": "Redução de 40% em custos operacionais"
      }
    ]
  },
  "contact": {
    "emails": ["contato@empresa.com", "vendas@empresa.com"],
    "phones": ["(11) 1234-5678", "(11) 9876-5432"],
    "linkedin_url": "https://linkedin.com/company/exemplo",
    "website_url": "https://www.empresa.com.br",
    "headquarters_address": "Av. Paulista, 1000, São Paulo - SP",
    "locations": ["São Paulo", "Rio de Janeiro", "Brasília"]
  },
  "sources": [
    "https://www.empresa.com.br",
    "https://www.empresa.com.br/sobre",
    "https://www.empresa.com.br/produtos"
  ]
}
```

---

## Fluxo de Execução Completo

```
┌─────────────────────────────────────────────────────────────────┐
│                    POST /monta_perfil                            │
│                    (Timeout: 300s)                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  FASE 1: DISCOVERY (se URL não fornecida)                        │
│  Timeout: 70s                                                    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  1. find_company_website()                               │    │
│  │     a. Busca no Google via Serper API                    │    │
│  │     b. Filtra resultados (blacklist)                     │    │
│  │     c. LLM analisa e identifica site oficial             │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  FASE 2: SCRAPING                                                │
│  Timeout: restante do total (300s - discovery)                   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  2. scrape_url()                                         │    │
│  │     a. Probe URL (encontrar variação ideal)              │    │
│  │     b. Analisar site (detectar proteção)                 │    │
│  │     c. Selecionar estratégia de scraping                 │    │
│  │     d. Scrape main page com fallback                     │    │
│  │     e. Selecionar links relevantes com LLM               │    │
│  │     f. Scrape subpages em paralelo                       │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  FASE 3: ANÁLISE LLM                                             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  3. analyze_content()                                    │    │
│  │     a. Chunking do conteúdo agregado                     │    │
│  │     b. Processamento paralelo de chunks com LLM          │    │
│  │     c. Merge de perfis parciais                          │    │
│  │     d. Normalização e limpeza                            │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  RESULTADO: CompanyProfile                                       │
│  - Adiciona sources (URLs visitadas)                             │
│  - Adiciona metadata de discovery se aplicável                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Funções Chamadas (Call Stack Detalhado)

### 1. `monta_perfil()` - Endpoint Principal
**Arquivo:** `app/main.py`

Orquestra todo o pipeline com:
- Timeout global de 300s
- Geração de request_id para rastreamento
- Logging estruturado

### 2. `find_company_website()` - Discovery
**Arquivo:** `app/services/discovery/discovery_service.py`

Localiza o site oficial quando URL não é fornecida:
- Busca no Google via Serper API
- Filtragem de resultados (blacklist)
- Análise LLM para identificação

### 3. `process_analysis()` - Orquestração Principal
**Arquivo:** `app/main.py`

Coordena scraping e análise:
```python
async def process_analysis(url: str, ctx_label: str, request_id: str):
    # 1. Scrape
    markdown, _, scraped_urls = await scrape_url(url, max_subpages=50, ...)
    
    # 2. Prepare content
    combined_text = f"--- WEB CRAWL START ({url}) ---\n{markdown}\n..."
    
    # 3. LLM Analysis
    profile = await analyze_content(combined_text, ...)
    
    # 4. Add sources
    profile.sources = list(set(scraped_urls))
    
    return profile
```

### 4. `scrape_url()` - Scraping Completo
**Arquivo:** `app/services/scraper/scraper_service.py`

Pipeline de scraping adaptativo:
- Probe URL
- Análise do site
- Seleção de estratégia
- Scrape main + subpages
- Consolidação

### 5. `analyze_content()` - Análise LLM
**Arquivo:** `app/services/profile_builder/__init__.py`

Extração de dados estruturados:
- Chunking inteligente
- Chamadas LLM paralelas
- Merge de perfis
- Normalização

---

## Configurações

### Timeouts

| Fase | Timeout | Descrição |
|------|---------|-----------|
| Discovery | 70s | Timeout para busca e identificação de site |
| Total | 300s | Timeout global do endpoint |

### Configuração do Discovery (`app/configs/discovery/discovery.json`)

```json
{
  "timeout": 70.0,
  "max_retries": 2,
  "serper_num_results": 25
}
```

### Configuração do Scraper (`app/configs/scraper/scraper_domain.json`)

```json
{
  "requests_per_minute": 100,
  "burst_size": 50,
  "slow_domain_rpm": 10
}
```

### Configuração do Chunking (`app/configs/chunking/chunking.json`)

```json
{
  "max_chunk_tokens": 20000,
  "group_target_tokens": 12000,
  "safety_margin": 0.85
}
```

### Configuração do Profile LLM (`app/configs/profile/profile_llm.json`)

```json
{
  "max_chunk_tokens": 20000,
  "retry_attempts": 1,
  "similarity_threshold": 0.3
}
```

---

## Autenticação

O endpoint requer API Key no header:

```bash
curl -X POST "http://localhost:8000/monta_perfil" \
  -H "X-API-Key: sua-api-key-aqui" \
  -H "Content-Type: application/json" \
  -d '...'
```

### Variável de Ambiente

```
API_KEY=sua-api-key-secreta
```

---

## Códigos de Erro

| Código HTTP | Descrição | Causa |
|-------------|-----------|-------|
| 200 | Sucesso | Perfil extraído com sucesso |
| 400 | Bad Request | Dados insuficientes no request |
| 401 | Unauthorized | API Key inválida ou ausente |
| 404 | Not Found | Site oficial não encontrado |
| 504 | Gateway Timeout | Timeout na análise (>300s) ou discovery (>70s) |
| 500 | Internal Error | Erro no scraping, LLM ou banco de dados |

---

## Exemplos de Uso

### Exemplo 1: Com URL Direta

```bash
curl -X POST "http://localhost:8000/monta_perfil" \
  -H "X-API-Key: sua-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.empresa.com.br"
  }'
```

### Exemplo 2: Com Dados da Empresa (Discovery Automático)

```bash
curl -X POST "http://localhost:8000/monta_perfil" \
  -H "X-API-Key: sua-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "razao_social": "Empresa Exemplo LTDA",
    "nome_fantasia": "Exemplo",
    "cnpj": "12345678000100",
    "municipio": "São Paulo"
  }'
```

### Exemplo 3: Completo com Todos os Campos

```bash
curl -X POST "http://localhost:8000/monta_perfil" \
  -H "X-API-Key: sua-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "razao_social": "Empresa Exemplo LTDA",
    "nome_fantasia": "Exemplo",
    "cnpj": "12345678000100",
    "email": "contato@empresa.com",
    "municipio": "São Paulo",
    "cnaes": ["6201-5/00", "6202-3/00"]
  }'
```

---

## Diagrama de Sequência Completo

```
Cliente        Endpoint        Discovery        Scraper         LLM
   │               │               │               │              │
   │─POST ─────────▶│               │               │              │
   │               │               │               │              │
   │               │  [Se URL não fornecida]       │              │
   │               │───find_website()─▶│               │              │
   │               │               │─Serper()──────▶│              │
   │               │               │◀──results──────│              │
   │               │               │──LLM()────────────────────────▶│
   │               │               │◀──site_url────────────────────│
   │               │◀──url─────────│               │              │
   │               │               │               │              │
   │               │  [Scraping]                   │              │
   │               │────scrape_url()───────────────▶│              │
   │               │               │               │─probe()──────▶
   │               │               │               │◀─best_url─────
   │               │               │               │─analyze()────▶
   │               │               │               │◀─profile──────
   │               │               │               │─scrape()─────▶
   │               │               │               │◀─pages────────
   │               │◀──content─────────────────────│              │
   │               │               │               │              │
   │               │  [Análise]                    │              │
   │               │──analyze_content()────────────────────────────▶│
   │               │               │               │   [Chunks]   │
   │               │               │               │──extract()──▶│
   │               │               │               │◀──profiles───│
   │               │               │               │──merge()────▶│
   │               │◀──profile─────────────────────────────────────│
   │               │               │               │              │
   │◀──CompanyProfile──│               │               │              │
```

---

## Comparação: v1 vs v2

| Aspecto | v1 (/monta_perfil) | v2 (endpoints modulares) |
|---------|-------------------|--------------------------|
| **Chamadas** | 1 única | 4 chamadas sequenciais |
| **Timeout** | 300s fixo | Configurável por etapa |
| **Persistência** | Sem (apenas retorna) | Cada etapa salva no DB |
| **Controle** | Menos | Mais granular |
| **Reprocessamento** | Todo o fluxo | Apenas etapas necessárias |
| **Custo LLM** | Igual | Igual |
| **Complexidade** | Menor | Maior |

---

## Quando Usar

### Use `/monta_perfil` (v1) quando:
- Precisa de uma solução simples e direta
- Processamento único (não precisa reprocessar etapas)
- Integração externa que espera resposta completa

### Use endpoints v2 quando:
- Precisa de controle granular sobre cada etapa
- Quer salvar resultados intermediários
- Precisa reprocessar apenas algumas etapas
- Monitoramento detalhado por fase

---

## Logging e Rastreamento

Cada request gera um `request_id` único para rastreamento:

```
[abc12345][CNPJ: 12345678 - Empresa Exemplo][DISCOVERY] Buscando site...
[abc12345][CNPJ: 12345678 - Empresa Exemplo][SCRAPER] Scraping 15 páginas...
[abc12345][CNPJ: 12345678 - Empresa Exemplo][LLM] Processando 5 chunks...
[abc12345][PERF] monta_perfil end url=https://... total=125.432s
```

---

## Tratamento de Erros

### Discovery Timeout
```json
{
  "detail": "Discovery timeout após 70s"
}
```

### Analysis Timeout
```json
{
  "detail": "Analysis timed out (exceeded 300s)"
}
```

### Site Não Encontrado
```json
{
  "detail": "Site oficial não encontrado com os dados fornecidos."
}
```

### Dados Insuficientes
```json
{
  "detail": "Deve fornecer URL ou dados da empresa (razao_social, nome_fantasia, cnpj)"
}
```

---

## Considerações de Performance

1. **Timeout de 300s**: Suficiente para a maioria dos sites, mas pode ser insuficiente para sites muito grandes.

2. **Discovery**: Adiciona ~10-30s se URL não for fornecida.

3. **Scraping Adaptativo**: Sites com proteção (Cloudflare) podem demorar mais.

4. **Paralelismo LLM**: Chunks são processados em paralelo, reduzindo tempo total.

5. **max_subpages=50**: Limite de subpáginas para balancear completude vs tempo.

