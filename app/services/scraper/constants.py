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

# Perfil R7 (SpeedCombo2) - Fast Track Otimizado
FAST_TRACK_CONFIG = {
    'site_semaphore_limit': 60,
    'circuit_breaker_threshold': 5,
    'page_timeout': 35000,
    'md_threshold': 0.3,         # Reduzido para aceitar conteúdo mais simples
    'min_word_threshold': 2,     # Reduzido para aceitar páginas com menos texto
    'chunk_size': 15,
    'chunk_semaphore_limit': 60,
    'session_timeout': 8,        # Reduzido para falhar rápido na conexão
    'slow_probe_threshold_ms': 5000,
    'slow_main_threshold_ms': 8000,
    'slow_subpage_cap': 2,       # Cap agressivo se detectado lento no fast track
    'slow_per_request_timeout': 8,
    'fast_per_request_timeout': 12,
    'fast_chunk_internal_limit': 10,
    'slow_chunk_internal_limit': 2,
    'slow_chunk_semaphore_limit': 4,
    'proxy_max_latency_ms': 250,
    'proxy_max_failures': 2,
    'per_domain_limit': 4
}

# Configuração padrão = Fast Track
DEFAULT_CONFIG = FAST_TRACK_CONFIG.copy()

# Perfil Robusto - Retry Track
RETRY_TRACK_CONFIG = {
    'site_semaphore_limit': 5,
    'circuit_breaker_threshold': 10,
    'page_timeout': 120000,
    'md_threshold': 0.6,
    'min_word_threshold': 4,
    'chunk_size': 5,
    'chunk_semaphore_limit': 5,
    'session_timeout': 30,
    'slow_probe_threshold_ms': 15000,
    'slow_main_threshold_ms': 20000,
    'slow_subpage_cap': 10,      # Mais permissivo no retry track
    'slow_per_request_timeout': 20,
    'fast_per_request_timeout': 20,
    'fast_chunk_internal_limit': 4,
    'slow_chunk_internal_limit': 2,
    'slow_chunk_semaphore_limit': 2,
    'proxy_max_latency_ms': 400,
    'proxy_max_failures': 5,
    'per_domain_limit': 1
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
