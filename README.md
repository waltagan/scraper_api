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
- `VLLM_BASE_URL` - URL base do endpoint vLLM
- `VLLM_API_KEY` - API key do vLLM
- `VLLM_MODEL` - Modelo a ser usado
- `SERPER_API_KEY` - API key do Serper.dev

### Opcionais
- `GOOGLE_API_KEY` - API key do Google Gemini (fallback)
- `OPENAI_API_KEY` - API key da OpenAI (fallback)
- `API_ACCESS_TOKEN` - Token de autenticação
- `PHOENIX_COLLECTOR_URL` - URL do Phoenix (observabilidade)

## Deploy

A API está configurada para deploy no Railway via Dockerfile ou Procfile.

Documentação interativa: `/docs`
