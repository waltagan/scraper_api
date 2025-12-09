"""
Constantes e configurações do módulo de scraping.
"""

import asyncio

# Headers que imitam um navegador real para evitar bloqueios WAF
DEFAULT_HEADERS = {
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

# Perfil R7 (SpeedCombo2) - Fast Track Otimizado para 1000 Proxies
# Com 1000 IPs, podemos aumentar significativamente a concorrência
# mantendo < 1 req/proxy simultâneo (menos detecção)
FAST_TRACK_CONFIG = {
    'site_semaphore_limit': 200,          # Era 60 → 200 (3.3x) - 1000 proxies suportam isso
    'circuit_breaker_threshold': 5,
    'page_timeout': 35000,
    'md_threshold': 0.3,
    'min_word_threshold': 2,
    'chunk_size': 25,                     # Era 15 → 25 (mais paralelo)
    'chunk_semaphore_limit': 200,         # Era 60 → 200 (3.3x)
    'session_timeout': 8,
    'slow_probe_threshold_ms': 5000,
    'slow_main_threshold_ms': 8000,
    'slow_subpage_cap': 5,                # Era 2 → 5 (mais subpáginas mesmo lento)
    'slow_per_request_timeout': 8,
    'fast_per_request_timeout': 12,
    'fast_chunk_internal_limit': 25,      # Era 10 → 25 (2.5x)
    'slow_chunk_internal_limit': 5,       # Era 2 → 5 (2.5x)
    'slow_chunk_semaphore_limit': 10,     # Era 4 → 10 (2.5x)
    'proxy_max_latency_ms': 300,          # Era 250 → 300 (mais tolerante com muitos proxies)
    'proxy_max_failures': 3,              # Era 2 → 3 (mais tolerante)
    'per_domain_limit': 8,                # Era 4 → 8 (mais paralelo por domínio)
    # Batch scraping settings - otimizado para 1000 proxies
    'batch_size': 15,                     # Era 6 → 15 (2.5x mais paralelo)
    'batch_min_delay': 1.0,               # Era 2.0 → 1.0 (mais rápido)
    'batch_max_delay': 3.0,               # Era 5.0 → 3.0 (mais rápido)
    'intra_batch_delay': 0.2              # Era 0.5 → 0.2 (mais rápido)
}

# Configuração padrão = Fast Track
DEFAULT_CONFIG = FAST_TRACK_CONFIG.copy()

# Perfil Robusto - Retry Track Otimizado para 1000 Proxies
# Com muitos proxies, podemos ser mais agressivos mesmo no retry
RETRY_TRACK_CONFIG = {
    'site_semaphore_limit': 25,           # Era 5 → 25 (5x) - proxies abundantes
    'circuit_breaker_threshold': 10,
    'page_timeout': 120000,
    'md_threshold': 0.6,
    'min_word_threshold': 4,
    'chunk_size': 15,                     # Era 5 → 15 (3x)
    'chunk_semaphore_limit': 25,          # Era 5 → 25 (5x)
    'session_timeout': 30,
    'slow_probe_threshold_ms': 15000,
    'slow_main_threshold_ms': 20000,
    'slow_subpage_cap': 20,               # Era 10 → 20 (mais subpáginas)
    'slow_per_request_timeout': 20,
    'fast_per_request_timeout': 20,
    'fast_chunk_internal_limit': 12,      # Era 4 → 12 (3x)
    'slow_chunk_internal_limit': 6,       # Era 2 → 6 (3x)
    'slow_chunk_semaphore_limit': 8,      # Era 2 → 8 (4x)
    'proxy_max_latency_ms': 500,          # Era 400 → 500 (mais tolerante)
    'proxy_max_failures': 5,
    'per_domain_limit': 3                 # Era 1 → 3 (mais paralelo)
}

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
