"""
Circuit Breaker para controle de falhas por domínio.

DEPRECATED: Este módulo foi movido para app/services/scraper_manager/circuit_breaker.py

Este arquivo mantém apenas re-exports para compatibilidade retroativa.
Use app.services.scraper_manager.circuit_breaker diretamente em novo código.
"""

# Re-export do novo módulo centralizado
from app.services.scraper_manager.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    circuit_breaker,
    is_circuit_open,
    record_failure,
    record_success,
    get_failure_count,
    reset_circuit,
)

# Alias para compatibilidade
_domain_failures = circuit_breaker._circuits  # Para acesso direto (não recomendado)

def get_domain(url: str) -> str:
    """Extrai o domínio de uma URL."""
    return circuit_breaker._extract_domain(url)

def reset_all() -> None:
    """Reseta todos os contadores de falha."""
    circuit_breaker.reset()

def reset_domain(url: str) -> None:
    """Reseta o contador de falha de um domínio específico."""
    circuit_breaker.reset(url)

__all__ = [
    'CircuitBreaker',
    'CircuitState',
    'circuit_breaker',
    'is_circuit_open',
    'record_failure',
    'record_success',
    'get_failure_count',
    'reset_circuit',
    'get_domain',
    'reset_all',
    'reset_domain',
    '_domain_failures',
]
