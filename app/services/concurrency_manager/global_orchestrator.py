"""
Global Orchestrator - Orquestração centralizada de recursos do sistema.

Fornece visão global de todos os recursos e permite:
- Balanceamento dinâmico entre módulos
- Prevenção de sobrecarga
- Métricas centralizadas
- Ajuste automático de limites
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ResourceType(Enum):
    """Tipos de recursos gerenciados."""
    SCRAPER = "scraper"           # Requisições de scraping
    DISCOVERY = "discovery"       # Buscas de discovery
    LLM = "llm"                   # Chamadas LLM
    PROXY = "proxy"               # Pool de proxies
    HTTP_CONNECTION = "http"      # Conexões HTTP


@dataclass
class ResourceAllocation:
    """Alocação atual de um tipo de recurso."""
    resource_type: ResourceType
    max_capacity: int
    current_usage: int = 0
    reserved: int = 0
    last_update: float = 0
    
    @property
    def available(self) -> int:
        return max(0, self.max_capacity - self.current_usage - self.reserved)
    
    @property
    def utilization(self) -> float:
        if self.max_capacity == 0:
            return 0.0
        return self.current_usage / self.max_capacity


class GlobalOrchestrator:
    """
    Orquestrador global de recursos do sistema.
    
    Centraliza o controle de todos os recursos para:
    - Visão unificada de utilização
    - Balanceamento entre módulos
    - Prevenção de sobrecarga global
    - Ajuste dinâmico de limites
    
    Features:
    - Semáforos globais por tipo de recurso
    - Reserva de recursos para operações críticas
    - Métricas em tempo real
    - Auto-scaling baseado em carga
    """
    
    def __init__(self):
        """Inicializa orquestrador com capacidades padrão."""
        self._allocations: Dict[ResourceType, ResourceAllocation] = {}
        self._semaphores: Dict[ResourceType, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()
        
        # Configurações padrão
        # NOTA: O controle de taxa do Serper é feito pelo TokenBucketRateLimiter (190 req/s)
        # Os semáforos aqui controlam RECURSOS (concorrência), não TAXA
        # v11.3: LLM reduzido para 6 para evitar sobrecarga de VRAM na Vast.ai (SGLang)
        # Com contextos de 10k+ tokens, GPU precisa de espaço suficiente para KV Cache
        # Picos de 30+ requisições simultâneas esgotam VRAM e causam content=None
        self._default_capacities = {
            ResourceType.SCRAPER: 1000,        # Sites em paralelo
            ResourceType.DISCOVERY: 1000,      # Buscas simultâneas (rate limit pelo TokenBucket)
            ResourceType.LLM: 6,               # Chamadas LLM (v11.3: reduzido para 6 com wait list)
            ResourceType.PROXY: 1000,          # Proxies ativos
            ResourceType.HTTP_CONNECTION: 1000, # Conexões HTTP
        }
        
        # Métricas globais
        self._total_requests = 0
        self._blocked_requests = 0
        self._start_time = time.time()
        
        # Inicializar recursos
        self._initialize_resources()
        
        logger.info("GlobalOrchestrator: Inicializado com capacidades padrão")
    
    def _initialize_resources(self):
        """Inicializa alocações e semáforos para cada tipo de recurso."""
        for resource_type, capacity in self._default_capacities.items():
            self._allocations[resource_type] = ResourceAllocation(
                resource_type=resource_type,
                max_capacity=capacity,
                last_update=time.time()
            )
            self._semaphores[resource_type] = asyncio.Semaphore(capacity)
    
    async def acquire(
        self,
        resource_type: ResourceType,
        amount: int = 1,
        timeout: float = 30.0,
        request_id: Optional[str] = None
    ) -> bool:
        """
        Adquire recursos de um tipo específico com wait list e logging.
        
        v11.3: Wait list implementada para LLM com timeout de 45s
              - Loga quando requisição está aguardando slot de GPU
              - Timeout específico para LLM (45s) para evitar sobrecarga
        
        Args:
            resource_type: Tipo de recurso
            amount: Quantidade de recursos
            timeout: Tempo máximo de espera (padrão 30s, LLM usa 45s)
            request_id: ID da requisição para rastreamento de fila (opcional)
            
        Returns:
            True se adquiriu, False se timeout
        """
        semaphore = self._semaphores.get(resource_type)
        allocation = self._allocations.get(resource_type)
        
        if not semaphore or not allocation:
            logger.warning(f"Tipo de recurso desconhecido: {resource_type}")
            return False
        
        # v11.3: Timeout específico para LLM (45s para evitar sobrecarga)
        if resource_type == ResourceType.LLM:
            timeout = 45.0
        
        # Verificar se semáforo está cheio (requisição vai esperar)
        available = semaphore._value
        if available < amount:
            logger.info(
                f"[WAIT] Aguardando slot de {resource_type.value}... "
                f"(disponível: {available}, necessário: {amount}, "
                f"request_id: {request_id or 'N/A'})"
            )
        
        # Medir tempo real de espera
        start_time = time.time()
        
        try:
            for _ in range(amount):
                await asyncio.wait_for(
                    semaphore.acquire(),
                    timeout=timeout
                )
            
            # Medir tempo de espera
            wait_ms = (time.time() - start_time) * 1000
            
            # Log se esperou significativamente
            if wait_ms > 100:
                logger.debug(
                    f"[Orchestrator] {resource_type.value} adquirido após {wait_ms:.0f}ms de espera "
                    f"(request_id: {request_id or 'N/A'})"
                )
            
            async with self._lock:
                allocation.current_usage += amount
                allocation.last_update = time.time()
                self._total_requests += 1
            
            return True
            
        except asyncio.TimeoutError:
            async with self._lock:
                self._blocked_requests += 1
            logger.error(
                f"[Orchestrator] Timeout ao adquirir {amount} {resource_type.value} "
                f"após {timeout}s (request_id: {request_id or 'N/A'}). "
                f"Possível sobrecarga - reduzir concorrência ou aumentar timeout."
            )
            return False
    
    def release(self, resource_type: ResourceType, amount: int = 1):
        """Libera recursos de um tipo específico."""
        semaphore = self._semaphores.get(resource_type)
        allocation = self._allocations.get(resource_type)
        
        if not semaphore or not allocation:
            return
        
        for _ in range(amount):
            semaphore.release()
        
        allocation.current_usage = max(0, allocation.current_usage - amount)
        allocation.last_update = time.time()
    
    def reserve(self, resource_type: ResourceType, amount: int) -> bool:
        """
        Reserva recursos para operações críticas.
        
        Recursos reservados não podem ser usados por operações normais.
        """
        allocation = self._allocations.get(resource_type)
        if not allocation:
            return False
        
        if allocation.available >= amount:
            allocation.reserved += amount
            logger.info(
                f"[Orchestrator] Reservado {amount} {resource_type.value} "
                f"(total reservado: {allocation.reserved})"
            )
            return True
        
        return False
    
    def unreserve(self, resource_type: ResourceType, amount: int):
        """Libera recursos reservados."""
        allocation = self._allocations.get(resource_type)
        if allocation:
            allocation.reserved = max(0, allocation.reserved - amount)
    
    def set_capacity(self, resource_type: ResourceType, capacity: int):
        """
        Define nova capacidade para um tipo de recurso.
        
        Recria o semáforo com a nova capacidade.
        """
        if resource_type not in self._allocations:
            return
        
        old_capacity = self._allocations[resource_type].max_capacity
        self._allocations[resource_type].max_capacity = capacity
        self._semaphores[resource_type] = asyncio.Semaphore(capacity)
        
        logger.info(
            f"[Orchestrator] Capacidade de {resource_type.value} alterada: "
            f"{old_capacity} -> {capacity}"
        )
    
    def get_utilization(self, resource_type: Optional[ResourceType] = None) -> Dict[str, Any]:
        """
        Retorna utilização de recursos.
        
        Args:
            resource_type: Se especificado, retorna apenas este tipo
            
        Returns:
            Dict com métricas de utilização
        """
        if resource_type:
            allocation = self._allocations.get(resource_type)
            if not allocation:
                return {}
            return {
                "type": resource_type.value,
                "capacity": allocation.max_capacity,
                "usage": allocation.current_usage,
                "reserved": allocation.reserved,
                "available": allocation.available,
                "utilization": f"{allocation.utilization:.1%}"
            }
        
        # Retornar todos
        result = {}
        for rt, allocation in self._allocations.items():
            result[rt.value] = {
                "capacity": allocation.max_capacity,
                "usage": allocation.current_usage,
                "reserved": allocation.reserved,
                "available": allocation.available,
                "utilization": f"{allocation.utilization:.1%}"
            }
        return result
    
    def get_global_status(self) -> dict:
        """Retorna status global do sistema."""
        total_capacity = sum(a.max_capacity for a in self._allocations.values())
        total_usage = sum(a.current_usage for a in self._allocations.values())
        
        uptime = time.time() - self._start_time
        requests_per_second = self._total_requests / uptime if uptime > 0 else 0
        
        return {
            "uptime_seconds": round(uptime, 2),
            "total_capacity": total_capacity,
            "total_usage": total_usage,
            "global_utilization": f"{(total_usage / total_capacity):.1%}" if total_capacity > 0 else "0%",
            "total_requests": self._total_requests,
            "blocked_requests": self._blocked_requests,
            "requests_per_second": round(requests_per_second, 2),
            "resources": self.get_utilization()
        }
    
    def is_overloaded(self, threshold: float = 0.9) -> bool:
        """
        Verifica se o sistema está sobrecarregado.
        
        Args:
            threshold: Limiar de utilização (0.0 a 1.0)
            
        Returns:
            True se algum recurso está acima do threshold
        """
        for allocation in self._allocations.values():
            if allocation.utilization > threshold:
                return True
        return False
    
    def get_bottleneck(self) -> Optional[ResourceType]:
        """Retorna o recurso com maior utilização (gargalo)."""
        max_utilization = 0
        bottleneck = None
        
        for rt, allocation in self._allocations.items():
            if allocation.utilization > max_utilization:
                max_utilization = allocation.utilization
                bottleneck = rt
        
        return bottleneck
    
    def auto_balance(self):
        """
        Ajusta capacidades automaticamente baseado em utilização.
        
        Aumenta recursos subutilizados e reduz sobrecarregados.
        """
        for rt, allocation in self._allocations.items():
            if allocation.utilization > 0.9:
                # Sobrecarregado - aumentar 20%
                new_capacity = int(allocation.max_capacity * 1.2)
                self.set_capacity(rt, new_capacity)
            elif allocation.utilization < 0.3 and allocation.max_capacity > 100:
                # Subutilizado - reduzir 10%
                new_capacity = max(100, int(allocation.max_capacity * 0.9))
                self.set_capacity(rt, new_capacity)
    
    def reset_metrics(self):
        """Reseta métricas globais."""
        self._total_requests = 0
        self._blocked_requests = 0
        self._start_time = time.time()
        logger.info("GlobalOrchestrator: Métricas resetadas")


# Instância singleton
global_orchestrator = GlobalOrchestrator()

