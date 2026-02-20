"""
Constantes e configurações do módulo de scraping.
"""

import asyncio
import logging

from app.services.concurrency_manager.config_loader import get_section as get_config
from app.configs.config_loader import load_config

logger = logging.getLogger(__name__)

# Headers que imitam um navegador real para evitar bloqueios WAF (externalizados)
_HEADERS_CFG = load_config("scraper/headers.json").get("default_headers", {})
DEFAULT_HEADERS = _HEADERS_CFG or {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0"
}

_fast_track_from_json = get_config("scraper/scraper_fast_track", {})
if _fast_track_from_json:
    logger.info(
        f"[ScraperConfig] ✅ FAST_TRACK carregado do JSON: "
        f"intra_batch_delay={_fast_track_from_json.get('intra_batch_delay')}, "
        f"batch_size={_fast_track_from_json.get('batch_size')}, "
        f"per_domain_limit={_fast_track_from_json.get('per_domain_limit')}, "
        f"batch_min_delay={_fast_track_from_json.get('batch_min_delay')}, "
        f"batch_max_delay={_fast_track_from_json.get('batch_max_delay')}"
    )
else:
    logger.warning(
        "[ScraperConfig] ⚠️ FAST_TRACK JSON não encontrado! "
        "Usando fallback hardcoded (intra_batch_delay=0.9, batch_size=30). "
        "Verifique se app/configs/scraper/scraper_fast_track.json existe."
    )

FAST_TRACK_CONFIG = _fast_track_from_json or {
    'site_semaphore_limit': 15000,
    'circuit_breaker_threshold': 12,
    'page_timeout': 15000,
    'md_threshold': 0.3,
    'min_word_threshold': 5,
    'chunk_size': 50,
    'chunk_semaphore_limit': 2000,
    'session_timeout': 10,
    'slow_probe_threshold_ms': 5000,
    'slow_main_threshold_ms': 20000,
    'slow_subpage_cap': 15,
    'slow_per_request_timeout': 15,
    'fast_per_request_timeout': 10,
    'fast_chunk_internal_limit': 50,
    'slow_chunk_internal_limit': 10,
    'slow_chunk_semaphore_limit': 100,
    'proxy_max_latency_ms': 800,
    'proxy_max_failures': 5,
    'per_domain_limit': 25,
    'batch_size': 50,
    'batch_min_delay': 0.05,
    'batch_max_delay': 0.15,
    'intra_batch_delay': 0.02
}

# Configuração padrão = Fast Track
DEFAULT_CONFIG = FAST_TRACK_CONFIG.copy()

# Perfil Robusto - Retry Track apontando para configs centralizadas
_retry_track_from_json = get_config("scraper/scraper_retry_track", {})
if _retry_track_from_json:
    logger.info(f"[ScraperConfig] ✅ RETRY_TRACK carregado do JSON")
else:
    logger.warning("[ScraperConfig] ⚠️ RETRY_TRACK JSON não encontrado, usando fallback hardcoded")

RETRY_TRACK_CONFIG = _retry_track_from_json or {
    'site_semaphore_limit': 500,
    'circuit_breaker_threshold': 8,
    'page_timeout': 20000,
    'md_threshold': 0.4,
    'min_word_threshold': 4,
    'chunk_size': 15,
    'chunk_semaphore_limit': 100,
    'session_timeout': 30,
    'slow_probe_threshold_ms': 15000,
    'slow_main_threshold_ms': 20000,
    'slow_subpage_cap': 8,
    'slow_per_request_timeout': 20,
    'fast_per_request_timeout': 25,
    'fast_chunk_internal_limit': 20,
    'slow_chunk_internal_limit': 8,
    'slow_chunk_semaphore_limit': 40,
    'proxy_max_latency_ms': 400,
    'proxy_max_failures': 4,
    'per_domain_limit': 10,
    'batch_size': 15,
    'batch_min_delay': 0.5,
    'batch_max_delay': 3.0,
    'intra_batch_delay': 0.2
}

# Override opcional via configs externos (compatibilidade)
_RETRY_OVERRIDE = get_config("scraper/scraper_retry_track_override", {})
if _RETRY_OVERRIDE:
    RETRY_TRACK_CONFIG = _RETRY_OVERRIDE

# Extensões de documentos (para identificar, não processar)
DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}

# Extensões excluídas (não são páginas HTML)
EXCLUDED_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.tiff',
    '.zip', '.rar', '.tar', '.gz', '.xls', '.xlsx', '.csv', '.txt', '.xml', '.json', '.js', '.css',
    '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.woff', '.woff2', '.ttf', '.eot', '.otf'
}

# Diretórios de assets (geralmente contêm arquivos estáticos, não páginas)
ASSET_DIRECTORIES = ['/wp-content/uploads/', '/assets/', '/images/', '/img/', '/static/', '/media/']

# Keywords de alta prioridade para seleção de links
HIGH_PRIORITY_KEYWORDS = [
    "quem-somos", "sobre", "institucional",
    "portfolio", "produto", "servico", "solucoes", "atuacao", "tecnologia",
    "catalogo", "catalogo-digital", "catalogo-online", "produtos", "servicos",
    "clientes", "cases", "projetos", "obras", "certificacoes", "premios", "parceiros",
    "equipe", "time", "lideranca", "contato", "fale-conosco", "unidades"
]

# Keywords de baixa prioridade para seleção de links
LOW_PRIORITY_KEYWORDS = ["login", "signin", "cart", "policy", "blog", "news", "politica-privacidade", "termos"]

# Assinaturas de Cloudflare challenge
CLOUDFLARE_SIGNATURES = [
    "just a moment...",
    "cf-browser-verification",
    "challenge-running",
    "cf_chl_opt",
    "checking your browser",
    "ray id:",
    "cloudflare"
]

# Assinaturas de páginas de erro 404
ERROR_404_KEYWORDS = [
    "404 not found", "page not found", "página não encontrada", 
    "erro 404", "não encontramos a página", "página inexistente",
    "ops! página não encontrada", "error 404", "file not found"
]


class ScraperConfig:
    """Gerenciador de configuração do scraper."""
    
    def __init__(self):
        self._config = DEFAULT_CONFIG.copy()
        self._site_semaphore = asyncio.Semaphore(self._config['site_semaphore_limit'])
    
    @property
    def site_semaphore_limit(self) -> int:
        return self._config.get('site_semaphore_limit', 60)
    
    @property
    def circuit_breaker_threshold(self) -> int:
        return self._config.get('circuit_breaker_threshold', 5)
    
    @property
    def session_timeout(self) -> int:
        return self._config.get('session_timeout', 15)
    
    @property
    def chunk_size(self) -> int:
        return self._config.get('chunk_size', 10)
    
    @property
    def chunk_semaphore_limit(self) -> int:
        return self._config.get('chunk_semaphore_limit', 60)
    
    @property
    def slow_probe_threshold_ms(self) -> int:
        return self._config.get('slow_probe_threshold_ms', 5000)
    
    @property
    def slow_main_threshold_ms(self) -> int:
        return self._config.get('slow_main_threshold_ms', 8000)
    
    @property
    def slow_subpage_cap(self) -> int:
        return self._config.get('slow_subpage_cap', 2)
    
    @property
    def slow_per_request_timeout(self) -> int:
        return self._config.get('slow_per_request_timeout', 8)
    
    @property
    def fast_per_request_timeout(self) -> int:
        return self._config.get('fast_per_request_timeout', 12)
    
    @property
    def fast_chunk_internal_limit(self) -> int:
        return self._config.get('fast_chunk_internal_limit', 10)
    
    @property
    def slow_chunk_internal_limit(self) -> int:
        return self._config.get('slow_chunk_internal_limit', 2)
    
    @property
    def slow_chunk_semaphore_limit(self) -> int:
        return self._config.get('slow_chunk_semaphore_limit', 4)
    
    @property
    def proxy_max_latency_ms(self) -> int:
        return self._config.get('proxy_max_latency_ms', 250)
        
    @property
    def proxy_max_failures(self) -> int:
        return self._config.get('proxy_max_failures', 2)
        
    @property
    def per_domain_limit(self) -> int:
        return self._config.get('per_domain_limit', 4)
    
    @property
    def site_semaphore(self) -> asyncio.Semaphore:
        return self._site_semaphore
    
    @property
    def md_threshold(self) -> float:
        return self._config.get('md_threshold', 0.6)
        
    @property
    def min_word_threshold(self) -> int:
        return self._config.get('min_word_threshold', 4)
    
    @property
    def batch_size(self) -> int:
        return self._config.get('batch_size', 4)
    
    @property
    def batch_min_delay(self) -> float:
        return self._config.get('batch_min_delay', 3.0)
    
    @property
    def batch_max_delay(self) -> float:
        return self._config.get('batch_max_delay', 7.0)
    
    @property
    def intra_batch_delay(self) -> float:
        return self._config.get('intra_batch_delay', 0.5)
    
    def update(self, **kwargs):
        """Atualiza configurações dinamicamente."""
        for key, value in kwargs.items():
            if key in self._config:
                self._config[key] = value
        
        # Recriar semáforo se limite mudar
        if 'site_semaphore_limit' in kwargs:
            self._site_semaphore = asyncio.Semaphore(kwargs['site_semaphore_limit'])


# Instância global de configuração
scraper_config = ScraperConfig()
