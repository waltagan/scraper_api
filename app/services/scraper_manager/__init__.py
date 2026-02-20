"""
Scraper Manager — Infraestrutura simplificada.
Apenas proxy pool (gateway mode).
"""

from .proxy_manager import (
    ProxyPool,
    proxy_pool,
    get_healthy_proxy,
    record_proxy_failure,
    record_proxy_success,
)

__all__ = [
    "ProxyPool",
    "proxy_pool",
    "get_healthy_proxy",
    "record_proxy_failure",
    "record_proxy_success",
]
