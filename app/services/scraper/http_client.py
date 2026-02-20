"""
Cliente HTTP para scraping usando curl_cffi e system curl.
Responsável por baixar o conteúdo das páginas.
"""

import asyncio
import subprocess
import logging
import re
from typing import Tuple, Set, Optional

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

from .constants import DEFAULT_HEADERS, scraper_config, build_headers, get_random_impersonate
from .html_parser import parse_html

logger = logging.getLogger(__name__)

# Regex para detectar charset na meta tag HTML
_CHARSET_META_REGEX = re.compile(
    rb'<meta[^>]+charset=["\']?([^"\'\s>]+)',
    re.IGNORECASE
)
_CHARSET_CONTENT_TYPE_REGEX = re.compile(
    rb'<meta[^>]+content=["\'][^"\']*charset=([^"\'\s;]+)',
    re.IGNORECASE
)


def _detect_encoding(content: bytes, content_type: Optional[str] = None) -> str:
    """
    Detecta o encoding do conteúdo HTML.
    
    Ordem de prioridade:
    1. Header Content-Type
    2. Meta tag charset
    3. Fallback para UTF-8
    
    Args:
        content: Bytes do conteúdo HTML
        content_type: Header Content-Type da resposta
    
    Returns:
        Nome do encoding detectado
    """
    # 1. Tentar extrair do header Content-Type
    if content_type:
        ct_lower = content_type.lower()
        if 'charset=' in ct_lower:
            charset = ct_lower.split('charset=')[-1].split(';')[0].strip()
            if charset:
                return charset
    
    # 2. Tentar extrair da meta tag (apenas primeiros 2KB para performance)
    head_content = content[:2048]
    
    # Padrão: <meta charset="utf-8">
    match = _CHARSET_META_REGEX.search(head_content)
    if match:
        return match.group(1).decode('ascii', errors='ignore').strip()
    
    # Padrão: <meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">
    match = _CHARSET_CONTENT_TYPE_REGEX.search(head_content)
    if match:
        return match.group(1).decode('ascii', errors='ignore').strip()
    
    # 3. Fallback para UTF-8
    return 'utf-8'


def _is_pdf_content(content: bytes, content_type: Optional[str] = None) -> bool:
    """
    Detecta se o conteúdo é um PDF.
    
    Args:
        content: Bytes do conteúdo
        content_type: Header Content-Type da resposta
    
    Returns:
        True se for PDF, False caso contrário
    """
    # 1. Verificar Content-Type
    if content_type and 'application/pdf' in content_type.lower():
        return True
    
    # 2. Verificar magic bytes do PDF (%PDF- no início)
    if content[:5] == b'%PDF-':
        return True
    
    return False


def _decode_content(content: bytes, content_type: Optional[str] = None) -> str:
    """
    Decodifica bytes para string usando encoding detectado.
    
    IMPORTANTE: PDFs são detectados e retornam string vazia para evitar corrupção.
    
    Args:
        content: Bytes do conteúdo
        content_type: Header Content-Type da resposta
    
    Returns:
        String decodificada ou vazia se for PDF
    """
    # Detectar e bloquear PDFs (evita corrupção de caracteres)
    if _is_pdf_content(content, content_type):
        logger.warning("PDF detectado - retornando conteúdo vazio (PDFs não são processados)")
        return ""
    
    encoding = _detect_encoding(content, content_type)
    
    # Normalizar nomes de encoding comuns
    encoding_map = {
        'iso-8859-1': 'latin-1',
        'iso8859-1': 'latin-1',
        'latin1': 'latin-1',
        'windows-1252': 'cp1252',
    }
    encoding = encoding_map.get(encoding.lower(), encoding)
    
    try:
        return content.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        # Se falhar, tentar UTF-8
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            # Último recurso: latin-1 (aceita qualquer byte)
            return content.decode('latin-1')


async def cffi_scrape(
    url: str, 
    proxy: Optional[str] = None, 
    session: Optional[AsyncSession] = None
) -> Tuple[str, Set[str], Set[str]]:
    """
    Faz scrape usando curl_cffi (imita Chrome).
    
    Args:
        url: URL para scrape
        proxy: Proxy opcional
        session: Sessão AsyncSession existente (para reutilização)
    
    Returns:
        Tuple de (texto, links_documentos, links_internos)
    """
    if not HAS_CURL_CFFI:
        raise RuntimeError("curl_cffi não está instalado")
    
    try:
        if session:
            headers, _ = build_headers()
            resp = await session.get(url, headers=headers)
        else:
            headers, impersonate = build_headers()
            async with AsyncSession(
                impersonate=impersonate, 
                proxy=proxy, 
                timeout=scraper_config.session_timeout,
                headers=headers,
                verify=False
            ) as s:
                resp = await s.get(url)
                
        if resp.status_code != 200:
            logger.warning(f"CFFI Status {resp.status_code} para {url}")
            raise Exception(f"Status {resp.status_code}")
        
        # Usar detecção de encoding para decodificar corretamente
        content_type = resp.headers.get('content-type', '')
        text = _decode_content(resp.content, content_type)
        
        return parse_html(text, url)
        
    except Exception as e:
        logger.debug(f"[CFFI] Erro em {url}: {type(e).__name__}: {str(e)}")
        raise


async def cffi_scrape_safe(
    url: str, 
    proxy: Optional[str] = None
) -> Tuple[str, Set[str], Set[str]]:
    """
    Versão safe do cffi_scrape que não propaga exceções.
    Retorna tupla vazia em caso de erro.
    Seta cffi_scrape_safe.last_error para diagnóstico.
    """
    cffi_scrape_safe.last_error = None
    if not HAS_CURL_CFFI:
        cffi_scrape_safe.last_error = "no_curl_cffi"
        return "", set(), set()
    
    try:
        headers, impersonate = build_headers()
        
        async with AsyncSession(
            impersonate=impersonate, 
            proxy=proxy, 
            timeout=scraper_config.session_timeout,
            headers=headers,
            verify=False
        ) as s:
            resp = await s.get(url)
            if resp.status_code != 200:
                cffi_scrape_safe.last_error = f"http_{resp.status_code}"
                return "", set(), set()
            
            content_type = resp.headers.get('content-type', '')
            text = _decode_content(resp.content, content_type)
            
            return parse_html(text, url)
    except Exception as e:
        err_name = type(e).__name__
        err_msg = str(e)[:60]
        if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
            cffi_scrape_safe.last_error = "proxy_timeout"
        elif "connect" in err_msg.lower() or "refused" in err_msg.lower():
            cffi_scrape_safe.last_error = "proxy_connection_error"
        elif "ssl" in err_msg.lower():
            cffi_scrape_safe.last_error = "ssl_error"
        else:
            cffi_scrape_safe.last_error = f"{err_name}:{err_msg[:30]}"
        return "", set(), set()

cffi_scrape_safe.last_error = None


async def system_curl_scrape(
    url: str, 
    proxy: Optional[str] = None
) -> Tuple[str, Set[str], Set[str]]:
    """
    Faz scrape usando system curl (comando do sistema).
    Fallback para quando curl_cffi falha.
    
    Args:
        url: URL para scrape
        proxy: Proxy opcional
    
    Returns:
        Tuple de (texto, links_documentos, links_internos)
    """
    headers_args = []
    for k, v in DEFAULT_HEADERS.items():
        headers_args.extend(["-H", f"{k}: {v}"])
    headers_args.extend(["-H", "Referer: https://www.google.com/"])
    
    # Usar capture como bytes para poder detectar encoding
    cmd = ["curl", "-L", "-k", "-s", "--compressed", "--max-time", "15"]
    
    if proxy:
        cmd.extend(["-x", proxy])
    cmd.extend(headers_args)
    cmd.append(url)
    
    try:
        res = await asyncio.to_thread(
            subprocess.run, cmd, 
            capture_output=True, timeout=20
        )
        
        if res.returncode != 0 or not res.stdout:
            logger.warning(f"Curl com headers falhou para {url}, tentando modo simples...")
            cmd_simple = [
                "curl", "-L", "-k", "-s", "--compressed", 
                "--max-time", "12", "-A", "Mozilla/5.0", url
            ]
            if proxy:
                cmd_simple.extend(["-x", proxy])
            res = await asyncio.to_thread(
                subprocess.run, cmd_simple, 
                capture_output=True, timeout=15
            )
            
            if res.returncode != 0 or not res.stdout:
                raise Exception("Curl Failed")
                
        # Decodificar com detecção de encoding
        text = _decode_content(res.stdout)
        return parse_html(text, url)
        
    except Exception as e:
        logger.debug(f"[SystemCurl] Erro em {url}: {type(e).__name__}: {str(e)}")
        return "", set(), set()


async def system_curl_scrape_with_exception(
    url: str, 
    proxy: Optional[str] = None
) -> Tuple[str, Set[str], Set[str]]:
    """
    Versão do system_curl_scrape que propaga exceções.
    Útil quando precisa saber se falhou para fazer retry.
    """
    headers_args = []
    for k, v in DEFAULT_HEADERS.items():
        headers_args.extend(["-H", f"{k}: {v}"])
    headers_args.extend(["-H", "Referer: https://www.google.com/"])
    
    # Usar capture como bytes para poder detectar encoding
    cmd = ["curl", "-L", "-k", "-s", "--compressed", "--max-time", "15"]
    
    if proxy:
        cmd.extend(["-x", proxy])
    cmd.extend(headers_args)
    cmd.append(url)
    
    res = await asyncio.to_thread(
        subprocess.run, cmd, 
        capture_output=True, timeout=20
    )
    
    if res.returncode != 0 or not res.stdout:
        cmd_simple = [
            "curl", "-L", "-k", "-s", "--compressed", 
            "--max-time", "12", "-A", "Mozilla/5.0", url
        ]
        if proxy:
            cmd_simple.extend(["-x", proxy])
        res = await asyncio.to_thread(
            subprocess.run, cmd_simple, 
            capture_output=True, timeout=15
        )
        
        if res.returncode != 0 or not res.stdout:
            raise Exception("Curl Failed")
            
    # Decodificar com detecção de encoding
    text = _decode_content(res.stdout)
    return parse_html(text, url)

