# Busca Fornecedor API

API para construção automática de perfis de empresas B2B brasileiras.

## Endpoints

- `POST /v2/serper` - Busca no Google
- `POST /v2/encontrar_site` - Identifica site oficial
- `POST /v2/scrape` - Extrai conteúdo do site
- `POST /v2/montagem_perfil` - Gera perfil estruturado

Todos os endpoints retornam imediatamente e processam em background.

## Variáveis de Ambiente

### Obrigatórias
- `DATABASE_URL` - URL de conexão PostgreSQL
- `VLLM_BASE_URL` - URL base do endpoint SGLang (RunPod, Vast.ai, ou self-hosted)
- `VLLM_API_KEY` - API key do SGLang (se necessário)
- `VLLM_MODEL` - Modelo carregado no SGLang (ex: `Qwen/Qwen2.5-3B-Instruct`)
- `SERPER_API_KEY` - API key do Serper.dev

**Nota**: As variáveis `VLLM_*` funcionam com qualquer instância SGLang compatível com OpenAI API (/v1/*).

### Proxy
- `PROXY_GATEWAY_URL` - URL do gateway rotativo 711Proxy (ex: `http://user:pass@us.rotgb.711proxy.com:10000`)
- `PROXY_BYPORT_URLS` - URLs das portas dedicadas 711Proxy, separadas por vírgula (ex: `http://user:pass@128.14.145.62:25001,...`)

### Opcionais
- `GOOGLE_API_KEY` - API key do Google Gemini (fallback)
- `OPENAI_API_KEY` - API key da OpenAI (fallback)
- `API_ACCESS_TOKEN` - Token de autenticação
- `PHOENIX_COLLECTOR_URL` - URL do Phoenix (observabilidade)

## Proxy Modes

O batch scrape suporta 3 modos de proxy (parâmetro `proxy_mode` na chamada):

| Modo | Semáforo | Descrição |
|------|----------|-----------|
| `gateway` (padrão) | 800 | Gateway rotativo 711Proxy — IPs rotativos por request |
| `byport` | 2000 | Portas dedicadas com IPs sticky — round-robin entre portas |
| `combined` | 2800 | Usa gateway + byport simultaneamente para máximo throughput |

## Patterns & Technology

- **Framework**: FastAPI + asyncio
- **HTTP Client**: curl_cffi (TLS fingerprint rotation)
- **Proxy**: 711Proxy (gateway rotating + byport sticky)
- **Concurrency Control**: asyncio.Semaphore (proxy_gate) — dinâmico por modo
- **Database**: PostgreSQL (Railway)
- **LLM**: SGLang via Vast.ai (Qwen)
- **Observability**: Phoenix tracing

## Deploy

A API está configurada para deploy no Railway via Dockerfile ou Procfile.

Documentação interativa: `/docs`
