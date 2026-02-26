# Endpoints da API

## Endpoints Disponíveis

### GET Endpoints (Informação)

- `GET /` - Status da API
- `GET /health` - Health check (banco de dados)
- `GET /v2` - Lista endpoints v2 disponíveis
- `GET /docs` - Documentação interativa (Swagger)
- `GET /redoc` - Documentação alternativa (ReDoc)

### POST Endpoints (Processamento Assíncrono)

**⚠️ IMPORTANTE: Todos os endpoints v2 são POST e retornam imediatamente após aceitar a requisição. O processamento ocorre em background.**

#### 1. `/v2/serper` - Busca Google via Serper
```json
POST /v2/serper
{
  "cnpj_basico": "12345678",
  "razao_social": "EMPRESA LTDA",
  "nome_fantasia": "Empresa",
  "municipio": "São Paulo"
}
```

#### 2. `/v2/encontrar_site` - Descoberta de Site Oficial
```json
POST /v2/encontrar_site
{
  "cnpj_basico": "12345678"
}
```

#### 3. `/v2/scrape` - Scraping de Site
```json
POST /v2/scrape
{
  "cnpj_basico": "12345678",
  "website_url": "https://example.com"
}
```

#### 4. `/v2/montagem_perfil` - Montagem de Perfil Completo
```json
POST /v2/montagem_perfil
{
  "cnpj_basico": "12345678"
}
```

#### 5. `/v2/scrape/main-page` - Etapa 1 (Main Page Raw)
```json
POST /v2/scrape/main-page
{
  "cnpj_basico": "12345678",
  "website_url": "https://example.com"
}
```

#### 6. `/v2/scrape/main-page/subpage-links` - Etapa 2 (Extrair Links)
```json
POST /v2/scrape/main-page/subpage-links
{
  "cnpj_basico": "12345678"
}
```

#### 7. `/v2/scrape/main-page/process-text` - Etapa 3 (Processar Texto)
```json
POST /v2/scrape/main-page/process-text
{
  "cnpj_basico": "12345678"
}
```

#### 8. `/v2/scrape/main-page/unified` - Fluxo Unificado (Single)
```json
POST /v2/scrape/main-page/unified
{
  "cnpj_basico": "12345678",
  "website_url": "https://example.com",
  "timeout_seconds": 30,
  "redis_ttl_seconds": 600
}
```

#### 9. `/v2/scrape/main-page/unified/batch` - Fluxo Unificado (Batch)
```json
POST /v2/scrape/main-page/unified/batch
{
  "total_samples": 3200,
  "batch_size": 3200,
  "save_every": 50,
  "timeout_seconds": 30,
  "redis_ttl_seconds": 600
}
```

## Fluxo unificado em 3 microetapas

- Etapa 1 captura `raw_content` e mantém temporariamente no Redis (TTL curto).
- Etapa 2 lê o `raw_content` temporário, extrai links de subpágina e salva em `subpage_links`.
- Etapa 3 lê o `raw_content` temporário, extrai texto limpo e salva em `mainpage_processada`.
- `raw_content` **não** é salvo no PostgreSQL.
- Chave de atualização: upsert por `cnpj_basico`.

## Respostas

Todos os endpoints POST retornam imediatamente com:
```json
{
  "success": true,
  "message": "Requisição aceita. Processamento em background.",
  "cnpj_basico": "12345678",
  "status": "accepted"
}
```

## Erros Comuns

### "Method Not Allowed"
- **Causa**: Tentando usar GET em endpoint POST
- **Solução**: Use POST para todos os endpoints v2

### "Not Found"
- **Causa**: Rota não existe
- **Solução**: Verifique a URL (deve começar com `/v2/`)

