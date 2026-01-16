"""
Constantes globais do sistema B2B Flash Profiler.

Este arquivo centraliza constantes que são usadas em múltiplos módulos.
Constantes específicas de cada módulo devem ficar em seus próprios arquivos.
"""

# Versão do sistema
VERSION = "2.0.0"

from app.configs.config_loader import load_config

_CORE_CFG = load_config("core_constants.json")
_UA_CFG = load_config("user_agents.json")

# User-Agents para rotação
USER_AGENTS = _UA_CFG.get("user_agents", [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
])

# Assinaturas de proteção (usadas em múltiplos módulos)
CLOUDFLARE_SIGNATURES = [
    "just a moment...",
    "cf-browser-verification",
    "challenge-running",
    "cf_chl_opt",
    "checking your browser",
    "ray id:",
    "cloudflare"
]

WAF_SIGNATURES = [
    "access denied",
    "403 forbidden",
    "blocked by security",
    "firewall",
    "security check"
]

CAPTCHA_SIGNATURES = [
    "recaptcha",
    "hcaptcha",
    "challenge-form",
    "g-recaptcha",
    "captcha"
]

# Domínios de diretórios empresariais (para exclusão no discovery)
DIRECTORY_DOMAINS = [
    "cnpj.biz",
    "econodata.com.br",
    "telelistas.net",
    "apontador.com.br",
    "serasaexperian.com.br",
    "olx.com.br",
    "mercadolivre.com.br",
    "shopee.com.br",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
]

# Extensões de documentos
DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}

# Extensões de arquivos excluídos
EXCLUDED_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.tiff',
    '.zip', '.rar', '.tar', '.gz', '.xls', '.xlsx', '.csv', '.txt', '.xml', '.json', '.js', '.css',
    '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.woff', '.woff2', '.ttf', '.eot', '.otf'
}

