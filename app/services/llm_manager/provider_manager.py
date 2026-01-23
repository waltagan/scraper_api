"""
Gerenciador de provedores LLM v3.2.

Centraliza configuração e chamadas aos providers.
Integrado com RateLimiter v2.0 para controle separado de RPM e TPM.

v3.2: Integração com rate limiter que controla RPM e TPM separadamente
      - Antes de cada chamada, adquire slot de RPM E tokens de TPM
      - Estima tokens da requisição baseado no conteúdo das mensagens
"""

import asyncio
import time
import logging
import random
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from openai import AsyncOpenAI, RateLimitError, APIError, APITimeoutError, BadRequestError

from app.core.config import settings
from app.services.concurrency_manager.config_loader import (
    get_section as get_concurrency_section,
)
from .priority import LLMPriority
from .rate_limiter import rate_limiter
from app.core.token_utils import estimate_tokens

logger = logging.getLogger(__name__)


def _detect_repetition_loop(content: str, ctx_label: str = "") -> bool:
    """
    Detecta loops de repetição degenerados no conteúdo da resposta.
    
    v8.0: Loop detector para identificar runaway generation
    
    Heurísticas:
    1. Mesmo n-gram (4-6 tokens) repetido > 8 vezes
    2. Mesma linha/trecho (> 20 chars) repetido > 5 vezes
    3. Output muito longo sem fechar JSON (> 3000 chars sem '}' no final)
    
    Args:
        content: Conteúdo da resposta do LLM
        ctx_label: Label de contexto para logs
    
    Returns:
        True se detectar loop, False caso contrário
    """
    if not content or len(content) < 100:
        return False
    
    # Heurística 1: n-grams repetidos (4-6 palavras)
    # Detectar padrões como "2 RCA + 2 RCA" repetidos muitas vezes
    import re
    words = re.findall(r'\b\w+\b', content.lower())
    
    # Verificar n-grams de 4 palavras
    if len(words) >= 4:
        ngram_counts = {}
        for i in range(len(words) - 3):
            ngram = ' '.join(words[i:i+4])
            ngram_counts[ngram] = ngram_counts.get(ngram, 0) + 1
        
        # Se algum n-gram aparece > 8 vezes, provável loop
        max_ngram_count = max(ngram_counts.values()) if ngram_counts else 0
        if max_ngram_count > 8:
            most_repeated = max(ngram_counts, key=ngram_counts.get)
            logger.warning(
                f"{ctx_label}LoopDetector: n-gram repetido detectado "
                f"('{most_repeated}' x{max_ngram_count})"
            )
            return True
    
    # Heurística 2: Linhas/trechos repetidos
    # Dividir em trechos de 20-50 chars e contar repetições
    chunk_size = 30
    chunk_counts = {}
    for i in range(0, len(content) - chunk_size, 10):
        chunk = content[i:i+chunk_size].strip()
        if len(chunk) >= 20:  # Ignorar trechos muito pequenos
            chunk_counts[chunk] = chunk_counts.get(chunk, 0) + 1
    
    # Se algum trecho aparece > 5 vezes, provável loop
    max_chunk_count = max(chunk_counts.values()) if chunk_counts else 0
    if max_chunk_count > 5:
        most_repeated = max(chunk_counts, key=chunk_counts.get)
        logger.warning(
            f"{ctx_label}LoopDetector: Trecho repetido detectado "
            f"('{most_repeated[:40]}...' x{max_chunk_count})"
        )
        return True
    
    # Heurística 3: Output muito longo sem fechar JSON
    # Indica que o modelo está gerando lista infinita
    if len(content) > 3000 and not content.rstrip().endswith('}'):
        logger.warning(
            f"{ctx_label}LoopDetector: JSON não fechado após {len(content)} chars "
            f"(possível runaway generation)"
        )
        return True
    
    return False


@dataclass
class ProviderConfig:
    """Configuração de um provider LLM."""
    name: str
    api_key: str
    base_url: str
    model: str
    max_concurrent: int = 100
    priority: int = 50
    timeout: float = 90.0
    enabled: bool = True
    weight: int = 10


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


class ProviderDegenerationError(ProviderError):
    """Erro de geração degenerada (loop/repetição detectada)."""
    pass


class ProviderManager:
    """
    Gerencia conexões e chamadas aos providers LLM.
    
    v3.3: Separação de providers por prioridade
          - HIGH (Discovery/LinkSelector) → Google Gemini exclusivo
          - NORMAL (Profile Building) → Outros providers (OpenAI, OpenRouter)
          - Elimina competição entre etapas críticas e profile building
    """
    
    def __init__(self, configs: List[ProviderConfig] = None):
        self._configs: Dict[str, ProviderConfig] = {}
        self._clients: Dict[str, AsyncOpenAI] = {}
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        
        # v3.3: Providers separados por prioridade
        self._high_priority_providers: List[str] = []   # Google Gemini exclusivo
        self._normal_priority_providers: List[str] = [] # Todos os outros
        
        # Sistema de prioridade (mantido para compatibilidade, mas menos crítico agora)
        self._high_priority_active = 0
        self._high_priority_done = asyncio.Event()
        self._high_priority_done.set()
        self._counter_lock = asyncio.Lock()
        
        # Rate limiter global
        self._rate_limiter = rate_limiter
        
        if configs:
            for config in configs:
                self.add_provider(config)
        else:
            self._load_default_providers()
    
    def _load_default_providers(self):
        """Carrega providers das configurações do sistema."""
        limits = self._load_limits_from_file()
        safety_margin = limits.get("config", {}).get("safety_margin", 0.8)
        
        # Carregar configuração de providers habilitados
        provider_enabled = self._load_provider_enabled_config()
        
        # RunPod (Provider Primário) - Detectar modelo configurado
        # v4.0: Suporte a Qwen2.5-3B-Instruct (SGLang) e Mistral
        vllm_model = settings.VLLM_MODEL or settings.RUNPOD_MODEL or ""
        is_qwen_model = "qwen" in vllm_model.lower()
        runpod_model_key = "Qwen/Qwen2.5-3B-Instruct" if is_qwen_model else "mistralai/Ministral-3-8B-Instruct-2512"
        runpod_config = limits.get("runpod", {}).get(runpod_model_key, {})
        
        # Log do modelo detectado
        if is_qwen_model:
            logger.info(f"ProviderManager: Detectado modelo Qwen: {vllm_model} (structured output via XGrammar)")
        else:
            logger.info(f"ProviderManager: Detectado modelo Mistral: {vllm_model}")
        
        gemini_config = limits.get("google", {}).get("gemini-2.0-flash", {})
        openai_config = limits.get("openai", {}).get("gpt-4.1-nano", {})
        openrouter1_config = limits.get("openrouter", {}).get("google/gemini-2.0-flash-lite-001", {})
        openrouter2_config = limits.get("openrouter", {}).get("google/gemini-2.5-flash-lite", {})
        openrouter3_config = limits.get("openrouter", {}).get("openai/gpt-4.1-nano", {})
        
        runpod_rpm = runpod_config.get("rpm", 30000)
        gemini_rpm = gemini_config.get("rpm", 10000)
        openai_rpm = openai_config.get("rpm", 5000)
        openrouter1_rpm = openrouter1_config.get("rpm", 20000)
        openrouter2_rpm = openrouter2_config.get("rpm", 15000)
        openrouter3_rpm = openrouter3_config.get("rpm", 10000)
        
        runpod_tpm = runpod_config.get("tpm", 5000000)
        gemini_tpm = gemini_config.get("tpm", 10000000)
        openai_tpm = openai_config.get("tpm", 4000000)
        openrouter1_tpm = openrouter1_config.get("tpm", 10000000)
        openrouter2_tpm = openrouter2_config.get("tpm", 8000000)
        openrouter3_tpm = openrouter3_config.get("tpm", 5000000)
        
        runpod_weight = runpod_config.get("weight", 50)
        gemini_weight = gemini_config.get("weight", 29)
        openai_weight = openai_config.get("weight", 14)
        openrouter1_weight = openrouter1_config.get("weight", 30)
        openrouter2_weight = openrouter2_config.get("weight", 25)
        openrouter3_weight = openrouter3_config.get("weight", 20)
        
        # Calcular concorrência baseado em RPM (80% de segurança)
        # Fórmula otimizada: (RPM * safety_margin) / 15 (assumindo ~2s por request)
        # Aumentado para suportar 500+ empresas simultâneas
        runpod_concurrent = max(800, int(runpod_rpm * safety_margin / 15))
        gemini_concurrent = max(600, int(gemini_rpm * safety_margin / 15))
        openai_concurrent = max(150, int(openai_rpm * safety_margin / 30))
        openrouter1_concurrent = max(300, int(openrouter1_rpm * safety_margin / 30))
        openrouter2_concurrent = max(250, int(openrouter2_rpm * safety_margin / 30))
        openrouter3_concurrent = max(200, int(openrouter3_rpm * safety_margin / 30))
        
        # Verificar se structured output está habilitado para RunPod
        runpod_structured = runpod_config.get("supports_structured_output", False)
        runpod_backend = runpod_config.get("structured_output_backend", "none")
        
        logger.info(f"LLM Limits carregados:")
        logger.info(
            f"  RunPod {runpod_model_key}: RPM={runpod_rpm}, TPM={runpod_tpm:,}, "
            f"weight={runpod_weight}%, structured_output={runpod_structured} ({runpod_backend})"
        )
        logger.info(f"  Google Gemini: RPM={gemini_rpm}, TPM={gemini_tpm:,}, weight={gemini_weight}%")
        logger.info(f"  OpenAI: RPM={openai_rpm}, TPM={openai_tpm:,}, weight={openai_weight}%")
        logger.info(f"  OpenRouter 1: RPM={openrouter1_rpm}, TPM={openrouter1_tpm:,}, weight={openrouter1_weight}%")
        logger.info(f"  OpenRouter 2: RPM={openrouter2_rpm}, TPM={openrouter2_tpm:,}, weight={openrouter2_weight}%")
        logger.info(f"  OpenRouter 3: RPM={openrouter3_rpm}, TPM={openrouter3_tpm:,}, weight={openrouter3_weight}%")
        
        default_providers = [
            ProviderConfig(
                name="RunPod",
                # Usar VLLM_BASE_URL e VLLM_API_KEY (unificado)
                api_key=settings.VLLM_API_KEY or settings.RUNPOD_API_KEY or "",
                base_url=settings.VLLM_BASE_URL or settings.RUNPOD_BASE_URL or "https://5u888x525vvzvs-8000.proxy.runpod.net/v1",
                model=settings.VLLM_MODEL or settings.RUNPOD_MODEL or "mistralai/Ministral-3-3B-Instruct-2512",
                max_concurrent=runpod_concurrent,
                priority=90,  # Prioridade mais alta (provider primário)
                weight=runpod_weight,
                enabled=True  # RunPod sempre habilitado
            ),
            ProviderConfig(
                name="Google Gemini",
                api_key=settings.GOOGLE_API_KEY or "",
                base_url=settings.GOOGLE_BASE_URL or "https://generativelanguage.googleapis.com/v1beta/openai/",
                model=settings.GOOGLE_MODEL or "gemini-2.0-flash",
                max_concurrent=gemini_concurrent,
                priority=70,
                weight=gemini_weight,
                enabled=provider_enabled.get("Google Gemini", False)
            ),
            ProviderConfig(
                name="OpenAI",
                api_key=settings.OPENAI_API_KEY or "",
                base_url=settings.OPENAI_BASE_URL or "https://api.openai.com/v1",
                model=settings.OPENAI_MODEL or "gpt-4.1-nano",
                max_concurrent=openai_concurrent,
                priority=60,
                weight=openai_weight,
                enabled=provider_enabled.get("OpenAI", False)
            ),
            ProviderConfig(
                name="OpenRouter",
                api_key=settings.OPENROUTER_API_KEY or "",
                base_url=settings.OPENROUTER_BASE_URL,
                model=settings.OPENROUTER_MODEL,
                max_concurrent=openrouter1_concurrent,
                priority=80,
                weight=openrouter1_weight,
                enabled=provider_enabled.get("OpenRouter", False)
            ),
            ProviderConfig(
                name="OpenRouter2",
                api_key=settings.OPENROUTER_API_KEY or "",
                base_url=settings.OPENROUTER_BASE_URL,
                model=settings.OPENROUTER_MODEL_2,
                max_concurrent=openrouter2_concurrent,
                priority=75,
                weight=openrouter2_weight,
                enabled=provider_enabled.get("OpenRouter2", False)
            ),
            ProviderConfig(
                name="OpenRouter3",
                api_key=settings.OPENROUTER_API_KEY or "",
                base_url=settings.OPENROUTER_BASE_URL,
                model=settings.OPENROUTER_MODEL_3,
                max_concurrent=openrouter3_concurrent,
                priority=72,
                weight=openrouter3_weight,
                enabled=provider_enabled.get("OpenRouter3", False)
            ),
        ]
        
        for config in default_providers:
            # RunPod sempre é adicionado se tiver API key, independente de enabled
            # Outros providers só são adicionados se tiverem API key E estiverem habilitados
            if config.name == "RunPod":
                if config.api_key:
                    self.add_provider(config)
            else:
                if config.api_key and config.enabled:
                    self.add_provider(config)
                    logger.info(f"ProviderManager: {config.name} habilitado conforme configuração")
                elif config.api_key and not config.enabled:
                    logger.info(f"ProviderManager: {config.name} desabilitado conforme llm_providers.json")
                else:
                    logger.debug(f"ProviderManager: {config.name} não configurado (sem API key)")
    
    def _load_limits_from_file(self) -> dict:
        """Carrega limites a partir do config centralizado."""
        cfg = get_concurrency_section("llm_limits", {})
        if cfg:
            return cfg
        logger.warning("ProviderManager: Configuração llm_limits ausente; usando vazio.")
        return {}
    
    def _load_provider_enabled_config(self) -> dict:
        """Carrega configuração de quais providers estão habilitados."""
        try:
            # Usar o config_loader do concurrency_manager para carregar o arquivo
            from app.services.concurrency_manager.config_loader import load_config
            providers_config = load_config("llm_providers")
            enabled_providers = providers_config.get("enabled_providers", {})
            
            logger.info("ProviderManager: Configuração de providers carregada:")
            for provider, enabled in enabled_providers.items():
                status = "✅ habilitado" if enabled else "❌ desabilitado"
                logger.info(f"  {provider}: {status}")
            
            return enabled_providers
        except Exception as e:
            logger.warning(f"ProviderManager: Erro ao carregar llm_providers.json: {e}")
            # Padrão: apenas RunPod habilitado
            logger.info("ProviderManager: Usando configuração padrão (apenas RunPod habilitado)")
            return {
                "RunPod": True,
                "Google Gemini": False,
                "OpenAI": False,
                "OpenRouter": False,
                "OpenRouter2": False,
                "OpenRouter3": False
            }
    
    def add_provider(self, config: ProviderConfig):
        """Adiciona um provider e categoriza por prioridade."""
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
        
        # v3.4: Categorizar provider por prioridade
        # RunPod → HIGH e NORMAL (provider primário para todas as chamadas)
        # Google Gemini (direto) → HIGH priority (Discovery/LinkSelector) - Fallback
        # Outros → NORMAL priority (Profile Building) - Fallback
        if config.name == "RunPod":
            # RunPod disponível para ambas as prioridades (primário)
            self._high_priority_providers.append(config.name)
            self._normal_priority_providers.append(config.name)
            priority_label = "HIGH+NORMAL"
        elif config.name == "Google Gemini":
            self._high_priority_providers.append(config.name)
            priority_label = "HIGH"
        else:
            self._normal_priority_providers.append(config.name)
            priority_label = "NORMAL"
        
        logger.info(f"ProviderManager: {config.name} adicionado (model={config.model}, queue={priority_label})")
    
    def remove_provider(self, name: str):
        """Remove um provider."""
        self._configs.pop(name, None)
        self._clients.pop(name, None)
        self._semaphores.pop(name, None)
        
        # v3.3: Remover das listas de prioridade
        if name in self._high_priority_providers:
            self._high_priority_providers.remove(name)
        if name in self._normal_priority_providers:
            self._normal_priority_providers.remove(name)
        # RunPod está em ambas as listas, então remove de ambas se necessário
    
    @property
    def available_providers(self) -> List[str]:
        """Lista de providers disponíveis."""
        return [name for name, config in self._configs.items() if config.enabled]
    
    @property
    def provider_priorities(self) -> Dict[str, int]:
        """Dict de prioridades dos providers."""
        return {name: config.priority for name, config in self._configs.items()}
    
    @property
    def provider_weights(self) -> Dict[str, int]:
        """Dict de pesos dos providers para distribuição proporcional."""
        return {name: config.weight for name, config in self._configs.items()}
    
    def get_weighted_provider_list(self, count: int) -> List[str]:
        """Gera lista de providers distribuídos por peso."""
        providers = self.available_providers
        if not providers:
            return []
        
        weights = self.provider_weights
        total_weight = sum(weights.get(p, 10) for p in providers)
        
        distributed = []
        for provider in providers:
            weight = weights.get(provider, 10)
            provider_count = max(1, int(count * weight / total_weight))
            distributed.extend([provider] * provider_count)
        
        while len(distributed) < count:
            best_provider = max(providers, key=lambda p: weights.get(p, 10))
            distributed.append(best_provider)
        
        random.shuffle(distributed)
        
        return distributed[:count]
    
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
        presence_penalty: float = 0.3,
        frequency_penalty: float = 0.4,
        seed: int = 42,
        response_format: dict = None,
        ctx_label: str = "",
        priority: LLMPriority = LLMPriority.NORMAL
    ) -> Tuple[str, float]:
        """
        Faz chamada a um provider com controle de rate limiting.
        
        v3.6: Parâmetros OpenAI-compatible (SGLang suporta via endpoint /v1/chat/completions)
              - presence_penalty: Penaliza tokens já aparecidos
              - frequency_penalty: Penaliza tokens frequentes
              - seed: Reprodutibilidade
        
        Args:
            provider: Nome do provider
            messages: Lista de mensagens
            timeout: Timeout opcional
            temperature: Temperatura da geração
            presence_penalty: Penaliza tokens já aparecidos (-2.0 a 2.0, padrão 0.3)
            frequency_penalty: Penaliza tokens frequentes (-2.0 a 2.0, padrão 0.4)
            seed: Seed para reprodutibilidade (padrão 42)
            response_format: Formato de resposta
            ctx_label: Label de contexto para logs
            priority: HIGH (Discovery/LinkSelector) ou NORMAL (Profile)
        
        Returns:
            Tuple de (response_content, latency_ms)
        
        Raises:
            ProviderRateLimitError, ProviderTimeoutError, 
            ProviderBadRequestError, ProviderError
        """
        config = self._configs.get(provider)
        if not config:
            raise ProviderError(f"Provider '{provider}' não encontrado")
        
        client = self._clients.get(provider)
        if not client:
            raise ProviderError(f"Cliente não inicializado para '{provider}'")
        
        semaphore = self._semaphores.get(provider)
        actual_timeout = timeout or config.timeout
        
        # Estimar tokens da requisição
        estimated_tokens = estimate_tokens(messages)
        
        # Verificar se o conteúdo cabe no context window do provider
        safe_input_tokens = self._rate_limiter.get_safe_input_tokens(provider)
        context_window = self._rate_limiter.get_context_window(provider)

        # CORREÇÃO CRÍTICA: Validação mais conservadora para RunPod
        # O SGLang calcula internamente: max_tokens = context_window - prompt_tokens - safety_margin
        # Quando prompt_tokens > context_window, max_tokens fica negativo causando "max_tokens must be at least 1, got -XXXX"
        is_runpod = "runpod" in provider.lower() or "runpod" in config.base_url.lower()
        if is_runpod:
            # Para RunPod, ser ainda mais conservador: usar apenas 80% do context window
            # Isso deixa margem para system prompts internos e formatação do SGLang
            safe_input_tokens = int(context_window * 0.8)  # 80% do context window

        if estimated_tokens > safe_input_tokens:
            logger.error(
                f"{ctx_label}❌ Conteúdo muito grande para {provider}! "
                f"Estimado: {estimated_tokens:,} tokens, "
                f"Limite seguro: {safe_input_tokens:,} tokens, "
                f"Context window: {context_window:,} tokens"
                f"{' (RunPod: usando 80% do context window)' if is_runpod else ''}"
            )
            raise ProviderBadRequestError(
                f"Conteúdo excede context window do {provider}. "
                f"Estimado: {estimated_tokens:,}, Limite: {safe_input_tokens:,}"
            )
        
        if priority == LLMPriority.HIGH:
            async with self._counter_lock:
                self._high_priority_active += 1
                self._high_priority_done.clear()
            
            try:
                return await self._execute_llm_call(
                    client, config, semaphore, messages,
                    actual_timeout, temperature, presence_penalty, frequency_penalty, seed,
                    response_format, ctx_label, provider, estimated_tokens
                )
            finally:
                async with self._counter_lock:
                    self._high_priority_active -= 1
                    if self._high_priority_active == 0:
                        self._high_priority_done.set()
        else:
            await self._high_priority_done.wait()
            
            return await self._execute_llm_call(
                client, config, semaphore, messages,
                actual_timeout, temperature, presence_penalty, frequency_penalty, seed,
                response_format, ctx_label, provider, estimated_tokens
            )
    
    async def _execute_llm_call(
        self,
        client: AsyncOpenAI,
        config: ProviderConfig,
        semaphore: asyncio.Semaphore,
        messages: List[dict],
        timeout: float,
        temperature: float,
        presence_penalty: float,
        frequency_penalty: float,
        seed: int,
        response_format: dict,
        ctx_label: str,
        provider: str,
        estimated_tokens: int
    ) -> Tuple[str, float]:
        """
        Executa a chamada LLM real com controle de rate limiting.
        
        v3.6: Parâmetros OpenAI-compatible para evitar repetições e loops
              - presence_penalty: Penaliza tokens já aparecidos
              - frequency_penalty: Penaliza tokens frequentes  
              - seed: Reprodutibilidade
        
        v4.0: Suporte a Structured Output via SGLang/XGrammar
              - SGLang suporta json_schema nativo com XGrammar
              - Habilita response_format para RunPod/SGLang
        """
        
        # 1. Adquirir permissão do rate limiter (RPM + TPM)
        # Timeout reduzido para 5s (fail fast) para evitar lock contenção
        rate_acquired = await self._rate_limiter.acquire(
            provider=provider,
            estimated_tokens=estimated_tokens,
            timeout=min(timeout, 5.0)
        )
        
        if not rate_acquired:
            logger.warning(
                f"{ctx_label}ProviderManager: {provider} rate limit local atingido "
                f"(tokens={estimated_tokens})"
            )
            raise ProviderRateLimitError(f"Rate limit local para {provider}")
        
        # 2. Usar semáforo de concorrência
        async with semaphore:
            start_time = time.perf_counter()
            
            try:
                # Detectar SGLang/RunPod (agora suporta response_format via XGrammar)
                is_runpod = "runpod" in provider.lower() or "runpod" in config.base_url.lower()
                is_sglang = is_runpod or "sglang" in config.base_url.lower()
                
                # v8.0: max_tokens ADAPTATIVO baseado no input
                # Input pequeno/médio → max_tokens menor (reduz risco de runaway)
                # Input grande → max_tokens maior (permite resposta completa)
                max_output_tokens_limit = self._rate_limiter.get_max_output_tokens(provider)
                
                if estimated_tokens < 3000:
                    # Input pequeno: limitar output a 1200 tokens (evita runaway)
                    max_output_tokens = min(1200, max_output_tokens_limit)
                    logger.debug(
                        f"{ctx_label}ProviderManager: Input pequeno ({estimated_tokens} tokens), "
                        f"limitando max_tokens a {max_output_tokens}"
                    )
                elif estimated_tokens < 8000:
                    # Input médio: limitar output a 2000 tokens
                    max_output_tokens = min(2000, max_output_tokens_limit)
                    logger.debug(
                        f"{ctx_label}ProviderManager: Input médio ({estimated_tokens} tokens), "
                        f"limitando max_tokens a {max_output_tokens}"
                    )
                else:
                    # Input grande: usar limite do provider (aceita risco de runaway)
                    max_output_tokens = max_output_tokens_limit
                    logger.debug(
                        f"{ctx_label}ProviderManager: Input grande ({estimated_tokens} tokens), "
                        f"usando max_tokens padrão: {max_output_tokens}"
                    )

                
                request_params = {
                    "model": config.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_output_tokens,  # Garantir valor explícito e válido
                    "presence_penalty": presence_penalty,
                    "frequency_penalty": frequency_penalty,
                    "seed": seed
                }
                
                # v3.6: Parâmetros anti-repetição HABILITADOS (OpenAI-compatible)
                # SGLang suporta presence_penalty e frequency_penalty via /v1/chat/completions
                # Referência: https://www.aidoczh.com/sglang/backend/openai_api_completions.html
                logger.debug(
                    f"{ctx_label}ProviderManager: Parâmetros anti-repetição habilitados "
                    f"(provider={provider}, presence_penalty={presence_penalty}, "
                    f"frequency_penalty={frequency_penalty}, seed={seed})"
                )
                
                # v4.0: SGLang com XGrammar suporta json_schema nativo
                # Habilitar response_format para todos os providers que suportam
                if response_format:
                    response_format_type = response_format.get("type", "")
                    
                    if is_sglang:
                        # SGLang: suporta json_schema e json_object via XGrammar
                        if response_format_type == "json_schema":
                            # json_schema: usar diretamente (XGrammar garante formato)
                            request_params["response_format"] = response_format
                            logger.debug(
                                f"{ctx_label}ProviderManager: {provider} usando json_schema "
                                f"(SGLang/XGrammar structured output)"
                            )
                        elif response_format_type == "json_object":
                            # json_object: SGLang também suporta
                            request_params["response_format"] = response_format
                            logger.debug(
                                f"{ctx_label}ProviderManager: {provider} usando json_object "
                                f"(SGLang structured output)"
                            )
                        else:
                            # Formato desconhecido: fallback para reforço de prompt
                            if messages and messages[-1].get("role") == "user":
                                user_msg = messages[-1]["content"]
                                messages[-1]["content"] = f"""{user_msg}

IMPORTANTE: Retorne APENAS um objeto JSON válido. Sem markdown, sem explicações."""
                            logger.debug(
                                f"{ctx_label}ProviderManager: {provider} usando reforço de prompt "
                                f"(formato {response_format_type} não suportado)"
                            )
                    else:
                        # Outros providers: usar response_format normalmente
                        request_params["response_format"] = response_format
                
                # Log dos parâmetros da requisição para debug
                logger.debug(
                    f"{ctx_label}ProviderManager: {provider} chamando com model={request_params.get('model')}, "
                    f"temperature={temperature}, "
                    f"presence_penalty={request_params.get('presence_penalty', 'N/A')}, "
                    f"frequency_penalty={request_params.get('frequency_penalty', 'N/A')}, "
                    f"seed={request_params.get('seed', 'N/A')}, "
                    f"response_format={request_params.get('response_format')}"
                )
                
                # Usar asyncio.wait_for para aplicar timeout se necessário
                try:
                    if timeout:
                        response = await asyncio.wait_for(
                            client.chat.completions.create(**request_params),
                            timeout=timeout
                        )
                    else:
                        response = await client.chat.completions.create(**request_params)
                except BadRequestError as bad_req:
                    bad_req_str = str(bad_req).lower()
                    
                    # Remover parâmetros não suportados e tentar novamente
                    retry_without_params = False
                    
                    # Se erro com presence_penalty, frequency_penalty ou seed
                    if "presence_penalty" in bad_req_str or "unexpected keyword argument" in bad_req_str:
                        if "presence_penalty" in request_params:
                            logger.warning(
                                f"{ctx_label}ProviderManager: {provider} não suporta presence_penalty, "
                                f"removendo e tentando novamente"
                            )
                            request_params.pop("presence_penalty", None)
                            retry_without_params = True
                    
                    if "frequency_penalty" in bad_req_str:
                        if "frequency_penalty" in request_params:
                            logger.warning(
                                f"{ctx_label}ProviderManager: {provider} não suporta frequency_penalty, "
                                f"removendo e tentando novamente"
                            )
                            request_params.pop("frequency_penalty", None)
                            retry_without_params = True
                    
                    if "seed" in bad_req_str:
                        if "seed" in request_params:
                            logger.warning(
                                f"{ctx_label}ProviderManager: {provider} não suporta seed, "
                                f"removendo e tentando novamente"
                            )
                            request_params.pop("seed", None)
                            retry_without_params = True
                    
                    # Se erro com response_format
                    if "response_format" in bad_req_str or (not retry_without_params and response_format and "response_format" in request_params):
                        logger.warning(
                            f"{ctx_label}ProviderManager: {provider} BAD_REQUEST com response_format, "
                            f"removendo e tentando novamente: {bad_req}"
                        )
                        request_params.pop("response_format", None)
                        # Adicionar reforço no prompt se ainda não tiver
                        if messages and messages[-1].get("role") == "user" and not is_runpod:
                            user_msg = messages[-1]["content"]
                            messages[-1]["content"] = f"""{user_msg}

IMPORTANTE: Retorne APENAS um objeto JSON válido. Sem markdown, sem explicações."""
                        retry_without_params = True
                    
                    # Tentar novamente sem os parâmetros problemáticos
                    if retry_without_params:
                        if timeout:
                            response = await asyncio.wait_for(
                                client.chat.completions.create(**request_params),
                                timeout=timeout
                            )
                        else:
                            response = await client.chat.completions.create(**request_params)
                    else:
                        raise
                
                latency_ms = (time.perf_counter() - start_time) * 1000
                
                # Debug detalhado para resposta vazia
                if not response.choices:
                    logger.error(f"{ctx_label}ProviderManager: {provider} resposta sem choices. Response: {response}")
                    raise ProviderError(f"{provider} retornou resposta sem choices")
                
                if not response.choices[0]:
                    logger.error(f"{ctx_label}ProviderManager: {provider} choices[0] está None. Response: {response}")
                    raise ProviderError(f"{provider} retornou choices[0] None")
                
                if not hasattr(response.choices[0], 'message'):
                    logger.error(f"{ctx_label}ProviderManager: {provider} choices[0] sem atributo 'message'. Response: {response.choices[0]}")
                    raise ProviderError(f"{provider} retornou choices[0] sem message")
                
                message = response.choices[0].message
                if not hasattr(message, 'content') or not message.content:
                    # Log detalhado para debug
                    logger.error(
                        f"{ctx_label}ProviderManager: {provider} retornou resposta vazia. "
                        f"Response object: {type(response)}, "
                        f"Choices count: {len(response.choices) if response.choices else 0}, "
                        f"Message type: {type(message) if message else None}, "
                        f"Content attr exists: {hasattr(message, 'content') if message else False}, "
                        f"Content value: {repr(getattr(message, 'content', None))}"
                    )
                
                # v8.0: LOOP DETECTOR - Detectar geração degenerada
                # Se detectar loop, lançar exceção para retry seletivo
                content = message.content
                if _detect_repetition_loop(content, ctx_label):
                    logger.warning(
                        f"{ctx_label}ProviderManager: Loop de repetição detectado "
                        f"(content_len={len(content)}, latency={latency_ms:.0f}ms)"
                    )
                    raise ProviderDegenerationError(
                        f"Loop de repetição detectado na resposta de {provider}"
                    )
                    raise ProviderError(f"{provider} retornou resposta vazia")
                
                content = message.content.strip()
                
                # Log com tokens reais e comparação com estimativa
                actual_tokens = getattr(response, 'usage', None)
                if actual_tokens and actual_tokens.prompt_tokens:
                    actual_prompt_tokens = actual_tokens.prompt_tokens
                    diff = actual_prompt_tokens - estimated_tokens
                    diff_percent = (diff / estimated_tokens * 100) if estimated_tokens > 0 else 0
                    
                    # Log detalhado para RunPod (comparação importante)
                    if "runpod" in provider.lower() or "runpod" in config.base_url.lower():
                        if abs(diff_percent) > 10:  # Diferença > 10%
                            logger.warning(
                                f"{ctx_label}ProviderManager: {provider} - Discrepância significativa de tokens: "
                                f"estimado={estimated_tokens:,}, real={actual_prompt_tokens:,}, "
                                f"diff={diff:+,} ({diff_percent:+.1f}%)"
                            )
                        else:
                            logger.debug(
                                f"{ctx_label}ProviderManager: {provider} - Tokens: estimado={estimated_tokens:,}, "
                                f"real={actual_prompt_tokens:,}, diff={diff:+,} ({diff_percent:+.1f}%)"
                            )
                    else:
                        logger.debug(
                            f"{ctx_label}ProviderManager: {provider} - {len(content)} chars em {latency_ms:.0f}ms "
                            f"(tokens: in={actual_prompt_tokens}, out={actual_tokens.completion_tokens})"
                        )
                else:
                    logger.debug(
                        f"{ctx_label}ProviderManager: {provider} - {len(content)} chars em {latency_ms:.0f}ms"
                    )
                
                return content, latency_ms
            
            except RateLimitError as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.warning(f"{ctx_label}ProviderManager: {provider} RATE_LIMIT (API) após {latency_ms:.0f}ms")
                raise ProviderRateLimitError(str(e))
            
            except APITimeoutError as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.warning(f"{ctx_label}ProviderManager: {provider} TIMEOUT após {latency_ms:.0f}ms")
                raise ProviderTimeoutError(str(e))
            
            except BadRequestError as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.error(f"{ctx_label}ProviderManager: {provider} BAD_REQUEST: {e}")
                raise ProviderBadRequestError(str(e))
            
            except asyncio.TimeoutError:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.warning(f"{ctx_label}ProviderManager: {provider} ASYNC_TIMEOUT após {latency_ms:.0f}ms")
                raise ProviderTimeoutError("Async timeout")
            
            except Exception as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.error(f"{ctx_label}ProviderManager: {provider} ERROR: {type(e).__name__}: {e}")
                raise ProviderError(str(e))
    
    async def call_with_retry(
        self,
        provider: str,
        messages: List[dict],
        max_retries: int = 2,
        retry_delay: float = 1.0,
        **kwargs
    ) -> Tuple[str, float]:
        """Faz chamada com retry automático."""
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                return await self.call(provider, messages, **kwargs)
            
            except ProviderBadRequestError:
                raise
            
            except (ProviderRateLimitError, ProviderTimeoutError, ProviderError) as e:
                last_error = e
                
                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt)
                    logger.info(
                        f"ProviderManager: {provider} retry {attempt + 1}/{max_retries} "
                        f"após {delay:.1f}s ({type(e).__name__})"
                    )
                    await asyncio.sleep(delay)
        
        raise last_error
    
    def get_status(self) -> dict:
        """Retorna status de todos os providers."""
        status = {
            "_queues": {
                "high_priority_providers": self._high_priority_providers,
                "normal_priority_providers": self._normal_priority_providers
            }
        }
        for name, config in self._configs.items():
            semaphore = self._semaphores.get(name)
            rate_status = self._rate_limiter.get_status().get(name, {})
            queue = "HIGH" if name in self._high_priority_providers else "NORMAL"
            status[name] = {
                "enabled": config.enabled,
                "model": config.model,
                "priority": config.priority,
                "queue": queue,
                "max_concurrent": config.max_concurrent,
                "semaphore_locked": semaphore.locked() if semaphore else None,
                "rate_limiter": rate_status
            }
        return status
    
    def get_rate_limiter_status(self) -> dict:
        """Retorna status detalhado do rate limiter."""
        return self._rate_limiter.get_status()


# Instância singleton
provider_manager = ProviderManager()
