"""
Constantes e configurações do módulo de scraping.
Calibrado com dados empíricos do benchmark 711Proxy (proxy_benchmark_findings.md).
"""

import logging
import random
from urllib.parse import urlparse

from app.configs.config_loader import load_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração carregada do JSON (com fallback hardcoded)
# ---------------------------------------------------------------------------
_cfg = load_config("scraper/scraper_config.json") or {}

REQUEST_TIMEOUT: int = _cfg.get("request_timeout", 12)
PROBE_TIMEOUT: int = _cfg.get("probe_timeout", 12)
MAX_RETRIES: int = _cfg.get("max_retries", 1)
RETRY_DELAY: float = _cfg.get("retry_delay", 0)
MAX_SUBPAGES: int = _cfg.get("max_subpages", 5)
PER_DOMAIN_CONCURRENT: int = _cfg.get("per_domain_concurrent", 5)
WORKERS_PER_INSTANCE: int = _cfg.get("workers_per_instance", 200)
NUM_INSTANCES: int = _cfg.get("num_instances", 3)
FLUSH_SIZE: int = _cfg.get("flush_size", 1000)
MIN_CONTENT_LENGTH: int = _cfg.get("min_content_length", 100)

logger.info(
    f"[ScraperConfig] timeout={REQUEST_TIMEOUT}s retries={MAX_RETRIES} "
    f"subpages={MAX_SUBPAGES} domain_conc={PER_DOMAIN_CONCURRENT} "
    f"workers={WORKERS_PER_INSTANCE} instances={NUM_INSTANCES}"
)

# ---------------------------------------------------------------------------
# Fingerprint Rotation — perfis de browser para anti-detecção
# ---------------------------------------------------------------------------
BROWSER_PROFILES = [
    {
        "impersonate": "chrome131",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    },
    {
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    },
    {
        "impersonate": "chrome131",
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    },
    {
        "impersonate": "safari17_0",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    },
    {
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    },
]

ACCEPT_LANGUAGES = [
    "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "pt-BR,pt;q=0.9,en;q=0.8",
    "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
    "pt-BR,pt;q=0.9",
]


def get_random_profile() -> dict:
    return random.choice(BROWSER_PROFILES)


def get_random_impersonate() -> str:
    return random.choice(BROWSER_PROFILES)["impersonate"]


def build_headers(referer: str | None = None) -> tuple:
    """
    Constrói headers dinâmicos com User-Agent variados.
    Accept header NÃO inclui imagens — apenas text/html.
    """
    profile = get_random_profile()
    headers = {
        "User-Agent": profile["user_agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if not referer else "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    if referer:
        headers["Referer"] = referer
    else:
        headers["Referer"] = "https://www.google.com/"
    return headers, profile["impersonate"]


def smart_referer(subpage_url: str) -> str:
    """Gera um referer realista: a raiz do domínio da subpage."""
    try:
        parsed = urlparse(subpage_url)
        return f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        return "https://www.google.com/"


# ---------------------------------------------------------------------------
# Constantes de filtragem de links
# ---------------------------------------------------------------------------
DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}

EXCLUDED_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.tiff',
    '.zip', '.rar', '.tar', '.gz', '.xls', '.xlsx', '.csv', '.txt', '.xml', '.json', '.js', '.css',
    '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
}

ASSET_DIRECTORIES = ['/wp-content/uploads/', '/assets/', '/images/', '/img/', '/static/', '/media/']

HIGH_PRIORITY_KEYWORDS = [
    "quem-somos", "sobre", "institucional",
    "portfolio", "produto", "servico", "solucoes", "atuacao", "tecnologia",
    "catalogo", "catalogo-digital", "catalogo-online", "produtos", "servicos",
    "clientes", "cases", "projetos", "obras", "certificacoes", "premios", "parceiros",
    "equipe", "time", "lideranca", "contato", "fale-conosco", "unidades",
]

LOW_PRIORITY_KEYWORDS = [
    "login", "signin", "cart", "policy", "blog", "news", "politica-privacidade", "termos",
]

CLOUDFLARE_SIGNATURES = [
    "just a moment...",
    "cf-browser-verification",
    "challenge-running",
    "cf_chl_opt",
    "checking your browser",
    "ray id:",
    "cloudflare",
]

ERROR_404_KEYWORDS = [
    "404 not found", "page not found", "página não encontrada",
    "erro 404", "não encontramos a página", "página inexistente",
    "ops! página não encontrada", "error 404", "file not found",
]
