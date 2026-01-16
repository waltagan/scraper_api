"""
Search Cache - Cache de resultados de busca.

Evita chamadas repetidas à API Serper para queries idênticas,
melhorando performance e reduzindo custos.
"""

import asyncio
import logging
import time
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Entrada do cache de busca."""
    query_hash: str
    results: List[Dict[str, str]]
    created_at: float
    hits: int = 0
    last_access: float = field(default_factory=time.time)


class SearchCache:
    """
    Cache LRU para resultados de busca.
    
    Features:
    - TTL configurável (tempo de vida dos resultados)
    - Limite máximo de entradas (LRU eviction)
    - Métricas de hit/miss
    - Thread-safe para uso assíncrono
    """
    
    def __init__(
        self,
        max_entries: int = 1000,
        ttl_seconds: float = 3600,  # 1 hora
        cleanup_interval: float = 300  # 5 minutos
    ):
        """
        Args:
            max_entries: Máximo de entradas no cache
            ttl_seconds: Tempo de vida das entradas em segundos
            cleanup_interval: Intervalo de limpeza de entradas expiradas
        """
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._cleanup_interval = cleanup_interval
        
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        
        # Métricas
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        
        self._last_cleanup = time.time()
        
        logger.info(
            f"SearchCache: max={max_entries}, ttl={ttl_seconds}s, "
            f"cleanup_interval={cleanup_interval}s"
        )
    
    def _hash_query(self, query: str, num_results: int = 100) -> str:
        """Gera hash único para uma query."""
        normalized = f"{query.lower().strip()}:{num_results}"
        return hashlib.md5(normalized.encode()).hexdigest()
    
    async def get(
        self,
        query: str,
        num_results: int = 100
    ) -> Optional[List[Dict[str, str]]]:
        """
        Busca resultados no cache.
        
        Args:
            query: Termo de busca
            num_results: Número de resultados esperados
            
        Returns:
            Lista de resultados ou None se não encontrado/expirado
        """
        query_hash = self._hash_query(query, num_results)
        
        async with self._lock:
            entry = self._cache.get(query_hash)
            
            if entry is None:
                self._misses += 1
                return None
            
            # Verificar expiração
            if time.time() - entry.created_at > self._ttl_seconds:
                del self._cache[query_hash]
                self._misses += 1
                return None
            
            # Atualizar métricas de acesso
            entry.hits += 1
            entry.last_access = time.time()
            self._hits += 1
            
            logger.debug(f"[Cache] HIT: {query[:30]}... ({len(entry.results)} resultados)")
            return entry.results
    
    async def set(
        self,
        query: str,
        results: List[Dict[str, str]],
        num_results: int = 100
    ):
        """
        Armazena resultados no cache.
        
        Args:
            query: Termo de busca
            results: Lista de resultados
            num_results: Número de resultados solicitados
        """
        if not results:
            return
        
        query_hash = self._hash_query(query, num_results)
        
        async with self._lock:
            # Verificar se precisa limpeza
            await self._maybe_cleanup()
            
            # Verificar limite de entradas
            if len(self._cache) >= self._max_entries:
                await self._evict_lru()
            
            self._cache[query_hash] = CacheEntry(
                query_hash=query_hash,
                results=results,
                created_at=time.time()
            )
            
            logger.debug(f"[Cache] SET: {query[:30]}... ({len(results)} resultados)")
    
    async def _maybe_cleanup(self):
        """Remove entradas expiradas se passou intervalo de limpeza."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        self._last_cleanup = now
        expired_keys = []
        
        for key, entry in self._cache.items():
            if now - entry.created_at > self._ttl_seconds:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]
        
        if expired_keys:
            logger.debug(f"[Cache] Cleanup: {len(expired_keys)} entradas expiradas removidas")
    
    async def _evict_lru(self):
        """Remove entrada menos recentemente usada."""
        if not self._cache:
            return
        
        # Encontrar entrada com acesso mais antigo
        lru_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].last_access
        )
        
        del self._cache[lru_key]
        self._evictions += 1
        logger.debug(f"[Cache] LRU eviction: {lru_key[:16]}...")
    
    async def invalidate(self, query: str, num_results: int = 100):
        """Invalida entrada específica do cache."""
        query_hash = self._hash_query(query, num_results)
        async with self._lock:
            if query_hash in self._cache:
                del self._cache[query_hash]
                logger.debug(f"[Cache] Invalidated: {query[:30]}...")
    
    async def clear(self):
        """Limpa todo o cache."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"[Cache] Cleared: {count} entradas removidas")
    
    def get_status(self) -> dict:
        """Retorna status e métricas do cache."""
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0
        
        return {
            "entries": len(self._cache),
            "max_entries": self._max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.1%}",
            "evictions": self._evictions,
            "config": {
                "ttl_seconds": self._ttl_seconds,
                "cleanup_interval": self._cleanup_interval
            }
        }
    
    def update_config(
        self,
        max_entries: Optional[int] = None,
        ttl_seconds: Optional[float] = None
    ):
        """Atualiza configurações do cache."""
        if max_entries is not None:
            self._max_entries = max_entries
        if ttl_seconds is not None:
            self._ttl_seconds = ttl_seconds
        
        logger.info(
            f"SearchCache: Configuração atualizada - "
            f"max={self._max_entries}, ttl={self._ttl_seconds}s"
        )
    
    def reset_metrics(self):
        """Reseta métricas."""
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        logger.info("SearchCache: Métricas resetadas")


# Instância singleton
search_cache = SearchCache()





