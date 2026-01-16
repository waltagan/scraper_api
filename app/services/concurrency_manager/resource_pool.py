"""
Resource Pool - Pool unificado de recursos do sistema.

Gerencia recursos compartilhados entre módulos:
- Proxies
- Conexões HTTP
- Slots de API
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class PoolResourceType(Enum):
    """Tipos de recursos do pool."""
    PROXY = "proxy"
    HTTP_CONNECTION = "http_connection"
    API_SLOT = "api_slot"


@dataclass
class PooledResource:
    """Recurso no pool."""
    id: str
    resource_type: PoolResourceType
    data: Any
    in_use: bool = False
    failures: int = 0
    last_used: float = 0
    created_at: float = field(default_factory=time.time)


class ResourcePool:
    """
    Pool unificado de recursos compartilhados.
    
    Features:
    - Checkout/checkin de recursos
    - Tracking de uso e falhas
    - Eviction de recursos problemáticos
    - Métricas de utilização
    """
    
    def __init__(
        self,
        max_failures: int = 3,
        idle_timeout: float = 300.0
    ):
        """
        Args:
            max_failures: Máximo de falhas antes de descartar recurso
            idle_timeout: Tempo máximo de ociosidade antes de cleanup
        """
        self._max_failures = max_failures
        self._idle_timeout = idle_timeout
        
        self._pools: Dict[PoolResourceType, Dict[str, PooledResource]] = {
            rt: {} for rt in PoolResourceType
        }
        
        self._lock = asyncio.Lock()
        
        # Métricas
        self._checkouts: Dict[PoolResourceType, int] = {rt: 0 for rt in PoolResourceType}
        self._evictions: Dict[PoolResourceType, int] = {rt: 0 for rt in PoolResourceType}
        
        logger.info(
            f"ResourcePool: max_failures={max_failures}, "
            f"idle_timeout={idle_timeout}s"
        )
    
    async def register(
        self,
        resource_type: PoolResourceType,
        resource_id: str,
        data: Any
    ):
        """
        Registra um recurso no pool.
        
        Args:
            resource_type: Tipo do recurso
            resource_id: ID único do recurso
            data: Dados do recurso
        """
        async with self._lock:
            self._pools[resource_type][resource_id] = PooledResource(
                id=resource_id,
                resource_type=resource_type,
                data=data
            )
    
    async def checkout(
        self,
        resource_type: PoolResourceType,
        timeout: float = 10.0
    ) -> Optional[PooledResource]:
        """
        Obtém um recurso disponível do pool.
        
        Args:
            resource_type: Tipo de recurso
            timeout: Tempo máximo de espera
            
        Returns:
            Recurso ou None se não disponível
        """
        start_time = time.monotonic()
        
        while True:
            async with self._lock:
                pool = self._pools[resource_type]
                
                # Encontrar recurso disponível
                for resource in pool.values():
                    if not resource.in_use and resource.failures < self._max_failures:
                        resource.in_use = True
                        resource.last_used = time.time()
                        self._checkouts[resource_type] += 1
                        return resource
            
            # Verificar timeout
            if time.monotonic() - start_time >= timeout:
                return None
            
            await asyncio.sleep(0.1)
    
    async def checkin(
        self,
        resource: PooledResource,
        success: bool = True
    ):
        """
        Devolve um recurso ao pool.
        
        Args:
            resource: Recurso a devolver
            success: Se o uso foi bem-sucedido
        """
        async with self._lock:
            if success:
                resource.failures = 0
            else:
                resource.failures += 1
                
                # Verificar se deve ser evicted
                if resource.failures >= self._max_failures:
                    self._evict(resource)
                    return
            
            resource.in_use = False
            resource.last_used = time.time()
    
    def _evict(self, resource: PooledResource):
        """Remove recurso do pool."""
        pool = self._pools[resource.resource_type]
        if resource.id in pool:
            del pool[resource.id]
            self._evictions[resource.resource_type] += 1
            logger.info(
                f"[ResourcePool] Evicted: {resource.resource_type.value} "
                f"({resource.id[:20]}...) após {resource.failures} falhas"
            )
    
    async def cleanup_idle(self):
        """Remove recursos ociosos há muito tempo."""
        now = time.time()
        removed = 0
        
        async with self._lock:
            for pool in self._pools.values():
                to_remove = []
                for resource_id, resource in pool.items():
                    if (not resource.in_use and 
                        now - resource.last_used > self._idle_timeout):
                        to_remove.append(resource_id)
                
                for resource_id in to_remove:
                    del pool[resource_id]
                    removed += 1
        
        if removed > 0:
            logger.info(f"[ResourcePool] Cleanup: {removed} recursos ociosos removidos")
    
    def get_pool_size(self, resource_type: PoolResourceType) -> dict:
        """Retorna tamanho do pool para um tipo de recurso."""
        pool = self._pools[resource_type]
        total = len(pool)
        in_use = sum(1 for r in pool.values() if r.in_use)
        available = total - in_use
        
        return {
            "total": total,
            "in_use": in_use,
            "available": available,
            "checkouts": self._checkouts[resource_type],
            "evictions": self._evictions[resource_type]
        }
    
    def get_status(self) -> dict:
        """Retorna status de todos os pools."""
        return {
            rt.value: self.get_pool_size(rt)
            for rt in PoolResourceType
        }
    
    def reset_metrics(self):
        """Reseta métricas."""
        self._checkouts = {rt: 0 for rt in PoolResourceType}
        self._evictions = {rt: 0 for rt in PoolResourceType}
        logger.info("ResourcePool: Métricas resetadas")


# Instância singleton
resource_pool = ResourcePool()





