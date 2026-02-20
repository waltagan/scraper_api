"""
Circuit Breaker - Controle centralizado de falhas por domínio.

Previne tentativas excessivas em domínios que estão falhando.
Implementa o padrão Circuit Breaker com estados: CLOSED, OPEN, HALF_OPEN.
"""

import asyncio
import logging
import time
from urllib.parse import urlparse
from typing import Dict, Optional
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Estados possíveis do circuit breaker."""
    CLOSED = "closed"      # Normal - permite requisições
    OPEN = "open"          # Aberto - bloqueia requisições
    HALF_OPEN = "half_open"  # Semi-aberto - permite teste


@dataclass
class DomainCircuit:
    """Estado do circuit breaker para um domínio."""
    domain: str
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    successes: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    opened_at: float = 0
    half_open_tests: int = 0


class CircuitBreaker:
    """
    Circuit Breaker centralizado para controle de falhas por domínio.
    
    Estados:
    - CLOSED: Normal, permite requisições. Abre após N falhas consecutivas.
    - OPEN: Bloqueado, rejeita requisições. Volta a HALF_OPEN após timeout.
    - HALF_OPEN: Permite uma requisição de teste. Sucesso fecha, falha reabre.
    
    Features:
    - Threshold configurável de falhas
    - Timeout automático para reset
    - Distinção entre falhas de proteção (WAF/Cloudflare) e outras
    - Métricas de monitoramento
    """
    
    def __init__(
        self,
        failure_threshold: int = 12,
        recovery_timeout: float = 30.0,
        half_open_max_tests: int = 3
    ):
        """
        Args:
            failure_threshold: Número de falhas para abrir o circuit
            recovery_timeout: Tempo em segundos antes de testar recuperação
            half_open_max_tests: Máximo de testes em HALF_OPEN antes de fechar
        """
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_tests = half_open_max_tests
        
        self._circuits: Dict[str, DomainCircuit] = {}
        self._lock = asyncio.Lock()
        
        # Métricas
        self._total_blocked = 0
        self._total_opened = 0
        
        logger.info(
            f"CircuitBreaker: threshold={failure_threshold}, "
            f"recovery={recovery_timeout}s, half_open_tests={half_open_max_tests}"
        )
    
    def _extract_domain(self, url: str) -> str:
        """Extrai domínio de uma URL."""
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return "unknown"
    
    def _get_circuit(self, domain: str) -> DomainCircuit:
        """Obtém ou cria circuit para um domínio."""
        if domain not in self._circuits:
            self._circuits[domain] = DomainCircuit(domain=domain)
        return self._circuits[domain]
    
    def _update_state(self, circuit: DomainCircuit):
        """Atualiza estado do circuit baseado em condições."""
        now = time.time()
        
        if circuit.state == CircuitState.OPEN:
            # Verificar se passou tempo suficiente para testar recuperação
            if now - circuit.opened_at >= self._recovery_timeout:
                circuit.state = CircuitState.HALF_OPEN
                circuit.half_open_tests = 0
                logger.info(
                    f"🔄 Circuit HALF_OPEN para {circuit.domain} "
                    f"(recuperação após {self._recovery_timeout}s)"
                )
    
    def is_open(self, url: str) -> bool:
        """
        Verifica se o circuit breaker está aberto para uma URL.
        
        Também atualiza estado se necessário (OPEN -> HALF_OPEN após timeout).
        
        Returns:
            True se bloqueado, False se permite requisição
        """
        domain = self._extract_domain(url)
        circuit = self._get_circuit(domain)
        
        # Atualizar estado (pode mudar OPEN -> HALF_OPEN)
        self._update_state(circuit)
        
        if circuit.state == CircuitState.OPEN:
            self._total_blocked += 1
            logger.debug(f"[CircuitBreaker] Bloqueado: {domain} (OPEN)")
            return True
        
        if circuit.state == CircuitState.HALF_OPEN:
            # Permitir teste, mas marcar
            circuit.half_open_tests += 1
            logger.debug(f"[CircuitBreaker] Teste HALF_OPEN: {domain}")
            return False
        
        return False
    
    def record_failure(self, url: str, is_protection: bool = False):
        """
        Registra falha de um domínio.
        
        Args:
            url: URL que falhou
            is_protection: Se True, é uma proteção (Cloudflare/WAF), 
                          não conta como falha para circuit breaker
        """
        if is_protection:
            logger.debug(f"[CircuitBreaker] Proteção detectada em {url}, não contando como falha")
            return
        
        domain = self._extract_domain(url)
        circuit = self._get_circuit(domain)
        
        circuit.failures += 1
        circuit.last_failure_time = time.time()
        
        if circuit.state == CircuitState.HALF_OPEN:
            # Falha em HALF_OPEN - volta para OPEN
            circuit.state = CircuitState.OPEN
            circuit.opened_at = time.time()
            logger.warning(
                f"🔌 Circuit REABERTO para {domain} "
                f"(falha em teste HALF_OPEN)"
            )
            
        elif circuit.state == CircuitState.CLOSED:
            # Verificar se atingiu threshold
            if circuit.failures >= self._failure_threshold:
                circuit.state = CircuitState.OPEN
                circuit.opened_at = time.time()
                self._total_opened += 1
                logger.warning(
                    f"🔌 Circuit OPEN para {domain} "
                    f"({circuit.failures} falhas consecutivas)"
                )
    
    def record_success(self, url: str):
        """Registra sucesso de um domínio (reseta contador de falhas)."""
        domain = self._extract_domain(url)
        circuit = self._get_circuit(domain)
        
        circuit.successes += 1
        circuit.last_success_time = time.time()
        
        if circuit.state == CircuitState.HALF_OPEN:
            # Sucesso em HALF_OPEN
            circuit.half_open_tests += 1
            if circuit.half_open_tests >= self._half_open_max_tests:
                # Passou nos testes - fechar circuit
                circuit.state = CircuitState.CLOSED
                circuit.failures = 0
                logger.info(f"✅ Circuit CLOSED para {domain} (recuperado)")
        
        elif circuit.state == CircuitState.CLOSED:
            # Reset de falhas em operação normal
            circuit.failures = 0
    
    def get_failure_count(self, url: str) -> int:
        """Retorna o número de falhas de um domínio."""
        domain = self._extract_domain(url)
        circuit = self._get_circuit(domain)
        return circuit.failures
    
    def get_state(self, url: str) -> CircuitState:
        """Retorna o estado atual do circuit de um domínio."""
        domain = self._extract_domain(url)
        circuit = self._get_circuit(domain)
        self._update_state(circuit)
        return circuit.state
    
    def reset(self, url: Optional[str] = None):
        """
        Reseta circuit breaker.
        
        Args:
            url: Se fornecido, reseta apenas este domínio. 
                 Se None, reseta todos.
        """
        if url:
            domain = self._extract_domain(url)
            if domain in self._circuits:
                del self._circuits[domain]
                logger.info(f"🔄 Circuit resetado para {domain}")
        else:
            self._circuits.clear()
            logger.info("🔄 Circuit breaker resetado para todos os domínios")
    
    def update_config(
        self,
        failure_threshold: Optional[int] = None,
        recovery_timeout: Optional[float] = None,
        half_open_max_tests: Optional[int] = None
    ):
        """Atualiza configurações do circuit breaker."""
        if failure_threshold is not None:
            self._failure_threshold = failure_threshold
        if recovery_timeout is not None:
            self._recovery_timeout = recovery_timeout
        if half_open_max_tests is not None:
            self._half_open_max_tests = half_open_max_tests
            
        logger.info(
            f"CircuitBreaker: Configuração atualizada - "
            f"threshold={self._failure_threshold}, "
            f"recovery={self._recovery_timeout}s"
        )
    
    def get_status(self) -> dict:
        """Retorna status geral do circuit breaker."""
        states = {"closed": 0, "open": 0, "half_open": 0}
        for circuit in self._circuits.values():
            self._update_state(circuit)
            states[circuit.state.value] += 1
        
        return {
            "domains_tracked": len(self._circuits),
            "states": states,
            "total_blocked": self._total_blocked,
            "total_opened": self._total_opened,
            "config": {
                "failure_threshold": self._failure_threshold,
                "recovery_timeout": self._recovery_timeout,
                "half_open_max_tests": self._half_open_max_tests
            }
        }
    
    def get_domain_status(self, url: str) -> dict:
        """Retorna status detalhado de um domínio."""
        domain = self._extract_domain(url)
        circuit = self._get_circuit(domain)
        self._update_state(circuit)
        
        return {
            "domain": domain,
            "state": circuit.state.value,
            "failures": circuit.failures,
            "successes": circuit.successes,
            "last_failure_time": circuit.last_failure_time,
            "last_success_time": circuit.last_success_time,
            "opened_at": circuit.opened_at if circuit.state != CircuitState.CLOSED else None
        }
    
    def get_open_circuits(self) -> list:
        """Retorna lista de domínios com circuit aberto."""
        open_domains = []
        for circuit in self._circuits.values():
            self._update_state(circuit)
            if circuit.state == CircuitState.OPEN:
                open_domains.append({
                    "domain": circuit.domain,
                    "failures": circuit.failures,
                    "opened_at": circuit.opened_at,
                    "remaining_timeout": max(
                        0, 
                        self._recovery_timeout - (time.time() - circuit.opened_at)
                    )
                })
        return open_domains


# Instância singleton
circuit_breaker = CircuitBreaker()


# Funções de conveniência para compatibilidade com código existente
def is_circuit_open(url: str) -> bool:
    """Verifica se circuit está aberto (para compatibilidade)."""
    return circuit_breaker.is_open(url)


def record_failure(url: str, is_protection: bool = False):
    """Registra falha (para compatibilidade)."""
    circuit_breaker.record_failure(url, is_protection)


def record_success(url: str):
    """Registra sucesso (para compatibilidade)."""
    circuit_breaker.record_success(url)


def get_failure_count(url: str) -> int:
    """Retorna contagem de falhas (para compatibilidade)."""
    return circuit_breaker.get_failure_count(url)


def reset_circuit(url: Optional[str] = None):
    """Reseta circuit (para compatibilidade)."""
    circuit_breaker.reset(url)





