"""
Serviço principal de análise de conteúdo por LLM v2.0.
Orquestra chunking, seleção de provider, processamento e consolidação.
"""

import asyncio
import time
import logging
from typing import List, Optional

from app.schemas.profile import CompanyProfile
from app.services.learning import (
    failure_tracker, FailureModule, FailureType as LearningFailureType
)
from .constants import llm_config, SYSTEM_PROMPT
from .content_chunker import chunk_content, estimate_tokens
from .profile_merger import merge_profiles
from .response_normalizer import normalize_llm_response
from .health_monitor import health_monitor, FailureType
from .provider_manager import (
    provider_manager,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderBadRequestError
)
from .queue_manager import create_queue_manager

logger = logging.getLogger(__name__)


class LLMService:
    """
    Serviço de análise LLM com balanceamento e fallback automático.
    """
    
    def __init__(self):
        self.provider_manager = provider_manager
        self.health_monitor = health_monitor
        self.queue_manager = create_queue_manager(
            providers=provider_manager.available_providers,
            priorities=provider_manager.provider_priorities
        )
    
    async def analyze(self, content: str, ctx_label: str = "") -> CompanyProfile:
        """
        Analisa conteúdo e extrai perfil da empresa.
        
        Args:
            content: Texto para análise
            ctx_label: Label de contexto para logs
        
        Returns:
            CompanyProfile com dados extraídos
        """
        start_time = time.perf_counter()
        tokens = estimate_tokens(content)
        logger.info(f"{ctx_label}LLMService: Analisando {tokens:,} tokens estimados")
        
        # Chunking
        chunks = chunk_content(content, llm_config.max_chunk_tokens)
        logger.info(f"{ctx_label}LLMService: {len(chunks)} chunks gerados")
        
        if len(chunks) == 1:
            return await self._process_single_chunk(chunks[0], start_time, ctx_label)
        
        return await self._process_multiple_chunks(chunks, start_time, ctx_label)
    
    async def _process_single_chunk(
        self,
        chunk: str,
        start_time: float,
        ctx_label: str = ""
    ) -> CompanyProfile:
        """Processa chunk único com fallback entre providers."""
        providers_tried = []
        
        for attempt in range(len(self.provider_manager.available_providers)):
            selection = await self.queue_manager.get_best_provider(
                estimated_tokens=1,
                exclude=providers_tried
            )
            
            if not selection:
                logger.error(f"{ctx_label}LLMService: Nenhum provider disponível")
                break
            
            provider = selection.provider
            providers_tried.append(provider)
            
            try:
                profile = await self._call_provider(provider, chunk, ctx_label)
                
                duration = time.perf_counter() - start_time
                logger.info(f"{ctx_label}LLMService: Sucesso com {provider} em {duration:.2f}s")
                
                return profile
            
            except ProviderBadRequestError:
                logger.error(f"{ctx_label}LLMService: BadRequest com {provider}, abortando")
                break
            
            except (ProviderRateLimitError, ProviderTimeoutError, ProviderError) as e:
                logger.warning(f"{ctx_label}LLMService: {provider} falhou: {type(e).__name__}")
                continue
        
        duration = time.perf_counter() - start_time
        logger.error(f"{ctx_label}LLMService: Todos providers falharam em {duration:.2f}s")
        return CompanyProfile()
    
    async def _process_multiple_chunks(
        self,
        chunks: List[str],
        start_time: float,
        ctx_label: str = ""
    ) -> CompanyProfile:
        """Processa múltiplos chunks em paralelo."""
        providers = self.provider_manager.available_providers
        
        logger.info(
            f"{ctx_label}LLMService: Processando {len(chunks)} chunks com "
            f"{len(providers)} providers"
        )
        
        # Criar tasks distribuindo entre providers
        tasks = []
        for i, chunk in enumerate(chunks):
            provider_idx = i % len(providers)
            provider = providers[provider_idx]
            tasks.append(self._process_chunk_with_fallback(chunk, i + 1, len(chunks), provider, ctx_label))
        
        # Executar em paralelo com timeout global
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=240.0
            )
        except asyncio.TimeoutError:
            logger.error(f"{ctx_label}LLMService: Timeout global (240s)")
            results = []
        
        # Filtrar resultados válidos
        valid_profiles = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"{ctx_label}LLMService: Chunk {i+1} falhou: {result}")
            elif result is not None:
                valid_profiles.append(result)
        
        if not valid_profiles:
            duration = time.perf_counter() - start_time
            logger.error(f"{ctx_label}LLMService: Todos chunks falharam em {duration:.2f}s")
            return CompanyProfile()
        
        # Consolidar resultados
        logger.info(f"{ctx_label}LLMService: Consolidando {len(valid_profiles)} perfis")
        final_profile = merge_profiles(valid_profiles)
        
        duration = time.perf_counter() - start_time
        logger.info(f"{ctx_label}LLMService: Concluído em {duration:.2f}s")
        
        return final_profile
    
    async def _process_chunk_with_fallback(
        self,
        chunk: str,
        chunk_num: int,
        total_chunks: int,
        primary_provider: str,
        ctx_label: str = ""
    ) -> Optional[CompanyProfile]:
        """Processa chunk com fallback entre providers."""
        providers_order = [primary_provider] + [
            p for p in self.provider_manager.available_providers
            if p != primary_provider
        ]
        
        for provider in providers_order:
            try:
                logger.debug(f"{ctx_label}LLMService: Chunk {chunk_num}/{total_chunks} -> {provider}")
                profile = await self._call_provider(provider, chunk, ctx_label)
                logger.info(f"{ctx_label}LLMService: Chunk {chunk_num}/{total_chunks} OK com {provider}")
                return profile
            
            except ProviderBadRequestError:
                logger.error(f"{ctx_label}LLMService: Chunk {chunk_num} BadRequest, abortando")
                return None
            
            except Exception as e:
                logger.warning(
                    f"{ctx_label}LLMService: Chunk {chunk_num} falhou com {provider}: "
                    f"{type(e).__name__}"
                )
                continue
        
        logger.error(f"{ctx_label}LLMService: Chunk {chunk_num}/{total_chunks} falhou em todos providers")
        return None
    
    async def _call_provider(self, provider: str, content: str, ctx_label: str = "") -> CompanyProfile:
        """
        Faz chamada ao provider e processa resposta.
        
        Args:
            provider: Nome do provider
            content: Conteúdo para análise
            ctx_label: Label de contexto para logs
        
        Returns:
            CompanyProfile
        
        Raises:
            ProviderError variantes em caso de falha
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analise este conteúdo e extraia os dados em Português:\n\n{content}"}
        ]
        
        try:
            response_content, latency_ms = await self.provider_manager.call(
                provider=provider,
                messages=messages,
                response_format={"type": "json_object"},
                ctx_label=ctx_label
            )
            
            # Registrar sucesso
            self.health_monitor.record_success(provider, latency_ms)
            
            # Processar resposta
            return self._parse_response(response_content)
        
        except ProviderRateLimitError as e:
            self.health_monitor.record_failure(provider, FailureType.RATE_LIMIT)
            failure_tracker.record_failure(
                module=FailureModule.LLM,
                error_type=LearningFailureType.LLM_RATE_LIMIT,
                url=provider,
                error_message=str(e),
                context={"provider": provider, "tokens_estimated": estimate_tokens(content)}
            )
            raise
        
        except ProviderTimeoutError as e:
            self.health_monitor.record_failure(provider, FailureType.TIMEOUT)
            failure_tracker.record_failure(
                module=FailureModule.LLM,
                error_type=LearningFailureType.LLM_TIMEOUT,
                url=provider,
                error_message=str(e),
                context={"provider": provider, "tokens_estimated": estimate_tokens(content)}
            )
            raise
        
        except ProviderBadRequestError as e:
            self.health_monitor.record_failure(provider, FailureType.BAD_REQUEST)
            failure_tracker.record_failure(
                module=FailureModule.LLM,
                error_type=LearningFailureType.LLM_BAD_REQUEST,
                url=provider,
                error_message=str(e),
                context={"provider": provider}
            )
            raise
        
        except ProviderError as e:
            self.health_monitor.record_failure(provider, FailureType.ERROR)
            failure_tracker.record_failure(
                module=FailureModule.LLM,
                error_type=LearningFailureType.LLM_PROVIDER_ERROR,
                url=provider,
                error_message=str(e),
                context={"provider": provider}
            )
            raise
    
    def _parse_response(self, raw_content: str) -> CompanyProfile:
        """Parse e valida resposta do LLM."""
        import json
        import json_repair
        
        # Limpar markdown
        content = raw_content
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("LLMService: JSON padrão falhou, tentando reparar")
            try:
                data = json_repair.loads(content)
            except Exception as e:
                logger.error(f"LLMService: Falha crítica no parse JSON: {e}")
                failure_tracker.record_failure(
                    module=FailureModule.LLM,
                    error_type=LearningFailureType.LLM_PARSE_ERROR,
                    url="parse",
                    error_message=str(e),
                    context={"raw_length": len(content) if content else 0}
                )
                return CompanyProfile()
        
        # Normalizar estrutura
        if isinstance(data, list):
            data = data[0] if data and isinstance(data[0], dict) else {}
        if not isinstance(data, dict):
            data = {}
        
        data = normalize_llm_response(data)
        
        try:
            return CompanyProfile(**data)
        except Exception as e:
            logger.error(f"LLMService: Erro ao criar CompanyProfile: {e}")
            return CompanyProfile()


# Instância singleton
_llm_service = None


def get_llm_service() -> LLMService:
    """Retorna instância singleton do LLMService."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


async def analyze_content(text_content: str, ctx_label: str = "") -> CompanyProfile:
    """
    Função de conveniência para análise de conteúdo.
    Mantém compatibilidade com código existente.
    """
    service = get_llm_service()
    return await service.analyze(text_content, ctx_label=ctx_label)
