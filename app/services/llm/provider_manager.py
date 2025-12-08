"""
Gerenciador de provedores LLM.
Centraliza configuração e chamadas aos providers.
"""

import asyncio
import time
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from openai import AsyncOpenAI, RateLimitError, APIError, APITimeoutError, BadRequestError

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """Configuração de um provider LLM."""
    name: str
    api_key: str
    base_url: str
    model: str
    max_concurrent: int = 100
    priority: int = 50  # 0-100, maior = melhor
    timeout: float = 90.0
    enabled: bool = True


class ProviderError(Exception):
    """Erro genérico de provider."""
    pass


class ProviderRateLimitError(ProviderError):
    """Erro de rate limit."""
    pass


class ProviderTimeoutError(ProviderError):
    """Erro de timeout."""
    pass


class ProviderBadRequestError(ProviderError):
    """Erro de requisição inválida."""
    pass


class ProviderManager:
    """
    Gerencia conexões e chamadas aos providers LLM.
    """
    
    def __init__(self, configs: List[ProviderConfig] = None):
        self._configs: Dict[str, ProviderConfig] = {}
        self._clients: Dict[str, AsyncOpenAI] = {}
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        
        if configs:
            for config in configs:
                self.add_provider(config)
        else:
            self._load_default_providers()
    
    def _load_default_providers(self):
        """Carrega providers das configurações do sistema com limites do llm_limits.json."""
        # Carregar limites reais do arquivo de configuração
        limits = self._load_limits_from_file()
        
        # Calcular max_concurrent baseado em RPM real (80% de segurança)
        # RPM / 60 = requests por segundo, usamos 80% do limite
        gemini_rpm = limits.get("google", {}).get("gemini-2.0-flash", {}).get("rpm", 10000)
        openai_rpm = limits.get("openai", {}).get("gpt-4o-mini", {}).get("rpm", 5000)
        safety_margin = limits.get("config", {}).get("safety_margin", 0.8)
        
        # Converter RPM para concorrência máxima razoável
        # max_concurrent = (RPM * safety_margin) / 60 * avg_request_time_seconds
        # Assumindo ~5s por request, max_concurrent = RPM * 0.8 / 12
        gemini_concurrent = int(gemini_rpm * safety_margin / 12)  # ~666 para 10K RPM
        openai_concurrent = int(openai_rpm * safety_margin / 12)  # ~333 para 5K RPM
        
        logger.info(f"LLM Limits: Gemini RPM={gemini_rpm}, concurrent={gemini_concurrent}")
        logger.info(f"LLM Limits: OpenAI RPM={openai_rpm}, concurrent={openai_concurrent}")
        
        default_providers = [
            ProviderConfig(
                name="Google Gemini",
                api_key=settings.GOOGLE_API_KEY or "",
                base_url=settings.GOOGLE_BASE_URL or "https://generativelanguage.googleapis.com/v1beta/openai/",
                model=settings.GOOGLE_MODEL or "gemini-2.0-flash",
                max_concurrent=gemini_concurrent,
                priority=60
            ),
            ProviderConfig(
                name="OpenAI",
                api_key=settings.OPENAI_API_KEY or "",
                base_url=settings.OPENAI_BASE_URL or "https://api.openai.com/v1",
                model=settings.OPENAI_MODEL or "gpt-4o-mini",
                max_concurrent=openai_concurrent,
                priority=50
            ),
            ProviderConfig(
                name="OpenRouter",
                api_key=settings.OPENROUTER_API_KEY or "",
                base_url=settings.OPENROUTER_BASE_URL,
                model=settings.OPENROUTER_MODEL,
                max_concurrent=200,  # Fallback robusto
                priority=10
            ),
        ]
        
        for config in default_providers:
            if config.api_key:
                self.add_provider(config)
    
    def _load_limits_from_file(self) -> dict:
        """Carrega limites do arquivo llm_limits.json."""
        import json
        from pathlib import Path
        
        limits_file = Path(__file__).parent.parent.parent / "core" / "llm_limits.json"
        
        try:
            if limits_file.exists():
                with open(limits_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Não foi possível carregar llm_limits.json: {e}")
        
        return {}
    
    def add_provider(self, config: ProviderConfig):
        """Adiciona um provider."""
        if not config.api_key:
            logger.warning(f"ProviderManager: {config.name} sem API key, ignorando")
            return
        
        self._configs[config.name] = config
        self._clients[config.name] = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout
        )
        self._semaphores[config.name] = asyncio.Semaphore(config.max_concurrent)
        
        logger.info(f"ProviderManager: {config.name} adicionado (model={config.model})")
    
    def remove_provider(self, name: str):
        """Remove um provider."""
        self._configs.pop(name, None)
        self._clients.pop(name, None)
        self._semaphores.pop(name, None)
    
    @property
    def available_providers(self) -> List[str]:
        """Lista de providers disponíveis."""
        return [name for name, config in self._configs.items() if config.enabled]
    
    @property
    def provider_priorities(self) -> Dict[str, int]:
        """Dict de prioridades dos providers."""
        return {name: config.priority for name, config in self._configs.items()}
    
    def get_config(self, provider: str) -> Optional[ProviderConfig]:
        """Retorna configuração de um provider."""
        return self._configs.get(provider)
    
    def get_client(self, provider: str) -> Optional[AsyncOpenAI]:
        """Retorna cliente de um provider."""
        return self._clients.get(provider)
    
    def get_model(self, provider: str) -> Optional[str]:
        """Retorna modelo de um provider."""
        config = self._configs.get(provider)
        return config.model if config else None
    
    async def call(
        self,
        provider: str,
        messages: List[dict],
        timeout: float = None,
        temperature: float = 0.0,
        response_format: dict = None
    ) -> Tuple[str, float]:
        """
        Faz chamada a um provider.
        
        Args:
            provider: Nome do provider
            messages: Lista de mensagens
            timeout: Timeout opcional (usa padrão do provider se None)
            temperature: Temperatura da geração
            response_format: Formato de resposta (ex: {"type": "json_object"})
        
        Returns:
            Tuple de (response_content, latency_ms)
        
        Raises:
            ProviderRateLimitError: Se rate limit
            ProviderTimeoutError: Se timeout
            ProviderBadRequestError: Se requisição inválida
            ProviderError: Para outros erros
        """
        config = self._configs.get(provider)
        if not config:
            raise ProviderError(f"Provider '{provider}' não encontrado")
        
        client = self._clients.get(provider)
        if not client:
            raise ProviderError(f"Cliente não inicializado para '{provider}'")
        
        semaphore = self._semaphores.get(provider)
        actual_timeout = timeout or config.timeout
        
        async with semaphore:
            start_time = time.perf_counter()
            
            try:
                request_params = {
                    "model": config.model,
                    "messages": messages,
                    "temperature": temperature,
                    "timeout": actual_timeout
                }
                
                if response_format:
                    request_params["response_format"] = response_format
                
                response = await client.chat.completions.create(**request_params)
                
                latency_ms = (time.perf_counter() - start_time) * 1000
                
                if not response.choices or not response.choices[0].message.content:
                    raise ProviderError(f"{provider} retornou resposta vazia")
                
                content = response.choices[0].message.content.strip()
                
                logger.debug(
                    f"ProviderManager: {provider} - "
                    f"{len(content)} chars em {latency_ms:.0f}ms"
                )
                
                return content, latency_ms
            
            except RateLimitError as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.warning(f"ProviderManager: {provider} RATE_LIMIT após {latency_ms:.0f}ms")
                raise ProviderRateLimitError(str(e))
            
            except APITimeoutError as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.warning(f"ProviderManager: {provider} TIMEOUT após {latency_ms:.0f}ms")
                raise ProviderTimeoutError(str(e))
            
            except BadRequestError as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.error(f"ProviderManager: {provider} BAD_REQUEST: {e}")
                raise ProviderBadRequestError(str(e))
            
            except asyncio.TimeoutError:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.warning(f"ProviderManager: {provider} ASYNC_TIMEOUT após {latency_ms:.0f}ms")
                raise ProviderTimeoutError("Async timeout")
            
            except Exception as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.error(f"ProviderManager: {provider} ERROR: {type(e).__name__}: {e}")
                raise ProviderError(str(e))
    
    async def call_with_retry(
        self,
        provider: str,
        messages: List[dict],
        max_retries: int = 2,
        retry_delay: float = 1.0,
        **kwargs
    ) -> Tuple[str, float]:
        """
        Faz chamada com retry automático.
        
        Args:
            provider: Nome do provider
            messages: Lista de mensagens
            max_retries: Número máximo de retries
            retry_delay: Delay entre retries em segundos
            **kwargs: Argumentos adicionais para call()
        
        Returns:
            Tuple de (response_content, latency_ms)
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                return await self.call(provider, messages, **kwargs)
            
            except ProviderBadRequestError:
                # Não faz retry para bad request
                raise
            
            except (ProviderRateLimitError, ProviderTimeoutError, ProviderError) as e:
                last_error = e
                
                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.info(
                        f"ProviderManager: {provider} retry {attempt + 1}/{max_retries} "
                        f"após {delay:.1f}s ({type(e).__name__})"
                    )
                    await asyncio.sleep(delay)
        
        raise last_error
    
    def get_status(self) -> dict:
        """Retorna status de todos os providers."""
        status = {}
        for name, config in self._configs.items():
            semaphore = self._semaphores.get(name)
            status[name] = {
                "enabled": config.enabled,
                "model": config.model,
                "priority": config.priority,
                "max_concurrent": config.max_concurrent,
                "semaphore_locked": semaphore.locked() if semaphore else None
            }
        return status


# Instância singleton
provider_manager = ProviderManager()

