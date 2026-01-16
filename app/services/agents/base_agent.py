"""
Classe base para agentes LLM.

Define interface padrão que todos os agentes devem implementar.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple

from app.services.llm_manager import (
    LLMCallManager,
    get_llm_manager,
    LLMPriority
)

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Classe base abstrata para agentes LLM.
    
    Todos os agentes devem herdar desta classe e implementar:
    - SYSTEM_PROMPT: Prompt de sistema do agente
    - _build_user_prompt(): Constrói o prompt do usuário
    - _parse_response(): Processa a resposta do LLM
    
    Observação: os valores DEFAULT_* aqui são apenas fallback.
    Cada agente deve carregar timeout/retries de config dedicada
    (ex.: app/configs/llm_agents.json).
    """
    
    # Prompt de sistema - deve ser sobrescrito nas subclasses
    SYSTEM_PROMPT: str = ""
    
    # Configurações padrão (fallback)
    DEFAULT_TIMEOUT: float = 60.0
    DEFAULT_TEMPERATURE: float = 0.0
    DEFAULT_MAX_RETRIES: int = 3
    
    def __init__(self, llm_manager: LLMCallManager = None):
        """
        Inicializa o agente.
        
        Args:
            llm_manager: Instância do gerenciador de LLM. Se None, usa singleton.
        """
        self.llm_manager = llm_manager or get_llm_manager()
    
    @abstractmethod
    def _build_user_prompt(self, **kwargs) -> str:
        """
        Constrói o prompt do usuário baseado nos parâmetros.
        
        Args:
            **kwargs: Parâmetros específicos do agente
        
        Returns:
            String com o prompt do usuário
        """
        pass
    
    @abstractmethod
    def _parse_response(self, response: str, **kwargs) -> Any:
        """
        Processa a resposta do LLM.
        
        Args:
            response: Resposta bruta do LLM
            **kwargs: Parâmetros adicionais para processamento
        
        Returns:
            Resultado processado (tipo específico do agente)
        """
        pass
    
    def _build_messages(self, user_prompt: str) -> List[dict]:
        """
        Constrói lista de mensagens para o LLM.
        
        Args:
            user_prompt: Prompt do usuário
        
        Returns:
            Lista de mensagens formatadas
        """
        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
    
    async def _call_llm(
        self,
        messages: List[dict],
        priority: LLMPriority = LLMPriority.NORMAL,
        timeout: float = None,
        temperature: float = None,
        response_format: dict = None,
        ctx_label: str = "",
        max_retries: int = None,
        request_id: str = ""
    ) -> Tuple[str, float]:
        """
        Faz chamada ao LLM usando o manager centralizado.
        
        Args:
            messages: Lista de mensagens
            priority: Nível de prioridade
            timeout: Timeout em segundos
            temperature: Temperatura da geração
            response_format: Formato de resposta
            ctx_label: Label de contexto para logs
            max_retries: Número máximo de tentativas
            request_id: ID da requisição
        
        Returns:
            Tuple de (response_content, latency_ms)
        """
        return await self.llm_manager.call(
            messages=messages,
            priority=priority,
            request_id=request_id,
            timeout=timeout or self.DEFAULT_TIMEOUT,
            temperature=temperature or self.DEFAULT_TEMPERATURE,
            response_format=response_format,
            ctx_label=ctx_label,
            max_retries=max_retries or self.DEFAULT_MAX_RETRIES
        )
    
    async def execute(
        self,
        priority: LLMPriority = LLMPriority.NORMAL,
        timeout: float = None,
        ctx_label: str = "",
        request_id: str = "",
        **kwargs
    ) -> Any:
        """
        Executa o agente.
        
        Método principal que orquestra:
        1. Construção do prompt
        2. Chamada ao LLM
        3. Processamento da resposta
        
        Args:
            priority: Nível de prioridade
            timeout: Timeout em segundos
            ctx_label: Label de contexto
            request_id: ID da requisição
            **kwargs: Parâmetros específicos do agente
        
        Returns:
            Resultado processado pelo agente
        """
        # 1. Construir prompt
        user_prompt = self._build_user_prompt(**kwargs)
        messages = self._build_messages(user_prompt)
        
        # 2. Chamar LLM
        response_content, latency_ms = await self._call_llm(
            messages=messages,
            priority=priority,
            timeout=timeout,
            response_format=self._get_response_format(),
            ctx_label=ctx_label,
            request_id=request_id
        )
        
        logger.debug(f"{ctx_label}{self.__class__.__name__}: Resposta em {latency_ms:.0f}ms")
        
        # 3. Processar resposta
        return self._parse_response(response_content, **kwargs)
    
    def _get_response_format(self) -> Optional[dict]:
        """
        Retorna formato de resposta para o LLM.
        Subclasses podem sobrescrever para formatos específicos.
        
        Returns:
            Dict com formato ou None para texto livre
        """
        return {"type": "json_object"}


