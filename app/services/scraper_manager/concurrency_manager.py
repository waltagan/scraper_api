"""
Concurrency Manager - Controle centralizado de concorrência para scraping.

Gerencia:
- Semáforos por domínio (evita sobrecarregar um único host)
- Limite global de requisições simultâneas
- Métricas de utilização
"""

import asyncio
import logging
import time
from urllib.parse import urlparse
from typing import Dict, Optional
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class ConcurrencyManager:
    """
    Gerenciador centralizado de concorrência para scraping.
    
    Controla:
    - Semáforos por domínio (limite de requisições simultâneas ao mesmo host)
    - Semáforo global (limite total de requisições simultâneas)
    - Métricas de utilização e espera
    """
    
    def __init__(
        self,
        global_limit: int = 1000,
        per_domain_limit: int = 15,
        slow_domain_limit: int = 10
    ):
        """
        Args:
            global_limit: Limite total de requisições simultâneas
            per_domain_limit: Limite de requisições por domínio
            slow_domain_limit: Limite para domínios lentos/problemáticos
        """
        self._global_semaphore = asyncio.Semaphore(global_limit)
        self._global_limit = global_limit
        self._per_domain_limit = per_domain_limit
        self._slow_domain_limit = slow_domain_limit
        
        self._domain_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._domain_locks: Dict[str, asyncio.Lock] = {}
        self._slow_domains: set = set()
        
        # Métricas
        self._active_requests = 0
        self._total_requests = 0
        self._domain_request_counts: Dict[str, int] = {}
        self._peak_concurrent = 0
        
        logger.info(
            f"ConcurrencyManager: global={global_limit}, "
            f"per_domain={per_domain_limit}, slow_domain={slow_domain_limit}"
        )
    
    def _extract_domain(self, url: str) -> str:
        """Extrai o domínio de uma URL."""
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return "unknown"
    
    def _get_domain_semaphore(self, domain: str) -> asyncio.Semaphore:
        """Retorna ou cria semáforo para um domínio."""
        if domain not in self._domain_semaphores:
            limit = (
                self._slow_domain_limit 
                if domain in self._slow_domains 
                else self._per_domain_limit
            )
            self._domain_semaphores[domain] = asyncio.Semaphore(limit)
            self._domain_locks[domain] = asyncio.Lock()
        return self._domain_semaphores[domain]
    
    def mark_domain_slow(self, url: str):
        """Marca um domínio como lento (reduz concorrência)."""
        domain = self._extract_domain(url)
        if domain not in self._slow_domains:
            self._slow_domains.add(domain)
            # Recriar semáforo com limite menor
            self._domain_semaphores[domain] = asyncio.Semaphore(self._slow_domain_limit)
            logger.info(f"🐢 Domínio marcado como lento: {domain}")
    
    def unmark_domain_slow(self, url: str):
        """Remove marcação de domínio lento."""
        domain = self._extract_domain(url)
        if domain in self._slow_domains:
            self._slow_domains.discard(domain)
            self._domain_semaphores[domain] = asyncio.Semaphore(self._per_domain_limit)
            logger.info(f"🚀 Domínio restaurado para velocidade normal: {domain}")
    
    @asynccontextmanager
    async def acquire(self, url: str, timeout: float = 30.0, request_id: str = "", substage: str = ""):
        """
        Context manager para adquirir slots de concorrência.
        
        Adquire tanto o slot global quanto o slot por domínio.
        Libera automaticamente ao sair do contexto.
        
        Args:
            url: URL que será acessada
            timeout: Tempo máximo de espera
            request_id: ID da requisição
            substage: Subetapa (main_page, subpages, etc)
            
        Yields:
            True se adquiriu, levanta TimeoutError se timeout
        """
        domain = self._extract_domain(url)
        domain_sem = self._get_domain_semaphore(domain)
        
        start_time = time.monotonic()
        acquired_global = False
        acquired_domain = False
        
        try:
            # Adquirir slot global
            try:
                await asyncio.wait_for(
                    self._global_semaphore.acquire(),
                    timeout=timeout
                )
                acquired_global = True
            except asyncio.TimeoutError:
                raise TimeoutError(f"Timeout aguardando slot global para {url}")
            
            # Adquirir slot de domínio
            remaining_timeout = timeout - (time.monotonic() - start_time)
            if remaining_timeout <= 0:
                raise TimeoutError(f"Timeout antes de adquirir slot de domínio para {url}")
            
            try:
                await asyncio.wait_for(
                    domain_sem.acquire(),
                    timeout=remaining_timeout
                )
                acquired_domain = True
            except asyncio.TimeoutError:
                raise TimeoutError(f"Timeout aguardando slot de domínio {domain}")
            
            # Medir tempo total de espera
            wait_ms = (time.monotonic() - start_time) * 1000
            
            
            # Atualizar métricas
            self._active_requests += 1
            self._total_requests += 1
            self._domain_request_counts[domain] = (
                self._domain_request_counts.get(domain, 0) + 1
            )
            self._peak_concurrent = max(self._peak_concurrent, self._active_requests)
            
            yield True
            
        finally:
            # Liberar slots
            if acquired_domain:
                domain_sem.release()
            if acquired_global:
                self._global_semaphore.release()
                self._active_requests -= 1
    
    async def acquire_domain_only(self, url: str, timeout: float = 30.0) -> bool:
        """
        Adquire apenas slot de domínio (sem slot global).
        
        Útil para requisições já dentro de um contexto global.
        """
        domain = self._extract_domain(url)
        domain_sem = self._get_domain_semaphore(domain)
        
        try:
            await asyncio.wait_for(domain_sem.acquire(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
    
    def release_domain(self, url: str):
        """Libera slot de domínio."""
        domain = self._extract_domain(url)
        if domain in self._domain_semaphores:
            self._domain_semaphores[domain].release()
    
    def update_limits(
        self,
        global_limit: Optional[int] = None,
        per_domain_limit: Optional[int] = None,
        slow_domain_limit: Optional[int] = None
    ):
        """Atualiza limites de concorrência dinamicamente."""
        if global_limit is not None:
            self._global_semaphore = asyncio.Semaphore(global_limit)
            self._global_limit = global_limit
            
        if per_domain_limit is not None:
            self._per_domain_limit = per_domain_limit
            # Recriar semáforos de domínios não-lentos
            for domain in list(self._domain_semaphores.keys()):
                if domain not in self._slow_domains:
                    self._domain_semaphores[domain] = asyncio.Semaphore(per_domain_limit)
                    
        if slow_domain_limit is not None:
            self._slow_domain_limit = slow_domain_limit
            # Recriar semáforos de domínios lentos
            for domain in self._slow_domains:
                self._domain_semaphores[domain] = asyncio.Semaphore(slow_domain_limit)
        
        logger.info(
            f"ConcurrencyManager: Limites atualizados - "
            f"global={self._global_limit}, per_domain={self._per_domain_limit}"
        )
    
    def get_status(self) -> dict:
        """Retorna status atual de concorrência."""
        return {
            "active_requests": self._active_requests,
            "total_requests": self._total_requests,
            "peak_concurrent": self._peak_concurrent,
            "global_limit": self._global_limit,
            "per_domain_limit": self._per_domain_limit,
            "slow_domains_count": len(self._slow_domains),
            "tracked_domains": len(self._domain_semaphores),
            "utilization": f"{(self._active_requests / self._global_limit):.1%}"
        }
    
    def get_domain_stats(self, url: str) -> dict:
        """Retorna estatísticas de um domínio específico."""
        domain = self._extract_domain(url)
        return {
            "domain": domain,
            "is_slow": domain in self._slow_domains,
            "request_count": self._domain_request_counts.get(domain, 0),
            "limit": (
                self._slow_domain_limit 
                if domain in self._slow_domains 
                else self._per_domain_limit
            )
        }
    
    def reset_metrics(self):
        """Reseta métricas (não afeta semáforos)."""
        self._total_requests = 0
        self._peak_concurrent = 0
        self._domain_request_counts.clear()
        logger.info("ConcurrencyManager: Métricas resetadas")


# Instância singleton
concurrency_manager = ConcurrencyManager()


# Funções de conveniência para compatibilidade
def get_domain_semaphore(url: str) -> asyncio.Semaphore:
    """Retorna semáforo de um domínio (para compatibilidade)."""
    domain = concurrency_manager._extract_domain(url)
    return concurrency_manager._get_domain_semaphore(domain)


async def acquire_domain_slot(url: str, timeout: float = 30.0) -> bool:
    """Adquire slot de domínio (para compatibilidade)."""
    return await concurrency_manager.acquire_domain_only(url, timeout)


def release_domain_slot(url: str):
    """Libera slot de domínio (para compatibilidade)."""
    concurrency_manager.release_domain(url)




