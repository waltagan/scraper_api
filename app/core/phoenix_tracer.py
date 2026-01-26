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
    
    CRÍTICO: Configura Resource com openinference.project.name para isolamento
    correto de projetos no Phoenix. Isso garante que traces não caiam no "default".
    
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
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            
            # CRÍTICO: Configuração robusta do Phoenix com BatchSpanProcessor
            # BatchSpanProcessor não bloqueia o loop de eventos (melhor performance)
            # SimpleSpanProcessor (padrão) pode bloquear em alta carga
            
            # Criar Resource explícito com isolamento de projeto
            resource = Resource.create({
                "service.name": "scraper-api",
                "openinference.project.name": project_name,  # Segregação de projeto
            })
            
            # Criar TracerProvider com Resource customizado
            tracer_provider = TracerProvider(resource=resource)
            
            # Usar BatchSpanProcessor para não bloquear performance
            # BatchSpanProcessor agrupa spans e envia em lotes, reduzindo overhead
            otlp_exporter = OTLPSpanExporter(
                endpoint=f"{settings.PHOENIX_COLLECTOR_URL}/v1/traces"
            )
            batch_processor = BatchSpanProcessor(otlp_exporter)
            tracer_provider.add_span_processor(batch_processor)
            
            # Registrar como global (opcional, mas garante compatibilidade)
            from opentelemetry import trace
            trace.set_tracer_provider(tracer_provider)
            
            # Instrumentar OpenAI (captura chamadas via AsyncOpenAI)
            OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
            
            _tracer_providers[project_name] = tracer_provider
            logger.info(
                f"✅ Phoenix tracing configurado para projeto: {project_name} "
                f"(endpoint: {settings.PHOENIX_COLLECTOR_URL}/v1/traces, "
                f"processor: BatchSpanProcessor)"
            )
        except ImportError as e:
            logger.warning(f"⚠️ Bibliotecas Phoenix não instaladas: {e}")
            logger.warning("⚠️ Tracing desabilitado. Instale: pip install arize-phoenix-otel openinference-instrumentation-openai")
            _tracer_providers[project_name] = None
        except Exception as e:
            logger.error(f"❌ Erro ao configurar Phoenix tracing: {e}")
            _tracer_providers[project_name] = None
    
    return _tracer_providers.get(project_name)


def _normalize_model_name(model_name: str) -> str:
    """
    Normaliza nome de modelo do SGLang.
    
    SGLang frequentemente retorna caminhos completos de arquivo como nome do modelo
    (ex: /data/models/deepseek-ai/DeepSeek-V3). Esta função extrai apenas o
    identificador significativo (ex: DeepSeek-V3).
    
    Args:
        model_name: Nome do modelo como retornado pelo SGLang
    
    Returns:
        Nome normalizado do modelo
    """
    if not model_name:
        return model_name
    
    # Se contém caminho de arquivo (começa com / ou contém /)
    if "/" in model_name:
        # Pegar última parte do caminho
        parts = model_name.split("/")
        model_name = parts[-1]
    
    # Remover espaços extras
    model_name = model_name.strip()
    
    return model_name


def _inject_sglang_stream_options(request_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Injeta automaticamente stream_options={"include_usage": True} para SGLang.
    
    CRÍTICO: SGLang omite estatísticas de uso (usage) em respostas de streaming
    a menos que stream_options={"include_usage": True} seja explicitamente enviado.
    Sem isso, os traces no Phoenix mostram 0 tokens, impossibilitando análise de custos.
    
    Esta função detecta se é uma requisição de streaming e injeta automaticamente
    o stream_options necessário, garantindo 100% de conformidade de rastreamento.
    
    Args:
        request_params: Parâmetros da requisição (será modificado in-place)
    
    Returns:
        request_params modificado (mesmo objeto)
    """
    # Verificar se é streaming
    if request_params.get("stream", False):
        # Verificar se stream_options já existe
        if "stream_options" not in request_params:
            # Injetar automaticamente
            request_params["stream_options"] = {"include_usage": True}
            logger.debug(
                "🔧 SGLang: Auto-injetado stream_options={'include_usage': True} "
                "para garantir rastreamento de tokens em streaming"
            )
        elif isinstance(request_params.get("stream_options"), dict):
            # Se já existe, garantir que include_usage está True
            stream_opts = request_params["stream_options"]
            if stream_opts.get("include_usage") is not True:
                stream_opts["include_usage"] = True
                logger.debug(
                    "🔧 SGLang: Forçado include_usage=True em stream_options existente"
                )
    
    return request_params


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
        # CRÍTICO: Usar SpanKind.CLIENT para que Phoenix reconheça como chamada LLM externa
        span = tracer.start_span(
            span_name,
            kind=SpanKind.CLIENT  # CLIENT para chamadas LLM externas
        )
        
        # CRÍTICO: Definir openinference.span.kind para garantir reconhecimento pelo Phoenix
        # Sem isso, o span pode não aparecer nas visualizações de LLM
        try:
            # Tentar usar constante do openinference se disponível
            from openinference.semconv import SpanAttributes
            span.set_attribute("openinference.span.kind", "LLM")
        except ImportError:
            # Fallback: usar string direta
            span.set_attribute("openinference.span.kind", "LLM")
        
        # ============================================================
        # Atributos OpenInference (convenções do Phoenix)
        # ============================================================
        
        # Normalizar nome do modelo (SGLang retorna caminhos completos)
        normalized_model = _normalize_model_name(model)
        
        # Identificação do LLM
        # Usar AMBOS gen_ai.* (OpenTelemetry GenAI) e llm.* (OpenInference nativo)
        # para máxima compatibilidade durante período de transição
        _set_attribute_safe(span, "gen_ai.request.model", normalized_model)
        _set_attribute_safe(span, "llm.model_name", normalized_model)  # OpenInference nativo
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
        
        # Nota: Não precisamos armazenar start_time manualmente
        # O OpenTelemetry já rastreia automaticamente o início e fim do span
        # A latência será calculada automaticamente pelo Phoenix baseado na duração do span
        
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
        # Normalizar nome do modelo na resposta também
        response_model = response_data.get("model", "")
        normalized_response_model = _normalize_model_name(response_model)
        
        _set_attribute_safe(span, "gen_ai.response.content", content)
        _set_attribute_safe(span, "llm.output.value", content)  # OpenInference nativo
        span.set_attribute("gen_ai.response.finish_reason", choice.get("finish_reason", "unknown"))
        span.set_attribute("gen_ai.response.model", normalized_response_model)
        span.set_attribute("llm.model_name", normalized_response_model)  # Atualizar se mudou
        span.set_attribute("gen_ai.response.id", response_data.get("id", ""))
        span.set_attribute("gen_ai.response.created", response_data.get("created", 0))
        
        # CRÍTICO: Capturar reasoning_content se presente (modelos de raciocínio)
        # SGLang pode retornar reasoning_content em choice.delta.reasoning_content
        # ou message.reasoning_content dependendo do parser
        reasoning_content = None
        if "reasoning_content" in message:
            reasoning_content = message.get("reasoning_content", "")
        elif "reasoning_content" in choice:
            reasoning_content = choice.get("reasoning_content", "")
        
        if reasoning_content:
            _set_attribute_safe(span, "llm.output.reasoning", reasoning_content)
            logger.debug(f"Capturado reasoning_content: {len(reasoning_content)} caracteres")
        
        # Métricas de uso
        # Usar AMBOS gen_ai.* e llm.* para compatibilidade máxima
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)
        
        # OpenTelemetry GenAI (gen_ai.*)
        span.set_attribute("gen_ai.usage.prompt_tokens", prompt_tokens)
        span.set_attribute("gen_ai.usage.completion_tokens", completion_tokens)
        span.set_attribute("gen_ai.usage.total_tokens", total_tokens)
        
        # OpenInference nativo (llm.*) - CRÍTICO para Phoenix
        span.set_attribute("llm.token_count.prompt", prompt_tokens)
        span.set_attribute("llm.token_count.completion", completion_tokens)
        span.set_attribute("llm.token_count.total", total_tokens)
        
        # v10.0: Métricas avançadas para SGLang/Vast.ai
        # TTFT (Time to First Token) - latência de preenchimento de cache
        # SGLang pode retornar ttft_ms na resposta se disponível
        ttft_ms = response_data.get("ttft_ms") or response_data.get("ttft") or None
        if ttft_ms is not None:
            span.set_attribute("llm.ttft_ms", float(ttft_ms))
            span.set_attribute("llm.vast.ttft", float(ttft_ms))
            logger.debug(f"TTFT capturado: {ttft_ms}ms")
        
        # Prefix Cache Hit (SGLang reutiliza KV Cache quando system_prompt é idêntico)
        # SGLang pode retornar prefix_cache_hit na resposta se disponível
        prefix_cache_hit = response_data.get("prefix_cache_hit") or response_data.get("cache_hit") or None
        if prefix_cache_hit is not None:
            span.set_attribute("llm.vast.prefix_cache_hit", bool(prefix_cache_hit))
            logger.debug(f"Prefix cache hit: {prefix_cache_hit}")
        
        # Node ID (Vast.ai específico)
        vast_node_id = response_data.get("node_id") or response_data.get("vast_node_id") or None
        if vast_node_id:
            span.set_attribute("llm.vast.node_id", str(vast_node_id))
        
        # Métricas adicionais
        span.set_attribute("llm.response.content_length", len(content))
        span.set_attribute("llm.response.status_code", http_status_code)
        
        # Latência (calcular usando atributo start_time_ns se disponível)
        # Nota: OpenTelemetry já calcula latência automaticamente baseado no start/end do span
        # Mas vamos adicionar nossa própria métrica também
        try:
            # Tentar obter start_time_ns dos atributos do span
            # Como os atributos podem não estar acessíveis diretamente, vamos usar uma abordagem diferente
            # O OpenTelemetry já calcula a duração do span automaticamente
            # Vamos apenas adicionar métricas de tokens por segundo baseadas na duração do span
            if usage.get("completion_tokens", 0) > 0:
                # Usar uma estimativa baseada no tempo de resposta HTTP
                # A latência real será calculada pelo Phoenix baseado no span duration
                pass
        except Exception:
            # Se não conseguir calcular, apenas pular
            pass
        
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


@asynccontextmanager
async def trace_workflow(project_name: str, workflow_name: str):
    """
    Context manager assíncrono para tracing de workflows completos.
    
    v10.0: Span pai que engloba múltiplas operações (chunking, LLM calls, merge)
    
    Uso:
        async with trace_workflow("profile-llm", "company_profiling_workflow") as workflow_span:
            # Chunking
            chunks = process_chunks(...)
            if workflow_span:
                workflow_span.set_attribute("workflow.chunks_count", len(chunks))
            
            # LLM calls (criarão spans filhos automaticamente)
            profiles = await process_llm_calls(...)
            
            # Merge
            final_profile = merge_profiles(profiles)
    
    Args:
        project_name: Nome do projeto no Phoenix
        workflow_name: Nome do workflow (ex: 'company_profiling_workflow')
    
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
        from opentelemetry.trace import set_span_in_context, SpanKind
        
        tracer_instance = otel_trace.get_tracer(__name__, tracer_provider=tracer_provider)
        
        # v10.0: Span pai com kind INTERNAL (workflow interno)
        span = tracer_instance.start_span(
            workflow_name,
            kind=SpanKind.INTERNAL
        )
        
        # Marcar como workflow
        try:
            from openinference.semconv import SpanAttributes
            span.set_attribute("workflow.name", workflow_name)
            span.set_attribute("workflow.project", project_name)
        except ImportError:
            span.set_attribute("workflow.name", workflow_name)
            span.set_attribute("workflow.project", project_name)
        
        try:
            token = otel_context.attach(set_span_in_context(span))
            try:
                yield span
            finally:
                otel_context.detach(token)
        except Exception as e:
            if span:
                span.set_attribute("workflow.error", str(e))
                span.set_attribute("workflow.error.type", type(e).__name__)
            span.end()
            raise
        else:
            span.end()
    except Exception as e:
        logger.warning(f"⚠️ Erro ao criar workflow span Phoenix: {e}")
        yield None
