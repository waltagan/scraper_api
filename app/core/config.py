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
    
    # 4. RunPod (Provider Primário - Mistral 3 8B)
    RUNPOD_API_KEY: str = os.getenv("RUNPOD_API_KEY", "sk-ABCDEFGHIJKLMNOPQRSTUVWZ")
    RUNPOD_MODEL: str = os.getenv("RUNPOD_MODEL", "mistralai/Ministral-3-8B-Instruct-2512")
    RUNPOD_BASE_URL: str = os.getenv("RUNPOD_BASE_URL", "https://h00gtsw9cqma00-8000.proxy.runpod.net/v1")
    
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
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:UQIXJbRUopTkZjjRbZZwORImhfpipQDg@trolley.proxy.rlwy.net:32994/railway"
    )
    
    # Phoenix Tracing (Observabilidade)
    PHOENIX_COLLECTOR_URL: str = os.getenv(
        "PHOENIX_COLLECTOR_URL",
        "https://arize-phoenix-buscafornecedor.up.railway.app"
    )
    
    # vLLM RunPod Configuration
    VLLM_BASE_URL: str = os.getenv(
        "VLLM_BASE_URL",
        "https://5u888x525vvzvs-8000.proxy.runpod.net/v1"
    )
    VLLM_API_KEY: str = os.getenv("VLLM_API_KEY", "buscafornecedor")
    VLLM_MODEL: str = os.getenv(
        "VLLM_MODEL",
        "mistralai/Ministral-3-3B-Instruct-2512"
    )

settings = Settings()
