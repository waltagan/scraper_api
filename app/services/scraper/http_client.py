"""
Cliente HTTP para scraping usando curl_cffi.
Responsável por baixar conteúdo de páginas (somente texto, sem imagens).
Usa sticky sessions do pool — sem semáforo, IPs já alocados.
"""

import logging
import re
import time
from typing import Tuple, Set, Optional

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

from .constants import REQUEST_TIMEOUT, build_headers
from .html_parser import parse_html
from .session_pool import get_session, record_result

logger = logging.getLogger(__name__)

_CHARSET_META_REGEX = re.compile(
    rb'<meta[^>]+charset=["\']?([^"\'\s>]+)', re.IGNORECASE
)
_CHARSET_CONTENT_TYPE_REGEX = re.compile(
    rb'<meta[^>]+content=["\'][^"\']*charset=([^"\'\s;]+)', re.IGNORECASE
)


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
    session: Optional[AsyncSession] = None,
) -> Tuple[str, Set[str], Set[str]]:
    """Scrape usando curl_cffi. Retorna (texto, docs, links_internos)."""
    if not HAS_CURL_CFFI:
        raise RuntimeError("curl_cffi não está instalado")

    if session:
        headers, _ = build_headers()
        resp = await session.get(url, headers=headers)
    else:
        headers, _ = build_headers()
        sticky = get_session()
        t0 = time.perf_counter()
        try:
            resp = await sticky.session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            lat = (time.perf_counter() - t0) * 1000
            record_result(sticky, resp.status_code == 200, lat)
        except Exception:
            lat = (time.perf_counter() - t0) * 1000
            record_result(sticky, False, lat)
            raise

    if resp.status_code != 200:
        raise Exception(f"Status {resp.status_code}")

    content_type = resp.headers.get('content-type', '')
    text = _decode_content(resp.content, content_type)
    return parse_html(text, url)


async def cffi_scrape_safe(
    url: str,
    proxy: Optional[str] = None,
) -> Tuple[str, Set[str], Set[str]]:
    """
    Versão safe do cffi_scrape — não propaga exceções.
    Seta cffi_scrape_safe.last_error para diagnóstico.
    """
    cffi_scrape_safe.last_error = None
    if not HAS_CURL_CFFI:
        cffi_scrape_safe.last_error = "no_curl_cffi"
        return "", set(), set()

    try:
        headers, _ = build_headers()
        sticky = get_session()
        t0 = time.perf_counter()
        try:
            resp = await sticky.session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            lat = (time.perf_counter() - t0) * 1000

            if resp.status_code != 200:
                record_result(sticky, False, lat)
                cffi_scrape_safe.last_error = f"http_{resp.status_code}"
                return "", set(), set()

            record_result(sticky, True, lat)
            content_type = resp.headers.get('content-type', '')
            text = _decode_content(resp.content, content_type)
            return parse_html(text, url)

        except Exception as e:
            lat = (time.perf_counter() - t0) * 1000
            record_result(sticky, False, lat)
            raise

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
