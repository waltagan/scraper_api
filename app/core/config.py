import os
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
    
    # 4. Vast.ai (Provider Primário - SGLang)
    # IMPORTANTE: Sistema usa SGLang via Vast.ai
    # Variáveis legadas mantidas por compatibilidade (deprecated)
    RUNPOD_API_KEY: str = os.getenv("RUNPOD_API_KEY", "")  # Deprecated: usar MODEL_KEY
    RUNPOD_MODEL: str = os.getenv("RUNPOD_MODEL", "")  # Deprecated: usar MODEL_NAME
    RUNPOD_BASE_URL: str = os.getenv("RUNPOD_BASE_URL", "")  # Deprecated: usar URL_MODEL
    
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
    
    # Vast.ai Configuration (Provider Primário - SGLang)
    # IMPORTANTE: Sistema usa SGLang via Vast.ai
    # 
    # CONFIGURAÇÃO (Railway/Environment Variables):
    # - URL_MODEL: URL da instância SGLang na Vast.ai (deve terminar com /v1)
    #   Exemplo: "https://xxxxx.vast.ai:8000/v1" ou "http://80.188.223.202:10154/v1"
    # - MODEL_KEY: Token Bearer para autenticação (usado em Authorization header)
    #   Obrigatório para Vast.ai
    # - MODEL_NAME: Nome do modelo carregado no SGLang
    #   Exemplo: "Qwen/Qwen3-8B" ou "Qwen/Qwen2.5-3B-Instruct"
    #
    # Variáveis legadas (deprecated, mantidas por compatibilidade):
    # - VLLM_BASE_URL, VLLM_API_KEY, VLLM_MODEL (fallback se novas variáveis não existirem)
    
    # Nova configuração (preferencial)
    _url_model_raw = os.getenv("URL_MODEL", "")
    _model_key_raw = os.getenv("MODEL_KEY", "")
    _model_name_raw = os.getenv("MODEL_NAME", "")
    
    # Fallback para variáveis legadas (compatibilidade)
    if not _url_model_raw:
        _url_model_raw = os.getenv("VLLM_BASE_URL", "")
    if not _model_key_raw:
        _model_key_raw = os.getenv("VLLM_API_KEY", "")
    if not _model_name_raw:
        _model_name_raw = os.getenv("VLLM_MODEL", "")
    
    # Garantir que a URL termine com /v1 para compatibilidade OpenAI API
    URL_MODEL: str = (
        _url_model_raw if _url_model_raw and _url_model_raw.endswith("/v1")
        else (_url_model_raw + "v1" if _url_model_raw and _url_model_raw.endswith("/")
              else (_url_model_raw + "/v1" if _url_model_raw else ""))
    )
    
    # MODEL_KEY: Token Bearer para Authorization header (obrigatório para Vast.ai)
    MODEL_KEY: str = _model_key_raw if _model_key_raw not in ("", "NONE", "none", None) else ""
    
    # MODEL_NAME: Nome do modelo
    MODEL_NAME: str = _model_name_raw if _model_name_raw else "Qwen/Qwen3-8B"
    
    # Variáveis legadas (mantidas por compatibilidade, apontam para novas)
    VLLM_BASE_URL: str = URL_MODEL
    VLLM_API_KEY: str = MODEL_KEY
    VLLM_MODEL: str = MODEL_NAME

settings = Settings()
