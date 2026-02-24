"""
Prober de URLs — fast probe com fallback DNS.

Faz um unico GET com follow redirect. Se DNS falhar, tenta www.
Retorna o conteudo da pagina junto com a URL resolvida, eliminando
a necessidade de um GET separado para a main page.
"""

import logging
import time
from typing import Tuple, Set, Optional
from enum import Enum

from .constants import REQUEST_TIMEOUT
from .retry_control import consume_retry_token, sleep_retry_jitter

logger = logging.getLogger(__name__)


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
    if any(x in err for x in ['resolve', 'nodename', 'getaddrinfo', 'dns', 'name or service']):
        return ProbeErrorType.DNS_ERROR, "DNS nao resolve"
    if any(x in err for x in ['connection refused', 'errno 111', 'errno 61']):
        return ProbeErrorType.CONNECTION_REFUSED, "Conexao recusada"
    if any(x in err for x in ['timeout', 'timed out']):
        return ProbeErrorType.CONNECTION_TIMEOUT, "Timeout"
    if any(x in err for x in ['connection reset', 'broken pipe', 'connection aborted']):
        return ProbeErrorType.CONNECTION_REFUSED, "Conexao interrompida"
    if any(x in err for x in ['ssl', 'certificate', 'handshake']):
        return ProbeErrorType.SSL_ERROR, "Erro SSL/TLS"
    if any(x in err for x in ['redirect', 'too many', '47']):
        return ProbeErrorType.TOO_MANY_REDIRECTS, "Loop de redirects"
    return ProbeErrorType.UNKNOWN, str(error)[:100]


def _is_dns_error(error: Exception) -> bool:
    err = str(error).lower()
    return any(x in err for x in ['resolve', 'nodename', 'getaddrinfo', 'dns', 'name or service'])


async def fast_probe_and_scrape(
    url: str,
    timeout: int = REQUEST_TIMEOUT,
    proxy: Optional[str] = None,
    proxy_provider: Optional[str] = None,
    retry_timeout: Optional[int] = None,
    max_retries: int = 0,
) -> Tuple[str, str, Set[str], Set[str], float]:
    """
    Probe rapido + scrape em um unico GET.

    Fluxo:
    1. GET na URL original com follow redirect
    2. Se DNS falhar e nao tem www., tenta com www.
    3. Retorna (url_final, text, docs, links, tempo_ms)

    Raises URLNotReachable se nenhuma variacao funcionar.
    """
    from .http_client import cffi_scrape

    fast_probe_and_scrape.last_retries_used = 0
    fast_probe_and_scrape.last_retries_dropped = 0

    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'

    t0 = time.perf_counter()

    def _is_retryable_error(err: Exception) -> bool:
        msg = str(err).lower()
        return any(k in msg for k in [
            "timeout", "timed out", "connection", "refused", "reset",
            "status 429", "status 502", "status 503", "status 504",
        ])

    async def _try_once(target_url: str, req_timeout: int):
        return await cffi_scrape(
            target_url,
            proxy=proxy,
            timeout=req_timeout,
            provider=proxy_provider,
        )

    try:
        text, docs, links = await _try_once(url, timeout)
        elapsed = (time.perf_counter() - t0) * 1000
        return url, text, docs, links, elapsed
    except Exception as first_error:
        if max_retries > 0 and retry_timeout and _is_retryable_error(first_error):
            if await consume_retry_token():
                fast_probe_and_scrape.last_retries_used += 1
                await sleep_retry_jitter()
                try:
                    text, docs, links = await _try_once(url, retry_timeout)
                    elapsed = (time.perf_counter() - t0) * 1000
                    return url, text, docs, links, elapsed
                except Exception as retried_error:
                    first_error = retried_error
            else:
                fast_probe_and_scrape.last_retries_dropped += 1

        if _is_dns_error(first_error) and 'www.' not in url:
            www_url = url.replace('://', '://www.', 1)
            try:
                text, docs, links = await _try_once(www_url, timeout)
                elapsed = (time.perf_counter() - t0) * 1000
                return www_url, text, docs, links, elapsed
            except Exception as www_error:
                if max_retries > 0 and retry_timeout and _is_retryable_error(www_error):
                    if await consume_retry_token():
                        fast_probe_and_scrape.last_retries_used += 1
                        await sleep_retry_jitter()
                        try:
                            text, docs, links = await _try_once(www_url, retry_timeout)
                            elapsed = (time.perf_counter() - t0) * 1000
                            return www_url, text, docs, links, elapsed
                        except Exception as www_retry_error:
                            www_error = www_retry_error
                    else:
                        fast_probe_and_scrape.last_retries_dropped += 1
                elapsed = (time.perf_counter() - t0) * 1000
                error_type, msg = _classify_error(www_error)
                raise URLNotReachable(msg, error_type=error_type, url=url)

        elapsed = (time.perf_counter() - t0) * 1000
        error_type, msg = _classify_error(first_error)
        raise URLNotReachable(msg, error_type=error_type, url=url)


# Mantido para compatibilidade com imports existentes
class URLProber:
    """Wrapper de compatibilidade. Usa fast_probe_and_scrape internamente."""

    async def probe(self, base_url: str) -> Tuple[str, float]:
        """Retorna (url_resolvida, tempo_ms). Compativel com interface antiga."""
        url, _text, _docs, _links, elapsed = await fast_probe_and_scrape(base_url)
        return url, elapsed


url_prober = URLProber()
fast_probe_and_scrape.last_retries_used = 0
fast_probe_and_scrape.last_retries_dropped = 0
