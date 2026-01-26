"""
Configuração Phoenix para observabilidade de chamadas LLM.

Instrumentação nativa do Phoenix usando OpenInference.
"""
import logging
import time
import json
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from app.core.config import settings

logger = logging.getLogger(__name__)

# Singleton do tracer provider por projeto
_tracer_providers: dict = {}

# Flag para desabilitar tracing (útil para testes)
_tracing_enabled: bool = True

# Limite de caracteres para atributos OpenTelemetry (padrão: 250)
# Phoenix/OpenInference pode aceitar mais, mas vamos usar eventos para dados grandes
MAX_ATTRIBUTE_LENGTH = 25000  # Aumentado para permitir prompts maiores


def set_tracing_enabled(enabled: bool):
    """Define se o tracing está habilitado."""
    global _tracing_enabled
    _tracing_enabled = enabled


def setup_phoenix_tracing(project_name: str):
    """
    Configura tracing Phoenix para um projeto específico.
    
    Args:
        project_name: Nome do projeto no Phoenix (ex: 'discovery-llm', 'profile-llm')
    
    Returns:
        TracerProvider configurado ou None se tracing desabilitado
    """
    if not _tracing_enabled:
        logger.debug(f"🔇 Tracing desabilitado para projeto: {project_name}")
        return None
    
    if project_name not in _tracer_providers:
        try:
            from phoenix.otel import register
            from openinference.instrumentation.openai import OpenAIInstrumentor
            
            tracer_provider = register(
                project_name=project_name,
                endpoint=f"{settings.PHOENIX_COLLECTOR_URL}/v1/traces",
            )
            OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
            _tracer_providers[project_name] = tracer_provider
            logger.info(f"✅ Phoenix tracing configurado para projeto: {project_name}")
        except ImportError as e:
            logger.warning(f"⚠️ Bibliotecas Phoenix não instaladas: {e}")
            logger.warning("⚠️ Tracing desabilitado. Instale: pip install arize-phoenix-otel openinference-instrumentation-openai")
            _tracer_providers[project_name] = None
        except Exception as e:
            logger.error(f"❌ Erro ao configurar Phoenix tracing: {e}")
            _tracer_providers[project_name] = None
    
    return _tracer_providers.get(project_name)


def _truncate_if_needed(value: str, max_length: int = MAX_ATTRIBUTE_LENGTH) -> str:
    """Trunca string se exceder o limite."""
    if len(value) > max_length:
        return value[:max_length] + f"... [truncated, original length: {len(value)}]"
    return value


def _set_attribute_safe(span, key: str, value: Any):
    """Define atributo no span, truncando se necessário."""
    if value is None:
        return
    
    if isinstance(value, str):
        value = _truncate_if_needed(value)
    elif isinstance(value, (dict, list)):
        value_str = json.dumps(value, ensure_ascii=False)
        value = _truncate_if_needed(value_str)
    
    try:
        span.set_attribute(key, value)
    except Exception as e:
        logger.debug(f"Erro ao definir atributo {key}: {e}")


def create_llm_span(
    tracer_provider,
    span_name: str,
    model: str,
    messages: List[Dict[str, str]],
    request_params: Dict[str, Any],
    provider: str = "unknown"
) -> Optional[Any]:
    """
    Cria um span LLM seguindo as convenções do OpenInference/Phoenix.
    
    Esta função cria spans que são nativamente reconhecidos pelo Phoenix
    como chamadas LLM, seguindo as convenções do OpenInference.
    
    Args:
        tracer_provider: TracerProvider do Phoenix
        span_name: Nome do span
        model: Nome do modelo LLM
        messages: Lista de mensagens (formato OpenAI)
        request_params: Parâmetros da requisição
        provider: Nome do provider (ex: "RunPod", "SGLang")
    
    Returns:
        Span do OpenTelemetry ou None se erro
    """
    if not tracer_provider:
        return None
    
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.trace import SpanKind
        
        # CRÍTICO: Usar o tracer do tracer_provider explicitamente
        # Isso garante que o span seja exportado para o Phoenix
        tracer = otel_trace.get_tracer(__name__, tracer_provider=tracer_provider)
        
        # Criar span com kind LLM (OpenInference)
        span = tracer.start_span(
            span_name,
            kind=SpanKind.CLIENT  # CLIENT para chamadas LLM externas
        )
        
        # ============================================================
        # Atributos OpenInference (convenções do Phoenix)
        # ============================================================
        
        # Identificação do LLM
        _set_attribute_safe(span, "gen_ai.request.model", model)
        _set_attribute_safe(span, "gen_ai.system", provider)
        
        # Parâmetros de geração
        if "temperature" in request_params:
            span.set_attribute("gen_ai.request.temperature", float(request_params["temperature"]))
        if "max_tokens" in request_params:
            span.set_attribute("gen_ai.request.max_tokens", int(request_params["max_tokens"]))
        if "top_p" in request_params:
            span.set_attribute("gen_ai.request.top_p", float(request_params["top_p"]))
        if "presence_penalty" in request_params:
            span.set_attribute("gen_ai.request.presence_penalty", float(request_params["presence_penalty"]))
        if "frequency_penalty" in request_params:
            span.set_attribute("gen_ai.request.frequency_penalty", float(request_params["frequency_penalty"]))
        if "seed" in request_params:
            span.set_attribute("gen_ai.request.seed", int(request_params["seed"]))
        
        # Mensagens (OpenInference)
        if messages:
            # Mensagens completas como JSON
            messages_json = json.dumps(messages, ensure_ascii=False)
            _set_attribute_safe(span, "gen_ai.input.messages", messages_json)
            
            # Extrair system e user messages
            system_msg = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
            user_msg = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
            
            if system_msg:
                _set_attribute_safe(span, "gen_ai.prompt.system", system_msg)
            
            if user_msg:
                _set_attribute_safe(span, "gen_ai.prompt.user", user_msg)
            
            # Métricas de tamanho
            total_chars = sum(len(m.get("content", "")) for m in messages)
            span.set_attribute("llm.request.total_chars", total_chars)
            span.set_attribute("llm.request.message_count", len(messages))
            if system_msg:
                span.set_attribute("llm.request.system_prompt_length", len(system_msg))
            if user_msg:
                span.set_attribute("llm.request.user_prompt_length", len(user_msg))
        
        # Response format (structured output)
        if "response_format" in request_params:
            response_format = request_params["response_format"]
            response_format_type = response_format.get("type", "unknown")
            span.set_attribute("gen_ai.request.response_format.type", response_format_type)
            
            if response_format_type == "json_schema":
                schema_info = response_format.get("json_schema", {})
                span.set_attribute("gen_ai.request.json_schema.name", schema_info.get("name", ""))
                span.set_attribute("gen_ai.request.json_schema.strict", schema_info.get("strict", False))
                schema_str = json.dumps(schema_info.get("schema", {}), ensure_ascii=False)
                span.set_attribute("gen_ai.request.json_schema.size", len(schema_str))
        
        # Informações adicionais
        span.set_attribute("llm.request.provider", provider)
        
        # Marcar início para cálculo de latência
        span.start_time = time.perf_counter()
        
        return span
        
    except Exception as e:
        logger.error(f"❌ Erro ao criar span LLM: {e}")
        return None


def update_llm_span_response(
    span: Any,
    response_data: Dict[str, Any],
    http_status_code: int = 200
):
    """
    Atualiza o span LLM com dados da resposta.
    
    Args:
        span: Span do OpenTelemetry
        response_data: Dados da resposta (formato OpenAI)
        http_status_code: Status HTTP da resposta
    """
    if not span:
        return
    
    try:
        choices = response_data.get("choices", [])
        if not choices:
            return
        
        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        usage = response_data.get("usage", {})
        
        # Resposta (OpenInference)
        _set_attribute_safe(span, "gen_ai.response.content", content)
        span.set_attribute("gen_ai.response.finish_reason", choice.get("finish_reason", "unknown"))
        span.set_attribute("gen_ai.response.model", response_data.get("model", ""))
        span.set_attribute("gen_ai.response.id", response_data.get("id", ""))
        span.set_attribute("gen_ai.response.created", response_data.get("created", 0))
        
        # Métricas de uso
        span.set_attribute("gen_ai.usage.prompt_tokens", usage.get("prompt_tokens", 0))
        span.set_attribute("gen_ai.usage.completion_tokens", usage.get("completion_tokens", 0))
        span.set_attribute("gen_ai.usage.total_tokens", usage.get("total_tokens", 0))
        
        # Métricas adicionais
        span.set_attribute("llm.response.content_length", len(content))
        span.set_attribute("llm.response.status_code", http_status_code)
        
        # Latência
        if hasattr(span, 'start_time'):
            latency_ms = (time.perf_counter() - span.start_time) * 1000
            span.set_attribute("llm.response.latency_ms", latency_ms)
            
            # Tokens por segundo
            if latency_ms > 0:
                tokens_per_sec = (usage.get("completion_tokens", 0) / latency_ms) * 1000
                span.set_attribute("llm.response.tokens_per_second", round(tokens_per_sec, 2))
        
        # Eficiência
        if usage.get("prompt_tokens", 0) > 0 and len(content) > 0:
            tokens_per_char = usage.get("completion_tokens", 0) / len(content)
            span.set_attribute("llm.response.tokens_per_char", round(tokens_per_char, 4))
        
    except Exception as e:
        logger.debug(f"Erro ao atualizar span com resposta: {e}")


@asynccontextmanager
async def trace_llm_call(project_name: str, operation_name: str):
    """
    Context manager assíncrono para tracing de chamadas LLM.
    
    Uso:
        async with trace_llm_call("discovery-llm", "find_website") as span:
            result = await llm_call(...)
            if span:
                span.set_attribute("result", result)
    
    Args:
        project_name: Nome do projeto no Phoenix (ex: 'discovery-llm', 'profile-llm')
        operation_name: Nome da operação sendo rastreada
    
    Yields:
        Span do OpenTelemetry ou None se tracing desabilitado
    """
    if not _tracing_enabled:
        yield None
        return
    
    tracer_provider = setup_phoenix_tracing(project_name)
    
    if tracer_provider is None:
        yield None
        return
    
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry import context as otel_context
        from opentelemetry.trace import set_span_in_context
        
        # CRÍTICO: Usar o tracer do tracer_provider explicitamente
        # Isso garante que o span seja exportado para o Phoenix
        tracer_instance = otel_trace.get_tracer(__name__, tracer_provider=tracer_provider)
        span = tracer_instance.start_span(operation_name)
        
        try:
            # API correta do OpenTelemetry para context management
            token = otel_context.attach(set_span_in_context(span))
            try:
                yield span
            finally:
                otel_context.detach(token)
        except Exception as e:
            if span:
                span.set_attribute("error", str(e))
                span.set_attribute("error.type", type(e).__name__)
            span.end()
            raise
        else:
            span.end()
    except Exception as e:
        logger.warning(f"⚠️ Erro ao criar span Phoenix: {e}")
        yield None
