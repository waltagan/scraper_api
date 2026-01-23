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

