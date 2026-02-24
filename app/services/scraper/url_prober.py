"""
Prober de URLs — versão simplificada para comportamento próximo do stress test.

Fluxo simplificado:
1) Um único GET com follow redirects
2) Sem retry e sem fallback para www
3) Aceita HTTP 2xx/3xx, depois o pipeline valida conteúdo
"""

import logging
import time
from typing import Tuple, Set, Optional
from enum import Enum

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

from .constants import REQUEST_TIMEOUT, build_headers
from .html_parser import parse_html

logger = logging.getLogger(__name__)
_PROBE_SESSION: Optional["AsyncSession"] = None


class ProbeErrorType(Enum):
    DNS_ERROR = "dns_error"
    CONNECTION_REFUSED = "connection_refused"
    CONNECTION_TIMEOUT = "connection_timeout"
    SSL_ERROR = "ssl_error"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    HTTP_ERROR = "http_error"
    SERVER_ERROR = "server_error"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class URLNotReachable(Exception):
    def __init__(self, message: str, error_type: ProbeErrorType = ProbeErrorType.UNKNOWN, url: str = ""):
        self.error_type = error_type
        self.url = url
        self.message = message
        super().__init__(message)

    def get_log_message(self) -> str:
        labels = {
            ProbeErrorType.DNS_ERROR: "DNS_ERROR",
            ProbeErrorType.CONNECTION_REFUSED: "CONNECTION_REFUSED",
            ProbeErrorType.CONNECTION_TIMEOUT: "TIMEOUT",
            ProbeErrorType.SSL_ERROR: "SSL_ERROR",
            ProbeErrorType.TOO_MANY_REDIRECTS: "REDIRECT_LOOP",
            ProbeErrorType.HTTP_ERROR: "HTTP_ERROR",
            ProbeErrorType.SERVER_ERROR: "SERVER_ERROR",
            ProbeErrorType.BLOCKED: "BLOCKED",
            ProbeErrorType.UNKNOWN: "UNKNOWN",
        }
        return f"[{labels.get(self.error_type, 'UNKNOWN')}] {self.message}"


def _classify_error(error: Exception) -> Tuple[ProbeErrorType, str]:
    err = str(error).lower()
    if any(x in err for x in ["resolve", "nodename", "getaddrinfo", "dns", "name or service"]):
        return ProbeErrorType.DNS_ERROR, "DNS nao resolve"
    if any(x in err for x in ["connection refused", "errno 111", "errno 61", "connection reset", "broken pipe", "aborted"]):
        return ProbeErrorType.CONNECTION_REFUSED, "Conexao recusada/interrompida"
    if any(x in err for x in ["timeout", "timed out"]):
        return ProbeErrorType.CONNECTION_TIMEOUT, "Timeout"
    if any(x in err for x in ["ssl", "certificate", "handshake"]):
        return ProbeErrorType.SSL_ERROR, "Erro SSL/TLS"
    if any(x in err for x in ["redirect", "too many", "max redirects"]):
        return ProbeErrorType.TOO_MANY_REDIRECTS, "Loop de redirects"
    return ProbeErrorType.UNKNOWN, str(error)[:100]


def _get_probe_session() -> "AsyncSession":
    global _PROBE_SESSION
    if _PROBE_SESSION is None:
        if not HAS_CURL_CFFI:
            raise RuntimeError("curl_cffi não está instalado")
        _PROBE_SESSION = AsyncSession(impersonate="chrome131", verify=False, max_clients=6000)
    return _PROBE_SESSION


async def fast_probe_and_scrape(
    url: str,
    timeout: int = REQUEST_TIMEOUT,
    proxy: Optional[str] = None,
    proxy_provider: Optional[str] = None,
    retry_timeout: Optional[int] = None,
    max_retries: int = 0,
) -> Tuple[str, str, Set[str], Set[str], float]:
    """
    Probe + scrape em um único GET simples, sem retry/fallback.
    Os parâmetros de retry são mantidos por compatibilidade da assinatura.
    """
    del proxy_provider, retry_timeout, max_retries  # compatibilidade de assinatura

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    headers, _ = build_headers()
    session = _get_probe_session()
    t0 = time.perf_counter()

    try:
        resp = await session.get(
            url,
            headers=headers,
            proxy=proxy or None,
            timeout=timeout,
            allow_redirects=True,
            max_redirects=5,
        )
    except Exception as e:
        error_type, msg = _classify_error(e)
        raise URLNotReachable(msg, error_type=error_type, url=url)

    status = int(getattr(resp, "status_code", 0) or 0)
    if status < 200 or status >= 400:
        if status == 403:
            raise URLNotReachable("Acesso bloqueado", error_type=ProbeErrorType.BLOCKED, url=url)
        if 500 <= status < 600:
            raise URLNotReachable(f"Server error HTTP {status}", error_type=ProbeErrorType.SERVER_ERROR, url=url)
        raise URLNotReachable(f"HTTP {status}", error_type=ProbeErrorType.HTTP_ERROR, url=url)

    final_url = str(getattr(resp, "url", url))
    content = resp.content or b""
    text = content.decode("utf-8", errors="ignore")
    parsed_text, docs, links = parse_html(text, final_url)
    elapsed = (time.perf_counter() - t0) * 1000
    return final_url, parsed_text, docs, links, elapsed


# Mantido para compatibilidade com imports existentes
class URLProber:
    """Wrapper de compatibilidade. Usa fast_probe_and_scrape internamente."""

    async def probe(self, base_url: str) -> Tuple[str, float]:
        """Retorna (url_resolvida, tempo_ms). Compativel com interface antiga."""
        url, _text, _docs, _links, elapsed = await fast_probe_and_scrape(base_url)
        return url, elapsed


url_prober = URLProber()
