"""
Cliente assíncrono para o modelo LLM hospedado no RunPod via SGLang/vLLM.
Usa a biblioteca openai com AsyncOpenAI para compatibilidade total.

v4.0: Suporte a Structured Output via SGLang/XGrammar
      - response_format com json_schema para outputs estruturados
      - Compatível com SGLang (XGrammar) e vLLM
"""
import logging
import time
from typing import Optional, List, Dict, Any
import httpx
from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# Singleton do cliente assíncrono
_vllm_client: Optional[AsyncOpenAI] = None


def get_vllm_client() -> AsyncOpenAI:
    """
    Retorna cliente SGLang assíncrono (singleton).
    
    IMPORTANTE: Apesar do nome "vllm_client", este cliente conecta ao SGLang.
    O nome foi mantido por compatibilidade com código existente.

    Usa AsyncOpenAI que é 100% compatível com a API SGLang OpenAI-compatible.
    
    Returns:
        AsyncOpenAI: Cliente assíncrono configurado
    """
    global _vllm_client
    if _vllm_client is None:
        _vllm_client = AsyncOpenAI(
            base_url=settings.VLLM_BASE_URL,
            api_key=settings.VLLM_API_KEY,
        )
        logger.info(
            f"✅ Cliente SGLang criado: base_url={settings.VLLM_BASE_URL}, "
            f"model={settings.VLLM_MODEL}, api_key={'***' if settings.VLLM_API_KEY else 'NONE'}"
        )
    return _vllm_client


async def chat_completion(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 500,
    model: Optional[str] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Executa chat completion no modelo SGLang (assíncrono).
    
    IMPORTANTE: Sistema usa APENAS SGLang (não vLLM).
    
    v4.0: Suporte a Structured Output
          - response_format com json_schema para outputs estruturados
          - SGLang usa XGrammar para garantir JSON válido
    
    Args:
        messages: Lista de mensagens no formato OpenAI
            Exemplo: [
                {"role": "system", "content": "Você é um assistente útil."},
                {"role": "user", "content": "Qual é o site oficial da empresa X?"}
            ]
        temperature: Temperatura para geração (0.0 a 1.0)
        max_tokens: Número máximo de tokens na resposta
        model: Modelo a usar (default: VLLM_MODEL do config)
        response_format: Formato de resposta estruturada (opcional)
            Exemplo json_schema: {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": {...}}
            }
            Exemplo json_object: {"type": "json_object"}
    
    Returns:
        Resposta completa do modelo no formato OpenAI
    
    Exemplo:
        response = await chat_completion([
            {"role": "system", "content": "Você é um assistente útil."},
            {"role": "user", "content": "Qual é o site oficial da empresa X?"}
        ])
        answer = response.choices[0].message.content
    """
    client = get_vllm_client()
    
    try:
        # Construir parâmetros da requisição
        request_params = {
            "model": model or settings.VLLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        # Adicionar response_format se fornecido (SGLang/XGrammar suporta)
        if response_format:
            request_params["response_format"] = response_format
            logger.debug(
                f"🎯 Structured output habilitado: type={response_format.get('type')}"
            )
        
        response = await client.chat.completions.create(**request_params)
        
        # Log de uso de tokens
        if response.usage:
            logger.debug(
                f"🔢 Tokens: prompt={response.usage.prompt_tokens}, "
                f"completion={response.usage.completion_tokens}, "
                f"total={response.usage.total_tokens}"
            )
        
        return response
    except Exception as e:
        logger.error(f"❌ Erro ao chamar SGLang: {e}")
        raise


async def check_vllm_health() -> Dict[str, Any]:
    """
    Verifica se o servidor SGLang está respondendo.
    
    IMPORTANTE: Apesar do nome "check_vllm_health", verifica SGLang.
    Nome mantido por compatibilidade.
    
    Returns:
        Dict com status e latência
    
    Exemplo de retorno:
        {
            "status": "healthy",
            "latency_ms": 45.2,
            "model": "mistralai/Ministral-3-3B-Instruct-2512",
            "endpoint": "https://5u888x525vvzvs-8000.proxy.runpod.net/v1"
        }
    """
    start = time.perf_counter()
    
    try:
        # Tentar fazer uma chamada simples de health check
        # SGLang pode não ter endpoint /health, então fazemos uma chamada mínima
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Tentar endpoint /health primeiro
            health_url = settings.VLLM_BASE_URL.replace('/v1', '') + '/health'
            try:
                response = await client.get(health_url)
                latency_ms = (time.perf_counter() - start) * 1000
                
                return {
                    "status": "healthy" if response.status_code == 200 else "unhealthy",
                    "latency_ms": round(latency_ms, 2),
                    "model": settings.VLLM_MODEL,
                    "endpoint": settings.VLLM_BASE_URL,
                }
            except httpx.RequestError:
                # Se /health não existir, tentar uma chamada mínima ao modelo
                try:
                    test_response = await chat_completion(
                        messages=[{"role": "user", "content": "test"}],
                        max_tokens=5,
                        temperature=0.0,
                    )
                    latency_ms = (time.perf_counter() - start) * 1000
                    
                    return {
                        "status": "healthy",
                        "latency_ms": round(latency_ms, 2),
                        "model": settings.VLLM_MODEL,
                        "endpoint": settings.VLLM_BASE_URL,
                    }
                except Exception as e:
                    latency_ms = (time.perf_counter() - start) * 1000
                    return {
                        "status": "error",
                        "error": str(e),
                        "latency_ms": round(latency_ms, 2),
                        "endpoint": settings.VLLM_BASE_URL,
                    }
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status": "error",
            "error": str(e),
            "latency_ms": round(latency_ms, 2),
            "endpoint": settings.VLLM_BASE_URL,
        }

