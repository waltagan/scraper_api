import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.core.phoenix_tracer import (
    setup_phoenix_tracing,
    create_llm_span,
    update_llm_span_response,
    _inject_sglang_stream_options,  # type: ignore[attr-defined]
)

logger = logging.getLogger(__name__)


class SGLangError(Exception):
    """Erro genérico ao chamar o SGLang."""


class SGLangTimeoutError(SGLangError):
    """Timeout ao chamar o SGLang."""


class SGLangBadResponseError(SGLangError):
    """Resposta inválida ou malformada do SGLang."""


class SGLangClient:
    """
    Cliente OpenAI‑compatible para SGLang (Vast.ai).

    Responsável apenas por:
    - Montar requisições HTTP para /v1/chat/completions
    - Anexar headers de autenticação (Bearer MODEL_KEY)
    - Integrar com Phoenix para spans de LLM
    - Retornar o dict da resposta no formato OpenAI

    Toda lógica de domínio (prompts, FactBundle, CompanyProfile) fica em serviços específicos.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
        phoenix_project: str = "sglang-qwen-vast",
    ) -> None:
        self.base_url = (base_url or settings.URL_MODEL).rstrip("/")
        self.model = model or settings.MODEL_NAME
        self.api_key = api_key or settings.MODEL_KEY
        self.timeout = timeout
        self.phoenix_project = phoenix_project

        if not self.base_url:
            raise ValueError("SGLangClient: URL_MODEL/BASE_URL não configurado.")

        # Garantir formato OpenAI‑compatible (/v1)
        if not self.base_url.endswith("/v1"):
            self.base_url = self.base_url.rstrip("/") + "/v1"

        # Preparar headers fixos
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._headers = headers
        self._tracer_provider = setup_phoenix_tracing(self.phoenix_project)

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.0,
        top_p: float = 1.0,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        extra_params: Optional[Dict[str, Any]] = None,
        ctx_label: str = "",
    ) -> Dict[str, Any]:
        """
        Chama /v1/chat/completions no SGLang e retorna o dict da resposta.

        - `messages`: lista de mensagens OpenAI (`role`, `content`).
        - `response_format`: pode ser json_schema para CompanyProfile ou FactBundle.
        - `extra_params`: permite passar parâmetros adicionais específicos (ex.: `seed`).
        """
        url = f"{self.base_url}/chat/completions"

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        if extra_params:
            payload.update(extra_params)

        # Garantir stream_options para SGLang quando stream=True (para Phoenix usage)
        try:
            _inject_sglang_stream_options(payload)
        except Exception:
            # Se a função não estiver disponível por alguma razão, seguimos sem ela.
            pass

        span = create_llm_span(
            tracer_provider=self._tracer_provider,
            span_name="sglang.chat_completion",
            model=self.model,
            messages=messages,
            request_params=payload,
            provider="SGLang",
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=self._headers, json=payload)
        except httpx.TimeoutException as e:
            if span:
                span.set_attribute("http.error", "timeout")
                span.set_attribute("http.error.detail", str(e))
                span.end()
            logger.error(f"{ctx_label}SGLangClient: Timeout ao chamar {url}: {e}")
            raise SGLangTimeoutError(str(e)) from e
        except Exception as e:
            if span:
                span.set_attribute("http.error", "network_error")
                span.set_attribute("http.error.detail", str(e))
                span.end()
            logger.error(f"{ctx_label}SGLangClient: Erro de rede ao chamar {url}: {e}")
            raise SGLangError(str(e)) from e

        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            if span:
                span.set_attribute("http.status_code", resp.status_code)
                span.set_attribute("http.raw_body_truncated", resp.text[:500])
                span.end()
            logger.error(f"{ctx_label}SGLangClient: Resposta não‑JSON ({resp.status_code}): {e}")
            raise SGLangBadResponseError("Resposta não é JSON válida") from e

        # Atualizar span com dados da resposta
        try:
            update_llm_span_response(span, data, http_status_code=resp.status_code)
        finally:
            if span:
                span.end()

        if resp.status_code >= 400:
            logger.error(
                f"{ctx_label}SGLangClient: Erro HTTP {resp.status_code} - corpo={json.dumps(data)[:500]}"
            )
            raise SGLangBadResponseError(f"HTTP {resp.status_code}: {data}")

        return data


_sglang_client: Optional[SGLangClient] = None


def get_sglang_client() -> SGLangClient:
    """Singleton do SGLangClient para uso em todo o pipeline de perfil."""
    global _sglang_client
    if _sglang_client is None:
        _sglang_client = SGLangClient()
    return _sglang_client

