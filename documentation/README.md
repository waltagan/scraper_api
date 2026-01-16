# Documentação dos Endpoints - B2B Flash Profiler

Esta pasta contém a documentação completa de todos os endpoints da API do B2B Flash Profiler.

---

## Índice de Documentação

| # | Arquivo | Endpoint | Descrição |
|---|---------|----------|-----------|
| 1 | [01_endpoint_serper.md](./01_endpoint_serper.md) | `POST /v2/serper` | Busca no Google via Serper API |
| 2 | [02_endpoint_encontrar_site.md](./02_endpoint_encontrar_site.md) | `POST /v2/encontrar_site` | Discovery de site oficial com LLM |
| 3 | [03_endpoint_scrape.md](./03_endpoint_scrape.md) | `POST /v2/scrape` | Scraping de site e chunking |
| 4 | [04_endpoint_montagem_perfil.md](./04_endpoint_montagem_perfil.md) | `POST /v2/montagem_perfil` | Extração de perfil com LLM |
| 5 | [05_endpoint_monta_perfil_v1.md](./05_endpoint_monta_perfil_v1.md) | `POST /monta_perfil` | Fluxo completo (v1) |

---

## Arquitetura da API

### Pipeline v2 (Modular)

O pipeline v2 divide o processamento em 4 etapas independentes, cada uma salvando resultados no banco de dados:

```
┌──────────────────┐    ┌────────────────────┐    ┌──────────────┐    ┌─────────────────────┐
│  POST /v2/serper │───▶│ POST /v2/encontrar │───▶│ POST /v2/    │───▶│ POST /v2/montagem   │
│                  │    │      _site         │    │    scrape    │    │      _perfil        │
└──────────────────┘    └────────────────────┘    └──────────────┘    └─────────────────────┘
       │                        │                       │                      │
       ▼                        ▼                       ▼                      ▼
┌──────────────────┐    ┌────────────────────┐    ┌──────────────┐    ┌─────────────────────┐
│  serper_results  │    │  website_discovery │    │ scraped_     │    │   company_profile   │
│      (DB)        │    │       (DB)         │    │ chunks (DB)  │    │        (DB)         │
└──────────────────┘    └────────────────────┘    └──────────────┘    └─────────────────────┘
```

### Pipeline v1 (Unificado)

O endpoint v1 executa todo o pipeline em uma única chamada:

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           POST /monta_perfil                                    │
│                                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────┐    ┌─────────────────┐   │
│  │ Discovery │───▶│   Scraping   │───▶│   Chunking  │───▶│  LLM Analysis   │   │
│  └──────────┘    └──────────────┘    └─────────────┘    └─────────────────┘   │
│                                                                                 │
└────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │    CompanyProfile    │
                              │      (Response)      │
                              └──────────────────────┘
```

---

## Comparação v1 vs v2

| Característica | v1 (/monta_perfil) | v2 (endpoints modulares) |
|----------------|-------------------|--------------------------|
| **Chamadas** | 1 | 4 |
| **Persistência** | Não | Sim (cada etapa) |
| **Controle** | Baixo | Alto |
| **Reprocessamento** | Todo o fluxo | Por etapa |
| **Complexidade** | Simples | Mais complexo |
| **Autenticação** | API Key | Não requerida |

---

## Configurações Principais

### Arquivos de Configuração

| Arquivo | Descrição |
|---------|-----------|
| `app/configs/discovery/serper.json` | Rate limiting da API Serper |
| `app/configs/discovery/discovery.json` | Timeouts do discovery |
| `app/configs/discovery/llm_agents.json` | Configurações do DiscoveryAgent |
| `app/configs/scraper/scraper_domain.json` | Rate limiting por domínio |
| `app/configs/chunking/chunking.json` | Limites de tokens e chunking |
| `app/configs/profile/profile_llm.json` | Configurações do Profile LLM |
| `app/configs/profile/llm_agents.json` | Configurações do ProfileExtractorAgent |

### Parâmetros Críticos

| Parâmetro | Arquivo | Valor | Impacto |
|-----------|---------|-------|---------|
| `rate_per_second` | serper.json | 190 | Taxa de requisições Serper |
| `max_chunk_tokens` | chunking.json | 20000 | Tamanho máximo de chunk |
| `timeout` | discovery.json | 70 | Timeout do discovery (s) |
| `requests_per_minute` | scraper_domain.json | 100 | RPM por domínio |

---

## Banco de Dados

### Tabelas Utilizadas

| Tabela | Endpoint | Descrição |
|--------|----------|-----------|
| `serper_results` | /v2/serper | Resultados de busca Google |
| `website_discovery` | /v2/encontrar_site | Sites identificados |
| `scraped_chunks` | /v2/scrape | Conteúdo chunkeado |
| `company_profile` | /v2/montagem_perfil | Perfis extraídos |

### Diagrama ER Simplificado

```
serper_results              website_discovery         scraped_chunks         company_profile
┌─────────────────┐        ┌────────────────────┐    ┌───────────────────┐   ┌──────────────────┐
│ id (PK)         │        │ id (PK)            │    │ id (PK)           │   │ id (PK)          │
│ cnpj_basico     │───────▶│ cnpj_basico (UK)   │───▶│ cnpj_basico       │   │ cnpj (UK)        │
│ results_json    │        │ serper_id (FK)     │    │ discovery_id (FK) │   │ profile_json     │
│ query_used      │        │ website_url        │    │ chunk_content     │   │ company_name     │
└─────────────────┘        │ discovery_status   │    │ token_count       │   │ industry         │
                           └────────────────────┘    └───────────────────┘   └──────────────────┘
```

---

## Estrutura dos Documentos

Cada documento de endpoint contém:

1. **Visão Geral** - Descrição do endpoint
2. **Request/Response** - Schemas e exemplos
3. **Fluxo de Execução** - Diagrama do pipeline
4. **Funções Chamadas** - Call stack detalhado
5. **Configurações** - Parâmetros ajustáveis e impactos
6. **Banco de Dados** - Tabelas e schemas SQL
7. **Códigos de Erro** - Tratamento de erros
8. **Exemplos de Uso** - Comandos curl
9. **Diagramas** - Sequência e fluxo

---

## Quick Start

### 1. Pipeline v2 Completo

```bash
# 1. Buscar no Google
curl -X POST "http://localhost:8000/v2/serper" \
  -H "Content-Type: application/json" \
  -d '{"cnpj_basico": "12345678", "nome_fantasia": "Exemplo", "municipio": "São Paulo"}'

# 2. Identificar site oficial
curl -X POST "http://localhost:8000/v2/encontrar_site" \
  -H "Content-Type: application/json" \
  -d '{"cnpj_basico": "12345678"}'

# 3. Fazer scraping
curl -X POST "http://localhost:8000/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{"cnpj_basico": "12345678", "website_url": "https://www.exemplo.com.br"}'

# 4. Extrair perfil
curl -X POST "http://localhost:8000/v2/montagem_perfil" \
  -H "Content-Type: application/json" \
  -d '{"cnpj_basico": "12345678"}'
```

### 2. Pipeline v1 (Tudo em Um)

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

---

## Manutenção da Documentação

### Quando Atualizar

- Ao adicionar novos endpoints
- Ao modificar schemas de request/response
- Ao alterar configurações
- Ao modificar fluxos de execução

### Convenção de Nomenclatura

- Arquivos: `XX_endpoint_nome.md`
- XX = número sequencial (01, 02, etc.)
- nome = identificador curto do endpoint

---

## Contato

Para dúvidas ou sugestões sobre a documentação, consulte o README.md principal do projeto.

