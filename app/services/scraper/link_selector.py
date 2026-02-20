"""
Seleção de links para scraping de subpáginas — apenas heurísticas.
"""

import logging
from typing import List, Set
from urllib.parse import urlparse

from .constants import (
    DOCUMENT_EXTENSIONS, EXCLUDED_EXTENSIONS,
    ASSET_DIRECTORIES, HIGH_PRIORITY_KEYWORDS, LOW_PRIORITY_KEYWORDS,
)

logger = logging.getLogger(__name__)


def filter_non_html_links(links: Set[str]) -> Set[str]:
    """Filtra links não-HTML (documentos, imagens, assets estáticos)."""
    filtered = set()
    for link in links:
        link = link.strip().rstrip(',')
        if not link:
            continue
        parsed = urlparse(link)
        path_lower = parsed.path.lower()

        if any(path_lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
            continue
        if any(path_lower.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
            continue
        if any(ext in parsed.query.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']):
            continue
        if any(d in path_lower for d in ASSET_DIRECTORIES):
            if any(path_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico']):
                continue
        filtered.add(link)
    return filtered


def prioritize_links(links: Set[str], base_url: str) -> List[str]:
    """Prioriza links por relevância usando heurísticas de keywords."""
    scored = []
    for link in links:
        link = link.strip().rstrip(',')
        if not link or link.rstrip('/') == base_url.rstrip('/'):
            continue
        score = 0
        lower = link.lower()

        if any(k in lower for k in LOW_PRIORITY_KEYWORDS):
            score -= 100
        if any(k in lower for k in HIGH_PRIORITY_KEYWORDS):
            score += 50

        score -= len(urlparse(link).path.split('/'))

        if any(x in lower for x in ["page", "p=", "pagina", "nav"]):
            if not any(k in lower for k in LOW_PRIORITY_KEYWORDS):
                score += 30

        scored.append((score, link))

    return [l for s, l in sorted(scored, key=lambda x: x[0], reverse=True) if s > -80]


def extract_and_prioritize_links(links: Set[str], base_url: str, max_links: int = 5) -> List[str]:
    """Filtra, prioriza e retorna até max_links subpáginas relevantes."""
    filtered = filter_non_html_links(links)
    prioritized = prioritize_links(filtered, base_url)
    return prioritized[:max_links]
