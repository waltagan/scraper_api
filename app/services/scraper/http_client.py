"""
Cliente HTTP para scraping usando curl_cffi.
Session compartilhada com max_clients alto — igual ao stress test.
Cada request recebe IP rotativo do proxy, mas reutiliza conexão TCP/TLS.
"""

import logging
import re
import os
import random
from typing import Tuple, Set, Optional, List

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

from .constants import REQUEST_TIMEOUT, build_headers, BROWSER_PROFILES
from .html_parser import parse_html

logger = logging.getLogger(__name__)

_PROXY_URL = os.getenv("PROXY_GATEWAY_URL", "")

_CHARSET_META_REGEX = re.compile(
    rb'<meta[^>]+charset=["\']?([^"\'\s>]+)', re.IGNORECASE
)
_CHARSET_CONTENT_TYPE_REGEX = re.compile(
    rb'<meta[^>]+content=["\'][^"\']*charset=([^"\'\s;]+)', re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Session compartilhada — mesma lógica do stress test que deu 83.8% sucesso
# ---------------------------------------------------------------------------
_MAX_CLIENTS = 3000
_sessions: List = []
_init_done = False


def _ensure_sessions():
    """Cria sessions compartilhadas (lazy, uma vez só). 5 fingerprints x 3000 conns."""
    global _sessions, _init_done
    if _init_done:
        return
    if not HAS_CURL_CFFI:
        _init_done = True
        return

    profiles = ["chrome131", "chrome124", "safari17_0", "chrome120", "edge101"]
    for p in profiles:
        s = AsyncSession(impersonate=p, verify=False, max_clients=_MAX_CLIENTS)
        _sessions.append(s)

    logger.info(
        f"[http_client] {len(_sessions)} sessions compartilhadas criadas "
        f"(max_clients={_MAX_CLIENTS}/session, total={len(_sessions) * _MAX_CLIENTS} conns)"
    )
    _init_done = True


def get_shared_session() -> "AsyncSession":
    """Retorna session compartilhada aleatória (fingerprint rotation)."""
    _ensure_sessions()
    if not _sessions:
        raise RuntimeError("curl_cffi não disponível ou sessions não inicializadas")
    return random.choice(_sessions)


def _get_proxy() -> str:
    return _PROXY_URL


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
) -> Tuple[str, Set[str], Set[str]]:
    """Scrape usando session compartilhada — IP rotativo, conexão reutilizada."""
    if not HAS_CURL_CFFI:
        raise RuntimeError("curl_cffi não está instalado")

    headers, _ = build_headers()
    proxy_url = proxy or _get_proxy()
    req_timeout = timeout or REQUEST_TIMEOUT
    session = get_shared_session()

    resp = await session.get(
        url, headers=headers, proxy=proxy_url,
        timeout=req_timeout, allow_redirects=True, max_redirects=5,
    )

    if resp.status_code != 200:
        raise Exception(f"Status {resp.status_code}")

    content_type = resp.headers.get('content-type', '')
    text = _decode_content(resp.content, content_type)
    return parse_html(text, url)


async def cffi_scrape_safe(
    url: str,
    proxy: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Tuple[str, Set[str], Set[str]]:
    """Versão safe — não propaga exceções."""
    cffi_scrape_safe.last_error = None
    if not HAS_CURL_CFFI:
        cffi_scrape_safe.last_error = "no_curl_cffi"
        return "", set(), set()

    try:
        headers, _ = build_headers()
        proxy_url = proxy or _get_proxy()
        req_timeout = timeout or REQUEST_TIMEOUT
        session = get_shared_session()

        resp = await session.get(
            url, headers=headers, proxy=proxy_url,
            timeout=req_timeout, allow_redirects=True, max_redirects=5,
        )

        if resp.status_code != 200:
            cffi_scrape_safe.last_error = f"http_{resp.status_code}"
            return "", set(), set()

        content_type = resp.headers.get('content-type', '')
        text = _decode_content(resp.content, content_type)
        return parse_html(text, url)

    except Exception as e:
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
