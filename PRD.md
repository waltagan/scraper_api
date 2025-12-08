# PRD - Product Requirements Document
## Sistema de Construção de Perfis de Empresas B2B - v2.0

**Versão:** 2.0  
**Data:** 2025-12-05  
**Autor:** Análise Técnica  
**Status:** Em Desenvolvimento  

---

## 📋 Sumário Executivo

### Objetivo do Sistema
Construir perfis completos de empresas B2B a partir de dados cadastrais (nome fantasia, razão social, CNPJ, CNAE, etc.) em até **90 segundos**, incluindo:
- Descoberta automática do site oficial
- Scraping do site e subpáginas
- Análise por LLM para geração de perfil estruturado

> **Nota v2.0**: O módulo de extração de documentos (PDFs, DOCs) foi removido desta versão para simplificar o fluxo e melhorar a performance. A extração de conteúdo foca exclusivamente em páginas HTML.

### Problema Atual
O sistema apresenta **falhas estruturais** ao processar 500 empresas consecutivas:
1. **Módulo de Scraper (71.5% das falhas):** Não adaptável a diferentes tipos de sites
2. **Módulo de LLM (19.2% das falhas):** Timeouts e rate limits não tratados adequadamente

### Meta
Taxa de sucesso ≥ 95% com tempo médio de processamento ≤ 90 segundos por empresa.

### 🎯 Critério de Aprovação Final: STRESS TEST

O sistema será considerado **APROVADO** quando passar no seguinte teste:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     STRESS TEST - CRITÉRIO DE APROVAÇÃO                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  📊 PARÂMETROS DO TESTE:                                                    │
│  ────────────────────────                                                   │
│  • Empresas processadas: 500 em paralelo                                    │
│  • Timeout por empresa: 90 segundos                                         │
│  • Fonte de dados: Lista real de empresas brasileiras (CNPJ válidos)        │
│                                                                             │
│  ✅ CRITÉRIOS DE SUCESSO:                                                   │
│  ────────────────────────                                                   │
│  1. Tempo médio ≤ 90s (apenas empresas COM site encontrado)                 │
│  2. Taxa de sucesso ≥ 90% (das empresas COM site encontrado)                │
│  3. Completude do perfil ≥ 85% (campos obrigatórios preenchidos)            │
│  4. Zero crashes/memory leaks durante execução                              │
│  5. Todos os LLM providers funcionando (fallback operacional)               │
│                                                                             │
│  ❌ EMPRESAS DESCARTADAS (não contam nas métricas):                         │
│  ────────────────────────────────────────────────────                       │
│  • Site oficial não encontrado pelo Discovery                               │
│  • Site fora do ar / domínio expirado                                       │
│  • Site bloqueado geograficamente                                           │
│                                                                             │
│  ⚠️ PRESERVAÇÃO DA QUALIDADE:                                               │
│  ──────────────────────────────                                             │
│  • NÃO reduzir número de subpáginas scraped                                 │
│  • NÃO reduzir campos extraídos pelo LLM                                    │
│  • NÃO simplificar prompts para acelerar                                    │
│  • MANTER extração completa de todas as seções do perfil                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Importante:** A qualidade dos perfis é **INEGOCIÁVEL**. Otimizações de performance NÃO podem sacrificar a completude dos dados extraídos.

### Decisões de Arquitetura v2.0

#### ❌ Remoção do Módulo de Documentos (PDF/DOC)

**Motivo da Remoção:**
1. **Complexidade adicional**: O download e parsing de documentos adiciona latência significativa (5-15s por documento)
2. **Taxa de sucesso baixa**: Muitos PDFs estão protegidos, corrompidos ou são muito grandes
3. **Valor marginal**: A maioria das informações relevantes já está disponível nas páginas HTML
4. **Simplificação do fluxo**: Menos pontos de falha = maior confiabilidade

**Impacto Esperado:**
- ⬇️ Tempo médio de processamento: -10s a -30s
- ⬆️ Taxa de sucesso: +5% a +10%
- ⬇️ Complexidade do código: -30%

**Alternativa Futura:**
Se necessário, o módulo de documentos pode ser reimplementado como um serviço separado, acionado sob demanda após a análise inicial do perfil.

#### ⚠️ Restrições de Recursos do Servidor

**Contexto:** O servidor de produção possui recursos limitados de memória e CPU. Soluções que exigem muitos recursos devem ser evitadas.

**Soluções PROIBIDAS (alto consumo de memória):**

| Solução | Consumo de Memória | Motivo da Proibição |
|---------|-------------------|---------------------|
| 🚫 Playwright | ~300-500MB/instância | Browser completo em memória |
| 🚫 Undetected Chrome | ~500MB+/instância | Chrome real + patches anti-detecção |
| 🚫 Selenium | ~400MB+/instância | Browser completo + driver |
| 🚫 Puppeteer | ~300-500MB/instância | Similar ao Playwright |

**Soluções APROVADAS (baixo consumo de memória):**

| Solução | Consumo de Memória | Uso Recomendado |
|---------|-------------------|-----------------|
| ✅ curl_cffi | ~5-10MB | Scraping principal (simula TLS fingerprint) |
| ✅ System Curl | ~2-5MB | Fallback para sites simples |
| ✅ httpx/aiohttp | ~10-20MB | Requisições HTTP simples |
| ✅ BeautifulSoup | ~20-50MB | Parsing de HTML |

**Princípio:** Sempre priorizar soluções baseadas em HTTP puro. Browsers headless são **ÚLTIMO RECURSO** e devem ser usados via serviço externo (ex: API de scraping terceirizada), nunca no servidor principal.

---

## 📊 Diagnóstico do Estado Atual

### Arquitetura Atual (v1.0)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API FastAPI                                     │
│                            /analyze endpoint                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐ │
│  │  Discovery   │───▶│   Scraper    │───▶│     PDF      │───▶│    LLM    │ │
│  │  (Google)    │    │  (curl_cffi) │    │  (PyMuPDF)   │    │  (Gemini/ │ │
│  │              │    │              │    │  ❌ REMOVIDO │    │   OpenAI) │ │
│  └──────────────┘    └──────────────┘    └──────────────┘    └───────────┘ │
│        ▲                    ▲                                       │      │
│        │                    │                                       ▼      │
│  ┌──────────────┐    ┌──────────────┐                      ┌───────────────┐
│  │   Serper     │    │    Proxy     │                      │CompanyProfile │
│  │     API      │    │   Manager    │                      │    (JSON)     │
│  └──────────────┘    └──────────────┘                      └───────────────┘
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Arquitetura v2.0 (Simplificada - sem módulo PDF)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API FastAPI                                     │
│                            /analyze endpoint                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────┐                     │
│  │  Discovery   │───▶│   Scraper    │───▶│    LLM    │                     │
│  │  (Serper)    │    │  (curl_cffi) │    │  (Gemini/ │                     │
│  │              │    │              │    │   OpenAI) │                     │
│  └──────────────┘    └──────────────┘    └───────────┘                     │
│        ▲                    ▲                  │                            │
│        │                    │                  ▼                            │
│  ┌──────────────┐    ┌──────────────┐   ┌───────────────┐                  │
│  │   Cache      │    │    Proxy     │   │CompanyProfile │                  │
│  │   Domains    │    │   Manager    │   │    (JSON)     │                  │
│  └──────────────┘    └──────────────┘   └───────────────┘                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Métricas de Falha (Análise de Logs)

| Categoria | Quantidade | % do Total | Causa Principal |
|-----------|------------|------------|-----------------|
| 📭 Empty Content | 693 | 71.5% | Cloudflare, WAF, SPA |
| ⏱️ Timeout | 186 | 19.2% | Proxy lento, rate limit |
| ❓ HTTP 404 | 24 | 2.5% | Links quebrados |
| ❔ Outros | 66 | 6.8% | Diversos |

### Testes de Validação Realizados

| Método | Taxa de Sucesso (sem proxy) | Taxa de Sucesso (com proxy) |
|--------|-----------------------------|-----------------------------|
| curl_cffi | **100%** ✅ | 85% |
| System Curl | 31% | 28% |

**Conclusão:** O problema principal está na **latência do proxy** e na **detecção de proteções anti-bot**.

---

## 🎯 Requisitos Funcionais

### RF01 - Scraper Adaptativo (Leve)
O sistema deve identificar automaticamente o tipo de site e adaptar a estratégia de scraping, **usando apenas soluções baseadas em HTTP** (sem browser headless).

**Critérios de Aceite:**
- [ ] Detectar presença de Cloudflare em < 2 segundos
- [ ] Detectar sites SPA/JavaScript-heavy e marcar como "conteúdo limitado"
- [ ] Tentar múltiplas variações de acesso (https/http, www/sem-www)
- [ ] Fallback automático entre métodos de scrape (FAST → STANDARD → ROBUST → AGGRESSIVE)
- [ ] Não contar proteções anti-bot como falhas no circuit breaker
- [ ] **NÃO usar** Playwright, Selenium ou qualquer browser headless

**Tratamento de Sites SPA:**
- Sites que requerem JavaScript para renderizar conteúdo serão marcados com flag `requer_js=True`
- O conteúdo extraído pode ser limitado (apenas HTML estático)
- Isso é aceitável - muitos sites têm informações básicas no HTML estático (meta tags, texto inicial)
- Se o conteúdo for insuficiente, o perfil será marcado como "parcial"

### RF02 - Gestão Inteligente de LLM
O sistema deve gerenciar múltiplos provedores de LLM com balanceamento de carga real.

**Critérios de Aceite:**
- [ ] Suportar 3+ provedores de LLM (Google, OpenAI, OpenRouter)
- [ ] Failover automático em caso de rate limit
- [ ] Retry com backoff exponencial
- [ ] Queue management para evitar burst de requisições
- [ ] Monitoramento de saúde em tempo real

### RF03 - Sistema de Auto-Aprendizado
O sistema deve aprender com falhas e melhorar automaticamente.

**Critérios de Aceite:**
- [ ] Registrar todas as falhas com contexto completo
- [ ] Categorizar falhas automaticamente
- [ ] Sugerir melhorias baseadas em padrões de falha
- [ ] Manter base de conhecimento de sites problemáticos
- [ ] Atualizar configurações dinamicamente

### RF04 - Testes Automatizados por Módulo
Cada módulo deve ter suite de testes independente.

**Critérios de Aceite:**
- [ ] Test suite para Scraper com 500+ sites
- [ ] Test suite para LLM com 300+ scrapes
- [ ] Métricas de performance por teste
- [ ] Relatórios automatizados de regressão

---

## 🏗️ Arquitetura Proposta v2.0

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    API FastAPI                                           │
│                                  /analyze endpoint                                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐│
│  │                           🧠 ORCHESTRATOR INTELIGENTE                               ││
│  │    • Timeout global configurável (90s padrão)                                       ││
│  │    • Retry manager centralizado                                                     ││
│  │    • Métricas e telemetria                                                          ││
│  └─────────────────────────────────────────────────────────────────────────────────────┘│
│                                          │                                              │
│       ┌──────────────────────────────────┼──────────────────────────────────┐          │
│       │                                  │                                  │          │
│       ▼                                  ▼                                  ▼          │
│  ┌──────────────┐                 ┌──────────────┐                 ┌──────────────┐    │
│  │  Discovery   │                 │   Scraper    │                 │     LLM      │    │
│  │   Service    │                 │   Service    │                 │   Service    │    │
│  │              │                 │              │                 │              │    │
│  │ ┌──────────┐ │                 │ ┌──────────┐ │                 │ ┌──────────┐ │    │
│  │ │  Serper  │ │                 │ │ Detector │ │                 │ │ Balancer │ │    │
│  │ │   API    │ │                 │ │   WAF    │ │                 │ │  v2.0    │ │    │
│  │ └──────────┘ │                 │ └──────────┘ │                 │ └──────────┘ │    │
│  │              │                 │ ┌──────────┐ │                 │ ┌──────────┐ │    │
│  │ ┌──────────┐ │                 │ │ Strategy │ │                 │ │  Queue   │ │    │
│  │ │  Cache   │ │                 │ │ Selector │ │                 │ │ Manager  │ │    │
│  │ │ Domains  │ │                 │ └──────────┘ │                 │ └──────────┘ │    │
│  │ └──────────┘ │                 │ ┌──────────┐ │                 │ ┌──────────┐ │    │
│  └──────────────┘                 │ │ Parallel │ │                 │ │ Provider │ │    │
│                                   │ │  Scraper │ │                 │ │  Pool    │ │    │
│                                   │ └──────────┘ │                 │ └──────────┘ │    │
│                                   └──────────────┘                 └──────────────┘    │
│                                          │                                  │          │
│       ┌──────────────────────────────────┼──────────────────────────────────┘          │
│       │                                  │                                              │
│       ▼                                  ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────────────────┐      │
│  │                        📊 LEARNING ENGINE (NOVO)                              │      │
│  │                                                                               │      │
│  │   ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐         │      │
│  │   │  Failure   │   │  Pattern   │   │   Config   │   │  Metrics   │         │      │
│  │   │  Tracker   │   │  Analyzer  │   │  Optimizer │   │  Reporter  │         │      │
│  │   └────────────┘   └────────────┘   └────────────┘   └────────────┘         │      │
│  │                                                                               │      │
│  └──────────────────────────────────────────────────────────────────────────────┘      │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Módulo 1: Scraper Adaptativo v2.0

### 1.1 Problema Atual
- Timeout fixo de 15s não adequado para todos os sites
- Não detecta tipo de proteção antes de tentar scrape
- Circuit breaker muito agressivo (threshold = 5)
- Não tenta variações de URL (http/https, www/non-www)

### 1.2 Solução Proposta

#### 1.2.1 Site Analyzer (Pré-Scrape)
```python
class SiteAnalyzer:
    """
    Analisa características do site ANTES do scrape completo.
    Tempo alvo: < 3 segundos
    Usa apenas requisições HTTP leves (sem browser).
    """
    
    async def analyze(self, url: str) -> SiteProfile:
        """
        Retorna:
        - tipo_protecao: cloudflare | waf | captcha | none
        - tipo_site: spa | static | hybrid
        - tempo_resposta: latência média
        - melhor_metodo: cffi | curl | cffi_aggressive
        - variacoes_validas: lista de URLs que respondem
        - requer_js: bool (se True, site pode ter conteúdo limitado)
        """
```

#### 1.2.2 Strategy Selector
```python
class ScrapingStrategy(Enum):
    """
    Estratégias de scraping LEVES (sem browser headless).
    Todas as estratégias usam curl_cffi ou system curl para economia de recursos.
    """
    FAST = "fast"              # curl_cffi sem proxy, timeout 10s
    STANDARD = "standard"      # curl_cffi com proxy, timeout 15s
    ROBUST = "robust"          # System curl com retry, timeout 20s
    AGGRESSIVE = "aggressive"  # curl_cffi com múltiplos user-agents e rotação de proxy
    
    # ❌ REMOVIDO: HEADLESS (Playwright) - Alto consumo de memória
    # ❌ REMOVIDO: STEALTH (Undetected Chrome) - Alto consumo de memória

class StrategySelector:
    """
    Seleciona estratégia baseada no SiteProfile.
    Prioriza sempre estratégias leves (curl-based).
    """
    def select(self, profile: SiteProfile) -> List[ScrapingStrategy]:
        # Retorna lista ordenada por prioridade
        # Para sites com Cloudflare: tenta AGGRESSIVE primeiro, depois ROBUST
        # Para sites normais: FAST -> STANDARD -> ROBUST
```

#### 1.2.3 Parallel URL Prober
```python
async def probe_url_variations(base_url: str) -> BestURLResult:
    """
    Testa em paralelo todas as variações de uma URL.
    
    Variações testadas:
    - https://www.domain.com
    - https://domain.com
    - http://www.domain.com
    - http://domain.com
    
    Retorna a primeira que responder com sucesso.
    Timeout por variação: 3s
    """
```

#### 1.2.4 Protection Detector
```python
class ProtectionDetector:
    """
    Detecta tipo de proteção anti-bot rapidamente.
    """
    
    CLOUDFLARE_SIGNATURES = [
        "cf-browser-verification",
        "cf_chl_opt",
        "checking your browser",
        "just a moment...",
        "ray id:",
        "__cf_bm"  # Cookie Cloudflare
    ]
    
    WAF_SIGNATURES = [
        "access denied",
        "403 forbidden",
        "blocked by security",
        "firewall"
    ]
    
    CAPTCHA_SIGNATURES = [
        "recaptcha",
        "hcaptcha",
        "challenge-form",
        "g-recaptcha"
    ]
    
    async def detect(self, response: Response) -> ProtectionType:
        # Analisa headers e conteúdo
        # Retorna: CLOUDFLARE | WAF | CAPTCHA | RATE_LIMIT | NONE
```

### 1.3 Configurações Propostas

```python
SCRAPER_CONFIG_V2 = {
    # Timeouts escalonados por estratégia (todas curl-based, sem browser)
    'fast_timeout': 10,
    'standard_timeout': 15,
    'robust_timeout': 20,
    'aggressive_timeout': 25,  # Para sites com proteção (mais retries)
    
    # Circuit Breaker inteligente
    'circuit_breaker_threshold': 10,  # Aumentado de 5
    'circuit_breaker_exclude_protections': True,  # Não contar Cloudflare
    'circuit_breaker_reset_after': 300,  # Reset após 5 min
    
    # Paralelismo (ajustado para servidor com recursos limitados)
    'max_concurrent_probes': 4,
    'max_concurrent_subpages': 15,  # Reduzido de 20
    'chunk_size': 8,  # Reduzido de 10 para economia de memória
    
    # Proxy
    'proxy_rotation_on_failure': True,
    'max_proxy_retries': 3,
    
    # Adaptativo
    'auto_adjust_timeout': True,
    'learn_from_failures': True,
    
    # User-Agent Rotation (para estratégia AGGRESSIVE)
    'rotate_user_agent': True,
    'user_agent_pool_size': 10
}
```

### 1.4 Fluxo de Scrape Adaptativo

```
┌─────────────────┐
│   URL Entrada   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│   1. PROBE PARALELO (3s max)    │
│   - Testar https/http           │
│   - Testar www/non-www          │
│   - Medir latência              │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│   2. DETECTAR PROTEÇÃO (2s)     │
│   - Verificar Cloudflare        │
│   - Verificar WAF               │
│   - Verificar Captcha           │
└────────────┬────────────────────┘
             │
     ┌───────┴───────┐
     │               │
     ▼               ▼
┌─────────┐   ┌─────────────────┐
│  NONE   │   │ CLOUDFLARE/WAF  │
└────┬────┘   └───────┬─────────┘
     │                │
     ▼                ▼
┌─────────┐   ┌─────────────────┐
│  FAST   │   │   AGGRESSIVE    │
│ STRATEGY│   │   STRATEGY      │
│(curl_cffi)│ │(curl_cffi + UA  │
│          │  │ rotation + proxy)│
└────┬────┘   └───────┬─────────┘
     │                │
     └───────┬────────┘
             │
             ▼
┌─────────────────────────────────┐
│   3. SCRAPE MAIN PAGE           │
│   - Usar estratégia selecionada │
│   - Timeout adaptativo          │
└────────────┬────────────────────┘
             │
     ┌───────┴───────┐
     │               │
     ▼               ▼
┌─────────┐   ┌─────────────────┐
│ SUCESSO │   │     FALHA       │
└────┬────┘   └───────┬─────────┘
     │                │
     │                ▼
     │        ┌─────────────────┐
     │        │ FALLBACK p/     │
     │        │ próxima strategy│
     │        └───────┬─────────┘
     │                │
     └───────┬────────┘
             │
             ▼
┌─────────────────────────────────┐
│   4. SELECIONAR SUBPÁGINAS      │
│   - LLM escolhe top N relevantes│
│   - Máx 30 subpáginas           │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│   5. SCRAPE PARALELO SUBPÁGINAS │
│   - Chunks de 10                │
│   - Mesma estratégia que main   │
│   - Circuit breaker por domínio │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│   6. CONSOLIDAR CONTEÚDO        │
│   - Remover duplicados          │
│   - Ordenar por relevância      │
└─────────────────────────────────┘
```

---

## 📦 Módulo 2: LLM Manager v2.0

### 2.1 Problema Atual
- Apenas 2 provedores configurados (Google Gemini, OpenAI)
- Semáforos com limites muito altos (300/250) não respeitando rate limits reais
- Round-robin simples não considera saúde do provedor
- Timeout fixo de 90s pode ser excessivo para modelos rápidos

### 2.2 Solução Proposta

#### 2.2.1 Adicionar OpenRouter como Fallback
```python
# Novos provedores no config.py
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL: str = "google/gemini-2.0-flash-exp:free"  # Modelo gratuito

# Ordem de prioridade:
# 1. Google Gemini (mais rápido, rate limit generoso)
# 2. OpenAI (confiável, rate limit médio)  
# 3. OpenRouter (fallback, múltiplos modelos)
```

#### 2.2.2 Queue Manager com Rate Limiting Real
```python
class LLMQueueManager:
    """
    Gerencia fila de requisições respeitando rate limits reais.
    """
    
    # Rate limits por provedor (tokens por minuto)
    RATE_LIMITS = {
        "Google Gemini": {"tpm": 4_000_000, "rpm": 1500},
        "OpenAI": {"tpm": 2_000_000, "rpm": 500},
        "OpenRouter": {"tpm": 100_000, "rpm": 100}
    }
    
    def __init__(self):
        self.queues = {name: asyncio.Queue() for name in RATE_LIMITS}
        self.token_buckets = {
            name: TokenBucket(limits["tpm"], limits["rpm"]) 
            for name, limits in RATE_LIMITS.items()
        }
    
    async def enqueue(self, request: LLMRequest) -> LLMResponse:
        """
        Enfileira requisição e aguarda slot disponível.
        Usa token bucket para controle de rate limit.
        """
        
    async def get_best_provider(self, estimated_tokens: int) -> str:
        """
        Retorna provedor com capacidade disponível.
        Considera:
        - Tokens disponíveis no bucket
        - Latência média recente
        - Taxa de sucesso
        """
```

#### 2.2.3 Health Monitor Aprimorado
```python
class LLMHealthMonitor:
    """
    Monitora saúde dos provedores em tempo real.
    """
    
    def __init__(self):
        self.metrics = defaultdict(lambda: {
            "requests_total": 0,
            "requests_success": 0,
            "requests_failed": 0,
            "rate_limits_hit": 0,
            "timeouts": 0,
            "avg_latency_ms": 0,
            "last_success": None,
            "last_failure": None,
            "consecutive_failures": 0,
            "health_score": 100  # 0-100
        })
    
    def update_health_score(self, provider: str):
        """
        Calcula score de saúde (0-100) baseado em:
        - Taxa de sucesso (peso 40%)
        - Latência (peso 30%)
        - Rate limits (peso 20%)
        - Recência de falhas (peso 10%)
        """
    
    def get_healthy_providers(self) -> List[Tuple[str, int]]:
        """
        Retorna provedores ordenados por health_score.
        Exclui provedores com score < 20.
        """
```

#### 2.2.4 Adaptive Timeout
```python
class AdaptiveTimeout:
    """
    Ajusta timeout baseado em histórico de latência.
    """
    
    def __init__(self):
        self.latency_history = defaultdict(lambda: deque(maxlen=100))
    
    def get_timeout(self, provider: str, content_size: int) -> float:
        """
        Calcula timeout ideal baseado em:
        - P95 de latência histórica
        - Tamanho do conteúdo
        - Modelo específico
        
        Fórmula: max(30, p95_latency * 1.5 + (content_size / 10000) * 5)
        """
```

### 2.3 Configurações Propostas

```python
LLM_CONFIG_V2 = {
    # Provedores (ordem de prioridade)
    'providers': [
        {
            'name': 'Google Gemini',
            'api_key_env': 'GOOGLE_API_KEY',
            'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai/',
            'model': 'gemini-2.0-flash',
            'max_concurrent': 50,  # Reduzido de 300
            'rate_limit_rpm': 1500,
            'rate_limit_tpm': 4_000_000,
            'priority': 1
        },
        {
            'name': 'OpenAI',
            'api_key_env': 'OPENAI_API_KEY', 
            'base_url': 'https://api.openai.com/v1',
            'model': 'gpt-4o-mini',
            'max_concurrent': 30,  # Reduzido de 250
            'rate_limit_rpm': 500,
            'rate_limit_tpm': 2_000_000,
            'priority': 2
        },
        {
            'name': 'OpenRouter',
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'model': 'google/gemini-2.0-flash-exp:free',
            'max_concurrent': 10,
            'rate_limit_rpm': 100,
            'rate_limit_tpm': 100_000,
            'priority': 3
        }
    ],
    
    # Retry
    'max_retries_per_provider': 2,
    'max_total_retries': 5,
    'retry_backoff_base': 2,
    'retry_backoff_max': 30,
    
    # Timeout
    'base_timeout': 60,
    'max_timeout': 120,
    'adaptive_timeout': True,
    
    # Chunking
    'max_chunk_tokens': 500_000,  # Reduzido de 800k para margem de segurança
    'group_target_tokens': 15_000,  # Reduzido de 20k
    
    # Health
    'health_check_interval': 10,
    'unhealthy_threshold': 20,
    'recovery_threshold': 50
}
```

### 2.4 Fluxo de Requisição LLM

```
┌─────────────────────────────────┐
│    Conteúdo para Análise        │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│   1. ESTIMAR TOKENS             │
│   - Contar caracteres           │
│   - Aplicar fator PT-BR (3.5)   │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│   2. CHUNKING (se necessário)   │
│   - Dividir por páginas         │
│   - Agrupar pequenas páginas    │
│   - Max 500k tokens/chunk       │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│   3. SELECIONAR PROVEDOR        │
│   - Verificar health_score      │
│   - Verificar rate limit bucket │
│   - Round-robin entre saudáveis │
└────────────┬────────────────────┘
             │
     ┌───────┴───────┐
     │               │
     ▼               ▼
┌─────────┐   ┌─────────────────┐
│DISPONÍVEL│   │ TODOS OCUPADOS  │
└────┬────┘   └───────┬─────────┘
     │                │
     │                ▼
     │        ┌─────────────────┐
     │        │ AGUARDAR FILA   │
     │        │ (max 30s)       │
     │        └───────┬─────────┘
     │                │
     └───────┬────────┘
             │
             ▼
┌─────────────────────────────────┐
│   4. ENVIAR REQUISIÇÃO          │
│   - Timeout adaptativo          │
│   - Registrar métricas          │
└────────────┬────────────────────┘
             │
     ┌───────┴───────┐
     │               │
     ▼               ▼
┌─────────┐   ┌─────────────────┐
│ SUCESSO │   │     FALHA       │
└────┬────┘   └───────┬─────────┘
     │                │
     │        ┌───────┴───────┐
     │        │               │
     │        ▼               ▼
     │   ┌─────────┐   ┌───────────┐
     │   │RATE LIMIT│   │ TIMEOUT/  │
     │   │         │   │  ERROR    │
     │   └────┬────┘   └─────┬─────┘
     │        │              │
     │        ▼              ▼
     │   ┌─────────────────────────┐
     │   │ RETRY COM OUTRO PROVIDER│
     │   │ (até max_total_retries) │
     │   └───────────┬─────────────┘
     │               │
     └───────┬───────┘
             │
             ▼
┌─────────────────────────────────┐
│   5. PROCESSAR RESPOSTA         │
│   - Validar JSON                │
│   - Normalizar campos           │
│   - Construir CompanyProfile    │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│   6. MERGE (se múltiplos chunks)│
│   - Consolidar perfis           │
│   - Remover duplicatas          │
│   - Priorizar dados completos   │
└─────────────────────────────────┘
```

---

## 📦 Módulo 3: Learning Engine (NOVO)

### 3.1 Objetivo
Criar um sistema que aprende com falhas e melhora automaticamente a performance.

### 3.2 Componentes

#### 3.2.1 Failure Tracker
```python
class FailureTracker:
    """
    Registra todas as falhas com contexto completo.
    """
    
    def record_failure(self, failure: FailureRecord):
        """
        Salva em banco de dados:
        - timestamp
        - módulo (scraper/llm/discovery)
        - tipo_erro
        - url/domínio
        - contexto (headers, response, etc)
        - stack_trace
        - configuração_usada
        - tentativas_anteriores
        """
    
    def get_failures_by_domain(self, domain: str) -> List[FailureRecord]:
        """Histórico de falhas de um domínio."""
    
    def get_failure_patterns(self, period: str = "24h") -> Dict[str, int]:
        """Agrupa falhas por tipo no período."""
```

#### 3.2.2 Pattern Analyzer
```python
class PatternAnalyzer:
    """
    Analisa padrões de falha e identifica causas raiz.
    """
    
    def analyze_scraper_failures(self) -> ScraperAnalysis:
        """
        Retorna:
        - sites_com_cloudflare: List[str]
        - sites_com_captcha: List[str]
        - sites_timeout_frequente: List[str]
        - melhor_estrategia_por_site: Dict[str, ScrapingStrategy]
        - recomendacoes: List[str]
        """
    
    def analyze_llm_failures(self) -> LLMAnalysis:
        """
        Retorna:
        - provedor_mais_estavel: str
        - horarios_com_mais_rate_limit: List[int]
        - tamanho_chunk_ideal: int
        - modelo_mais_preciso: str
        - recomendacoes: List[str]
        """
```

#### 3.2.3 Config Optimizer
```python
class ConfigOptimizer:
    """
    Otimiza configurações baseado em análise de falhas.
    """
    
    def suggest_scraper_config(self, analysis: ScraperAnalysis) -> Dict:
        """
        Sugere ajustes de configuração do scraper:
        - timeout ideal por tipo de site
        - threshold do circuit breaker
        - estratégia padrão
        """
    
    def suggest_llm_config(self, analysis: LLMAnalysis) -> Dict:
        """
        Sugere ajustes de configuração do LLM:
        - limites de semáforo por provedor
        - tamanho de chunk
        - timeout por modelo
        """
    
    def apply_suggestions(self, suggestions: Dict, auto_apply: bool = False):
        """
        Aplica sugestões automaticamente ou gera relatório para review.
        """
```

#### 3.2.4 Site Knowledge Base
```python
class SiteKnowledgeBase:
    """
    Base de conhecimento sobre sites específicos.
    """
    
    def add_site_profile(self, profile: SiteKnowledgeProfile):
        """
        Armazena:
        - domínio
        - tipo_protecao
        - melhor_estrategia
        - tempo_medio_resposta
        - ultima_tentativa_sucesso
        - configuracao_especial (se houver)
        """
    
    def get_site_profile(self, domain: str) -> Optional[SiteKnowledgeProfile]:
        """Retorna perfil se existir."""
    
    def get_strategy_for_site(self, domain: str) -> ScrapingStrategy:
        """
        Retorna melhor estratégia baseada em histórico.
        Se não houver histórico, retorna STANDARD.
        """
```

### 3.3 Fluxo de Aprendizado

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CICLO DE APRENDIZADO CONTÍNUO                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────┐                                                         │
│  │  REQUISIÇÃO   │                                                         │
│  │   NORMAL      │                                                         │
│  └───────┬───────┘                                                         │
│          │                                                                  │
│          ▼                                                                  │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                      PROCESSAMENTO                                     │ │
│  │                                                                        │ │
│  │    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐               │ │
│  │    │  Discovery  │──▶│   Scraper   │──▶│     LLM     │               │ │
│  │    └─────────────┘   └─────────────┘   └─────────────┘               │ │
│  │           │                │                  │                       │ │
│  │           └────────────────┴──────────────────┘                       │ │
│  │                            │                                           │ │
│  │                            ▼                                           │ │
│  │                    ┌───────────────┐                                  │ │
│  │                    │   RESULTADO   │                                  │ │
│  │                    └───────┬───────┘                                  │ │
│  │                            │                                           │ │
│  └────────────────────────────┼──────────────────────────────────────────┘ │
│                               │                                             │
│          ┌────────────────────┼────────────────────┐                       │
│          │                    │                    │                       │
│          ▼                    ▼                    ▼                       │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                 │
│   │   SUCESSO   │     │    FALHA    │     │  PARCIAL    │                 │
│   └──────┬──────┘     └──────┬──────┘     └──────┬──────┘                 │
│          │                   │                    │                        │
│          ▼                   ▼                    ▼                        │
│   ┌─────────────────────────────────────────────────────────────────────┐ │
│   │                       FAILURE TRACKER                                │ │
│   │   • Registrar resultado                                              │ │
│   │   • Coletar métricas                                                 │ │
│   │   • Armazenar contexto                                               │ │
│   └─────────────────────────────────────────────────────────────────────┘ │
│                               │                                             │
│                               ▼                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐ │
│   │                      PATTERN ANALYZER                                │ │
│   │   • Executar a cada 100 requisições                                  │ │
│   │   • Identificar padrões de falha                                     │ │
│   │   • Calcular estatísticas                                            │ │
│   └─────────────────────────────────────────────────────────────────────┘ │
│                               │                                             │
│                               ▼                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐ │
│   │                      CONFIG OPTIMIZER                                │ │
│   │   • Gerar sugestões de otimização                                    │ │
│   │   • Validar contra thresholds                                        │ │
│   │   • Aplicar automaticamente (se habilitado)                          │ │
│   └─────────────────────────────────────────────────────────────────────┘ │
│                               │                                             │
│                               ▼                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐ │
│   │                    SITE KNOWLEDGE BASE                               │ │
│   │   • Atualizar perfil do site                                         │ │
│   │   • Armazenar estratégia bem-sucedida                                │ │
│   │   • Marcar sites problemáticos                                       │ │
│   └─────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🧪 Módulo 4: Sistema de Testes Automatizados

### 4.1 Objetivo
Criar testes que validem cada módulo isoladamente e em conjunto, com capacidade de identificar regressões.

### 4.2 Test Suites

#### 4.2.1 Scraper Test Suite (500 sites)

```python
# tests/test_scraper_suite.py

class ScraperTestSuite:
    """
    Suite de testes para o módulo de scraping.
    Deve ser executada semanalmente ou antes de cada deploy.
    """
    
    # Categorias de sites para teste
    TEST_SITES = {
        "static_simple": [
            # 100 sites estáticos simples
        ],
        "static_complex": [
            # 100 sites estáticos com muitas subpáginas
        ],
        "spa_react": [
            # 50 sites React/Next.js
        ],
        "spa_vue": [
            # 50 sites Vue.js
        ],
        "cloudflare_protected": [
            # 50 sites com Cloudflare
        ],
        "waf_protected": [
            # 50 sites com WAF
        ],
        "slow_response": [
            # 50 sites com resposta > 5s
        ],
        "international": [
            # 50 sites internacionais
        ]
    }
    
    async def run_full_suite(self) -> TestReport:
        """
        Executa todos os testes e gera relatório.
        
        Métricas coletadas por site:
        - tempo_total
        - tempo_main_page
        - tempo_subpages
        - chars_extraidos
        - links_encontrados
        - estrategia_usada
        - protecao_detectada
        - sucesso (bool)
        - erro (se houver)
        """
    
    async def test_single_category(self, category: str) -> CategoryReport:
        """Testa apenas uma categoria de sites."""
    
    def compare_with_baseline(self, report: TestReport) -> ComparisonReport:
        """
        Compara resultados com baseline anterior.
        Identifica regressões (> 5% queda na taxa de sucesso).
        """
    
    def generate_recommendations(self, report: TestReport) -> List[str]:
        """
        Gera recomendações baseadas nos resultados:
        - Sites que precisam de estratégia específica
        - Configurações que podem ser otimizadas
        - Bugs identificados
        """
```

#### 4.2.2 LLM Test Suite (300 scrapes)

```python
# tests/test_llm_suite.py

class LLMTestSuite:
    """
    Suite de testes para o módulo de LLM.
    Usa conteúdo pré-scrapado para isolar testes de LLM.
    """
    
    # Amostras de conteúdo para teste (scraped previamente)
    TEST_CONTENT = {
        "small": [
            # 50 conteúdos < 10k tokens
        ],
        "medium": [
            # 100 conteúdos 10k-50k tokens
        ],
        "large": [
            # 100 conteúdos 50k-200k tokens
        ],
        "very_large": [
            # 50 conteúdos > 200k tokens
        ]
    }
    
    async def run_full_suite(self) -> LLMTestReport:
        """
        Executa todos os testes e gera relatório.
        
        Métricas coletadas:
        - provider_usado
        - tempo_total
        - tokens_input
        - tokens_output
        - chunks_processados
        - campos_extraidos
        - qualidade_extracao (score 0-100)
        - rate_limits_encontrados
        - retries_necessarios
        - sucesso (bool)
        - erro (se houver)
        """
    
    async def test_provider_isolation(self, provider: str) -> ProviderReport:
        """
        Testa um provedor específico isoladamente.
        Útil para identificar problemas específicos.
        """
    
    async def test_concurrent_load(self, concurrency: int) -> LoadTestReport:
        """
        Testa comportamento sob carga.
        Simula N requisições simultâneas.
        """
    
    def calculate_extraction_quality(self, profile: CompanyProfile, expected: Dict) -> int:
        """
        Calcula score de qualidade da extração (0-100).
        Compara campos extraídos com ground truth.
        """
```

#### 4.2.3 Integration Test Suite

```python
# tests/test_integration_suite.py

class IntegrationTestSuite:
    """
    Testes de integração end-to-end.
    Simula fluxo completo de análise de empresa.
    """
    
    TEST_COMPANIES = [
        # 100 empresas com ground truth conhecido
        {
            "nome_fantasia": "Empresa X",
            "razao_social": "Empresa X LTDA",
            "cnpj": "12.345.678/0001-90",
            "site_esperado": "https://empresax.com.br",
            "campos_esperados": {
                "identity.company_name": "Empresa X",
                "classification.industry": "Tecnologia",
                # ...
            }
        }
    ]
    
    async def run_full_integration(self) -> IntegrationReport:
        """
        Executa fluxo completo para cada empresa.
        
        Métricas:
        - tempo_total (deve ser < 90s)
        - discovery_sucesso
        - scraper_sucesso
        - llm_sucesso
        - perfil_completo
        - campos_corretos (comparado com ground truth)
        """
```

#### 4.2.4 🏆 STRESS TEST (Critério de Aprovação Final)

```python
# tests/test_stress_500.py

class StressTest500:
    """
    TESTE DEFINITIVO DE APROVAÇÃO DO SISTEMA.
    Processa 500 empresas em paralelo e valida métricas.
    
    Este teste DEVE passar para o sistema ser considerado pronto para produção.
    """
    
    # Lista de 500 empresas brasileiras reais (CNPJs válidos)
    # Fonte: Base de dados de empresas ativas
    TEST_COMPANIES_500 = "tests/data/empresas_500.json"
    
    # Configuração do teste
    CONFIG = {
        "total_empresas": 500,
        "timeout_por_empresa": 90,  # segundos
        "workers_paralelos": 50,    # Requisições simultâneas
        "timeout_global": 3600,     # 1 hora máximo para todo o teste
    }
    
    # Critérios de APROVAÇÃO (todos devem ser atendidos)
    CRITERIOS_APROVACAO = {
        "tempo_medio_max": 90,        # segundos (apenas empresas com site)
        "taxa_sucesso_min": 0.90,     # 90% das empresas com site encontrado
        "completude_perfil_min": 0.85, # 85% dos campos obrigatórios
        "crashes_max": 0,              # Zero crashes
        "memory_leak": False,          # Sem vazamento de memória
    }
    
    async def run_stress_test(self) -> StressTestReport:
        """
        Executa o stress test completo.
        
        Fluxo:
        1. Carrega 500 empresas
        2. Processa em paralelo (50 workers)
        3. Coleta métricas de cada empresa
        4. Separa: com_site vs sem_site
        5. Calcula métricas apenas das com_site
        6. Valida contra critérios de aprovação
        
        Returns:
            StressTestReport com resultado APROVADO/REPROVADO
        """
    
    def calcular_metricas(self, resultados: List[EmpresaResult]) -> Metricas:
        """
        Calcula métricas APENAS das empresas com site encontrado.
        
        Empresas descartadas (NÃO contam):
        - site_nao_encontrado: Discovery não achou site
        - site_fora_do_ar: Site existe mas não responde
        - site_bloqueado: Acesso negado geograficamente
        """
        
        # Filtrar apenas empresas com site encontrado
        com_site = [r for r in resultados if r.site_encontrado and r.site_acessivel]
        
        # Calcular métricas
        tempo_medio = sum(r.tempo_total for r in com_site) / len(com_site)
        taxa_sucesso = sum(1 for r in com_site if r.perfil_gerado) / len(com_site)
        completude_media = sum(r.completude for r in com_site) / len(com_site)
        
        return Metricas(
            total_empresas=len(resultados),
            com_site=len(com_site),
            sem_site=len(resultados) - len(com_site),
            tempo_medio=tempo_medio,
            taxa_sucesso=taxa_sucesso,
            completude_media=completude_media
        )
    
    def calcular_completude(self, perfil: CompanyProfile) -> float:
        """
        Calcula completude do perfil (0.0 a 1.0).
        
        Seções e pesos:
        - Identity (company_name, description): 25%
        - Classification (industry, business_model): 15%
        - Offerings (products OU services ≥3): 25%
        - Contact (email/telefone, website): 20%
        - Reputation (certifications/partnerships/clients): 15%
        """
        score = 0.0
        
        # Identity (25%)
        if perfil.identity.company_name and perfil.identity.description:
            score += 0.25
        
        # Classification (15%)
        if perfil.classification.industry and perfil.classification.business_model:
            score += 0.15
        
        # Offerings (25%)
        produtos = len(perfil.offerings.products) if perfil.offerings.products else 0
        servicos = len(perfil.offerings.services) if perfil.offerings.services else 0
        if produtos >= 3 or servicos >= 3:
            score += 0.25
        
        # Contact (20%)
        tem_contato = (
            (perfil.contact.emails and len(perfil.contact.emails) > 0) or
            (perfil.contact.phones and len(perfil.contact.phones) > 0)
        )
        if tem_contato and perfil.contact.website_url:
            score += 0.20
        
        # Reputation (15%)
        tem_reputacao = (
            (perfil.reputation.certifications and len(perfil.reputation.certifications) > 0) or
            (perfil.reputation.partnerships and len(perfil.reputation.partnerships) > 0) or
            (perfil.reputation.client_list and len(perfil.reputation.client_list) > 0)
        )
        if tem_reputacao:
            score += 0.15
        
        return score
    
    def validar_aprovacao(self, metricas: Metricas) -> Tuple[bool, List[str]]:
        """
        Valida se o teste passou nos critérios de aprovação.
        
        Returns:
            (aprovado: bool, motivos_reprovacao: List[str])
        """
        motivos = []
        
        if metricas.tempo_medio > self.CRITERIOS_APROVACAO["tempo_medio_max"]:
            motivos.append(f"Tempo médio {metricas.tempo_medio:.1f}s > {self.CRITERIOS_APROVACAO['tempo_medio_max']}s")
        
        if metricas.taxa_sucesso < self.CRITERIOS_APROVACAO["taxa_sucesso_min"]:
            motivos.append(f"Taxa sucesso {metricas.taxa_sucesso:.1%} < {self.CRITERIOS_APROVACAO['taxa_sucesso_min']:.0%}")
        
        if metricas.completude_media < self.CRITERIOS_APROVACAO["completude_perfil_min"]:
            motivos.append(f"Completude {metricas.completude_media:.1%} < {self.CRITERIOS_APROVACAO['completude_perfil_min']:.0%}")
        
        return (len(motivos) == 0, motivos)
    
    def gerar_relatorio(self, metricas: Metricas, aprovado: bool, motivos: List[str]) -> str:
        """
        Gera relatório detalhado do stress test.
        """
        return f"""
        ╔══════════════════════════════════════════════════════════════════════════════╗
        ║                    RELATÓRIO DO STRESS TEST - 500 EMPRESAS                   ║
        ╠══════════════════════════════════════════════════════════════════════════════╣
        ║                                                                              ║
        ║  RESULTADO: {'✅ APROVADO' if aprovado else '❌ REPROVADO'}                   ║
        ║                                                                              ║
        ║  📊 MÉTRICAS:                                                                ║
        ║  ────────────                                                                ║
        ║  Total de empresas:     {metricas.total_empresas}                            ║
        ║  Com site encontrado:   {metricas.com_site} ({metricas.com_site/metricas.total_empresas:.1%})║
        ║  Sem site (descartadas):{metricas.sem_site}                                  ║
        ║                                                                              ║
        ║  Tempo médio:           {metricas.tempo_medio:.1f}s (meta: ≤90s)             ║
        ║  Taxa de sucesso:       {metricas.taxa_sucesso:.1%} (meta: ≥90%)             ║
        ║  Completude média:      {metricas.completude_media:.1%} (meta: ≥85%)         ║
        ║                                                                              ║
        {'║  ❌ MOTIVOS DA REPROVAÇÃO:' if motivos else ''}
        {''.join(f'║     • {m}' for m in motivos)}
        ║                                                                              ║
        ╚══════════════════════════════════════════════════════════════════════════════╝
        """
```

### 4.3 Estrutura de Relatórios

```
tests/
├── reports/
│   ├── scraper/
│   │   ├── 2025-12-05_full_suite.json
│   │   ├── 2025-12-05_cloudflare_only.json
│   │   └── baseline.json
│   ├── llm/
│   │   ├── 2025-12-05_full_suite.json
│   │   ├── 2025-12-05_google_gemini.json
│   │   └── baseline.json
│   └── integration/
│       ├── 2025-12-05_full_integration.json
│       └── sla_compliance.json
├── fixtures/
│   ├── scraped_content/
│   │   ├── small/
│   │   ├── medium/
│   │   └── large/
│   └── expected_profiles/
│       └── company_x.json
└── data/
    ├── test_sites.json
    └── test_companies.json
```

---

## 📋 Plano de Implementação

### Fase 1: Fundação (Semana 1-2)

| Task | Prioridade | Estimativa | Responsável |
|------|------------|------------|-------------|
| Implementar SiteAnalyzer | Alta | 3 dias | - |
| Implementar ProtectionDetector | Alta | 2 dias | - |
| Adicionar OpenRouter ao LLM_BALANCER | Alta | 1 dia | - |
| Implementar FailureTracker | Média | 2 dias | - |
| Criar estrutura de testes | Média | 2 dias | - |

### Fase 2: Scraper Adaptativo (Semana 3-4)

| Task | Prioridade | Estimativa | Responsável |
|------|------------|------------|-------------|
| Implementar StrategySelector | Alta | 2 dias | - |
| Implementar Parallel URL Prober | Alta | 1 dia | - |
| Refatorar scrape_url para usar estratégias | Alta | 3 dias | - |
| Implementar fallback em cascata | Alta | 2 dias | - |
| Criar Scraper Test Suite | Média | 2 dias | - |

### Fase 3: LLM Manager v2.0 (Semana 5-6)

| Task | Prioridade | Estimativa | Responsável |
|------|------------|------------|-------------|
| Implementar LLMQueueManager | Alta | 3 dias | - |
| Implementar AdaptiveTimeout | Média | 1 dia | - |
| Refatorar LLMHealthMonitor | Alta | 2 dias | - |
| Ajustar semáforos e rate limits | Alta | 1 dia | - |
| Criar LLM Test Suite | Média | 2 dias | - |

### Fase 4: Learning Engine (Semana 7-8)

| Task | Prioridade | Estimativa | Responsável |
|------|------------|------------|-------------|
| Implementar PatternAnalyzer | Média | 3 dias | - |
| Implementar ConfigOptimizer | Média | 2 dias | - |
| Implementar SiteKnowledgeBase | Média | 2 dias | - |
| Integrar Learning Engine ao fluxo | Média | 2 dias | - |
| Criar Integration Test Suite | Média | 1 dia | - |

### Fase 5: Validação e Ajustes (Semana 9-10)

| Task | Prioridade | Estimativa | Responsável |
|------|------------|------------|-------------|
| Preparar dataset 500 empresas para stress test | Alta | 1 dia | - |
| Executar stress test inicial | Alta | 1 dia | - |
| Analisar falhas e gargalos | Alta | 2 dias | - |
| Ajustar configurações baseado em resultados | Alta | 2 dias | - |
| Corrigir bugs identificados | Alta | 2 dias | - |
| Re-executar stress test até aprovação | Alta | 2 dias | - |

### Fase 6: Aprovação Final (Semana 11)

| Task | Prioridade | Estimativa | Responsável |
|------|------------|------------|-------------|
| **Executar STRESS TEST 500** | **CRÍTICA** | 1 dia | - |
| Validar métricas contra critérios | Alta | 0.5 dia | - |
| Gerar relatório de aprovação | Alta | 0.5 dia | - |
| Preparar deploy para produção | Alta | 1 dia | - |
| Monitoramento pós-deploy | Alta | 2 dias | - |

**⚠️ GATE DE APROVAÇÃO:** O sistema SÓ será liberado para produção após passar no Stress Test 500.

---

## 📊 Métricas de Sucesso

### 🏆 KPIs do Stress Test (Critério de Aprovação)

| Métrica | Meta | Descrição |
|---------|------|-----------|
| **Empresas processadas** | 500 | Em paralelo, simultaneamente |
| **Tempo médio** | ≤ 90s | Apenas empresas com site encontrado |
| **Taxa de sucesso** | ≥ 90% | Das empresas com site encontrado |
| **Completude do perfil** | ≥ 85% | Campos obrigatórios preenchidos |
| **Estabilidade** | 100% | Zero crashes durante execução |

### 📋 Definição de Completude do Perfil

Um perfil é considerado **COMPLETO** quando possui:

| Seção | Campos Obrigatórios | Peso |
|-------|---------------------|------|
| **Identity** | company_name, description | 25% |
| **Classification** | industry, business_model | 15% |
| **Offerings** | products OU services (≥3 itens) | 25% |
| **Contact** | ≥1 email OU telefone, website_url | 20% |
| **Reputation** | ≥1 de: certifications, partnerships, client_list | 15% |

**Fórmula de Completude:**
```
completude = (seções_completas / 5) * 100
perfil_aprovado = completude >= 85%
```

### KPIs Secundários (Monitoramento)

| Métrica | Atual | Meta | Método de Medição |
|---------|-------|------|-------------------|
| Taxa de Sucesso Geral | ~65% | ≥90% | (sucessos / tentativas) * 100 |
| Tempo Médio de Processamento | ~45s | ≤90s | Média de tempo por empresa |
| Taxa de Timeout | 19.2% | ≤5% | Timeouts / Total |
| Taxa de Rate Limit | ~15% | ≤3% | Rate limits / Total LLM calls |
| Taxa de Discovery | ~80% | ≥85% | Sites encontrados / Total empresas |

### KPIs por Módulo

#### Scraper
| Métrica | Atual | Meta |
|---------|-------|------|
| Sites com Cloudflare | 25% falha | ≤15% falha |
| Sites estáticos | 5% falha | ≤2% falha |
| Tempo Main Page | ~5s | ≤5s |
| Tempo Subpages (30 páginas) | ~20s | ≤25s |
| Conteúdo extraído | ~50k chars | ≥30k chars |

#### LLM
| Métrica | Atual | Meta |
|---------|-------|------|
| Taxa de Sucesso Google | ~85% | ≥95% |
| Taxa de Sucesso OpenAI | ~80% | ≥90% |
| Latência Média por Chunk | ~15s | ≤20s |
| Retries Necessários | ~30% | ≤15% |

### ⚠️ Regras de Qualidade (INVIOLÁVEIS)

Para manter a qualidade dos perfis, as seguintes otimizações são **PROIBIDAS**:

| Otimização Proibida | Motivo |
|---------------------|--------|
| ❌ Reduzir número de subpáginas | Perde informações de produtos/serviços |
| ❌ Truncar conteúdo antes do LLM | Perde contexto e detalhes |
| ❌ Simplificar prompts do LLM | Reduz precisão da extração |
| ❌ Pular seções do perfil | Perfil incompleto |
| ❌ Usar modelos LLM menores/piores | Menor qualidade de extração |
| ❌ Reduzir timeout de scraping | Perde sites lentos mas válidos |

**Otimizações PERMITIDAS:**
- ✅ Paralelismo (mais requisições simultâneas)
- ✅ Caching de resultados
- ✅ Melhor seleção de links (priorização inteligente)
- ✅ Retry automático com fallback
- ✅ Load balancing entre provedores LLM

---

## 🔐 Considerações de Segurança

1. **API Keys**: Nunca commitar em código. Usar variáveis de ambiente.
2. **Rate Limiting**: Implementar rate limiting na API para evitar abuse.
3. **Proxy**: Rotacionar IPs para evitar bloqueios.
4. **Dados Sensíveis**: Não logar conteúdo de sites ou respostas de LLM em produção.
5. **HTTPS**: Sempre usar HTTPS para conexões externas.

---

## 📝 Changelog

### v2.0 (Proposta)
- [ ] Scraper Adaptativo com estratégias leves (curl-based)
- [ ] LLM Manager com queue e rate limiting real
- [ ] Learning Engine para auto-otimização
- [ ] Test Suites automatizadas
- [ ] **NOVO**: Stress Test 500 empresas como critério de aprovação
- [ ] **NOVO**: Métricas de completude de perfil bem definidas
- [ ] **NOVO**: Regras de qualidade invioláveis
- [ ] **NOVO**: Arquitetura Multi-Agente Sequencial (inspirado Fire-Enrich)
- [ ] **NOVO**: OpenRouter como provider de LLM com fallback automático
- [ ] **NOVO**: Sistema de semáforos granulares por recurso
- [ ] **NOVO**: Validação de schema Pydantic por agente
- [ ] **NOVO**: Tracking de rate limits via headers HTTP
- [ ] **REMOVIDO**: Módulo de extração de documentos (PDFs, DOCs) - simplificação do fluxo
- [ ] **REMOVIDO**: Playwright/Headless browsers - alto consumo de memória

### v1.0 (Atual)
- [x] Scraper básico com curl_cffi
- [x] LLM com round-robin simples
- [x] Circuit breaker básico
- [x] Proxy rotation
- [x] Extração de PDFs (será removido na v2.0)

---

## 📚 Referências

- [curl_cffi Documentation](https://github.com/yifeikong/curl_cffi)
- [OpenRouter API](https://openrouter.ai/docs)
- [Google Gemini API](https://ai.google.dev/docs)
- [Cloudflare Bot Management](https://developers.cloudflare.com/bots/)

---

## 🔬 Análise de Projetos Similares (Pesquisa GitHub/Web)

### Projetos Analisados

| Projeto | Stars | Descrição | Relevância |
|---------|-------|-----------|------------|
| **ScrapeGraphAI** | 21.9k ⭐ | Scraper baseado em LLM com pipelines em grafos | Alta |
| **Fire-Enrich** | 1k ⭐ | Enriquecimento de dados de empresas multi-agente | Muito Alta |
| **Firecrawl** | 50k+ ⭐ | API de scraping para IA | Alta |
| **BrightData Company Enrichment** | 3 ⭐ | Enriquecimento de dados com Bright Data API | Média |

### 🔥 Insights do Fire-Enrich (Firecrawl)

O projeto **fire-enrich** é o mais similar ao nosso caso de uso. Sua arquitetura de **agentes sequenciais** é muito relevante:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                 ARQUITETURA MULTI-AGENTE (Fire-Enrich)                      │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  Fase 1: Discovery Agent ──▶ Encontra empresa e website base               │
│              │                                                             │
│              ▼                                                             │
│  Fase 2: Company Profile Agent ──▶ Industry, business model                │
│              │              (usa contexto da Fase 1)                       │
│              ▼                                                             │
│  Fase 3: Financial Intel Agent ──▶ Funding, investors                      │
│              │              (usa contexto das Fases 1-2)                   │
│              ▼                                                             │
│  Fase 4: Tech Stack Agent ──▶ Tecnologias utilizadas                       │
│              │              (usa contexto das Fases 1-3)                   │
│              ▼                                                             │
│  Fase 5: General Agent ──▶ Campos customizados                             │
│              │              (usa todo o contexto)                          │
│              ▼                                                             │
│  Síntese Final: GPT-4o ──▶ Combina todos os dados, resolve conflitos       │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

**Lições Aplicáveis:**
1. ✅ **Execução sequencial de agentes** - Cada fase constrói contexto para a próxima
2. ✅ **Buscas paralelas DENTRO de cada fase** - 3+ buscas simultâneas por agente
3. ✅ **Schemas type-safe com Zod** - Validação de dados em cada etapa
4. ✅ **Síntese final com LLM** - Resolução de conflitos entre fontes

### 🕷️ Insights do ScrapeGraphAI (21.9k stars)

```python
# Arquitetura de Pipelines do ScrapeGraphAI
Pipelines disponíveis:
├── SmartScraperGraph      # Scraper de página única
├── SearchGraph            # Multi-página via busca
├── SmartScraperMultiGraph # Múltiplas páginas em paralelo
├── ScriptCreatorGraph     # Gera scripts de extração
└── SpeechGraph            # Extrai e gera áudio

# Configuração de timeout (implementado recentemente)
graph_config = {
    "llm": {...},
    "verbose": True,
    "headless": False,
    "node_config": {
        "timeout": 30  # Timeout configurável por nó!
    }
}
```

**Lições Aplicáveis:**
1. ✅ **Timeout por operação** - Não apenas timeout global
2. ✅ **Suporte multi-LLM** - Ollama, OpenAI, Groq, Azure, Gemini
3. ✅ **Pipeline graph-based** - Permite reuso e composição
4. ✅ **Telemetria built-in** - Métricas de uso anônimas

### 🌐 Insights do OpenRouter (API de LLM)

OpenRouter oferece funcionalidades que devemos considerar:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    OPENROUTER - FUNCIONALIDADES CHAVE                       │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  🔄 Model Fallbacks (Automático)                                           │
│  ────────────────────────────────                                          │
│  • Qualquer erro pode triggar fallback: rate limit, context length,        │
│    moderation, timeout                                                     │
│  • Configuração simples via header: X-Fallback-Models                      │
│                                                                            │
│  📊 Rate Limits                                                            │
│  ────────────────                                                          │
│  • Free tier: 20 req/min, 50-1000 req/day                                  │
│  • Paid tier: Significativamente maior                                     │
│  • Headers de resposta incluem: X-RateLimit-Remaining, X-RateLimit-Reset   │
│                                                                            │
│  🧭 Smart Routing                                                          │
│  ──────────────                                                            │
│  • Rota automática para provider mais rápido/barato                        │
│  • Fallback automático quando providers ficam down                         │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

**Integração Proposta:**
```python
# OpenRouter como provider adicional
OPENROUTER_CONFIG = {
    "api_key": "sk-or-v1-xxx",
    "base_url": "https://openrouter.ai/api/v1",
    "models": [
        "google/gemini-2.0-flash-exp:free",  # Fallback gratuito
        "anthropic/claude-3.5-sonnet",       # Alta qualidade
        "openai/gpt-4o-mini",                # Rápido e barato
    ],
    "fallback_enabled": True,
    "headers": {
        "HTTP-Referer": "https://nossa-api.com",  # Obrigatório
        "X-Title": "Company Profile Builder"
    }
}
```

### 🔧 Melhores Práticas de Asyncio para Alto Volume

```python
# Padrão recomendado para 500 requisições paralelas
import asyncio
from asyncio import Semaphore

class HighThroughputScraper:
    def __init__(self):
        # Semáforos por tipo de recurso
        self.scrape_semaphore = Semaphore(50)   # 50 scrapes simultâneos
        self.llm_semaphore = Semaphore(10)       # 10 LLM calls simultâneos
        self.proxy_semaphore = Semaphore(100)    # 100 conexões proxy
        
        # Rate limiting com token bucket
        self.tokens = asyncio.Queue(maxsize=100)
        
    async def process_with_rate_limit(self, func, *args):
        """Controle de taxa com semáforo + token bucket"""
        await self.tokens.get()  # Aguarda token disponível
        async with self.scrape_semaphore:
            try:
                return await asyncio.wait_for(func(*args), timeout=30)
            finally:
                # Repõe token após cooldown
                asyncio.create_task(self._replenish_token(0.1))
    
    async def _replenish_token(self, delay):
        await asyncio.sleep(delay)
        await self.tokens.put(True)
```

**Padrões Identificados:**
1. ✅ **Semaphores por recurso** - Limites diferentes para scraping vs LLM
2. ✅ **Token bucket** - Rate limiting suave, não hard limit
3. ✅ **Timeout por operação** - `asyncio.wait_for()` em cada chamada
4. ✅ **Replenish assíncrono** - Não bloqueia enquanto repõe tokens

---

## 🚀 Melhorias Incorporadas ao PRD (baseado na pesquisa)

### 1. Arquitetura Multi-Agente Sequencial (inspirado Fire-Enrich)

**Proposta:** Reorganizar o fluxo de LLM em agentes especializados:

```
┌────────────────────────────────────────────────────────────────────────────┐
│              FLUXO DE AGENTES PARA CONSTRUÇÃO DE PERFIL                     │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  🔍 Agente 1: Discovery                                                    │
│     Input: Nome empresa + CNPJ + CNAE                                      │
│     Output: URL do site oficial, nome confirmado                           │
│     Buscas paralelas: 3 queries diferentes no Google                       │
│                                                                            │
│  📄 Agente 2: Content Scraper                                              │
│     Input: URL do site + contexto do Agente 1                              │
│     Output: Conteúdo HTML de até 30 páginas                                │
│     Buscas paralelas: Main page + subpáginas priorizadas                   │
│                                                                            │
│  🏢 Agente 3: Identity & Classification                                    │
│     Input: Conteúdo scraped + contexto anterior                            │
│     Output: company_name, description, industry, business_model            │
│     Schema: IdentitySchema (validado com Pydantic)                         │
│                                                                            │
│  📦 Agente 4: Products & Services                                          │
│     Input: Conteúdo + Identity (para contexto)                             │
│     Output: products[], services[], key_features[]                         │
│     Schema: OfferingsSchema                                                │
│                                                                            │
│  📞 Agente 5: Contact & Reputation                                         │
│     Input: Conteúdo + tudo anterior                                        │
│     Output: emails[], phones[], certifications[], partnerships[]           │
│     Schema: ContactSchema + ReputationSchema                               │
│                                                                            │
│  🔄 Agente 6: Synthesizer                                                  │
│     Input: Outputs de todos os agentes                                     │
│     Output: CompanyProfile completo e validado                             │
│     Função: Resolver conflitos, preencher gaps, validar consistência       │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 2. OpenRouter como Provider de Fallback

**Implementação Proposta:**
```python
LLM_PROVIDERS = {
    "primary": {
        "google": {"model": "gemini-2.0-flash-exp", "priority": 1},
        "openai": {"model": "gpt-4o-mini", "priority": 2},
    },
    "fallback": {
        "openrouter": {
            "models": [
                "google/gemini-2.0-flash-exp:free",
                "anthropic/claude-3.5-haiku",
                "openai/gpt-4o-mini",
            ],
            "auto_fallback": True,
            "priority": 3
        }
    }
}
```

### 3. Sistema de Semáforos Granulares

**Proposta:**
```python
SEMAPHORE_CONFIG = {
    # Scraping
    "main_page_scrape": 100,      # 100 main pages em paralelo
    "subpage_scrape": 200,        # 200 subpáginas em paralelo
    "proxy_connections": 150,     # 150 conexões proxy simultâneas
    
    # LLM
    "llm_google": 15,             # 15 chamadas Google simultâneas
    "llm_openai": 10,             # 10 chamadas OpenAI simultâneas
    "llm_openrouter": 20,         # 20 chamadas OpenRouter simultâneas
    "llm_global": 40,             # Total máximo de chamadas LLM
    
    # Discovery
    "serper_search": 20,          # 20 buscas Serper simultâneas
}
```

### 4. Validação de Schema por Agente (inspirado ScrapeGraphAI)

**Proposta:**
```python
from pydantic import BaseModel, validator

class IdentitySchema(BaseModel):
    company_name: str
    description: str | None
    industry: str | None
    business_model: str | None
    
    @validator('company_name')
    def name_not_empty(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('Nome da empresa inválido')
        return v.strip()

class OfferingsSchema(BaseModel):
    products: list[str] = []
    services: list[str] = []
    key_features: list[str] = []
    
    @validator('products', 'services')
    def deduplicate(cls, v):
        return list(set(v))

# Validação em cada etapa do pipeline
def validate_agent_output(agent_name: str, data: dict) -> bool:
    schemas = {
        "identity": IdentitySchema,
        "offerings": OfferingsSchema,
        # ...
    }
    try:
        schemas[agent_name](**data)
        return True
    except Exception as e:
        logger.warning(f"Validação falhou para {agent_name}: {e}")
        return False
```

### 5. Métricas de Headers de Rate Limit (inspirado OpenRouter)

**Proposta:**
```python
async def track_rate_limits(response: httpx.Response, provider: str):
    """Extrai e rastreia headers de rate limit"""
    headers = response.headers
    
    metrics = {
        "remaining": headers.get("X-RateLimit-Remaining"),
        "limit": headers.get("X-RateLimit-Limit"),
        "reset": headers.get("X-RateLimit-Reset"),
        "provider": provider
    }
    
    # Se estiver chegando no limite, reduzir velocidade
    remaining = int(metrics.get("remaining") or 100)
    if remaining < 10:
        logger.warning(f"⚠️ {provider}: Apenas {remaining} requests restantes")
        await asyncio.sleep(1)  # Cooldown preventivo
    
    return metrics
```

---

## 📋 Checklist de Implementação (baseado na pesquisa)

### Fase 1: Fundação Revisada
- [ ] Implementar sistema de semáforos granulares
- [ ] Adicionar OpenRouter como provider de fallback
- [ ] Implementar tracking de rate limits via headers
- [ ] Criar schemas Pydantic para cada tipo de dados

### Fase 2: Arquitetura Multi-Agente
- [ ] Refatorar LLM para arquitetura de agentes sequenciais
- [ ] Implementar validação de schema por agente
- [ ] Adicionar contexto compartilhado entre agentes
- [ ] Criar Synthesizer para consolidação final

### Fase 3: Otimização de Performance
- [ ] Token bucket para rate limiting suave
- [ ] Timeout por operação (não apenas global)
- [ ] Buscas paralelas dentro de cada fase
- [ ] Cooldown preventivo baseado em headers

---

*Documento gerado em 2025-12-05. Última atualização: 2025-12-05 (Análise de projetos similares: ScrapeGraphAI, Fire-Enrich, OpenRouter + Arquitetura Multi-Agente)*

