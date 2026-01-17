"""
LLM Call Manager - Interface unificada para gerenciamento de chamadas LLM.

v3.0: Integrado com concurrency_manager para visão global de recursos.

Esta classe fornece uma interface simplificada para todos os serviços
que precisam fazer chamadas LLM, centralizando:
- Seleção de provider (weighted/round-robin)
- Rate limiting (RPM + TPM)
- Health monitoring
- Sistema de prioridades
- Fallback automático
- Integração com Global Orchestrator (visão global de recursos)
"""

import asyncio
import logging
from typing import List, Optional, Tuple, Dict

from .priority import LLMPriority
from .provider_manager import (
    provider_manager,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderBadRequestError
)
from .queue_manager import create_queue_manager
from .health_monitor import health_monitor, FailureType

# Integração com concurrency_manager
from app.services.concurrency_manager import (
    global_orchestrator,
    ResourceType,
)

logger = logging.getLogger(__name__)


class LLMCallManager:
    """
    Interface centralizada para chamadas LLM.
    
    v3.0: Agora integrado com Global Orchestrator para:
    - Visão global de recursos LLM
    - Prevenção de sobrecarga do sistema
    - Métricas centralizadas
    
    Todos os serviços devem usar esta classe para fazer chamadas LLM,
    garantindo consistência no gerenciamento de recursos.
    
    Exemplo de uso:
        manager = get_llm_manager()
        response = await manager.call(
            messages=[{"role": "user", "content": "Hello"}],
            priority=LLMPriority.HIGH,
            ctx_label="[Discovery]"
        )
    """
    
    def __init__(self):
        self.provider_manager = provider_manager
        self.health_monitor = health_monitor
        self.orchestrator = global_orchestrator
        self._queue_manager = None
        self._use_orchestrator = True  # Flag para habilitar/desabilitar integração
    
    @property
    def queue_manager(self):
        """Lazy initialization do queue manager."""
        if self._queue_manager is None:
            self._queue_manager = create_queue_manager(
                providers=self.provider_manager.available_providers,
                priorities=self.provider_manager.provider_weights
            )
        return self._queue_manager
    
    @property
    def available_providers(self) -> List[str]:
        """Lista de providers disponíveis."""
        return self.provider_manager.available_providers
    
    @property
    def provider_weights(self) -> Dict[str, int]:
        """Pesos dos providers para distribuição."""
        return self.provider_manager.provider_weights
    
    async def _acquire_orchestrator_slot(self, timeout: float = 30.0, request_id: Optional[str] = None) -> bool:
        """
        Adquire slot do Global Orchestrator para chamada LLM.
        
        Isso garante que o sistema tenha visão global de quantas
        chamadas LLM estão ocorrendo simultaneamente.
        """
        if not self._use_orchestrator:
            return True
        
        try:
            return await self.orchestrator.acquire(
                ResourceType.LLM,
                amount=1,
                timeout=timeout,
                request_id=request_id
            )
        except Exception as e:
            logger.warning(f"LLMCallManager: Erro ao adquirir slot do orchestrator: {e}")
            return True  # Continuar mesmo se falhar
    
    def _release_orchestrator_slot(self):
        """Libera slot do Global Orchestrator."""
        if not self._use_orchestrator:
            return
        
        try:
            self.orchestrator.release(ResourceType.LLM, amount=1)
        except Exception as e:
            logger.warning(f"LLMCallManager: Erro ao liberar slot do orchestrator: {e}")
    
    async def call(
        self,
        messages: List[dict],
        priority: LLMPriority = LLMPriority.NORMAL,
        timeout: float = None,
        temperature: float = 0.0,
        response_format: dict = None,
        ctx_label: str = "",
        max_retries: int = 3,
        provider: str = None,
        request_id: Optional[str] = None
    ) -> Tuple[str, float]:
        """
        Faz chamada LLM com seleção automática de provider.
        
        v3.4: HIGH bypassa orchestrator (usa rate limiter próprio do Gemini)
              NORMAL usa orchestrator para controle global
        
        Args:
            messages: Lista de mensagens para o LLM
            priority: Nível de prioridade (HIGH para Discovery/LinkSelector)
            timeout: Timeout em segundos (opcional)
            temperature: Temperatura da geração
            response_format: Formato de resposta (ex: {"type": "json_object"})
            ctx_label: Label de contexto para logs
            max_retries: Número máximo de tentativas
            provider: Provider específico (opcional, se None usa weighted selection)
        
        Returns:
            Tuple de (response_content, latency_ms)
        
        Raises:
            ProviderError: Se todos os providers falharem
        """
        # v3.4: HIGH (Discovery/LinkSelector) bypassa orchestrator
        # Gemini tem seu próprio rate limiter, não precisa competir com Profile Building
        use_orchestrator = priority != LLMPriority.HIGH
        
        if use_orchestrator:
            orchestrator_timeout = timeout or 30.0
            acquired = await self._acquire_orchestrator_slot(orchestrator_timeout, request_id=request_id)
            
            if not acquired:
                logger.warning(f"{ctx_label}LLMCallManager: Sistema sobrecarregado, timeout no orchestrator")
                raise ProviderError("Sistema sobrecarregado - timeout aguardando slot LLM")
        
        try:
            return await self._do_call(
                messages=messages,
                priority=priority,
                timeout=timeout,
                temperature=temperature,
                response_format=response_format,
                ctx_label=ctx_label,
                max_retries=max_retries,
                provider=provider,
                request_id=request_id
            )
        finally:
            if use_orchestrator:
                self._release_orchestrator_slot()
    
    def _get_providers_for_priority(self, priority: LLMPriority) -> List[str]:
        """
        Retorna lista de providers disponíveis para a prioridade.
        
        v3.3: Separação de filas
        - HIGH → Google Gemini exclusivo (Discovery, LinkSelector)
        - NORMAL → OpenAI + OpenRouter (Profile Building)
        """
        if priority == LLMPriority.HIGH:
            providers = self.provider_manager._high_priority_providers
            if providers:
                return providers
            # Fallback se não há provider HIGH configurado
            logger.warning("LLMCallManager: Sem provider HIGH, usando todos")
            return self.available_providers
        else:
            providers = self.provider_manager._normal_priority_providers
            if providers:
                return providers
            # Fallback se não há provider NORMAL configurado
            logger.warning("LLMCallManager: Sem provider NORMAL, usando todos")
            return self.available_providers
    
    async def _do_call(
        self,
        messages: List[dict],
        priority: LLMPriority,
        timeout: float,
        temperature: float,
        response_format: dict,
        ctx_label: str,
        max_retries: int,
        provider: str,
        request_id: Optional[str] = None
    ) -> Tuple[str, float]:
        """Executa a chamada LLM propriamente dita."""
        providers_tried = []
        last_error = None
        
        # Determinar substage para tracking de retries
        substage = "profile_llm" if priority == LLMPriority.NORMAL else "discovery_llm"
        if "LinkSelector" in ctx_label:
            substage = "link_selector_llm"
        
        # v3.3: Obter providers específicos para a prioridade
        priority_providers = self._get_providers_for_priority(priority)
        priority_weights = {p: self.provider_weights.get(p, 10) for p in priority_providers}
        
        # Backoff exponencial: delay inicial de 5s, multiplicado por 2 a cada tentativa (5s -> 10s -> 20s)
        retry_base_delay = 5.0
        
        for attempt in range(max_retries):
            # Selecionar provider da fila correta
            if provider and attempt == 0 and provider in priority_providers:
                selected_provider = provider
            else:
                selected_provider = self.queue_manager.get_weighted_provider(
                    exclude=providers_tried,
                    weights=priority_weights  # Usar apenas pesos dos providers da fila
                )
            
            if not selected_provider:
                logger.error(f"{ctx_label}LLMCallManager: Nenhum provider disponível para {priority.name}")
                break
            
            providers_tried.append(selected_provider)
            
            try:
                content, latency_ms = await self.provider_manager.call(
                    provider=selected_provider,
                    messages=messages,
                    timeout=timeout,
                    temperature=temperature,
                    response_format=response_format,
                    ctx_label=ctx_label,
                    priority=priority
                )
                
                # Registrar sucesso
                self.health_monitor.record_success(selected_provider, latency_ms)
                
                logger.debug(
                    f"{ctx_label}LLMCallManager: Sucesso com {selected_provider} "
                    f"em {latency_ms:.0f}ms"
                )
                
                return content, latency_ms
            
            except ProviderBadRequestError as e:
                # Bad request não faz retry
                self.health_monitor.record_failure(selected_provider, FailureType.BAD_REQUEST)
                logger.error(f"{ctx_label}LLMCallManager: BadRequest com {selected_provider}: {e}")
                raise
            
            except ProviderRateLimitError as e:
                self.health_monitor.record_failure(selected_provider, FailureType.RATE_LIMIT)
                logger.warning(f"{ctx_label}LLMCallManager: RateLimit com {selected_provider}")
                last_error = e
                # Backoff exponencial antes do próximo retry
                if attempt < max_retries - 1:
                    delay = retry_base_delay * (2 ** attempt)
                    logger.info(f"{ctx_label}LLMCallManager: Retry {attempt + 1}/{max_retries} após {delay:.1f}s (backoff exponencial)")
                    await asyncio.sleep(delay)
                continue
            
            except ProviderTimeoutError as e:
                self.health_monitor.record_failure(selected_provider, FailureType.TIMEOUT)
                logger.warning(f"{ctx_label}LLMCallManager: Timeout com {selected_provider}")
                last_error = e
                # Backoff exponencial antes do próximo retry
                if attempt < max_retries - 1:
                    delay = retry_base_delay * (2 ** attempt)
                    logger.info(f"{ctx_label}LLMCallManager: Retry {attempt + 1}/{max_retries} após {delay:.1f}s (backoff exponencial)")
                    await asyncio.sleep(delay)
                continue
            
            except ProviderError as e:
                self.health_monitor.record_failure(selected_provider, FailureType.ERROR)
                logger.warning(f"{ctx_label}LLMCallManager: Erro com {selected_provider}: {e}")
                last_error = e
                # Backoff exponencial antes do próximo retry
                if attempt < max_retries - 1:
                    delay = retry_base_delay * (2 ** attempt)
                    logger.info(f"{ctx_label}LLMCallManager: Retry {attempt + 1}/{max_retries} após {delay:.1f}s (backoff exponencial)")
                    await asyncio.sleep(delay)
                continue
        
        # Todas tentativas falharam
        error_msg = f"Todos providers falharam após {max_retries} tentativas"
        logger.error(f"{ctx_label}LLMCallManager: {error_msg}")
        raise ProviderError(error_msg) if not last_error else last_error
    
    async def call_with_fallback(
        self,
        messages: List[dict],
        priority: LLMPriority = LLMPriority.NORMAL,
        timeout: float = None,
        temperature: float = 0.0,
        response_format: dict = None,
        ctx_label: str = ""
    ) -> Optional[Tuple[str, float]]:
        """
        Faz chamada LLM com fallback silencioso.
        
        Diferente de call(), não levanta exceção se falhar.
        Útil para casos onde a chamada LLM é opcional.
        
        Returns:
            Tuple de (response_content, latency_ms) ou None se falhar
        """
        try:
            return await self.call(
                messages=messages,
                priority=priority,
                timeout=timeout,
                temperature=temperature,
                response_format=response_format,
                ctx_label=ctx_label
            )
        except Exception as e:
            logger.warning(f"{ctx_label}LLMCallManager: Chamada falhou (fallback): {e}")
            return None
    
    def get_provider_for_distribution(self, exclude: List[str] = None) -> Optional[str]:
        """
        Obtém um provider usando distribuição weighted.
        
        Útil para distribuir trabalho entre múltiplos providers.
        
        Args:
            exclude: Lista de providers a excluir
        
        Returns:
            Nome do provider selecionado ou None
        """
        return self.queue_manager.get_weighted_provider(
            exclude=exclude,
            weights=self.provider_weights
        )
    
    def get_distributed_providers(self, count: int) -> List[str]:
        """
        Obtém lista de providers distribuída por peso.
        
        Útil para processar múltiplos itens em paralelo.
        
        Args:
            count: Número de providers necessários
        
        Returns:
            Lista de nomes de providers
        """
        return self.provider_manager.get_weighted_provider_list(count)
    
    def get_status(self) -> dict:
        """Retorna status completo do sistema."""
        status = {
            "providers": self.provider_manager.get_status(),
            "health": self.health_monitor.get_all_metrics(),
            "queue": self.queue_manager.get_status() if self._queue_manager else {}
        }
        
        # Adicionar status do orchestrator se integrado
        if self._use_orchestrator:
            try:
                orchestrator_status = self.orchestrator.get_utilization(ResourceType.LLM)
                status["orchestrator"] = orchestrator_status
            except Exception:
                pass
        
        return status
    
    def set_orchestrator_enabled(self, enabled: bool):
        """
        Habilita/desabilita integração com Global Orchestrator.
        
        Útil para debugging ou quando se quer usar apenas o rate limiter interno.
        """
        self._use_orchestrator = enabled
        logger.info(f"LLMCallManager: Orchestrator {'habilitado' if enabled else 'desabilitado'}")


# Instância singleton
_llm_manager: Optional[LLMCallManager] = None


def get_llm_manager() -> LLMCallManager:
    """Retorna instância singleton do LLMCallManager."""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMCallManager()
    return _llm_manager
