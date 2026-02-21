"""
Prober de URLs — encontra a melhor variação acessível (http/https, www/non-www).
Usa apenas curl_cffi via proxy gateway.
"""

import asyncio
import time
import logging
import socket
from typing import List, Tuple, Optional
from urllib.parse import urlparse
from enum import Enum

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

from .constants import PROBE_TIMEOUT, MAX_RETRIES, build_headers
from .proxy_gate import acquire_proxy_slot

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


def _classify_probe_error(error: Exception, url: str) -> Tuple[ProbeErrorType, str]:
    error_str = str(error).lower()

    if any(x in error_str for x in ['nodename nor servname', 'name or service not known',
                                      'getaddrinfo failed', 'dns', 'resolve']):
        return ProbeErrorType.DNS_ERROR, "DNS não resolve"
    if isinstance(error, socket.gaierror):
        return ProbeErrorType.DNS_ERROR, f"Falha DNS: {error}"
    if any(x in error_str for x in ['connection refused', 'errno 111', 'errno 61']):
        return ProbeErrorType.CONNECTION_REFUSED, "Conexão recusada"
    if any(x in error_str for x in ['timeout', 'timed out', 'time out']):
        return ProbeErrorType.CONNECTION_TIMEOUT, "Timeout"
    if any(x in error_str for x in ['connection reset', 'broken pipe', 'connection aborted']):
        return ProbeErrorType.CONNECTION_REFUSED, "Conexão interrompida"
    if any(x in error_str for x in ['ssl', 'certificate', 'cert', 'handshake']):
        return ProbeErrorType.SSL_ERROR, "Erro SSL/TLS"
    if any(x in error_str for x in ['redirect', 'too many', '47']):
        return ProbeErrorType.TOO_MANY_REDIRECTS, "Loop de redirects"
    if 'http' in type(error).__name__.lower():
        return ProbeErrorType.HTTP_ERROR, f"Erro HTTP: {error}"
    return ProbeErrorType.UNKNOWN, str(error)


RETRYABLE_PROBE_ERRORS = frozenset({
    ProbeErrorType.CONNECTION_TIMEOUT,
    ProbeErrorType.CONNECTION_REFUSED,
    ProbeErrorType.UNKNOWN,
    ProbeErrorType.BLOCKED,
})


class URLProber:
    """Testa variações de URL via proxy gateway para encontrar a melhor."""

    def __init__(self, timeout: float = PROBE_TIMEOUT, max_retries: int = MAX_RETRIES):
        self.timeout = timeout
        self.max_retries = max_retries
        self._cache: dict = {}

    async def probe(self, base_url: str) -> Tuple[str, float]:
        """
        Testa variações de URL com retry automático.
        Returns: (melhor_url, tempo_resposta_ms)
        Raises: URLNotReachable se todas tentativas falharem.
        """
        if base_url in self._cache:
            cached = self._cache[base_url]
            return cached['url'], cached['time']

        if not base_url.startswith(('http://', 'https://')):
            base_url = 'https://' + base_url

        last_error: Optional[URLNotReachable] = None
        for attempt in range(self.max_retries):
            try:
                url, resp_time = await self._probe_once(base_url)
                self._cache[base_url] = {'url': url, 'time': resp_time}
                return url, resp_time
            except URLNotReachable as e:
                last_error = e
                if e.error_type not in RETRYABLE_PROBE_ERRORS:
                    raise
                if attempt < self.max_retries - 1:
                    logger.info(f"Probe retry {attempt+2}/{self.max_retries} para {base_url} ({e.error_type.value})")

        raise last_error  # type: ignore[misc]

    async def _probe_once(self, base_url: str) -> Tuple[str, float]:
        collected_errors: List[Tuple[str, ProbeErrorType, str]] = []

        result, error_info = await self._test_url(base_url)
        if result and result[1] < 400:
            return base_url, result[0]
        if error_info:
            collected_errors.append((base_url, error_info[0], error_info[1]))

        variations = self._generate_variations(base_url)
        variations = [v for v in variations if v != base_url]

        if not variations:
            error_type, error_msg = self._best_error(collected_errors, base_url)
            raise URLNotReachable(error_msg, error_type=error_type, url=base_url)

        tasks = [self._test_url(url) for url in variations]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful = []
        for url, res in zip(variations, results):
            if isinstance(res, Exception):
                et, em = _classify_probe_error(res, url)
                collected_errors.append((url, et, em))
                continue
            if res is not None:
                resp_result, ei = res
                if resp_result:
                    rt, status = resp_result
                    if status < 400:
                        successful.append((url, rt, status))
                    elif status >= 500:
                        collected_errors.append((url, ProbeErrorType.SERVER_ERROR, f"Erro {status}"))
                    elif status == 403:
                        collected_errors.append((url, ProbeErrorType.BLOCKED, "Bloqueado (403)"))
                if ei:
                    collected_errors.append((url, ei[0], ei[1]))

        if not successful:
            error_type, error_msg = self._best_error(collected_errors, base_url)
            raise URLNotReachable(error_msg, error_type=error_type, url=base_url)

        successful.sort(key=lambda x: (x[2] >= 300, x[1]))
        best_url, best_time, _ = successful[0]
        return best_url, best_time

    def _best_error(self, errors, base_url):
        if not errors:
            return ProbeErrorType.UNKNOWN, f"Nenhuma variação de {base_url} respondeu"
        priority = {
            ProbeErrorType.DNS_ERROR: 1, ProbeErrorType.SSL_ERROR: 2,
            ProbeErrorType.CONNECTION_REFUSED: 3, ProbeErrorType.CONNECTION_TIMEOUT: 4,
            ProbeErrorType.TOO_MANY_REDIRECTS: 5, ProbeErrorType.BLOCKED: 6,
            ProbeErrorType.SERVER_ERROR: 7, ProbeErrorType.HTTP_ERROR: 8,
            ProbeErrorType.UNKNOWN: 9,
        }
        errors.sort(key=lambda x: priority.get(x[1], 99))
        return errors[0][1], errors[0][2]

    async def _test_url(self, url):
        """Testa URL via curl_cffi + proxy. Retorna ((time_ms, status), error_info) ou (None, error_info)."""
        if not HAS_CURL_CFFI:
            return None, (ProbeErrorType.UNKNOWN, "curl_cffi não disponível")
        try:
            from app.services.scraper_manager.proxy_manager import proxy_pool
            proxy = proxy_pool.get_next_proxy()
            headers, impersonate = build_headers()

            async with acquire_proxy_slot():
                async with AsyncSession(
                    impersonate=impersonate, proxy=proxy,
                    timeout=self.timeout, verify=False, max_redirects=5,
                ) as session:
                    start = time.perf_counter()
                    try:
                        resp = await session.head(url, headers=headers, allow_redirects=True)
                        elapsed = (time.perf_counter() - start) * 1000

                        if resp.status_code == 403:
                            start = time.perf_counter()
                            resp = await session.get(url, headers=headers, allow_redirects=True)
                            elapsed = (time.perf_counter() - start) * 1000

                        return (elapsed, resp.status_code), None
                    except Exception as head_error:
                        if "redirect" in str(head_error).lower() or "47" in str(head_error):
                            start = time.perf_counter()
                            resp = await session.get(url, headers=headers, allow_redirects=True)
                            elapsed = (time.perf_counter() - start) * 1000
                            return (elapsed, resp.status_code), None
                        raise

        except Exception as e:
            et, em = _classify_probe_error(e, url)
            return None, (et, em)

    def _generate_variations(self, base_url: str) -> List[str]:
        if not base_url.startswith(('http://', 'https://')):
            base_url = 'https://' + base_url

        parsed = urlparse(base_url)
        domain = parsed.netloc
        path = parsed.path or '/'
        base_domain = domain.replace('www.', '')
        variations = set()

        for scheme in ['https', 'http']:
            for prefix in ['', 'www.']:
                full_domain = prefix + base_domain
                if not full_domain.startswith('www.www.'):
                    url = f"{scheme}://{full_domain}{path}"
                    variations.add(url.rstrip('/'))

        original = f"{parsed.scheme}://{domain}{path}".rstrip('/')
        variations.add(original)

        return sorted(variations, key=lambda x: (not x.startswith('https'), 'www.' not in x))


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


url_prober = URLProber()
