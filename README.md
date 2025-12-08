# 🔍 Busca Fornecedor

Sistema de construção automática de perfis de empresas B2B brasileiras.

## 📖 Documentação

**[Acesse a documentação completa](docs/index.html)** - Visualização interativa do fluxo do sistema, parâmetros, métricas e mais.

## 🎯 Objetivo

Construir perfis completos de empresas em até **90 segundos** com taxa de sucesso de **~80%**.

## 📊 Métricas (Último Stress Test)

| Métrica | Valor |
|---------|-------|
| Throughput | 155 empresas/min |
| Taxa de Sucesso | 79.7% |
| Tempo Médio | 72s |
| RAM (300 paralelo) | ~3.5GB |

## 🏗️ Arquitetura

O sistema é composto por 3 etapas principais:

1. **Discovery** (~8s) - Busca do site oficial via Serper API + LLM
2. **Scrape** (~45s) - Extração de conteúdo com curl_cffi e estratégias adaptativas
3. **Profile** (~12s) - Análise LLM (Gemini/OpenAI) para extração estruturada

## 🚀 Início Rápido

### Requisitos

- Python 3.11+
- API Keys: Serper, Gemini, OpenAI (opcional), WebShare (opcional)

### Instalação

```bash
# Clone o repositório
git clone <repo-url>
cd busca_fornecedo_crawl

# Crie o ambiente virtual
python -m venv venv
source venv/bin/activate

# Instale dependências
pip install -r requirements.txt

# Configure variáveis de ambiente
cp .env.example .env
# Edite .env com suas API keys
```

### Uso

```bash
# Iniciar servidor
uvicorn app.main:app --reload

# Testar endpoint
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sua-api-key" \
  -d '{
    "razao_social": "EMPRESA LTDA",
    "nome_fantasia": "EMPRESA",
    "cnpj": "12345678000199",
    "municipio": "São Paulo",
    "uf": "SP"
  }'
```

## ⚙️ Configuração

| Variável | Descrição | Obrigatório |
|----------|-----------|-------------|
| `SERPER_API_KEY` | API key do Serper.dev | ✅ |
| `GEMINI_API_KEY` | API key do Google Gemini | ✅ |
| `OPENAI_API_KEY` | API key da OpenAI | Fallback |
| `WEBSHARE_API_KEY` | API key do WebShare | Opcional |
| `API_KEY` | Chave de autenticação | ✅ |

## 🧪 Testes

```bash
# Teste completo
python tests/suites/test_final_production.py 100 --concurrent 100 --timeout 120

# Teste individual
pytest tests/
```

## 📁 Estrutura

```
busca_fornecedo_crawl/
├── app/
│   ├── api/              # Endpoints FastAPI
│   ├── core/             # Configurações
│   ├── schemas/          # Modelos Pydantic
│   └── services/
│       ├── discovery/    # Busca de sites
│       ├── scraper/      # Extração de conteúdo
│       └── llm/          # Análise LLM
├── docs/                 # Documentação interativa
├── tests/                # Testes automatizados
└── data/                 # Dados de aprendizado
```

## 🔧 Padrões e Tecnologias

- **Framework**: FastAPI
- **HTTP Client**: curl_cffi (sem browser headless)
- **LLM**: Google Gemini (primário), OpenAI (fallback)
- **Busca**: Serper.dev (Google Search API)
- **Proxies**: WebShare (rotating residential)
- **Validação**: Pydantic v2
- **Testes**: pytest + asyncio
- **Scraping**: Batch processing (mini-batches com delays variáveis)

## 📝 Decisões Arquiteturais

1. **Sem Browser Headless**: Por restrição de RAM do servidor (Playwright usa ~400MB/instância)
2. **Estratégias Adaptativas**: FAST → STANDARD → ROBUST → AGGRESSIVE
3. **Sistema RESCUE**: Tenta subpages quando main page tem < 500 chars
4. **Circuit Breaker**: Evita bater em domínios problemáticos
5. **Learning Engine**: Aprende estratégias bem-sucedidas por domínio
6. **Batch Scraping**: Meio termo entre sequencial e paralelo (3-5x mais rápido, simula navegação humana)

## 📊 Monitoramento

- Logs estruturados com timestamps
- Métricas de performance por etapa
- Tracking de falhas por domínio
- Relatórios JSON detalhados

## 🐛 Erros Comuns

| Erro | Causa | Mitigação |
|------|-------|-----------|
| Conteúdo Insuficiente | Site SPA ou main page vazia | Sistema RESCUE |
| Site Não Encontrado | Empresa sem presença online | Múltiplas queries |
| Timeout | Site lento ou proteção | Estratégias adaptativas |

## 📜 Changelog

### v2.2 (Atual)
- ✅ Batch Scraping: 3-5x mais rápido que sequencial (delays variáveis 3-7s)
- ✅ Simula navegação humana para evitar detecção de bot
- ✅ Configurável por ambiente (batch_size, delays)

### v2.1
- ✅ Sistema RESCUE para main pages com < 500 chars
- ✅ Documentação interativa completa
- ✅ Teste de stress com 300 empresas

### v2.0
- ✅ Scraper adaptativo com múltiplas estratégias
- ✅ LLM Provider Manager com fallback
- ✅ Circuit Breaker por domínio
- ✅ Learning Engine

### v1.0
- ✅ Scraper básico com curl_cffi
- ✅ Discovery via Serper
- ✅ Análise LLM simples

## 📄 Licença

Proprietário - Uso interno apenas.

---

*Documentação gerada em Dezembro 2025*



