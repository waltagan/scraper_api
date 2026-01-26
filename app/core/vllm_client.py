"""
Cliente assíncrono para o modelo LLM hospedado no RunPod via SGLang/vLLM.
Usa a biblioteca openai com AsyncOpenAI para compatibilidade total.

v4.0: Suporte a Structured Output via SGLang/XGrammar
      - response_format com json_schema para outputs estruturados
      - Compatível com SGLang (XGrammar) e vLLM

v9.1: Suporte a SGLang com autenticação Bearer Token
      - SEMPRE usa httpx diretamente (nunca AsyncOpenAI)
      - Usa Authorization: Bearer Token header quando VLLM_API_KEY estiver definido
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

    NOTA: Este cliente não é mais usado diretamente. Todas as chamadas ao SGLang
    usam httpx diretamente (com Authorization Bearer header quando necessário) na função chat_completion().
    Este singleton é mantido apenas por compatibilidade com código legado.
    
    v9.1: SGLang SEMPRE usa httpx diretamente (nunca AsyncOpenAI)
          - Usa Authorization: Bearer Token header quando VLLM_API_KEY estiver definido
    
    Returns:
        AsyncOpenAI: Cliente assíncrono (não usado para SGLang)
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
        
        # v9.1: SEMPRE usar httpx diretamente para SGLang
        # Autenticação via Authorization: Bearer Token (se VLLM_API_KEY estiver definido)
        request_url = f"{settings.VLLM_BASE_URL}/chat/completions"
        
        # Preparar headers (com Authorization Bearer se token disponível)
        headers = {"Content-Type": "application/json"}
        if settings.VLLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.VLLM_API_KEY}"
            logger.debug(
                f"vllm_client: Usando httpx direto para SGLang com Authorization Bearer "
                f"(token={settings.VLLM_API_KEY[:20]}...)"
            )
        else:
            logger.debug(
                f"vllm_client: Usando httpx direto para SGLang (sem autenticação)"
            )
        
        # Tracing manual do Phoenix para chamadas httpx (SGLang)
        from app.core.phoenix_tracer import setup_phoenix_tracing
        tracer_provider = setup_phoenix_tracing("profile-llm")
        
        span = None
        token = None
        if tracer_provider:
            try:
                from opentelemetry import trace as otel_trace
                from opentelemetry import context as otel_context
                from opentelemetry.trace import set_span_in_context
                
                tracer = otel_trace.get_tracer(__name__)
                span = tracer.start_span("vllm_client.chat_completion")
                
                # Adicionar atributos do OpenInference
                span.set_attribute("gen_ai.request.model", request_params.get("model", ""))
                span.set_attribute("gen_ai.request.temperature", request_params.get("temperature", 0.0))
                span.set_attribute("gen_ai.request.max_tokens", request_params.get("max_tokens", 0))
                span.set_attribute("gen_ai.system", "SGLang")
                
                # Adicionar mensagens do prompt
                if messages:
                    system_msg = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
                    user_msg = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
                    if system_msg:
                        span.set_attribute("gen_ai.prompt.system", system_msg[:1000])
                    if user_msg:
                        span.set_attribute("gen_ai.prompt.user", user_msg[:2000])
                
                token = otel_context.attach(set_span_in_context(span))
            except Exception as e:
                logger.debug(f"vllm_client: Erro ao criar span Phoenix: {e}")
                span = None
                token = None
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as http_client:
                http_response = await http_client.post(
                    request_url,
                    json=request_params,
                    headers=headers
                )
                
                http_response.raise_for_status()
                response_data = http_response.json()
                
                # Adicionar atributos de resposta ao span
                if span:
                    try:
                        content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        usage = response_data.get("usage", {})
                        
                        span.set_attribute("gen_ai.response.finish_reason", 
                                          response_data.get("choices", [{}])[0].get("finish_reason", "unknown"))
                        span.set_attribute("gen_ai.usage.prompt_tokens", usage.get("prompt_tokens", 0))
                        span.set_attribute("gen_ai.usage.completion_tokens", usage.get("completion_tokens", 0))
                        span.set_attribute("gen_ai.usage.total_tokens", usage.get("total_tokens", 0))
                        span.set_attribute("gen_ai.response.content", content[:5000])
                    except Exception as e:
                        logger.debug(f"vllm_client: Erro ao adicionar atributos ao span: {e}")
        finally:
            if span and token is not None:
                try:
                    from opentelemetry import context as otel_context
                    otel_context.detach(token)
                    span.end()
                except Exception:
                    pass
            elif span:
                # Se span existe mas token não, apenas finalizar
                try:
                    span.end()
                except Exception:
                    pass
            
            # Converter resposta httpx para formato OpenAI-like
            # Usar imports compatíveis com diferentes versões do openai
            try:
                from openai.types.chat import ChatCompletion, ChatCompletionMessage
                from openai.types.chat.chat_completion import Choice
            except ImportError:
                try:
                    from openai.types.chat import ChatCompletion, ChatCompletionMessage, Choice
                except ImportError:
                    # Fallback: criar classe Choice simples compatível
                    from openai.types.chat import ChatCompletion, ChatCompletionMessage
                    from types import SimpleNamespace
                    def Choice(**kwargs):
                        return SimpleNamespace(**kwargs)
            
            from openai.types.completion_usage import CompletionUsage
            
            # Extrair dados da resposta
            choices_data = response_data.get("choices", [])
            if not choices_data:
                raise ValueError("Resposta sem choices")
            
            message_data = choices_data[0].get("message", {})
            content = message_data.get("content", "")
            
            # Criar objeto de resposta compatível com OpenAI
            # Criar Choice com atributos corretos
            choice_obj = Choice(
                index=0,
                message=ChatCompletionMessage(
                    role=message_data.get("role", "assistant"),
                    content=content
                ),
                finish_reason=choices_data[0].get("finish_reason", "stop")
            )
            
            response = ChatCompletion(
                id=response_data.get("id", "unknown"),
                object="chat.completion",
                created=response_data.get("created", int(time.time())),
                model=response_data.get("model", model or settings.VLLM_MODEL),
                choices=[choice_obj],
                usage=CompletionUsage(
                    prompt_tokens=response_data.get("usage", {}).get("prompt_tokens", 0),
                    completion_tokens=response_data.get("usage", {}).get("completion_tokens", 0),
                    total_tokens=response_data.get("usage", {}).get("total_tokens", 0)
                ) if "usage" in response_data else None
            )
        
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

