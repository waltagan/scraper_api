import os
from urllib.parse import urlparse, parse_qs, urlunparse
from dotenv import load_dotenv

# Carregar variáveis do arquivo .env
load_dotenv()

class Settings:
    XAI_API_KEY: str = os.getenv("XAI_API_KEY", "")
    
    # LLM Settings
    # 1. Primary: Google Native
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_MODEL: str = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
    GOOGLE_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # 2. Secondary: xAI Native
    XAI_API_KEY: str = os.getenv("XAI_API_KEY", "")
    XAI_MODEL: str = os.getenv("XAI_MODEL", "grok-4-1-fast-non-reasoning")
    XAI_BASE_URL: str = "https://api.x.ai/v1"

    # 3. Tertiary: OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4.1-nano")
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    
    # 4. SGLang (Provider Primário - suporta RunPod, Vast.ai, ou qualquer host)
    # IMPORTANTE: Sistema usa APENAS SGLang (não vLLM)
    # Variáveis VLLM_* mantidas por compatibilidade, mas apontam para SGLang
    # Funciona com qualquer instância SGLang compatível com OpenAI API (/v1/*)
    RUNPOD_API_KEY: str = os.getenv("RUNPOD_API_KEY", "")  # Deprecated: usar VLLM_API_KEY
    RUNPOD_MODEL: str = os.getenv("RUNPOD_MODEL", "mistralai/Ministral-3-8B-Instruct-2512")
    RUNPOD_BASE_URL: str = os.getenv("RUNPOD_BASE_URL", "")  # Deprecated: usar VLLM_BASE_URL
    
    # 5. OpenRouter (3 modelos para maior capacidade - Fallback)
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-lite-001")
    OPENROUTER_MODEL_2: str = os.getenv("OPENROUTER_MODEL_2", "google/gemini-2.5-flash-lite")
    OPENROUTER_MODEL_3: str = os.getenv("LLM_MODEL3", "openai/gpt-4.1-nano")  # Terceiro modelo
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    
    # Timeout específico para seleção de links (LLM) - agora preferir config em app/configs/llm_agents.json (link_selector)
    LLM_LINK_SELECTION_TIMEOUT: float = float(os.getenv("LLM_LINK_SELECTION_TIMEOUT", "30.0"))
    
    # Logic to select provider (Priority: Google > xAI > OpenAI)
    if GOOGLE_API_KEY:
        LLM_API_KEY: str = GOOGLE_API_KEY
        LLM_BASE_URL: str = GOOGLE_BASE_URL
        LLM_MODEL: str = GOOGLE_MODEL
    elif XAI_API_KEY:
        LLM_API_KEY: str = XAI_API_KEY
        LLM_BASE_URL: str = XAI_BASE_URL
        LLM_MODEL: str = XAI_MODEL
    else:
        LLM_API_KEY: str = OPENAI_API_KEY
        LLM_BASE_URL: str = OPENAI_BASE_URL
        LLM_MODEL: str = OPENAI_MODEL
    
    # Security
    API_ACCESS_TOKEN: str = os.getenv("API_ACCESS_TOKEN", "my-secret-token-dev")
    
    # Discovery (Serper API)
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")

    WEBSHARE_PROXY_LIST_URL: str = os.getenv("WEBSHARE_PROXY_LIST_URL", "")

    # Database (PostgreSQL Railway)
    # IMPORTANTE: Configure DATABASE_URL como variável de ambiente no Railway
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    if not DATABASE_URL:
        raise ValueError(
            "DATABASE_URL não configurada. Configure como variável de ambiente no Railway."
        )
    
    # Phoenix Tracing (Observabilidade)
    PHOENIX_COLLECTOR_URL: str = os.getenv(
        "PHOENIX_COLLECTOR_URL",
        "https://arize-phoenix-buscafornecedor.up.railway.app"
    )
    
    # SGLang Configuration (Provider Primário)
    # IMPORTANTE: Sistema usa SGLang (não vLLM)
    # Funciona com qualquer instância SGLang: RunPod, Vast.ai, ou self-hosted
    # Variáveis mantêm nome VLLM_* por compatibilidade com código legado
    # 
    # CONFIGURAÇÃO (Railway/Environment Variables):
    # - VLLM_BASE_URL: URL da instância SGLang (com ou sem /v1, pode conter ?token=XXX)
    #   Exemplos: 
    #     - Vast.ai: "https://xxxxx.vast.ai:8000"
    #     - RunPod: "https://xxxxx.proxy.runpod.net"
    #     - Cloudflare: "https://xxxxx.trycloudflare.com/docs?token=XXX"
    #     - Self-hosted: "http://localhost:8000"
    # - VLLM_API_KEY: Token para autenticação (usado como query parameter ?token=XXX)
    #   Se vazio/None/"NONE", tenta extrair da URL ou usa "dummy"
    # - VLLM_MODEL: Modelo carregado no SGLang (ex: "Qwen/Qwen2.5-3B-Instruct")
    _vllm_url_raw = os.getenv("VLLM_BASE_URL", "https://7bwtva7ris0ehj-8000.proxy.runpod.net")
    
    # Extrair token da URL se existir (ex: ?token=XXX)
    parsed_url = urlparse(_vllm_url_raw)
    query_params = parse_qs(parsed_url.query)
    token_from_url = query_params.get("token", [None])[0]
    
    # Remover token da URL base (limpar query string)
    # Também remover /docs se existir (ex: Cloudflare tunnel)
    clean_path = parsed_url.path
    if clean_path.endswith("/docs"):
        clean_path = clean_path[:-5]  # Remove "/docs"
    elif clean_path.endswith("/docs/"):
        clean_path = clean_path[:-6]  # Remove "/docs/"
    
    clean_url = urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        clean_path,
        parsed_url.params,
        "",  # Query string vazia
        parsed_url.fragment
    ))
    
    # Garantir que a URL termine com /v1 para compatibilidade OpenAI API
    VLLM_BASE_URL: str = (
        clean_url if clean_url.endswith("/v1")
        else (clean_url + "v1" if clean_url.endswith("/")
              else clean_url + "/v1")
    )
    
    # VLLM_API_KEY: Prioridade: token da URL > VLLM_API_KEY env > "dummy"
    _vllm_key_raw = os.getenv("VLLM_API_KEY", "NONE")
    if token_from_url:
        # Token encontrado na URL, usar ele
        VLLM_API_KEY: str = token_from_url
    elif _vllm_key_raw not in ("", "NONE", "none", None):
        # Token fornecido via env var
        VLLM_API_KEY: str = _vllm_key_raw
    else:
        # Sem token, usar "dummy" (não será usado, mas mantém compatibilidade)
        VLLM_API_KEY: str = "dummy"
    VLLM_MODEL: str = os.getenv(
        "VLLM_MODEL",
        "Qwen/Qwen2.5-3B-Instruct"
    )

settings = Settings()
