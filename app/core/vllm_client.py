"""
Cliente assíncrono para o modelo LLM hospedado na Vast.ai via SGLang.
Usa a biblioteca openai com AsyncOpenAI para compatibilidade total.

v4.0: Suporte a Structured Output via SGLang/XGrammar
      - response_format com json_schema para outputs estruturados
      - Compatível com SGLang (XGrammar)

v9.1: Suporte a SGLang com autenticação Bearer Token
      - SEMPRE usa httpx diretamente (nunca AsyncOpenAI)
      - Usa Authorization: Bearer Token header quando MODEL_KEY estiver definido

v11.0: Refatorado para usar Vast.ai
      - Usa MODEL_KEY, MODEL_NAME, URL_MODEL das variáveis de ambiente
      - Variáveis legadas (VLLM_*) mantidas por compatibilidade
"""
import logging
import time
import json
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
        # v11.0: Usar novas variáveis (MODEL_KEY, URL_MODEL) com fallback para legadas
        base_url = settings.URL_MODEL or settings.VLLM_BASE_URL
        api_key = settings.MODEL_KEY or settings.VLLM_API_KEY
        
        _vllm_client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        
        # Log com indicação se está usando auth real ou dummy
        auth_status = (
            "dummy (sem auth)" if api_key == "dummy" 
            else "Bearer Token ✅" if api_key 
            else "NONE ⚠️"
        )
        
        model_name = settings.MODEL_NAME or settings.VLLM_MODEL
        
        logger.info(
            f"✅ Cliente Vast.ai (SGLang) criado: "
            f"base_url={base_url}, model={model_name}, auth={auth_status}"
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
        
        # CRÍTICO: Auto-injetar stream_options para SGLang se streaming
        # SGLang omite usage stats em streaming a menos que include_usage=True
        from app.core.phoenix_tracer import _inject_sglang_stream_options
        request_params = _inject_sglang_stream_options(request_params)
        
        # v11.0: SEMPRE usar httpx diretamente para Vast.ai (SGLang)
        # Autenticação via Authorization: Bearer Token (MODEL_KEY obrigatório)
        base_url = settings.URL_MODEL or settings.VLLM_BASE_URL
        model_key = settings.MODEL_KEY or settings.VLLM_API_KEY
        
        request_url = f"{base_url}/chat/completions"
        
        # Preparar headers (com Authorization Bearer - obrigatório para Vast.ai)
        headers = {"Content-Type": "application/json"}
        if model_key:
            headers["Authorization"] = f"Bearer {model_key}"
            logger.debug(
                f"vllm_client: Vast.ai com Authorization Bearer "
                f"(token={model_key[:20]}...)"
            )
        else:
            logger.warning(
                f"vllm_client: ⚠️ Vast.ai sem autenticação (MODEL_KEY não configurado)"
            )
        
        # Instrumentação nativa do Phoenix para chamadas httpx (SGLang)
        from app.core.phoenix_tracer import (
            setup_phoenix_tracing,
            create_llm_span,
            update_llm_span_response
        )
        from opentelemetry import context as otel_context
        from opentelemetry.trace import set_span_in_context
        
        tracer_provider = setup_phoenix_tracing("profile-llm")
        
        span = None
        token = None
        if tracer_provider:
            try:
                # Criar span LLM usando função helper nativa do Phoenix
                # Segue convenções OpenInference para reconhecimento automático
                span = create_llm_span(
                    tracer_provider=tracer_provider,
                    span_name="vllm_client.chat_completion",
                    model=request_params.get("model", ""),
                    messages=messages,
                    request_params=request_params,
                    provider="SGLang"
                )
                
                if span:
                    # Adicionar informações adicionais específicas
                    span.set_attribute("llm.request.url", request_url)
                    model_key = settings.MODEL_KEY or settings.VLLM_API_KEY
                    span.set_attribute("llm.request.has_auth", bool(model_key))
                    span.set_attribute("llm.provider", "Vast.ai")
                    
                    # Adicionar headers (sem expor token completo)
                    headers_info = {
                        "Content-Type": headers.get("Content-Type", ""),
                        "has_authorization": bool(headers.get("Authorization")),
                        "authorization_prefix": headers.get("Authorization", "")[:20] + "..." if headers.get("Authorization") else None
                    }
                    span.set_attribute("llm.request.headers", json.dumps(headers_info, ensure_ascii=False))
                    
                    # Anexar span ao contexto OpenTelemetry
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
                
                # Atualizar span com resposta usando função helper nativa do Phoenix
                if span:
                    try:
                        update_llm_span_response(
                            span=span,
                            response_data=response_data,
                            http_status_code=http_response.status_code
                        )
                    except Exception as e:
                        logger.debug(f"vllm_client: Erro ao atualizar span com resposta: {e}")
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
                model=response_data.get("model", model or settings.MODEL_NAME or settings.VLLM_MODEL),
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
        base_url = settings.URL_MODEL or settings.VLLM_BASE_URL
        model_key = settings.MODEL_KEY or settings.VLLM_API_KEY
        
        # Preparar headers com autenticação
        headers = {}
        if model_key:
            headers["Authorization"] = f"Bearer {model_key}"
        
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            # Tentar endpoint /health primeiro
            health_url = base_url.replace('/v1', '') + '/health'
            
            try:
                response = await http_client.get(health_url, headers=headers)
                latency_ms = (time.perf_counter() - start) * 1000
                
                # SGLang retorna 200 quando saudável
                if response.status_code == 200:
                    logger.debug(f"✅ Vast.ai /health endpoint OK: {response.status_code}")
                    model_name = settings.MODEL_NAME or settings.VLLM_MODEL
                    return {
                        "status": "healthy",
                        "latency_ms": round(latency_ms, 2),
                        "model": model_name,
                        "endpoint": base_url,
                        "health_endpoint": "OK"
                    }
                else:
                    # Status != 200, mas endpoint existe - tentar chamada de teste
                    logger.warning(
                        f"⚠️ Vast.ai /health retornou {response.status_code}, "
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
                    
                    model_name = settings.MODEL_NAME or settings.VLLM_MODEL
                    return {
                        "status": "healthy",
                        "latency_ms": round(model_latency_ms, 2),
                        "model": model_name,
                        "endpoint": base_url,
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
                    
                    model_name = settings.MODEL_NAME or settings.VLLM_MODEL
                    return {
                        "status": "unhealthy",
                        "error": error_msg,
                        "error_type": type(model_error).__name__,
                        "latency_ms": round(total_latency_ms, 2),
                        "model": model_name,
                        "endpoint": base_url,
                    }
                    
    except Exception as e:
        # Erro geral (ex: timeout no httpx.AsyncClient)
        latency_ms = (time.perf_counter() - start) * 1000
        error_msg = str(e)
        
        logger.error(f"❌ Erro crítico no health check: {type(e).__name__}: {error_msg}")
        
        base_url = settings.URL_MODEL or settings.VLLM_BASE_URL
        model_name = settings.MODEL_NAME or settings.VLLM_MODEL
        return {
            "status": "error",
            "error": error_msg,
            "error_type": type(e).__name__,
            "latency_ms": round(latency_ms, 2),
            "model": model_name,
            "endpoint": base_url,
        }

