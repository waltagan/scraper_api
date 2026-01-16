"""
Priority Queue - Fila de prioridades para requisições.

Gerencia a ordem de processamento de requisições
baseado em prioridade e tempo de espera.
"""

import asyncio
import logging
import time
import heapq
from typing import Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Níveis de prioridade (menor número = maior prioridade)."""
    CRITICAL = 0    # Operações críticas (retry de falhas)
    HIGH = 1        # Alta prioridade
    NORMAL = 2      # Prioridade normal
    LOW = 3         # Baixa prioridade
    BACKGROUND = 4  # Tarefas de background


@dataclass(order=True)
class QueueItem:
    """Item na fila de prioridades."""
    priority: int
    timestamp: float = field(compare=False)
    task_id: str = field(compare=False)
    callback: Callable[[], Awaitable[Any]] = field(compare=False, repr=False)
    metadata: dict = field(default_factory=dict, compare=False)


class PriorityQueue:
    """
    Fila de prioridades para processamento de requisições.
    
    Features:
    - Múltiplos níveis de prioridade
    - Aging (prioridade aumenta com tempo de espera)
    - Limite de tamanho da fila
    - Workers configuráveis para processamento
    
    Uso típico:
    1. Enfileirar tarefas com prioridade
    2. Workers processam na ordem de prioridade
    3. Tarefas antigas ganham prioridade (aging)
    """
    
    def __init__(
        self,
        max_size: int = 10000,
        aging_seconds: float = 30.0,
        num_workers: int = 100
    ):
        """
        Args:
            max_size: Tamanho máximo da fila
            aging_seconds: Tempo para aumentar prioridade
            num_workers: Número de workers paralelos
        """
        self._max_size = max_size
        self._aging_seconds = aging_seconds
        self._num_workers = num_workers
        
        self._queue: list = []  # heap queue
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Condition()
        
        self._running = False
        self._workers: list = []
        
        # Métricas
        self._enqueued = 0
        self._processed = 0
        self._rejected = 0
        self._task_counter = 0
        
        logger.info(
            f"PriorityQueue: max_size={max_size}, "
            f"aging={aging_seconds}s, workers={num_workers}"
        )
    
    async def enqueue(
        self,
        callback: Callable[[], Awaitable[Any]],
        priority: Priority = Priority.NORMAL,
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Adiciona tarefa à fila.
        
        Args:
            callback: Função assíncrona a executar
            priority: Nível de prioridade
            metadata: Metadados opcionais
            
        Returns:
            ID da tarefa ou None se fila cheia
        """
        async with self._lock:
            if len(self._queue) >= self._max_size:
                self._rejected += 1
                logger.warning("[PriorityQueue] Fila cheia, tarefa rejeitada")
                return None
            
            self._task_counter += 1
            task_id = f"task_{self._task_counter}"
            
            item = QueueItem(
                priority=priority.value,
                timestamp=time.time(),
                task_id=task_id,
                callback=callback,
                metadata=metadata or {}
            )
            
            heapq.heappush(self._queue, item)
            self._enqueued += 1
        
        # Notificar workers
        async with self._not_empty:
            self._not_empty.notify()
        
        return task_id
    
    async def _dequeue(self) -> Optional[QueueItem]:
        """Remove e retorna item de maior prioridade."""
        async with self._not_empty:
            while not self._queue and self._running:
                await self._not_empty.wait()
            
            if not self._queue:
                return None
            
            async with self._lock:
                if self._queue:
                    return heapq.heappop(self._queue)
                return None
    
    async def _apply_aging(self):
        """Aumenta prioridade de tarefas antigas."""
        now = time.time()
        
        async with self._lock:
            new_queue = []
            for item in self._queue:
                age = now - item.timestamp
                if age > self._aging_seconds and item.priority > 0:
                    # Aumentar prioridade (diminuir valor)
                    item.priority = max(0, item.priority - 1)
                new_queue.append(item)
            
            heapq.heapify(new_queue)
            self._queue = new_queue
    
    async def _worker(self, worker_id: int):
        """Worker que processa tarefas da fila."""
        logger.debug(f"[PriorityQueue] Worker {worker_id} iniciado")
        
        while self._running:
            item = await self._dequeue()
            if item is None:
                continue
            
            try:
                await item.callback()
                self._processed += 1
            except Exception as e:
                logger.error(
                    f"[PriorityQueue] Worker {worker_id} erro ao processar "
                    f"{item.task_id}: {e}"
                )
    
    async def start(self):
        """Inicia os workers de processamento."""
        if self._running:
            return
        
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self._num_workers)
        ]
        
        logger.info(f"[PriorityQueue] {self._num_workers} workers iniciados")
    
    async def stop(self, timeout: float = 10.0):
        """Para os workers de processamento."""
        if not self._running:
            return
        
        self._running = False
        
        # Notificar todos os workers para acordar e sair
        async with self._not_empty:
            self._not_empty.notify_all()
        
        # Aguardar workers terminarem
        if self._workers:
            done, pending = await asyncio.wait(
                self._workers,
                timeout=timeout
            )
            for task in pending:
                task.cancel()
        
        self._workers = []
        logger.info("[PriorityQueue] Workers parados")
    
    def get_queue_size(self) -> dict:
        """Retorna tamanho atual da fila por prioridade."""
        sizes = {p.name: 0 for p in Priority}
        
        for item in self._queue:
            for p in Priority:
                if item.priority == p.value:
                    sizes[p.name] += 1
                    break
        
        return {
            "total": len(self._queue),
            "by_priority": sizes
        }
    
    def get_status(self) -> dict:
        """Retorna status da fila."""
        return {
            "size": len(self._queue),
            "max_size": self._max_size,
            "running": self._running,
            "num_workers": self._num_workers,
            "metrics": {
                "enqueued": self._enqueued,
                "processed": self._processed,
                "rejected": self._rejected,
                "pending": len(self._queue)
            },
            "by_priority": self.get_queue_size()["by_priority"]
        }
    
    def reset_metrics(self):
        """Reseta métricas."""
        self._enqueued = 0
        self._processed = 0
        self._rejected = 0
        logger.info("PriorityQueue: Métricas resetadas")


# Instância singleton
priority_queue = PriorityQueue()

