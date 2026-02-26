"""
Parser de HTML para extração de texto e links.
"""

import logging
from typing import Tuple, Set
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from .constants import (
    DOCUMENT_EXTENSIONS, 
    EXCLUDED_EXTENSIONS,
    CLOUDFLARE_SIGNATURES,
    ERROR_404_KEYWORDS
)

logger = logging.getLogger(__name__)


def is_cloudflare_challenge(content: str) -> bool:
    """Detecta se o conteúdo é uma página de desafio Cloudflare."""
    if not content:
        return False
    
    content_lower = content.lower()
    has_cloudflare = "cloudflare" in content_lower
    has_challenge = any(
        sig in content_lower 
        for sig in CLOUDFLARE_SIGNATURES[:5]  # Primeiros 5 são indicadores de challenge
    )
    return has_cloudflare and has_challenge


def is_soft_404(text: str) -> bool:
    """Detecta 'soft 404s' (páginas de erro com status 200)."""
    if len(text) > 1000:
        return False
        
    lower_text = text.lower()
    
    if len(text) < 200 and ("found" in lower_text or "erro" in lower_text or "página" in lower_text):
        if any(k in lower_text for k in ERROR_404_KEYWORDS) or "not found" in lower_text:
            return True
            
    return any(k in lower_text for k in ERROR_404_KEYWORDS)


def parse_html(html: str, url: str) -> Tuple[str, Set[str], Set[str]]:
    """
    Extrai texto limpo e links do HTML.
    
    Args:
        html: Conteúdo HTML da página
        url: URL da página (para resolver links relativos)
    
    Returns:
        Tuple de (texto_limpo, links_documentos, links_internos)
    """
    try:
        try:
            soup = BeautifulSoup(html, 'lxml')
        except:
            soup = BeautifulSoup(html, 'html.parser')
            
        # Remover elementos não textuais
        for tag in soup(["script", "style", "noscript", "iframe", "svg", "path", "defs", "symbol", "use"]): 
            tag.extract()
            
        text = soup.get_text(separator='\n\n')
        lines = [line.strip() for line in text.splitlines()]
        clean_text = '\n'.join(line for line in lines if line)
        
        documents, internal = extract_links(str(soup), url)
        return clean_text, documents, internal
        
    except Exception as e:
        logger.error(f"Erro no parsing HTML de {url}: {e}")
        return "", set(), set()


def _extract_links_from_soup(soup, base_url: str) -> Tuple[Set[str], Set[str]]:
    """Extrai links de documentos e internos a partir de um BeautifulSoup já parseado."""
    documents: Set[str] = set()
    internal: Set[str] = set()
    try:
        base_domain = urlparse(base_url).netloc
        for a in soup.find_all('a', href=True):
            href = a['href'].strip().rstrip(',')
            if href.startswith('#') or href.lower().startswith('javascript:'):
                continue
            full = urljoin(base_url, href).rstrip(',')
            if '#' in full:
                if full.split('#')[0] == base_url.split('#')[0]:
                    continue
            parsed = urlparse(full)
            path_lower = parsed.path.lower()
            if any(path_lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
                documents.add(full)
            elif any(path_lower.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
                continue
            elif parsed.netloc == base_domain:
                if not any(ext in parsed.query.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']):
                    internal.add(full)
    except:
        pass
    return documents, internal


def extract_links(html: str, base_url: str) -> Tuple[Set[str], Set[str]]:
    """
    Extrai links de documentos e links internos do HTML.
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')
    except:
        return set(), set()
    return _extract_links_from_soup(soup, base_url)


def extract_text_and_internal_links(html: str, base_url: str) -> Tuple[str, Set[str], Set[str]]:
    """
    Single-pass: parse HTML uma vez, extrai texto limpo + links internos + documentos.
    Evita 3x re-parse do BeautifulSoup usado nos steps 2+3 separados.
    """
    if not html:
        return "", set(), set()
    try:
        try:
            soup = BeautifulSoup(html, 'lxml')
        except:
            soup = BeautifulSoup(html, 'html.parser')

        documents, internal = _extract_links_from_soup(soup, base_url)

        for tag in soup(["script", "style", "noscript", "iframe", "svg", "path", "defs", "symbol", "use"]):
            tag.extract()
        text = soup.get_text(separator='\n\n')
        lines = [line.strip() for line in text.splitlines()]
        clean_text = '\n'.join(line for line in lines if line)
        return clean_text, documents, internal
    except Exception as e:
        logger.error(f"Erro no parsing HTML de {base_url}: {e}")
        return "", set(), set()


def normalize_url(url: str) -> str:
    """
    Normaliza URL removendo caracteres problemáticos.
    Corrige bug com vírgulas finais que causavam falhas.
    """
    from urllib.parse import urlparse, quote
    
    try:
        url = url.strip()
        
        # Remover vírgulas finais
        url = url.rstrip(',')
        
        # Remover aspas
        if url.startswith('"') and url.endswith('"'):
            url = url[1:-1]
        if url.startswith("'") and url.endswith("'"):
            url = url[1:-1]
        url = url.strip().rstrip(',')
        
        parsed = urlparse(url)
        
        # Limpar path de fragmentos problemáticos
        path = parsed.path
        if '%20%22' in path or '%22' in path:
            for marker in ['%20%22', '%22']:
                if marker in path:
                    path = path[:path.index(marker)]
                    break
        
        # Codificar path se necessário
        if '%' not in path:
            path_parts = path.split('/')
            encoded_parts = [quote(part, safe='') if part else part for part in path_parts]
            path = '/'.join(encoded_parts)
        
        # Limpar query string
        query = parsed.query
        if query:
            if '%20%22' in query or '%22' in query:
                query = query.split('%20%22')[0].split('%22')[0]
            if query and '%' not in query:
                query_parts = query.split('&')
                encoded_query_parts = []
                for part in query_parts:
                    if '=' in part:
                        key, value = part.split('=', 1)
                        encoded_query_parts.append(f"{quote(key, safe='')}={quote(value, safe='')}")
                    else:
                        encoded_query_parts.append(quote(part, safe=''))
                query = '&'.join(encoded_query_parts)
        
        # Reconstruir URL
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        if query:
            normalized += f"?{query}"
        
        return normalized
        
    except Exception as e:
        logger.warning(f"Erro ao normalizar URL {url}: {e}")
        return url.strip().rstrip(',')

