"""
Adaptive Config Manager - Aplica aprendizados automaticamente.
Ajusta configurações globais baseado em padrões de falha.
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from .failure_tracker import failure_tracker, FailureModule, FailureType
from .pattern_analyzer import pattern_analyzer
from .config_optimizer import config_optimizer

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveState:
    """Estado adaptativo do sistema."""
    # Estratégia padrão para sites novos
    default_strategy: str = "standard"
    
    # Configurações do scraper
    scraper_timeout: int = 15
    scraper_chunk_size: int = 20
    circuit_breaker_threshold: int = 5
    
    # Configurações do LLM
    llm_max_concurrent: int = 300
    llm_timeout: int = 240
    llm_chunk_tokens: int = 500000
    
    # Estatísticas de aprendizado
    total_sites_processed: int = 0
    cloudflare_rate: float = 0.0
    timeout_rate: float = 0.0
    last_optimization: str = ""
    optimizations_applied: int = 0


class AdaptiveConfigManager:
    """
    Gerenciador de configuração adaptativa.
    
    Analisa padrões de falha e ajusta configurações automaticamente
    para melhorar performance em sites futuros.
    """
    
    # Thresholds para adaptação
    CLOUDFLARE_THRESHOLD = 30  # Se > 30% são CF, usar estratégia mais agressiva
    TIMEOUT_THRESHOLD = 20     # Se > 20% são timeout, aumentar timeout
    RATE_LIMIT_THRESHOLD = 25  # Se > 25% são rate limit, reduzir concorrência
    
    def __init__(self):
        self.state = AdaptiveState()
        self._load_initial_state()
    
    def _load_initial_state(self):
        """Carrega estado inicial baseado em dados históricos."""
        try:
            summary = failure_tracker.get_summary()
            patterns = summary.get("last_24h", {})
            
            scraper_patterns = patterns.get("scraper", {})
            total_scraper = sum(scraper_patterns.values()) if scraper_patterns else 0
            
            if total_scraper > 10:  # Mínimo de dados para análise
                self._analyze_and_adapt(scraper_patterns, total_scraper)
                logger.info(f"AdaptiveConfig: Estado inicial carregado com {total_scraper} falhas analisadas")
        except Exception as e:
            logger.warning(f"AdaptiveConfig: Erro ao carregar estado inicial: {e}")
    
    def _analyze_and_adapt(self, patterns: Dict[str, int], total: int):
        """Analisa padrões e adapta configurações."""
        if total == 0:
            return
        
        # Calcular taxas
        cf_count = patterns.get("cloudflare", 0) + patterns.get("waf", 0) + patterns.get("captcha", 0)
        timeout_count = patterns.get("timeout", 0)
        
        self.state.cloudflare_rate = (cf_count / total) * 100
        self.state.timeout_rate = (timeout_count / total) * 100
        
        # Adaptar estratégia padrão
        if self.state.cloudflare_rate > self.CLOUDFLARE_THRESHOLD:
            self.state.default_strategy = "robust"
            logger.info(f"🔄 Estratégia padrão alterada para 'robust' (CF rate: {self.state.cloudflare_rate:.1f}%)")
        elif self.state.cloudflare_rate > 50:
            self.state.default_strategy = "aggressive"
            logger.info(f"🔄 Estratégia padrão alterada para 'aggressive' (CF rate: {self.state.cloudflare_rate:.1f}%)")
        
        # Adaptar timeout
        if self.state.timeout_rate > self.TIMEOUT_THRESHOLD:
            new_timeout = min(int(self.state.scraper_timeout * 1.5), 60)
            if new_timeout != self.state.scraper_timeout:
                self.state.scraper_timeout = new_timeout
                logger.info(f"🔄 Timeout adaptado para {new_timeout}s (timeout rate: {self.state.timeout_rate:.1f}%)")
    
    def optimize_after_batch(self, batch_size: int = 0):
        """
        Chamado após processar um lote de empresas.
        Analisa padrões recentes e ajusta configurações.
        
        Args:
            batch_size: Número de empresas processadas no lote
        """
        self.state.total_sites_processed += batch_size
        
        # Analisar últimas 6 horas (mais recente = mais relevante)
        patterns = failure_tracker.get_patterns(period_hours=6)
        scraper_patterns = patterns.get("scraper", {})
        llm_patterns = patterns.get("llm", {})
        
        total_scraper = sum(scraper_patterns.values())
        total_llm = sum(llm_patterns.values())
        
        changes_made = []
        
        # Adaptar scraper
        if total_scraper > 5:
            self._analyze_and_adapt(scraper_patterns, total_scraper)
            changes_made.append("scraper")
        
        # Adaptar LLM
        if total_llm > 5:
            rate_limit_count = llm_patterns.get("llm_rate_limit", 0)
            rate_limit_rate = (rate_limit_count / total_llm) * 100
            
            if rate_limit_rate > self.RATE_LIMIT_THRESHOLD:
                new_concurrent = max(int(self.state.llm_max_concurrent * 0.8), 20)
                if new_concurrent != self.state.llm_max_concurrent:
                    self.state.llm_max_concurrent = new_concurrent
                    logger.info(f"🔄 Concorrência LLM reduzida para {new_concurrent} (rate limit: {rate_limit_rate:.1f}%)")
                    changes_made.append("llm_concurrent")
        
        if changes_made:
            self.state.optimizations_applied += 1
            self.state.last_optimization = datetime.utcnow().isoformat()
            logger.info(f"✅ Otimização #{self.state.optimizations_applied} aplicada: {changes_made}")
    
    def get_default_strategy_for_new_site(self) -> str:
        """
        Retorna a melhor estratégia padrão para um site nunca visto,
        baseada nos padrões aprendidos.
        
        Returns:
            Nome da estratégia ("fast", "standard", "robust", "aggressive")
        """
        return self.state.default_strategy
    
    def get_recommended_timeout(self) -> int:
        """Retorna timeout recomendado baseado em aprendizado."""
        return self.state.scraper_timeout
    
    def get_recommended_llm_concurrent(self) -> int:
        """Retorna concorrência LLM recomendada."""
        return self.state.llm_max_concurrent
    
    def should_use_aggressive_strategy(self) -> bool:
        """
        Indica se o sistema deve preferir estratégia agressiva
        baseado nos padrões de proteção encontrados.
        """
        return self.state.cloudflare_rate > 40
    
    def get_scraper_config(self) -> Dict[str, Any]:
        """Retorna configuração adaptada do scraper."""
        return {
            "session_timeout": self.state.scraper_timeout,
            "chunk_size": self.state.scraper_chunk_size,
            "circuit_breaker_threshold": self.state.circuit_breaker_threshold,
            "default_strategy": self.state.default_strategy
        }
    
    def get_llm_config(self) -> Dict[str, Any]:
        """Retorna configuração adaptada do LLM."""
        return {
            "max_concurrent": self.state.llm_max_concurrent,
            "timeout": self.state.llm_timeout,
            "max_chunk_tokens": self.state.llm_chunk_tokens
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Retorna status completo do sistema adaptativo."""
        return {
            "default_strategy": self.state.default_strategy,
            "scraper_config": self.get_scraper_config(),
            "llm_config": self.get_llm_config(),
            "learning_stats": {
                "total_sites_processed": self.state.total_sites_processed,
                "cloudflare_rate": f"{self.state.cloudflare_rate:.1f}%",
                "timeout_rate": f"{self.state.timeout_rate:.1f}%",
                "optimizations_applied": self.state.optimizations_applied,
                "last_optimization": self.state.last_optimization
            }
        }
    
    def reset(self):
        """Reseta para configurações padrão."""
        self.state = AdaptiveState()
        logger.info("AdaptiveConfig: Estado resetado para padrão")


# Instância singleton
adaptive_config = AdaptiveConfigManager()

