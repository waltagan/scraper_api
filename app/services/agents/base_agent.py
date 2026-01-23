"""
Classe base para agentes LLM.

Define interface padrão que todos os agentes devem implementar.

v4.0: Suporte a Structured Output via SGLang/XGrammar
      - Método _get_json_schema() para definir schema Pydantic
      - Método _get_response_format() suporta json_schema nativo
      - Compatibilidade com SGLang, vLLM e OpenAI
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from app.services.llm_manager import (
    LLMCallManager,
    get_llm_manager,
    LLMPriority
)
from app.services.concurrency_manager.config_loader import get_section as get_config

logger = logging.getLogger(__name__)

# Carregar configuração de structured output
_PROFILE_LLM_CONFIG = get_config("profile/profile_llm", {})


class BaseAgent(ABC):
    """
    Classe base abstrata para agentes LLM.
    
    Todos os agentes devem herdar desta classe e implementar:
    - SYSTEM_PROMPT: Prompt de sistema do agente
    - _build_user_prompt(): Constrói o prompt do usuário
    - _parse_response(): Processa a resposta do LLM
    
    v4.0: Suporte a Structured Output
    - _get_json_schema(): Retorna schema JSON para structured output (opcional)
    - _get_response_format(): Retorna formato de resposta (json_object ou json_schema)
    
    Observação: os valores DEFAULT_* aqui são apenas fallback.
    Cada agente deve carregar timeout/retries de config dedicada
    (ex.: app/configs/llm_agents.json).
    """
    
    # Prompt de sistema - deve ser sobrescrito nas subclasses
    SYSTEM_PROMPT: str = ""
    
    # Configurações padrão (fallback)
    DEFAULT_TIMEOUT: float = 60.0
    DEFAULT_TEMPERATURE: float = 0.0
    DEFAULT_PRESENCE_PENALTY: float = 0.3    # Anti-loop: penaliza tokens já aparecidos
    DEFAULT_FREQUENCY_PENALTY: float = 0.4   # Anti-repetição: penaliza tokens frequentes
    DEFAULT_SEED: int = 42                   # Reprodutibilidade
    DEFAULT_MAX_RETRIES: int = 3
    
    # Configuração de structured output
    USE_STRUCTURED_OUTPUT: bool = _PROFILE_LLM_CONFIG.get("use_structured_output", True)
    
    def __init__(self, llm_manager: LLMCallManager = None):
        """
        Inicializa o agente.
        
        Args:
            llm_manager: Instância do gerenciador de LLM. Se None, usa singleton.
        """
        self.llm_manager = llm_manager or get_llm_manager()
        
        # Carregar configuração de structured output
        self._use_structured_output = _PROFILE_LLM_CONFIG.get("use_structured_output", True)
    
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
        presence_penalty: float = None,
        frequency_penalty: float = None,
        seed: int = None,
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
            presence_penalty: Penaliza tokens já aparecidos (-2.0 a 2.0, padrão 0.3)
            frequency_penalty: Penaliza tokens frequentes (-2.0 a 2.0, padrão 0.4)
            seed: Seed para reprodutibilidade (padrão 42)
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
            presence_penalty=presence_penalty if presence_penalty is not None else self.DEFAULT_PRESENCE_PENALTY,
            frequency_penalty=frequency_penalty if frequency_penalty is not None else self.DEFAULT_FREQUENCY_PENALTY,
            seed=seed if seed is not None else self.DEFAULT_SEED,
            response_format=response_format,
            ctx_label=ctx_label,
            max_retries=max_retries or self.DEFAULT_MAX_RETRIES
        )
    
    async def execute(
        self,
        priority: LLMPriority = LLMPriority.NORMAL,
        timeout: float = None,
        max_retries: int = None,
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
            max_retries: Número máximo de tentativas (com backoff exponencial)
            ctx_label: Label de contexto
            request_id: ID da requisição
            **kwargs: Parâmetros específicos do agente
        
        Returns:
            Resultado processado pelo agente
        """
        # 1. Construir prompt
        user_prompt = self._build_user_prompt(**kwargs)
        messages = self._build_messages(user_prompt)
        
        logger.debug(
            f"{ctx_label}{self.__class__.__name__}: Executando com "
            f"priority={priority.name}, timeout={timeout}, "
            f"presence_penalty={getattr(self, 'DEFAULT_PRESENCE_PENALTY', 0.3)}, "
            f"frequency_penalty={getattr(self, 'DEFAULT_FREQUENCY_PENALTY', 0.4)}, "
            f"seed={getattr(self, 'DEFAULT_SEED', 42)}"
        )
        
        # 2. Chamar LLM
        response_content, latency_ms = await self._call_llm(
            messages=messages,
            priority=priority,
            timeout=timeout,
            presence_penalty=getattr(self, 'DEFAULT_PRESENCE_PENALTY', 0.3),
            frequency_penalty=getattr(self, 'DEFAULT_FREQUENCY_PENALTY', 0.4),
            seed=getattr(self, 'DEFAULT_SEED', 42),
            max_retries=max_retries or self.DEFAULT_MAX_RETRIES,
            response_format=self._get_response_format(),
            ctx_label=ctx_label,
            request_id=request_id
        )
        
        logger.debug(f"{ctx_label}{self.__class__.__name__}: Resposta em {latency_ms:.0f}ms")
        
        # 3. Processar resposta
        return self._parse_response(response_content, **kwargs)
    
    def _get_json_schema(self) -> Optional[Dict[str, Any]]:
        """
        Retorna JSON Schema para structured output.
        
        Subclasses devem sobrescrever para fornecer schema específico.
        Se retornar None, usa json_object genérico.
        
        Returns:
            Dict com JSON Schema ou None
        """
        return None
    
    def _get_schema_name(self) -> str:
        """
        Retorna nome do schema para identificação.
        
        Returns:
            Nome do schema (default: nome da classe)
        """
        return self.__class__.__name__.lower()
    
    def _get_response_format(self) -> Optional[dict]:
        """
        Retorna formato de resposta para o LLM.
        
        v4.0: Suporta três modos:
        1. json_schema: Usa schema Pydantic (SGLang/XGrammar - mais preciso)
        2. json_object: Fallback genérico para providers sem suporte a schema
        3. None: Texto livre
        
        Returns:
            Dict com formato ou None para texto livre
        """
        # Se structured output está habilitado e temos schema
        if self._use_structured_output:
            schema = self._get_json_schema()
            if schema:
                # SGLang/XGrammar: usar json_schema para garantia de formato
                return {
                    "type": "json_schema",
                    "json_schema": {
                        "name": self._get_schema_name(),
                        "schema": schema
                    }
                }
        
        # Fallback: json_object genérico
        return {"type": "json_object"}


