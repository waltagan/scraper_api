"""
Constantes e configuracoes do modulo de scraping.
Pipeline simplificado: GET unico (probe+main) -> subpages (max 5).
"""

import logging
import random
from typing import Optional
from urllib.parse import urlparse

from app.configs.config_loader import load_config

logger = logging.getLogger(__name__)

_cfg = load_config("scraper/scraper_config.json") or {}

REQUEST_TIMEOUT: int = _cfg.get("request_timeout", 15)
SUBPAGE_TIMEOUT: int = _cfg.get("subpage_timeout", 12)
RETRY_TIMEOUT: int = _cfg.get("retry_timeout", 30)
MAX_RETRIES: int = _cfg.get("max_retries", 1)
MAX_SUBPAGES: int = _cfg.get("max_subpages", 10)
PER_DOMAIN_CONCURRENT: int = _cfg.get("per_domain_concurrent", 3)
STAGGER_DELAY: float = _cfg.get("stagger_delay", 0.3)
CIRCUIT_BREAKER_THRESHOLD: int = _cfg.get("circuit_breaker_threshold", 2)
FLUSH_SIZE: int = _cfg.get("flush_size", 500)
MIN_CONTENT_LENGTH: int = _cfg.get("min_content_length", 100)
MAX_CONCURRENT_711: int = _cfg.get("max_concurrent_711", 800)
MAX_CONCURRENT_DECODO: int = _cfg.get("max_concurrent_decodo", 1500)
MAX_CONCURRENT_EVOMI: int = _cfg.get("max_concurrent_evomi", 1200)
MAX_CONCURRENT_PER_PROXY: int = _cfg.get("max_concurrent_per_proxy", 4)
MAX_CONCURRENT_REQUESTS: int = MAX_CONCURRENT_711 + MAX_CONCURRENT_DECODO + MAX_CONCURRENT_EVOMI
CHUNK_SIZE: int = _cfg.get("chunk_size", 5000)
BATCH_MAX_WORKERS: int = _cfg.get("batch_max_workers", 120)
PROBE_ONLY_MODE: bool = bool(_cfg.get("probe_only_mode", False))

logger.info(
    f"[ScraperConfig] timeout={REQUEST_TIMEOUT}s sub_timeout={SUBPAGE_TIMEOUT}s retry_timeout={RETRY_TIMEOUT}s retries={MAX_RETRIES} "
    f"subpages={MAX_SUBPAGES} domain_conc={PER_DOMAIN_CONCURRENT} "
    f"stagger={STAGGER_DELAY}s cb_threshold={CIRCUIT_BREAKER_THRESHOLD} "
    f"flush={FLUSH_SIZE} chunk={CHUNK_SIZE} "
    f"batch_workers={BATCH_MAX_WORKERS} "
    f"probe_only={PROBE_ONLY_MODE} "
    f"concurrent: 711={MAX_CONCURRENT_711} decodo={MAX_CONCURRENT_DECODO} evomi={MAX_CONCURRENT_EVOMI} per_proxy={MAX_CONCURRENT_PER_PROXY} "
    f"total={MAX_CONCURRENT_REQUESTS}"
)

# ---------------------------------------------------------------------------
# Fingerprint Rotation
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


def build_headers(referer: Optional[str] = None) -> tuple:
    """Headers dinamicos com User-Agent variados."""
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
    "404 not found", "page not found", "pagina nao encontrada",
    "erro 404", "nao encontramos a pagina", "pagina inexistente",
    "ops! pagina nao encontrada", "error 404", "file not found",
]
