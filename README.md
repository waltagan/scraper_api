# Busca Fornecedor API

API para construção automática de perfis de empresas B2B brasileiras.

## Endpoints

- `POST /v2/serper` - Busca no Google
- `POST /v2/encontrar_site` - Identifica site oficial
- `POST /v2/scrape` - Extrai conteúdo do site
- `POST /v2/scrape/main-page/unified` - Executa etapas 1/2/3 em um único fluxo
- `POST /v2/scrape/main-page/unified/batch` - Processamento em lote no fluxo unificado
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

### Opcionais
- `GOOGLE_API_KEY` - API key do Google Gemini (fallback)
- `OPENAI_API_KEY` - API key da OpenAI (fallback)
- `API_ACCESS_TOKEN` - Token de autenticação
- `PHOENIX_COLLECTOR_URL` - URL do Phoenix (observabilidade)

## Deploy

A API está configurada para deploy no Railway via Dockerfile ou Procfile.

Documentação interativa: `/docs`

## Padrões no Scraper

- Pipeline em 2 etapas globais com limite de 1000 conexões por provider (até 3000 por onda com 3 providers).
- Timeouts fixos de 30s e sem retry para manter comportamento previsível próximo ao stress test.
- Distribuição de providers em round-robin fixo (sem pesos) no pool, com execução isolada por provider no batch e cap de 1000 por provider.
- Probe simplificado para GET único (sem fallback/retry), usando proxy gateway único, headers fixos, sessão compartilhada por execução e timeout hard (`asyncio.wait_for`) alinhado ao comportamento do stress test.
- Fluxo unificado em uma chamada: scrape da main page + extração de links + extração de texto processado.
- Persistência com upsert por `cnpj_basico` na tabela `scrape_main`, sem armazenar `raw_content`.
- No batch unificado, os resultados são persistidos somente ao final da execução (flush único).
