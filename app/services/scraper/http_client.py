"""
Cliente HTTP para scraping usando curl_cffi.
Semáforos por provider: 711Proxy (800) + Decodo (1500) = 2300 total.
"""

import asyncio
import logging
import re
import os
import random
import time as _time
from typing import Tuple, Set, Optional, List, Dict

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

from .constants import (
    REQUEST_TIMEOUT, MAX_CONCURRENT_REQUESTS,
    MAX_CONCURRENT_711, MAX_CONCURRENT_DECODO, MAX_CONCURRENT_EVOMI,
    MAX_CONCURRENT_PER_PROXY,
    RATE_LIMIT_ENABLED, RATE_LIMIT_PROVIDERS,
    build_headers, BROWSER_PROFILES,
)
from .html_parser import parse_html

logger = logging.getLogger(__name__)

_PROXY_URL = os.getenv("PROXY_GATEWAY_URL", "")

_CHARSET_META_REGEX = re.compile(
    rb'<meta[^>]+charset=["\']?([^"\'\s>]+)', re.IGNORECASE
)
_CHARSET_CONTENT_TYPE_REGEX = re.compile(
    rb'<meta[^>]+content=["\'][^"\']*charset=([^"\'\s;]+)', re.IGNORECASE
)

_MAX_CLIENTS = 3000
_sessions: List = []
_sem_711: Optional[asyncio.Semaphore] = None
_sem_decodo: Optional[asyncio.Semaphore] = None
_sem_evomi: Optional[asyncio.Semaphore] = None
_proxy_semaphores: dict[str, asyncio.Semaphore] = {}
_init_done = False

_active_connections: int = 0
_peak_connections: int = 0
_total_requests: int = 0
_rate_buckets: Dict[str, "AsyncTokenBucket"] = {}
_rate_wait_ms_by_provider: Dict[str, float] = {}
_rate_wait_count_by_provider: Dict[str, int] = {}
_rate_blocked_count_by_provider: Dict[str, int] = {}


class AsyncTokenBucket:
    """Token bucket simples para suavizar rajadas por provider."""

    def __init__(self, rate_per_sec: float, burst_capacity: int):
        self.rate_per_sec = max(float(rate_per_sec), 0.0)
        self.burst_capacity = max(int(burst_capacity), 1)
        self._tokens = float(self.burst_capacity)
        self._last_refill = _time.perf_counter()
        self._lock = asyncio.Lock()

    async def acquire(self) -> tuple[float, bool]:
        if self.rate_per_sec <= 0:
            return 0.0, False

        total_wait = 0.0
        blocked = False
        while True:
            async with self._lock:
                now = _time.perf_counter()
                elapsed = now - self._last_refill
                if elapsed > 0:
                    self._tokens = min(
                        float(self.burst_capacity),
                        self._tokens + elapsed * self.rate_per_sec,
                    )
                    self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return total_wait * 1000.0, blocked

                wait_s = (1.0 - self._tokens) / self.rate_per_sec
                blocked = True
            total_wait += wait_s
            await asyncio.sleep(wait_s)


def _ensure_sessions():
    """Cria sessions compartilhadas e semáforos por provider (lazy, uma vez só)."""
    global _sessions, _sem_711, _sem_decodo, _sem_evomi, _init_done
    if _init_done:
        return
    if not HAS_CURL_CFFI:
        _init_done = True
        return

    profiles = ["chrome131", "chrome124", "safari17_0", "chrome120", "edge101"]
    for p in profiles:
        s = AsyncSession(impersonate=p, verify=False, max_clients=_MAX_CLIENTS)
        _sessions.append(s)

    _sem_711 = asyncio.Semaphore(MAX_CONCURRENT_711)
    _sem_decodo = asyncio.Semaphore(MAX_CONCURRENT_DECODO)
    _sem_evomi = asyncio.Semaphore(MAX_CONCURRENT_EVOMI)
    _init_rate_limiters()

    logger.info(
        f"[http_client] {len(_sessions)} sessions | "
        f"sem_711={MAX_CONCURRENT_711} sem_decodo={MAX_CONCURRENT_DECODO} sem_evomi={MAX_CONCURRENT_EVOMI} "
        f"rate_limit={RATE_LIMIT_ENABLED} "
        f"sem_proxy={MAX_CONCURRENT_PER_PROXY} "
        f"total={MAX_CONCURRENT_REQUESTS}"
    )
    _init_done = True


def _init_rate_limiters():
    _rate_buckets.clear()
    _rate_wait_ms_by_provider.clear()
    _rate_wait_count_by_provider.clear()
    _rate_blocked_count_by_provider.clear()

    for provider in ("711proxy", "decodo", "evomi"):
        cfg = RATE_LIMIT_PROVIDERS.get(provider, {})
        rate = float(cfg.get("rate_per_sec", 0.0))
        burst = int(cfg.get("burst_capacity", 1))
        _rate_buckets[provider] = AsyncTokenBucket(rate_per_sec=rate, burst_capacity=burst)
        _rate_wait_ms_by_provider[provider] = 0.0
        _rate_wait_count_by_provider[provider] = 0
        _rate_blocked_count_by_provider[provider] = 0


async def _acquire_rate_limit(provider: str) -> float:
    if not RATE_LIMIT_ENABLED:
        return 0.0
    bucket = _rate_buckets.get(provider)
    if not bucket:
        return 0.0
    wait_ms, blocked = await bucket.acquire()
    _rate_wait_ms_by_provider[provider] = _rate_wait_ms_by_provider.get(provider, 0.0) + wait_ms
    _rate_wait_count_by_provider[provider] = _rate_wait_count_by_provider.get(provider, 0) + 1
    if blocked:
        _rate_blocked_count_by_provider[provider] = _rate_blocked_count_by_provider.get(provider, 0) + 1
    return wait_ms


def get_shared_session() -> "AsyncSession":
    """Retorna session compartilhada aleatória (fingerprint rotation)."""
    _ensure_sessions()
    if not _sessions:
        raise RuntimeError("curl_cffi não disponível ou sessions não inicializadas")
    return random.choice(_sessions)


def _infer_provider(proxy: str = "", provider: Optional[str] = None) -> str:
    if provider in {"711proxy", "decodo", "evomi"}:
        return provider
    p = (proxy or "").lower()
    if "evomi" in p:
        return "evomi"
    if "decodo" in p:
        return "decodo"
    return "711proxy"


def get_provider_semaphore(proxy: str = "", provider: Optional[str] = None) -> asyncio.Semaphore:
    """Retorna semáforo do provider correto baseado na proxy URL/provider."""
    _ensure_sessions()
    resolved_provider = _infer_provider(proxy, provider)
    if resolved_provider == "decodo":
        return _sem_decodo or asyncio.Semaphore(MAX_CONCURRENT_DECODO)
    if resolved_provider == "evomi":
        return _sem_evomi or asyncio.Semaphore(MAX_CONCURRENT_EVOMI)
    return _sem_711 or asyncio.Semaphore(MAX_CONCURRENT_711)


def get_proxy_semaphore(proxy: str = "") -> asyncio.Semaphore:
    """Retorna semáforo por proxy específico para evitar hot proxy."""
    _ensure_sessions()
    key = proxy or _get_proxy()
    sem = _proxy_semaphores.get(key)
    if sem is None:
        sem = asyncio.Semaphore(MAX_CONCURRENT_PER_PROXY)
        _proxy_semaphores[key] = sem
    return sem


def _get_proxy() -> str:
    return _PROXY_URL


def _track_request_start():
    global _active_connections, _peak_connections, _total_requests
    _active_connections += 1
    _total_requests += 1
    if _active_connections > _peak_connections:
        _peak_connections = _active_connections


def _track_request_end():
    global _active_connections
    _active_connections -= 1


def get_connection_stats() -> dict:
    rate_stats = {}
    for provider in ("711proxy", "decodo", "evomi"):
        wait_count = _rate_wait_count_by_provider.get(provider, 0)
        wait_total = _rate_wait_ms_by_provider.get(provider, 0.0)
        rate_cfg = RATE_LIMIT_PROVIDERS.get(provider, {})
        rate_stats[provider] = {
            "rate_per_sec": float(rate_cfg.get("rate_per_sec", 0.0)),
            "burst_capacity": int(rate_cfg.get("burst_capacity", 0)),
            "wait_count": wait_count,
            "blocked_count": _rate_blocked_count_by_provider.get(provider, 0),
            "wait_ms_total": round(wait_total, 1),
            "wait_ms_avg": round(wait_total / wait_count, 1) if wait_count > 0 else 0.0,
        }
    return {
        "active": _active_connections,
        "peak": _peak_connections,
        "total_requests": _total_requests,
        "capacity_711": MAX_CONCURRENT_711,
        "capacity_decodo": MAX_CONCURRENT_DECODO,
        "capacity_evomi": MAX_CONCURRENT_EVOMI,
        "capacity_total": MAX_CONCURRENT_REQUESTS,
        "rate_limit": {
            "enabled": RATE_LIMIT_ENABLED,
            "providers": rate_stats,
        },
    }


def reset_connection_stats():
    global _active_connections, _peak_connections, _total_requests
    _active_connections = 0
    _peak_connections = 0
    _total_requests = 0
    for provider in ("711proxy", "decodo", "evomi"):
        _rate_wait_ms_by_provider[provider] = 0.0
        _rate_wait_count_by_provider[provider] = 0
        _rate_blocked_count_by_provider[provider] = 0


def _detect_encoding(content: bytes, content_type: Optional[str] = None) -> str:
    if content_type:
        ct_lower = content_type.lower()
        if 'charset=' in ct_lower:
            charset = ct_lower.split('charset=')[-1].split(';')[0].strip()
            if charset:
                return charset

    head_content = content[:2048]

    match = _CHARSET_META_REGEX.search(head_content)
    if match:
        return match.group(1).decode('ascii', errors='ignore').strip()

    match = _CHARSET_CONTENT_TYPE_REGEX.search(head_content)
    if match:
        return match.group(1).decode('ascii', errors='ignore').strip()

    return 'utf-8'


def _is_pdf_content(content: bytes, content_type: Optional[str] = None) -> bool:
    if content_type and 'application/pdf' in content_type.lower():
        return True
    return content[:5] == b'%PDF-'


def _decode_content(content: bytes, content_type: Optional[str] = None) -> str:
    if _is_pdf_content(content, content_type):
        logger.warning("PDF detectado - retornando conteúdo vazio")
        return ""

    encoding = _detect_encoding(content, content_type)

    encoding_map = {
        'iso-8859-1': 'latin-1', 'iso8859-1': 'latin-1',
        'latin1': 'latin-1', 'windows-1252': 'cp1252',
    }
    encoding = encoding_map.get(encoding.lower(), encoding)

    try:
        return content.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            return content.decode('latin-1')


async def cffi_scrape(
    url: str,
    proxy: Optional[str] = None,
    timeout: Optional[int] = None,
    provider: Optional[str] = None,
) -> Tuple[str, Set[str], Set[str]]:
    """Scrape com semáforo por provider (711=800, Decodo=1500)."""
    if not HAS_CURL_CFFI:
        raise RuntimeError("curl_cffi não está instalado")

    headers, _ = build_headers()
    proxy_url = proxy or _get_proxy()
    req_timeout = timeout or REQUEST_TIMEOUT
    resolved_provider = _infer_provider(proxy_url, provider)
    await _acquire_rate_limit(resolved_provider)
    sem_provider = get_provider_semaphore(proxy_url, provider)
    sem_proxy = get_proxy_semaphore(proxy_url)

    async with sem_provider:
        async with sem_proxy:
            _track_request_start()
            try:
                session = get_shared_session()
                resp = await session.get(
                    url, headers=headers, proxy=proxy_url,
                    timeout=req_timeout, allow_redirects=True, max_redirects=5,
                )
            finally:
                _track_request_end()

    if resp.status_code != 200:
        raise Exception(f"Status {resp.status_code}")

    content_type = resp.headers.get('content-type', '')
    text = _decode_content(resp.content, content_type)
    return parse_html(text, url)


async def cffi_scrape_safe(
    url: str,
    proxy: Optional[str] = None,
    timeout: Optional[int] = None,
    referer: Optional[str] = None,
    provider: Optional[str] = None,
) -> Tuple[str, Set[str], Set[str]]:
    """Versão safe com semáforo global — não propaga exceções."""
    cffi_scrape_safe.last_error = None
    cffi_scrape_safe.elapsed_ms = 0.0
    cffi_scrape_safe.sem_wait_ms = 0.0
    cffi_scrape_safe.http_time_ms = 0.0
    cffi_scrape_safe.rate_wait_ms = 0.0
    if not HAS_CURL_CFFI:
        cffi_scrape_safe.last_error = "no_curl_cffi"
        return "", set(), set()

    t0 = _time.perf_counter()
    try:
        headers, _ = build_headers(referer=referer)
        proxy_url = proxy or _get_proxy()
        req_timeout = timeout or REQUEST_TIMEOUT
        resolved_provider = _infer_provider(proxy_url, provider)
        cffi_scrape_safe.rate_wait_ms = await _acquire_rate_limit(resolved_provider)
        sem_provider = get_provider_semaphore(proxy_url, provider)
        sem_proxy = get_proxy_semaphore(proxy_url)

        async with sem_provider:
            async with sem_proxy:
                t_http = _time.perf_counter()
                cffi_scrape_safe.sem_wait_ms = (t_http - t0) * 1000
                _track_request_start()
                try:
                    session = get_shared_session()
                    resp = await session.get(
                        url, headers=headers, proxy=proxy_url,
                        timeout=req_timeout, allow_redirects=True, max_redirects=5,
                    )
                finally:
                    _track_request_end()
        cffi_scrape_safe.http_time_ms = (_time.perf_counter() - t_http) * 1000
        cffi_scrape_safe.elapsed_ms = (_time.perf_counter() - t0) * 1000

        if resp.status_code != 200:
            cffi_scrape_safe.last_error = f"http_{resp.status_code}"
            return "", set(), set()

        content_type = resp.headers.get('content-type', '')
        text = _decode_content(resp.content, content_type)
        return parse_html(text, url)

    except Exception as e:
        now = _time.perf_counter()
        cffi_scrape_safe.elapsed_ms = (now - t0) * 1000
        if cffi_scrape_safe.sem_wait_ms > 0:
            cffi_scrape_safe.http_time_ms = cffi_scrape_safe.elapsed_ms - cffi_scrape_safe.sem_wait_ms
        else:
            cffi_scrape_safe.http_time_ms = cffi_scrape_safe.elapsed_ms
        err_msg = str(e).lower()
        if "timeout" in err_msg or "timed out" in err_msg:
            cffi_scrape_safe.last_error = "proxy_timeout"
        elif "connect" in err_msg or "refused" in err_msg:
            cffi_scrape_safe.last_error = "proxy_connection_error"
        elif "ssl" in err_msg:
            cffi_scrape_safe.last_error = "ssl_error"
        else:
            cffi_scrape_safe.last_error = f"{type(e).__name__}:{str(e)[:30]}"
        return "", set(), set()


cffi_scrape_safe.last_error = None
cffi_scrape_safe.elapsed_ms = 0.0
cffi_scrape_safe.sem_wait_ms = 0.0
cffi_scrape_safe.http_time_ms = 0.0
cffi_scrape_safe.rate_wait_ms = 0.0
