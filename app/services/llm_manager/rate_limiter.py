"""
Rate Limiter v2.0 - Controle separado de RPM e TPM.

Controla dois limites distintos por provider:
- RPM (Requests Per Minute): Quantidade de chamadas à API por minuto
- TPM (Tokens Per Minute): Quantidade de tokens processados por minuto

Cada chamada LLM deve:
1. Adquirir 1 slot do RPM bucket
2. Adquirir N tokens do TPM bucket (onde N = tokens estimados da requisição)
"""

import asyncio
import time
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from app.services.concurrency_manager.config_loader import (
    get_section as get_concurrency_section,
)

logger = logging.getLogger(__name__)


@dataclass
class ProviderLimits:
    """Limites de um provider LLM."""
    rpm: int  # Requests Per Minute
    tpm: int  # Tokens Per Minute
    context_window: int = 128000  # Tamanho máximo de contexto em tokens
    max_output_tokens: int = 16384  # Máximo de tokens de saída
    weight: int = 10  # Peso para distribuição
    
    @property
    def rpm_per_second(self) -> float:
        """Taxa de requests por segundo."""
        return self.rpm / 60.0
    
    @property
    def tpm_per_second(self) -> float:
        """Taxa de tokens por segundo."""
        return self.tpm / 60.0
    
    @property
    def safe_input_tokens(self) -> int:
        """Máximo seguro de tokens de entrada (context - output - overhead)."""
        overhead = 2500  # System prompt overhead
        return self.context_window - self.max_output_tokens - overhead


class TokenBucket:
    """
    Implementa algoritmo Token Bucket para rate limiting.
    Thread-safe para uso assíncrono.
    
    Pode ser usado para controlar RPM ou TPM dependendo da configuração.
    """
    
    def __init__(
        self,
        rate_per_minute: int,
        max_burst: int = None,
        name: str = "bucket"
    ):
        """
        Args:
            rate_per_minute: Taxa de reabastecimento por minuto
            max_burst: Máximo de tokens acumulados (burst capacity)
            name: Nome para logging
        """
        self.rate_per_minute = rate_per_minute
        self.max_burst = max_burst or min(rate_per_minute, rate_per_minute // 10 + 1)
        self.tokens = float(self.max_burst)
        self.last_refill = time.monotonic()
        self.lock = asyncio.Lock()
        self._refill_rate = rate_per_minute / 60.0  # por segundo
        self._name = name
    
    async def acquire(self, amount: int = 1, timeout: float = 30.0) -> bool:
        """
        Tenta adquirir tokens do bucket.
        
        Args:
            amount: Quantidade de tokens necessários
            timeout: Tempo máximo de espera em segundos
        
        Returns:
            True se adquiriu, False se timeout
        """
        start_time = time.monotonic()
        
        while True:
            async with self.lock:
                self._refill()
                
                if self.tokens >= amount:
                    self.tokens -= amount
                    return True
            
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                logger.warning(
                    f"TokenBucket[{self._name}]: Timeout após {elapsed:.1f}s "
                    f"aguardando {amount} (disponível: {self.tokens:.1f})"
                )
                return False
            
            wait_time = self._get_wait_time(amount)
            remaining_timeout = timeout - elapsed
            actual_wait = min(wait_time, remaining_timeout, 0.5)
            
            await asyncio.sleep(actual_wait)
    
    def try_acquire(self, amount: int = 1) -> bool:
        """
        Tenta adquirir tokens sem esperar.
        
        Returns:
            True se adquiriu imediatamente, False se não há tokens suficientes
        """
        self._refill()
        
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False
    
    def _refill(self):
        """Reabastece tokens baseado no tempo passado."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        
        tokens_to_add = elapsed * self._refill_rate
        self.tokens = min(self.max_burst, self.tokens + tokens_to_add)
        self.last_refill = now
    
    def _get_wait_time(self, amount: int) -> float:
        """Calcula tempo estimado de espera."""
        if self.tokens >= amount:
            return 0.0
        
        tokens_needed = amount - self.tokens
        return tokens_needed / self._refill_rate
    
    @property
    def available(self) -> float:
        """Tokens disponíveis atualmente."""
        return self.tokens
    
    @property
    def utilization(self) -> float:
        """Taxa de utilização (0.0 a 1.0)."""
        return 1.0 - (self.tokens / self.max_burst)
    
    def get_status(self) -> dict:
        """Retorna status atual."""
        return {
            "available": round(self.tokens, 2),
            "max_burst": self.max_burst,
            "rate_per_minute": self.rate_per_minute,
            "utilization": f"{self.utilization:.1%}",
            "wait_time_1": f"{self._get_wait_time(1):.2f}s"
        }


class ProviderRateLimiter:
    """
    Rate limiter para um único provider.
    Gerencia dois buckets separados: RPM e TPM.
    """
    
    def __init__(self, name: str, limits: ProviderLimits, safety_margin: float = 0.8):
        """
        Args:
            name: Nome do provider
            limits: Limites de RPM e TPM
            safety_margin: Margem de segurança (0.8 = usar 80% do limite)
        """
        self.name = name
        self.limits = limits
        self.safety_margin = safety_margin
        
        # Bucket para controle de requests (RPM)
        # Burst = 20% do RPM ou mínimo 1000 (otimizado para 500+ empresas simultâneas)
        rpm_safe = int(limits.rpm * safety_margin)
        rpm_burst = max(1000, rpm_safe // 5)
        self.rpm_bucket = TokenBucket(
            rate_per_minute=rpm_safe,
            max_burst=rpm_burst,
            name=f"{name}_rpm"
        )
        
        # Bucket para controle de tokens (TPM)
        # Burst = 5% do TPM ou mínimo 500k (otimizado para 500 empresas x 800 tokens = 400k)
        tpm_safe = int(limits.tpm * safety_margin)
        tpm_burst = max(500000, tpm_safe // 20)
        self.tpm_bucket = TokenBucket(
            rate_per_minute=tpm_safe,
            max_burst=tpm_burst,
            name=f"{name}_tpm"
        )
        
        logger.info(
            f"ProviderRateLimiter[{name}]: RPM={rpm_safe} (burst={rpm_burst}), "
            f"TPM={tpm_safe:,} (burst={tpm_burst:,})"
        )
    
    async def acquire(
        self,
        estimated_tokens: int = 1000,
        timeout: float = 30.0
    ) -> Tuple[bool, str]:
        """
        Adquire permissão para fazer uma requisição.
        
        Args:
            estimated_tokens: Tokens estimados para a requisição
            timeout: Timeout máximo
        
        Returns:
            Tuple de (sucesso, motivo_falha)
        """
        start_time = time.monotonic()
        
        # 1. Primeiro adquirir slot de RPM (1 request)
        rpm_acquired = await self.rpm_bucket.acquire(1, timeout)
        if not rpm_acquired:
            return False, "rpm_limit"
        
        # 2. Depois adquirir tokens de TPM
        remaining_timeout = timeout - (time.monotonic() - start_time)
        if remaining_timeout <= 0:
            return False, "timeout"
        
        tpm_acquired = await self.tpm_bucket.acquire(estimated_tokens, remaining_timeout)
        if not tpm_acquired:
            # Devolver o slot de RPM já que não conseguimos completar
            self.rpm_bucket.tokens = min(
                self.rpm_bucket.max_burst,
                self.rpm_bucket.tokens + 1
            )
            return False, "tpm_limit"
        
        return True, "ok"
    
    def can_acquire(self, estimated_tokens: int = 1000) -> bool:
        """Verifica se pode adquirir sem esperar."""
        return (
            self.rpm_bucket.available >= 1 and
            self.tpm_bucket.available >= estimated_tokens
        )
    
    def get_wait_time(self, estimated_tokens: int = 1000) -> float:
        """Retorna tempo estimado de espera."""
        rpm_wait = self.rpm_bucket._get_wait_time(1)
        tpm_wait = self.tpm_bucket._get_wait_time(estimated_tokens)
        return max(rpm_wait, tpm_wait)
    
    def get_status(self) -> dict:
        """Retorna status completo."""
        return {
            "provider": self.name,
            "rpm": self.rpm_bucket.get_status(),
            "tpm": self.tpm_bucket.get_status(),
            "limits": {
                "rpm": self.limits.rpm,
                "tpm": self.limits.tpm,
                "weight": self.limits.weight
            }
        }


class RateLimiter:
    """
    Gerenciador central de rate limiting para múltiplos providers.
    
    Carrega limites centralizados e cria rate limiters
    separados para cada provider com controle de RPM e TPM.
    """
    
    def __init__(self, config_file: str = None):
        """
        Args:
            config_file: Caminho opcional alternativo; por padrão usa
                        a seção llm_limits do concurrency_config.json.
        """
        self._providers: Dict[str, ProviderRateLimiter] = {}
        self._config = self._load_config(config_file)
        self._safety_margin = self._config.get("config", {}).get("safety_margin", 0.8)
        self._init_providers()
    
    def _load_config(self, config_file: str = None) -> dict:
        """Carrega configuração de limites LLM."""
        central_cfg = get_concurrency_section("llm_limits")
        if central_cfg:
            logger.info("RateLimiter: Configuração carregada de concurrency_config.json")
            return central_cfg
        # Fallback para defaults hardcoded se central estiver ausente
        return self._get_default_config()
    
    def _get_default_config(self) -> dict:
        """Retorna configuração padrão."""
        return {
            "vastai": {
                "Qwen/Qwen3-8B": {
                    "rpm": 30000, "tpm": 5000000, "weight": 50,
                    "context_window": 131072, "max_output_tokens": 8192
                }
            },
            "runpod": {
                "mistralai/Ministral-3-8B-Instruct-2512": {
                    "rpm": 30000, "tpm": 5000000, "weight": 50,
                    "context_window": 131072, "max_output_tokens": 8192
                }
            },
            "google": {
                "gemini-2.0-flash": {
                    "rpm": 10000, "tpm": 10000000, "weight": 29,
                    "context_window": 1048576, "max_output_tokens": 8192
                }
            },
            "openai": {
                "gpt-4.1-nano": {
                    "rpm": 5000, "tpm": 4000000, "weight": 14,
                    "context_window": 1047576, "max_output_tokens": 32768
                }
            },
            "openrouter": {
                "google/gemini-2.0-flash-lite-001": {
                    "rpm": 20000, "tpm": 10000000, "weight": 30,
                    "context_window": 1048576, "max_output_tokens": 8192
                },
                "google/gemini-2.5-flash-lite": {
                    "rpm": 15000, "tpm": 8000000, "weight": 25,
                    "context_window": 1048576, "max_output_tokens": 65536
                },
                "openai/gpt-4.1-nano": {
                    "rpm": 10000, "tpm": 5000000, "weight": 20,
                    "context_window": 1047576, "max_output_tokens": 32768
                }
            },
            "config": {"safety_margin": 0.8}
        }
    
    def _detect_vast_model(self) -> str:
        """
        Detecta qual modelo está configurado na Vast.ai.
        
        v11.0: Refatorado para Vast.ai (antes era RunPod)
        
        Returns:
            Nome do modelo configurado ou default
        """
        from app.core.config import settings
        
        model = settings.MODEL_NAME or settings.VLLM_MODEL or ""
        
        # Verificar se é Qwen
        if "qwen" in model.lower():
            # Tentar encontrar configuração específica do Qwen
            # v11.0: Tentar vastai primeiro, fallback para runpod (compatibilidade)
            qwen_config = (
                self._config.get("vastai", {}).get(model) or
                self._config.get("vastai", {}).get("Qwen/Qwen3-8B") or
                self._config.get("runpod", {}).get("Qwen/Qwen2.5-3B-Instruct", {})
            )
            if qwen_config:
                logger.info(f"RateLimiter: Vast.ai - Modelo Qwen detectado: {model}")
                return model if model else "Qwen/Qwen3-8B"
        
        # Default: Qwen3-8B (Vast.ai padrão)
        return "Qwen/Qwen3-8B"
    
    def _init_providers(self):
        """Inicializa rate limiters para cada provider."""
        # Mapear nomes de providers para configurações
        # v11.0: Refatorado para Vast.ai (antes era RunPod)
        vast_model = self._detect_vast_model()
        
        # v11.0: Tentar vastai primeiro, fallback para runpod (compatibilidade)
        vast_group = "vastai" if "vastai" in self._config else "runpod"
        
        provider_mapping = {
            "Vast.ai": (vast_group, vast_model),
            "Google Gemini": ("google", "gemini-2.0-flash"),
            "OpenAI": ("openai", "gpt-4.1-nano"),
            "OpenRouter": ("openrouter", "google/gemini-2.0-flash-lite-001"),
            "OpenRouter2": ("openrouter", "google/gemini-2.5-flash-lite"),
            "OpenRouter3": ("openrouter", "openai/gpt-4.1-nano"),
        }
        
        for provider_name, (group, model) in provider_mapping.items():
            model_config = self._config.get(group, {}).get(model, {})
            
            if model_config:
                limits = ProviderLimits(
                    rpm=model_config.get("rpm", 1000),
                    tpm=model_config.get("tpm", 1000000),
                    context_window=model_config.get("context_window", 128000),
                    max_output_tokens=model_config.get("max_output_tokens", 16384),
                    weight=model_config.get("weight", 10)
                )
                
                self._providers[provider_name] = ProviderRateLimiter(
                    name=provider_name,
                    limits=limits,
                    safety_margin=self._safety_margin
                )
                
                logger.info(
                    f"Provider {provider_name}: context_window={limits.context_window:,}, "
                    f"safe_input={limits.safe_input_tokens:,}"
                )
    
    def get_provider(self, name: str) -> Optional[ProviderRateLimiter]:
        """Retorna rate limiter de um provider."""
        return self._providers.get(name)
    
    async def acquire(
        self,
        provider: str,
        estimated_tokens: int = 1000,
        timeout: float = 30.0
    ) -> bool:
        """
        Adquire permissão para fazer requisição a um provider.
        
        Args:
            provider: Nome do provider
            estimated_tokens: Tokens estimados para a requisição
            timeout: Timeout máximo
        
        Returns:
            True se adquiriu permissão, False se timeout ou limite atingido
        """
        limiter = self._providers.get(provider)
        if not limiter:
            # Provider não configurado - criar um padrão
            limiter = ProviderRateLimiter(
                name=provider,
                limits=ProviderLimits(rpm=60, tpm=100000, weight=10),
                safety_margin=self._safety_margin
            )
            self._providers[provider] = limiter
            logger.warning(f"RateLimiter: Provider {provider} não configurado, usando defaults")
        
        success, reason = await limiter.acquire(estimated_tokens, timeout)
        
        if success:
            logger.debug(f"RateLimiter: {provider} - Adquirido (est_tokens={estimated_tokens})")
        else:
            logger.warning(f"RateLimiter: {provider} - Falha ({reason})")
        
        return success
    
    def get_wait_time(self, provider: str, estimated_tokens: int = 1000) -> float:
        """Retorna tempo de espera estimado para um provider."""
        limiter = self._providers.get(provider)
        if not limiter:
            return 0.0
        return limiter.get_wait_time(estimated_tokens)
    
    def get_best_provider(
        self,
        providers: list,
        estimated_tokens: int = 1000
    ) -> Optional[str]:
        """
        Retorna o provider com menor tempo de espera.
        
        Args:
            providers: Lista de providers a considerar
            estimated_tokens: Tokens estimados
        
        Returns:
            Nome do provider ou None
        """
        best_provider = None
        min_wait = float('inf')
        
        for provider in providers:
            wait = self.get_wait_time(provider, estimated_tokens)
            if wait < min_wait:
                min_wait = wait
                best_provider = provider
        
        return best_provider
    
    def get_available_providers(
        self,
        providers: list,
        estimated_tokens: int = 1000
    ) -> list:
        """
        Retorna providers que podem aceitar requisição imediatamente.
        
        Args:
            providers: Lista de providers a considerar
            estimated_tokens: Tokens estimados
        
        Returns:
            Lista de providers disponíveis
        """
        available = []
        for provider in providers:
            limiter = self._providers.get(provider)
            if limiter and limiter.can_acquire(estimated_tokens):
                available.append(provider)
        return available
    
    def get_status(self) -> dict:
        """Retorna status de todos os providers."""
        return {
            name: limiter.get_status()
            for name, limiter in self._providers.items()
        }
    
    def reset(self, provider: str = None):
        """Reseta buckets para capacidade máxima."""
        if provider:
            limiter = self._providers.get(provider)
            if limiter:
                limiter.rpm_bucket.tokens = limiter.rpm_bucket.max_burst
                limiter.tpm_bucket.tokens = limiter.tpm_bucket.max_burst
                logger.info(f"RateLimiter: Reset {provider}")
        else:
            for name, limiter in self._providers.items():
                limiter.rpm_bucket.tokens = limiter.rpm_bucket.max_burst
                limiter.tpm_bucket.tokens = limiter.tpm_bucket.max_burst
            logger.info("RateLimiter: Reset all providers")
    
    def get_limits(self, provider: str) -> Optional[ProviderLimits]:
        """Retorna limites configurados de um provider."""
        limiter = self._providers.get(provider)
        return limiter.limits if limiter else None
    
    def get_context_window(self, provider: str) -> int:
        """
        Retorna o context window de um provider.
        
        Args:
            provider: Nome do provider
        
        Returns:
            Tamanho do context window em tokens
        """
        limiter = self._providers.get(provider)
        if limiter:
            return limiter.limits.context_window
        return 128000  # Default conservador
    
    def get_safe_input_tokens(self, provider: str) -> int:
        """
        Retorna o máximo seguro de tokens de entrada para um provider.
        
        Considera: context_window - max_output_tokens - system_prompt_overhead
        
        Args:
            provider: Nome do provider
        
        Returns:
            Máximo seguro de tokens de entrada
        """
        limiter = self._providers.get(provider)
        if limiter:
            return limiter.limits.safe_input_tokens
        return 100000  # Default conservador
    
    def get_max_output_tokens(self, provider: str) -> int:
        """
        Retorna o máximo de tokens de saída para um provider.
        
        Args:
            provider: Nome do provider
        
        Returns:
            Máximo de tokens de saída
        """
        limiter = self._providers.get(provider)
        if limiter:
            return limiter.limits.max_output_tokens
        return 8192  # Default conservador
    
    def get_min_context_window(self) -> int:
        """
        Retorna o menor context window entre todos os providers.
        
        Útil para determinar o limite máximo de chunk que funciona com todos.
        """
        min_window = float('inf')
        for limiter in self._providers.values():
            min_window = min(min_window, limiter.limits.context_window)
        return int(min_window) if min_window != float('inf') else 128000
    
    def get_min_safe_input_tokens(self) -> int:
        """
        Retorna o menor safe_input_tokens entre todos os providers.
        
        Útil para determinar o tamanho máximo de chunk seguro para todos.
        """
        min_safe = float('inf')
        for limiter in self._providers.values():
            min_safe = min(min_safe, limiter.limits.safe_input_tokens)
        return int(min_safe) if min_safe != float('inf') else 100000
    
    def can_fit_in_context(self, provider: str, estimated_tokens: int) -> bool:
        """
        Verifica se o conteúdo cabe no context window do provider.
        
        Args:
            provider: Nome do provider
            estimated_tokens: Tokens estimados do conteúdo
        
        Returns:
            True se cabe, False se excede o limite
        """
        safe_tokens = self.get_safe_input_tokens(provider)
        return estimated_tokens <= safe_tokens
    
    def get_providers_for_content_size(
        self,
        providers: list,
        estimated_tokens: int
    ) -> list:
        """
        Filtra providers que suportam o tamanho de conteúdo especificado.
        
        Args:
            providers: Lista de providers a considerar
            estimated_tokens: Tokens estimados do conteúdo
        
        Returns:
            Lista de providers que suportam o tamanho
        """
        compatible = []
        for provider in providers:
            if self.can_fit_in_context(provider, estimated_tokens):
                compatible.append(provider)
        return compatible


# Para compatibilidade retroativa
@dataclass
class BucketConfig:
    """DEPRECATED: Use ProviderLimits instead."""
    tokens_per_minute: int
    max_tokens: int = None
    
    def __post_init__(self):
        if self.max_tokens is None:
            self.max_tokens = self.tokens_per_minute // 10


# Instância singleton
rate_limiter = RateLimiter()
