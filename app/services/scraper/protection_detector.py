"""
Detector de proteções de sites (Cloudflare, WAF, Captcha, etc).
Analisa headers e corpo da resposta para identificar proteções.
"""

import logging
from typing import Optional, Dict
from .models import ProtectionType
from app.configs.config_loader import load_config

logger = logging.getLogger(__name__)


class ProtectionDetector:
    """Detecta tipo de proteção baseado em resposta HTTP."""
    
    _SIG = load_config("scraper/protection_signatures.json")
    
    CLOUDFLARE_BODY_SIGNATURES = _SIG.get("cloudflare_body_signatures", [])
    CLOUDFLARE_HEADERS = _SIG.get("cloudflare_headers", [])
    WAF_BODY_SIGNATURES = _SIG.get("waf_body_signatures", [])
    WAF_HEADERS = _SIG.get("waf_headers", [])
    CAPTCHA_SIGNATURES = _SIG.get("captcha_signatures", [])
    RATE_LIMIT_SIGNATURES = _SIG.get("rate_limit_signatures", [])
    BOT_DETECTION_SIGNATURES = _SIG.get("bot_detection_signatures", [])
    
    def detect(
        self, 
        response_headers: Optional[Dict] = None, 
        response_body: Optional[str] = None,
        status_code: int = 200
    ) -> ProtectionType:
        """
        Detecta tipo de proteção baseado na resposta HTTP.
        
        Args:
            response_headers: Headers da resposta
            response_body: Corpo da resposta (HTML)
            status_code: Código de status HTTP
        
        Returns:
            Tipo de proteção detectada
        """
        headers = response_headers or {}
        body = (response_body or "").lower()
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        # Verificar por código de status
        if status_code == 429:
            logger.debug("Rate limit detectado via status 429")
            return ProtectionType.RATE_LIMIT
        
        if status_code == 403:
            # 403 pode ser WAF ou rate limit - verificar corpo
            if self._check_rate_limit(body, headers_lower):
                return ProtectionType.RATE_LIMIT
            if self._check_waf(body, headers_lower):
                return ProtectionType.WAF
        
        # Verificar Cloudflare (mais específico primeiro)
        if self._check_cloudflare(body, headers_lower):
            logger.debug("Proteção Cloudflare detectada")
            return ProtectionType.CLOUDFLARE
        
        # Verificar Captcha
        if self._check_captcha(body):
            logger.debug("Captcha detectado")
            return ProtectionType.CAPTCHA
        
        # Verificar WAF
        if self._check_waf(body, headers_lower):
            logger.debug("WAF detectado")
            return ProtectionType.WAF
        
        # Verificar Rate Limit
        if self._check_rate_limit(body, headers_lower):
            logger.debug("Rate limit detectado")
            return ProtectionType.RATE_LIMIT
        
        # Verificar detecção de bot
        if self._check_bot_detection(body):
            logger.debug("Detecção de bot detectada")
            return ProtectionType.BOT_DETECTION
        
        return ProtectionType.NONE
    
    def _check_cloudflare(self, body: str, headers: Dict) -> bool:
        """Verifica se é proteção Cloudflare."""
        # Verificar headers específicos do Cloudflare
        for cf_header in self.CLOUDFLARE_HEADERS:
            if cf_header in headers:
                # Só considera como proteção se também tiver challenge no body
                if any(sig in body for sig in self.CLOUDFLARE_BODY_SIGNATURES[:5]):
                    return True
        
        # Verificar assinaturas no corpo
        has_cloudflare = "cloudflare" in body
        has_challenge = any(sig in body for sig in self.CLOUDFLARE_BODY_SIGNATURES[:5])
        
        return has_cloudflare and has_challenge
    
    def _check_waf(self, body: str, headers: Dict) -> bool:
        """Verifica se é WAF genérico."""
        # Verificar headers de WAF
        for key in headers:
            for waf_header in self.WAF_HEADERS:
                if waf_header in key.lower():
                    return True
        
        # Verificar assinaturas no corpo
        match_count = sum(1 for sig in self.WAF_BODY_SIGNATURES if sig in body)
        return match_count >= 2  # Precisa de 2+ assinaturas para confirmar
    
    def _check_captcha(self, body: str) -> bool:
        """Verifica se há captcha na página."""
        return any(sig in body for sig in self.CAPTCHA_SIGNATURES)
    
    def _check_rate_limit(self, body: str, headers: Dict) -> bool:
        """Verifica se há rate limiting."""
        # Verificar header Retry-After
        if "retry-after" in headers:
            return True
        
        # Verificar assinaturas no corpo
        return any(sig in body for sig in self.RATE_LIMIT_SIGNATURES)
    
    def _check_bot_detection(self, body: str) -> bool:
        """Verifica se há detecção de bot."""
        return any(sig in body for sig in self.BOT_DETECTION_SIGNATURES)
    
    def is_blocking_protection(self, protection: ProtectionType) -> bool:
        """Verifica se a proteção bloqueia o scraping."""
        blocking = {
            ProtectionType.CLOUDFLARE,
            ProtectionType.CAPTCHA,
            ProtectionType.BOT_DETECTION
        }
        return protection in blocking
    
    def get_retry_recommendation(self, protection: ProtectionType) -> dict:
        """Retorna recomendações para contornar a proteção."""
        recommendations = {
            ProtectionType.NONE: {
                "can_retry": True,
                "delay_seconds": 0,
                "change_strategy": False
            },
            ProtectionType.CLOUDFLARE: {
                "can_retry": True,
                "delay_seconds": 5,
                "change_strategy": True,
                "recommended_strategy": "aggressive",
                "tip": "Use rotação de proxy e headers"
            },
            ProtectionType.WAF: {
                "can_retry": True,
                "delay_seconds": 3,
                "change_strategy": True,
                "recommended_strategy": "robust"
            },
            ProtectionType.CAPTCHA: {
                "can_retry": False,
                "delay_seconds": 0,
                "change_strategy": False,
                "tip": "Site requer interação humana"
            },
            ProtectionType.RATE_LIMIT: {
                "can_retry": True,
                "delay_seconds": 60,
                "change_strategy": False,
                "tip": "Aguardar cooldown"
            },
            ProtectionType.BOT_DETECTION: {
                "can_retry": True,
                "delay_seconds": 10,
                "change_strategy": True,
                "recommended_strategy": "aggressive"
            }
        }
        return recommendations.get(protection, recommendations[ProtectionType.NONE])


# Instância singleton para uso fácil
protection_detector = ProtectionDetector()

