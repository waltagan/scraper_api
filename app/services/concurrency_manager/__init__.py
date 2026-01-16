"""
Concurrency Manager - Orquestração global de recursos.

Este módulo centraliza a visão e controle de todos os recursos do sistema:
- Orquestrador global de concorrência
- Pool unificado de recursos (proxies, APIs, LLM)
- Fila de prioridades para requisições

Permite balanceamento dinâmico e prevenção de sobrecarga.
"""

from .global_orchestrator import (
    GlobalOrchestrator,
    global_orchestrator,
    ResourceType,
)
from .resource_pool import (
    ResourcePool,
    resource_pool,
)
from .priority_queue import (
    PriorityQueue,
    priority_queue,
    Priority,
)
from .config_loader import (
    load_config,
    get_section,
    reset_cache,
)

__all__ = [
    # Orchestrator
    "GlobalOrchestrator",
    "global_orchestrator",
    "ResourceType",
    # Resource Pool
    "ResourcePool",
    "resource_pool",
    # Priority Queue
    "PriorityQueue",
    "priority_queue",
    "Priority",
    # Config Loader
    "load_config",
    "get_section",
    "reset_cache",
]





