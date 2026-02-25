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

## Novo fluxo em 3 etapas

- Etapa 1 salva `raw_content` (sucesso) ou `error` (falha) em `busca_fornecedor.scrape_main`.
- Etapa 2 lê `raw_content`, extrai links de subpágina e salva em `subpage_links`.
- Etapa 3 lê `raw_content`, extrai texto limpo e salva em `mainpage_processada`.
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

