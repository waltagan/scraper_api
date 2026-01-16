# Endpoint: POST /v2/scrape

## Visão Geral

O endpoint `/v2/scrape` é responsável por fazer scraping do site oficial da empresa, extrair conteúdo de múltiplas páginas e salvar os dados em chunks no banco de dados. É o terceiro passo no pipeline de extração de perfil.

---

## Informações Básicas

| Propriedade | Valor |
|-------------|-------|
| **URL** | `POST /v2/scrape` |
| **Tag** | `v2-scrape` |
| **Autenticação** | Não requerida (endpoint interno) |
| **Content-Type** | `application/json` |

---

## Request

### Schema: `ScrapeRequest`

```json
{
  "cnpj_basico": "12345678",
  "website_url": "https://www.empresa.com.br"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `cnpj_basico` | string(8) | ✅ Sim | CNPJ básico da empresa (8 primeiros dígitos) |
| `website_url` | string | ✅ Sim | URL do site oficial para scraping |

---

## Response

### Schema: `ScrapeResponse`

```json
{
  "success": true,
  "chunks_saved": 15,
  "total_tokens": 125000,
  "pages_scraped": 8,
  "processing_time_ms": 3450.5
}
```

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `success` | boolean | Indica se a operação foi bem-sucedida |
| `chunks_saved` | int | Número de chunks salvos no banco de dados |
| `total_tokens` | int | Total de tokens processados em todos os chunks |
| `pages_scraped` | int | Número de páginas scraped com sucesso |
| `processing_time_ms` | float | Tempo total de processamento (ms) |

---

## Fluxo de Execução

```
┌─────────────────────────────────────────────────────────────────┐
│                    POST /v2/scrape                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. scrape_all_subpages()                                        │
│     a. url_prober.probe() - Encontra melhor variação da URL      │
│     b. site_analyzer.analyze() - Detecta proteção e tipo         │
│     c. strategy_selector.select() - Escolhe estratégia           │
│     d. _scrape_main_page() - Scrape página principal             │
│     e. prioritize_links() - Seleciona links por heurísticas      │
│     f. _scrape_subpages_batch() - Scrape subpáginas em paralelo  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. Agregação de Conteúdo                                        │
│     - Combina conteúdo de todas as páginas                       │
│     - Formato: --- PAGE START: <url> --- ... --- PAGE END ---    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. process_content() - Chunking                                 │
│     - SmartChunker divide por páginas                            │
│     - Divide páginas grandes em sub-chunks                       │
│     - Agrupa páginas pequenas                                    │
│     - Respeita limite de tokens                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. db_service.save_chunks_batch()                               │
│     - Salva todos os chunks em transação única                   │
│     - Tabela: scraped_chunks                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. Retorna ScrapeResponse                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Funções Chamadas (Call Stack Detalhado)

### 1. `scrape_website()` - Endpoint Principal
**Arquivo:** `app/api/v2/scrape.py`

Orquestra todo o fluxo de scraping.

### 2. `scrape_all_subpages()` - Scraping Completo
**Arquivo:** `app/services/scraper/scraper_service.py`

Pipeline de scraping:

#### 2.1 `url_prober.probe()` - Probe URL
Testa variações da URL (www, https, http) para encontrar a melhor.

#### 2.2 `site_analyzer.analyze()` - Análise do Site
Detecta:
- Tipo de proteção (Cloudflare, WAF, CAPTCHA)
- Características do site (CMS, tecnologia)
- Latência de resposta

#### 2.3 `strategy_selector.select()` - Seleção de Estratégia
Escolhe estratégia de scraping baseada no perfil do site:
- `DIRECT` - Requisição direta
- `STEALTH` - Com User-Agent rotativo
- `PROXY` - Via proxy
- `CURL_CFFI` - Biblioteca curl-cffi

#### 2.4 `_scrape_main_page()` - Página Principal
Scrape da home page com fallback entre estratégias.

#### 2.5 `prioritize_links()` - Seleção de Links
Prioriza links por heurísticas (sem LLM):
- Páginas de "sobre", "produtos", "serviços"
- Links internos (mesmo domínio)
- Remove arquivos não-HTML

#### 2.6 `_scrape_subpages_batch()` - Subpáginas em Batch
Processa subpáginas em mini-batches paralelos com delays.

### 3. `process_content()` - Chunking
**Arquivo:** `app/core/chunking/chunker.py`

Divide conteúdo em chunks respeitando limites de tokens.

### 4. `db_service.save_chunks_batch()` - Persistência
**Arquivo:** `app/services/database_service.py`

Salva chunks em transação única.

---

## Configurações

### Arquivo: `app/configs/chunking/chunking.json`

```json
{
  "max_chunk_tokens": 20000,
  "system_prompt_overhead": 2500,
  "message_overhead": 200,
  "safety_margin": 0.85,
  "group_target_tokens": 12000,
  "min_chunk_chars": 500,
  "dedupe": {
    "enabled": true,
    "scope": "document",
    "min_line_length": 5,
    "preserve_first_occurrence": true
  },
  "tokenizer": {
    "type": "mistral-common",
    "model": "mistralai/Ministral-3-8B-Instruct-2512",
    "fallback_chars_per_token": 3
  }
}
```

### Descrição das Configurações de Chunking

| Parâmetro | Valor | Descrição | Impacto ao Aumentar | Impacto ao Diminuir |
|-----------|-------|-----------|---------------------|---------------------|
| `max_chunk_tokens` | 20000 | Limite máximo de tokens por chunk | Chunks maiores, menos chamadas LLM | Chunks menores, mais seguros |
| `system_prompt_overhead` | 2500 | Tokens reservados para system prompt | Mais margem para prompts grandes | Risco de overflow |
| `safety_margin` | 0.85 | Fator de segurança (85% do limite) | Mais tokens por chunk, mais risco | Menos tokens, mais seguro |
| `group_target_tokens` | 12000 | Alvo de tokens ao agrupar páginas | Menos chamadas LLM | Mais chamadas, melhor granularidade |
| `min_chunk_chars` | 500 | Mínimo de caracteres por chunk | Menos fragmentação | Chunks muito pequenos mesclados |

### Configurações de Deduplicação

| Parâmetro | Valor | Descrição |
|-----------|-------|-----------|
| `dedupe.enabled` | true | Ativa deduplicação de linhas |
| `dedupe.scope` | "document" | Remove em todo documento (vs consecutivas) |
| `dedupe.min_line_length` | 5 | Linhas menores que 5 chars são ignoradas |

### Arquivo: `app/configs/scraper/scraper_domain.json`

```json
{
  "requests_per_minute": 100,
  "burst_size": 50,
  "slow_domain_rpm": 10
}
```

| Parâmetro | Valor | Descrição | Impacto ao Aumentar | Impacto ao Diminuir |
|-----------|-------|-----------|---------------------|---------------------|
| `requests_per_minute` | 100 | RPM máximo por domínio | Scraping mais rápido, risco de bloqueio | Mais seguro, mais lento |
| `burst_size` | 50 | Rajada permitida por domínio | Picos maiores | Fluxo mais nivelado |
| `slow_domain_rpm` | 10 | RPM para domínios lentos | Mais pressão em sites lentos | Mais conservador |

---

## Estratégias de Scraping

### ScrapingStrategy Enum

| Estratégia | Descrição | Quando Usar |
|------------|-----------|-------------|
| `DIRECT` | Requisição HTTP direta | Sites sem proteção |
| `STEALTH` | User-Agent rotativo | Sites com filtro básico |
| `PROXY` | Via servidor proxy | Sites com geo-blocking |
| `PROXY_ROTATE` | Proxy com rotação | Sites com rate limiting |
| `CURL_CFFI` | Biblioteca curl-cffi | Sites com fingerprint detection |

### Detecção de Proteção

O sistema detecta automaticamente:
- **Cloudflare** - JavaScript challenge
- **WAF** - Web Application Firewall
- **CAPTCHA** - Desafios de verificação
- **Rate Limit** - Limite de requisições

---

## Sistema de Batch Scraping

### Configurações de Batch

```python
scraper_config = {
    "batch_size": 5,           # URLs por batch
    "batch_min_delay": 1.0,    # Delay mínimo entre batches (s)
    "batch_max_delay": 2.0,    # Delay máximo entre batches (s)
    "intra_batch_delay": 0.2,  # Delay entre URLs no batch (s)
}
```

### Fluxo de Batch

```
┌────────────────────────────────────────────────────────────────┐
│  URLs para processar: [url1, url2, url3, url4, url5, ...]      │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────┐    ┌─────────────────────┐
│  Batch 1            │    │  Batch 2            │
│  [url1, url2, url3, │────│  [url6, url7, url8, │ ...
│   url4, url5]       │    │   url9, url10]      │
└─────────────────────┘    └─────────────────────┘
         │                           │
         ▼                           ▼
   Paralelo com              Delay 1-2s entre
   delay interno             batches
   (0.2s entre URLs)
```

---

## Sistema RESCUE

Quando a main page tem pouco conteúdo mas tem links:

```python
if len(main_page.content) < 500 and main_page.links:
    # Tenta até 3 subpages de alta relevância
    rescue_links = prioritize_links(filtered_links, url)[:3]
    rescue_subpages = await _scrape_subpages_batch(rescue_links, ...)
```

---

## Banco de Dados

### Tabela: `scraped_chunks`

```sql
CREATE TABLE scraped_chunks (
    id SERIAL PRIMARY KEY,
    cnpj_basico VARCHAR(8) NOT NULL,
    discovery_id INTEGER REFERENCES website_discovery(id),
    website_url TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    chunk_content TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    page_source TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Códigos de Erro

| Código HTTP | Descrição | Causa |
|-------------|-----------|-------|
| 200 | Sucesso | Scraping realizado com sucesso |
| 500 | Erro interno | Falha no scraping ou no banco de dados |

---

## Exemplos de Uso

### Request
```bash
curl -X POST "http://localhost:8000/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "cnpj_basico": "12345678",
    "website_url": "https://www.empresa.com.br"
  }'
```

### Response (Sucesso)
```json
{
  "success": true,
  "chunks_saved": 12,
  "total_tokens": 85000,
  "pages_scraped": 15,
  "processing_time_ms": 4250.8
}
```

### Response (Sem Conteúdo)
```json
{
  "success": false,
  "chunks_saved": 0,
  "total_tokens": 0,
  "pages_scraped": 0,
  "processing_time_ms": 1500.0
}
```

---

## Diagrama de Sequência

```
Cliente        Endpoint        ScraperService      URLProber      SiteAnalyzer
   │               │                 │                │               │
   │─POST ─────────▶│                 │                │               │
   │               │                 │                │               │
   │               │─scrape_all()───▶│                │               │
   │               │                 │──probe()──────▶│               │
   │               │                 │◀──best_url─────│               │
   │               │                 │                │               │
   │               │                 │───analyze()────────────────────▶│
   │               │                 │◀──site_profile─────────────────│
   │               │                 │                │               │
   │               │                 │──scrape_main()────────────────▶
   │               │                 │◀──main_page─────────────────────
   │               │                 │                │               │
   │               │                 │──scrape_batch()────────────────▶
   │               │                 │◀──subpages───────────────────────
   │               │                 │                │               │
   │               │◀──pages─────────│                │               │
   │               │                 │                │               │
   │               │──process_content()──────────────────────────────▶
   │               │◀──chunks────────────────────────────────────────│
   │               │                 │                │               │
   │               │──save_chunks_batch()────────────────────────────▶
   │               │◀──count─────────────────────────────────────────│
   │               │                 │                │               │
   │◀──Response────│                 │                │               │
```

---

## Estrutura de Chunk

```python
@dataclass
class Chunk:
    content: str          # Conteúdo do chunk
    tokens: int           # Número de tokens
    index: int            # Índice (1-based)
    total_chunks: int     # Total de chunks
    pages_included: List[str]  # URLs das páginas
```

---

## Gerenciadores de Infraestrutura

### ConcurrencyManager
- Controla slots por domínio
- Marca domínios lentos
- Aplica rate limiting

### CircuitBreaker
- Abre após falhas consecutivas
- Evita sobrecarregar sites problemáticos

### ProxyPool
- Rotação de proxies
- Health check de proxies
- Fallback para proxy saudável

---

## Considerações de Performance

1. **Batch Processing**: Processa até 5 URLs em paralelo por batch.

2. **Adaptive Timeout**: Sites lentos recebem timeout maior automaticamente.

3. **Smart Delays**: Delays entre requisições simulam navegação humana.

4. **Chunking Otimizado**: Agrupa páginas pequenas para reduzir chamadas LLM.

5. **Transação Única**: Todos os chunks são salvos em uma transação atômica.

---

## Pré-requisitos

Antes de chamar este endpoint, é necessário:

1. **Descoberta de Site**: Executar `POST /v2/encontrar_site` para obter o website_url

---

## Próximo Passo no Pipeline

Após salvar os chunks, o próximo endpoint a ser chamado é:

**`POST /v2/montagem_perfil`** - Processa os chunks com LLM para extrair perfil estruturado.

