"""
Prober de URLs — versão simplificada para comportamento próximo do stress test.

Fluxo simplificado:
1) Um único GET com follow redirects
2) Sem retry e sem fallback para www
3) Aceita HTTP 2xx/3xx, depois o pipeline valida conteúdo
"""

import logging
import time
import os
import asyncio
from typing import Tuple, Set, Optional
from enum import Enum

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

from .constants import REQUEST_TIMEOUT
from .html_parser import parse_html

logger = logging.getLogger(__name__)
_GATEWAY_PROXY = os.getenv("PROXY_GATEWAY_URL", "")
_PROBE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.google.com/",
}


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


def _new_probe_session() -> "AsyncSession":
    if not HAS_CURL_CFFI:
        raise RuntimeError("curl_cffi não está instalado")
    # Sessão dedicada por request para evitar estado degradado acumulado entre batches.
    return AsyncSession(impersonate="chrome131", verify=False, max_clients=1)


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

    t0 = time.perf_counter()

    effective_proxy = (_GATEWAY_PROXY or proxy or "").strip() or None
    session = _new_probe_session()

    try:
        try:
            resp = await asyncio.wait_for(
                session.get(
                    url,
                    headers=_PROBE_HEADERS,
                    proxy=effective_proxy,
                    timeout=timeout,
                    allow_redirects=True,
                    max_redirects=5,
                ),
                timeout=timeout + 5,
            )
        except asyncio.TimeoutError:
            fast_probe_and_scrape.last_meta = {
                "final_url": url,
                "status_code": 0,
                "raw_content_len": 0,
                "parsed_text_len": 0,
            }
            raise URLNotReachable("Timeout", error_type=ProbeErrorType.CONNECTION_TIMEOUT, url=url)
    except Exception as e:
        fast_probe_and_scrape.last_meta = {
            "final_url": url,
            "status_code": 0,
            "raw_content_len": 0,
            "parsed_text_len": 0,
        }
        error_type, msg = _classify_error(e)
        raise URLNotReachable(msg, error_type=error_type, url=url)
    finally:
        await session.close()

    status = int(getattr(resp, "status_code", 0) or 0)
    if status < 200 or status >= 400:
        fast_probe_and_scrape.last_meta = {
            "final_url": str(getattr(resp, "url", url)),
            "status_code": status,
            "raw_content_len": len(resp.content or b""),
            "parsed_text_len": 0,
        }
        if status == 403:
            raise URLNotReachable("Acesso bloqueado", error_type=ProbeErrorType.BLOCKED, url=url)
        if 500 <= status < 600:
            raise URLNotReachable(f"Server error HTTP {status}", error_type=ProbeErrorType.SERVER_ERROR, url=url)
        raise URLNotReachable(f"HTTP {status}", error_type=ProbeErrorType.HTTP_ERROR, url=url)

    final_url = str(getattr(resp, "url", url))
    content = resp.content or b""
    text = content.decode("utf-8", errors="ignore")
    parsed_text, docs, links = parse_html(text, final_url)
    fast_probe_and_scrape.last_meta = {
        "final_url": final_url,
        "status_code": status,
        "raw_content_len": len(content),
        "parsed_text_len": len(parsed_text or ""),
    }
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
fast_probe_and_scrape.last_meta = {}
