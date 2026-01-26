"""
Cliente assíncrono para o modelo LLM hospedado no RunPod via SGLang/vLLM.
Usa a biblioteca openai com AsyncOpenAI para compatibilidade total.

v4.0: Suporte a Structured Output via SGLang/XGrammar
      - response_format com json_schema para outputs estruturados
      - Compatível com SGLang (XGrammar) e vLLM

v9.1: Suporte a SGLang sem autenticação
      - Quando API key for "dummy" ou vazia, usa httpx diretamente
      - Evita enviar Authorization header que causa 401
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
    
    v9.1: Suporte a SGLang sem autenticação (Cloudflare tunnels, self-hosted)
          - Se VLLM_API_KEY não definido ou "NONE", usa "dummy"
    
    Returns:
        AsyncOpenAI: Cliente assíncrono configurado
    """
    global _vllm_client
    if _vllm_client is None:
        _vllm_client = AsyncOpenAI(
            base_url=settings.VLLM_BASE_URL,
            api_key=settings.VLLM_API_KEY,
        )
        
        # Log com indicação se está usando auth real ou dummy
        auth_status = (
            "dummy (sem auth)" if settings.VLLM_API_KEY == "dummy" 
            else "***" if settings.VLLM_API_KEY 
            else "NONE"
        )
        
        logger.info(
            f"✅ Cliente SGLang criado: base_url={settings.VLLM_BASE_URL}, "
            f"model={settings.VLLM_MODEL}, api_key={auth_status}"
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
        
        # v9.1: Se API key for "dummy" ou vazia, usar httpx diretamente (sem Authorization header)
        api_key = settings.VLLM_API_KEY or ""
        use_httpx_direct = api_key in ("", "dummy", "NONE", "none", None)
        
        if use_httpx_direct:
            # Usar httpx diretamente SEM Authorization header
            logger.debug(
                f"vllm_client: Usando httpx direto (sem Authorization header, api_key={api_key})"
            )
            
            async with httpx.AsyncClient(timeout=120.0) as http_client:
                http_response = await http_client.post(
                    f"{settings.VLLM_BASE_URL}/chat/completions",
                    json=request_params,
                    headers={"Content-Type": "application/json"}
                    # SEM Authorization header
                )
                
                http_response.raise_for_status()
                response_data = http_response.json()
                
                # Converter resposta httpx para formato OpenAI-like
                from openai.types.chat import ChatCompletion, ChatCompletionMessage, Choice
                from openai.types.completion_usage import CompletionUsage
                
                # Extrair dados da resposta
                choices_data = response_data.get("choices", [])
                if not choices_data:
                    raise ValueError("Resposta sem choices")
                
                message_data = choices_data[0].get("message", {})
                content = message_data.get("content", "")
                
                # Criar objeto de resposta compatível com OpenAI
                response = ChatCompletion(
                    id=response_data.get("id", "unknown"),
                    object="chat.completion",
                    created=response_data.get("created", int(time.time())),
                    model=response_data.get("model", model or settings.VLLM_MODEL),
                    choices=[
                        Choice(
                            index=0,
                            message=ChatCompletionMessage(
                                role=message_data.get("role", "assistant"),
                                content=content
                            ),
                            finish_reason=choices_data[0].get("finish_reason", "stop")
                        )
                    ],
                    usage=CompletionUsage(
                        prompt_tokens=response_data.get("usage", {}).get("prompt_tokens", 0),
                        completion_tokens=response_data.get("usage", {}).get("completion_tokens", 0),
                        total_tokens=response_data.get("usage", {}).get("total_tokens", 0)
                    ) if "usage" in response_data else None
                )
        else:
            # Usar AsyncOpenAI normalmente (com Authorization header)
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
    
    v9.1: Health check mais robusto
          - Tenta /health primeiro
          - Se falhar, faz chamada de teste ao modelo
          - Retorna mais detalhes sobre erros
    
    Returns:
        Dict com status e latência
    
    Exemplo de retorno:
        {
            "status": "healthy",
            "latency_ms": 45.2,
            "model": "Qwen/Qwen3-8B",
            "endpoint": "https://example.trycloudflare.com/v1"
        }
    """
    start = time.perf_counter()
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            # Tentar endpoint /health primeiro
            health_url = settings.VLLM_BASE_URL.replace('/v1', '') + '/health'
            
            try:
                response = await http_client.get(health_url)
                latency_ms = (time.perf_counter() - start) * 1000
                
                # SGLang/vLLM retorna 200 quando saudável
                if response.status_code == 200:
                    logger.debug(f"✅ SGLang /health endpoint OK: {response.status_code}")
                    return {
                        "status": "healthy",
                        "latency_ms": round(latency_ms, 2),
                        "model": settings.VLLM_MODEL,
                        "endpoint": settings.VLLM_BASE_URL,
                        "health_endpoint": "OK"
                    }
                else:
                    # Status != 200, mas endpoint existe - tentar chamada de teste
                    logger.warning(
                        f"⚠️ SGLang /health retornou {response.status_code}, "
                        f"tentando chamada de teste ao modelo..."
                    )
                    raise httpx.RequestError("Health endpoint returned non-200")
                    
            except (httpx.RequestError, httpx.HTTPError, Exception) as health_error:
                # Se /health não existir ou falhar, tentar uma chamada mínima ao modelo
                logger.debug(
                    f"ℹ️ Endpoint /health não disponível ({type(health_error).__name__}), "
                    f"tentando chamada de teste ao modelo..."
                )
                
                try:
                    # Reset timer para medir latência da chamada ao modelo
                    model_start = time.perf_counter()
                    
                    test_response = await chat_completion(
                        messages=[{"role": "user", "content": "test"}],
                        max_tokens=5,
                        temperature=0.0,
                    )
                    
                    model_latency_ms = (time.perf_counter() - model_start) * 1000
                    
                    # Se chegou aqui, modelo está respondendo
                    logger.info(
                        f"✅ SGLang modelo respondeu em {model_latency_ms:.0f}ms "
                        f"(endpoint /health não disponível, mas modelo OK)"
                    )
                    
                    return {
                        "status": "healthy",
                        "latency_ms": round(model_latency_ms, 2),
                        "model": settings.VLLM_MODEL,
                        "endpoint": settings.VLLM_BASE_URL,
                        "health_endpoint": "unavailable",
                        "health_method": "model_test"
                    }
                    
                except Exception as model_error:
                    # Falhou tanto /health quanto chamada ao modelo
                    total_latency_ms = (time.perf_counter() - start) * 1000
                    error_msg = str(model_error)
                    
                    logger.error(
                        f"❌ SGLang não respondeu: {type(model_error).__name__}: {error_msg}"
                    )
                    
                    return {
                        "status": "unhealthy",
                        "error": error_msg,
                        "error_type": type(model_error).__name__,
                        "latency_ms": round(total_latency_ms, 2),
                        "model": settings.VLLM_MODEL,
                        "endpoint": settings.VLLM_BASE_URL,
                    }
                    
    except Exception as e:
        # Erro geral (ex: timeout no httpx.AsyncClient)
        latency_ms = (time.perf_counter() - start) * 1000
        error_msg = str(e)
        
        logger.error(f"❌ Erro crítico no health check: {type(e).__name__}: {error_msg}")
        
        return {
            "status": "error",
            "error": error_msg,
            "error_type": type(e).__name__,
            "latency_ms": round(latency_ms, 2),
            "model": settings.VLLM_MODEL,
            "endpoint": settings.VLLM_BASE_URL,
        }

