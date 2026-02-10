"""
Serper Manager - Gerenciamento centralizado da API Serper.

Controla:
- Cliente HTTP com connection pooling
- Rate limiting por token bucket (200 req/s)
- Retry logic com backoff exponencial
- Métricas de uso da API

IMPORTANTE: A API Serper tem limite de 200 req/SEGUNDO, não 200 concurrent.
Usamos TokenBucketRateLimiter para controlar a taxa de requisições,
permitindo alta concorrência enquanto respeitamos o limite de taxa.
"""

import asyncio
import logging
import json
import random
import time
from email.utils import parsedate_to_datetime
from typing import List, Dict, Optional, Any, Tuple

import httpx

from app.core.config import settings
from app.services.concurrency_manager.config_loader import (
    get_section as get_concurrency_section,
)
from .rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


def _parse_retry_after(header_value: Optional[str], max_seconds: float = 60.0) -> Optional[float]:
    """
    Parseia o header Retry-After conforme RFC 7231.
    
    Pode ser:
    - Número em segundos (ex: "120")
    - HTTP-date (ex: "Wed, 21 Oct 2015 07:28:00 GMT")
    
    Returns:
        Segundos a esperar, ou None se inválido/não presente.
        Limitado a max_seconds.
    """
    import datetime as dt_module
    if not header_value or not header_value.strip():
        return None
    val = header_value.strip()
    # Número em segundos
    try:
        seconds = float(val)
        return min(max(0, seconds), max_seconds) if seconds > 0 else None
    except ValueError:
        pass
    # HTTP-date
    try:
        retry_dt = parsedate_to_datetime(val)
        now = dt_module.datetime.now(dt_module.timezone.utc)
        if retry_dt.tzinfo is None:
            retry_dt = retry_dt.replace(tzinfo=dt_module.timezone.utc)
        delta = (retry_dt - now).total_seconds()
        return min(max(0, delta), max_seconds) if delta > 0 else None
    except (ValueError, TypeError):
        return None


class SerperManager:
    """
    Gerenciador centralizado da API Serper.
    
    Features:
    - Connection pooling com HTTP/2
    - Rate limiting por Token Bucket (200 req/s)
    - Alta concorrência (1000+ requisições simultâneas)
    - Retry automático com backoff exponencial
    - Tratamento de rate limiting (429)
    - Métricas de uso
    
    MUDANÇA v2: Removido semáforo de concorrência. Agora usa TokenBucketRateLimiter
    para controlar taxa de requisições, permitindo muito mais requisições
    simultâneas enquanto respeita o limite de 200 req/s da API.
    """
    
    def __init__(
        self,
        rate_per_second: float = None,  # Valores default vêm da config central
        max_burst: int = None,
        max_concurrent: int = None,  # Alta concorrência para conexões HTTP
        request_timeout: float = None,
        connect_timeout: float = None,
        max_retries: int = None,
        retry_base_delay: float = None,
        retry_max_delay: float = None
    ):
        """
        Args:
            rate_per_second: Taxa máxima de requisições por segundo
            max_burst: Máximo de requisições em burst
            max_concurrent: Limite de conexões HTTP simultâneas (não é rate limit!)
            request_timeout: Timeout de leitura em segundos
            connect_timeout: Timeout de conexão em segundos
            max_retries: Máximo de tentativas
            retry_base_delay: Delay base para retry (segundos)
            retry_max_delay: Delay máximo para retry (segundos)
        """
        serper_cfg = get_concurrency_section("discovery/serper", {})
        self._rate_per_second = rate_per_second if rate_per_second is not None else serper_cfg.get("rate_per_second", 190.0)
        self._max_burst = max_burst if max_burst is not None else serper_cfg.get("max_burst", 200)
        self._max_concurrent = max_concurrent if max_concurrent is not None else serper_cfg.get("max_concurrent", 1000)
        self._request_timeout = request_timeout if request_timeout is not None else serper_cfg.get("request_timeout", 15.0)
        self._connect_timeout = connect_timeout if connect_timeout is not None else serper_cfg.get("connect_timeout", 5.0)
        self._max_retries = max_retries if max_retries is not None else serper_cfg.get("max_retries", 3)
        self._retry_base_delay = retry_base_delay if retry_base_delay is not None else serper_cfg.get("retry_base_delay", 1.0)
        self._retry_max_delay = retry_max_delay if retry_max_delay is not None else serper_cfg.get("retry_max_delay", 10.0)
        self._rate_limiter_timeout = serper_cfg.get("rate_limiter_timeout", 10.0)
        self._rate_limiter_retry_timeout = serper_cfg.get("rate_limiter_retry_timeout", 5.0)
        self._connection_semaphore_timeout = serper_cfg.get("connection_semaphore_timeout", 10.0)
        self._retry_after_max = serper_cfg.get("retry_after_max", 60.0)
        
        # Rate limiter (controla taxa, NÃO concorrência)
        self._rate_limiter = TokenBucketRateLimiter(
            rate_per_second=self._rate_per_second,
            max_burst=self._max_burst,
            name="serper"
        )
        
        # Semáforo para limitar conexões HTTP (recurso, não taxa)
        # Este é um limite de RECURSOS (conexões), não de TAXA
        self._connection_semaphore: Optional[asyncio.Semaphore] = None
        self._semaphore_lock = asyncio.Lock()
        
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()
        
        # Métricas
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._rate_limited_requests = 0
        self._total_latency_ms = 0
        
        logger.info(
            f"SerperManager v2: rate={self._rate_per_second}/s, burst={self._max_burst}, "
            f"max_concurrent={self._max_concurrent}, timeout={self._request_timeout}s"
        )
    
    async def _get_connection_semaphore(self) -> asyncio.Semaphore:
        """Retorna semáforo de conexões (lazy initialization)."""
        async with self._semaphore_lock:
            if self._connection_semaphore is None:
                self._connection_semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._connection_semaphore
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Retorna cliente HTTP global com connection pooling."""
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        connect=self._connect_timeout,
                        read=self._request_timeout,
                        write=self._request_timeout,
                        pool=self._request_timeout
                    ),
                    limits=httpx.Limits(
                        max_keepalive_connections=100,
                        max_connections=self._max_concurrent,
                        keepalive_expiry=30.0
                    ),
                    http2=True
                )
                logger.info(
                    f"🌐 Serper: Cliente HTTP criado "
                    f"(pool={self._max_concurrent}, http2=True)"
                )
        return self._client
    
    async def close(self):
        """Fecha o cliente HTTP global."""
        async with self._client_lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
                self._client = None
                logger.info("🌐 Serper: Cliente HTTP fechado")
    
    async def search(
        self,
        query: str,
        num_results: int = 100,
        country: str = "br",
        language: str = "pt-br",
        request_id: str = ""
    ) -> Tuple[List[Dict[str, str]], int]:
        """
        Realiza busca no Google usando API Serper.
        
        O fluxo agora é:
        1. Adquirir token do rate limiter (controla taxa de envio)
        2. Adquirir slot de conexão (controla recursos HTTP)
        3. Executar requisição
        
        Isso permite que muitas requisições esperem apenas pelo rate limit,
        não por requisições anteriores terminarem.
        
        Args:
            query: Termo de busca
            num_results: Número máximo de resultados
            country: Código do país (gl)
            language: Código do idioma (hl)
            request_id: ID da requisição
            
        Returns:
            Tuple de (lista de resultados, número de retries)
        """
        if not settings.SERPER_API_KEY:
            logger.warning("⚠️ SERPER_API_KEY não configurada")
            return [], 0
        
        import time as time_module
        
        # 1. Aguardar rate limit (controla TAXA de envio)
        # Medir tempo real de espera para detectar fila
        rate_start = time_module.perf_counter()
        
        # Timeout configurável para fail-fast: se não conseguir token rapidamente,
        # melhor falhar rápido do que esperar muito e travar a empresa
        rate_limit_acquired = await self._rate_limiter.acquire(timeout=self._rate_limiter_timeout)
        
        rate_wait_ms = (time_module.perf_counter() - rate_start) * 1000
        
        # Se esperou mais que 10ms, considerar como fila
        
        if not rate_limit_acquired:
            logger.error(f"❌ Serper: Rate limit timeout para query: {query[:50]}...")
            return [], 0
        
        # 2. Adquirir slot de conexão HTTP (controla RECURSOS)
        connection_semaphore = await self._get_connection_semaphore()
        
        conn_start = time_module.perf_counter()
        
        # Adquirir semáforo com timeout para evitar espera indefinida
        try:
            await asyncio.wait_for(
                connection_semaphore.acquire(),
                timeout=self._connection_semaphore_timeout
            )
        except asyncio.TimeoutError:
            conn_wait_ms = (time_module.perf_counter() - conn_start) * 1000
            # Calcular vagas quando timeout ocorre (todas ocupadas provavelmente)
            available = connection_semaphore._value
            used = self._max_concurrent - available
            logger.error(
                f"❌ Serper: Timeout aguardando slot de conexão após {conn_wait_ms:.0f}ms "
                f"(timeout={self._connection_semaphore_timeout}s) | "
                f"Vagas: {used}/{self._max_concurrent} usadas, {available} disponíveis"
            )
            return [], 0
        
        conn_wait_ms = (time_module.perf_counter() - conn_start) * 1000
        
        
        try:
            # 3. Executar requisição
            req_start = time_module.perf_counter()
            result = await self._search_with_retry(
                query, num_results, country, language, request_id
            )
            req_duration = (time_module.perf_counter() - req_start) * 1000
            
            # Log se requisição demorou muito (possível travamento)
            if req_duration > self._request_timeout * 1000 * 1.5:  # 50% acima do timeout
                available = connection_semaphore._value
                used = self._max_concurrent - available
                logger.warning(
                    f"⚠️ Serper: Requisição demorou {req_duration:.0f}ms "
                    f"(timeout configurado: {self._request_timeout * 1000:.0f}ms) | "
                    f"Vagas: {used}/{self._max_concurrent} usadas"
                )
            
            return result
        finally:
            # Sempre liberar semáforo, mesmo em caso de erro
            connection_semaphore.release()
            available_after = connection_semaphore._value
            used_after = self._max_concurrent - available_after
    
    async def _search_with_retry(
        self,
        query: str,
        num_results: int,
        country: str,
        language: str,
        request_id: str = ""
    ) -> Tuple[List[Dict[str, str]], int]:
        """Executa busca com retry logic."""
        url = "https://google.serper.dev/search"
        payload = json.dumps({
            "q": query,
            "num": num_results,
            "gl": country,
            "hl": language
        })
        headers = {
            'X-API-KEY': settings.SERPER_API_KEY,
            'Content-Type': 'application/json'
        }
        
        client = await self._get_client()
        last_error = None
        last_error_type = None
        last_retry_after: Optional[float] = None
        retries_count = 0
        
        for attempt in range(self._max_retries):
            try:
                # Delay para retry (exceto primeira tentativa)
                if attempt > 0:
                    retries_count += 1
                    # Usar Retry-After da API se disponível (429), senão backoff exponencial
                    if last_retry_after is not None:
                        delay = last_retry_after
                        delay_src = "Retry-After"
                    else:
                        delay = min(
                            self._retry_base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5),
                            self._retry_max_delay
                        )
                        delay_src = "backoff"
                    logger.warning(
                        f"🔄 Serper retry {attempt + 1}/{self._max_retries} "
                        f"após {delay:.1f}s (reason={last_error_type}, src={delay_src})"
                    )
                    
                    await asyncio.sleep(delay)
                    last_retry_after = None  # Usado apenas uma vez
                    
                    # Re-adquirir rate limit para retry (timeout configurável)
                    if not await self._rate_limiter.acquire(timeout=self._rate_limiter_retry_timeout):
                        logger.warning("⚠️ Serper: Rate limit timeout no retry")
                        continue
                
                start_time = time.perf_counter()
                response = await client.post(url, headers=headers, content=payload)
                latency_ms = (time.perf_counter() - start_time) * 1000
                
                self._total_requests += 1
                self._total_latency_ms += latency_ms
                
                # Tratamento de códigos de status
                if response.status_code == 429:
                    self._rate_limited_requests += 1
                    retry_after_val = response.headers.get("Retry-After")
                    parsed = _parse_retry_after(retry_after_val, self._retry_after_max)
                    if parsed is not None:
                        last_retry_after = parsed
                        logger.warning(
                            f"⚠️ Serper rate limit (429), "
                            f"tentativa {attempt + 1}/{self._max_retries} "
                            f"(Retry-After: {parsed:.1f}s)"
                        )
                    else:
                        logger.warning(
                            f"⚠️ Serper rate limit (429), "
                            f"tentativa {attempt + 1}/{self._max_retries}"
                        )
                    last_error = "Rate limit (429)"
                    last_error_type = "rate_limit"
                    continue
                
                if response.status_code >= 500:
                    logger.warning(
                        f"⚠️ Serper server error ({response.status_code}), "
                        f"tentativa {attempt + 1}/{self._max_retries}"
                    )
                    last_error = f"Server error ({response.status_code})"
                    last_error_type = "error"
                    continue
                
                if response.status_code >= 400:
                    self._failed_requests += 1
                    logger.error(f"❌ Serper client error: {response.status_code}")
                    return [], retries_count
                
                # Sucesso
                data = response.json()
                organic_results = data.get("organic", [])
                
                results = []
                for item in organic_results:
                    results.append({
                        "title": item.get("title"),
                        "link": item.get("link"),
                        "snippet": item.get("snippet", "")
                    })
                
                self._successful_requests += 1
                logger.info(f"✅ Serper: {len(results)} resultados retornados de {num_results} solicitados ({latency_ms:.0f}ms)")
                return results, retries_count
                
            except httpx.TimeoutException:
                last_error_type = "timeout"
                last_error = f"timeout após {self._request_timeout}s"
                logger.warning(
                    f"⚠️ Serper {last_error_type}: {last_error}, "
                    f"tentativa {attempt + 1}/{self._max_retries}"
                )
                
            except httpx.ConnectError as e:
                last_error_type = "error"
                last_error = str(e) if str(e) else "falha ao conectar"
                logger.warning(
                    f"⚠️ Serper ConnectError: {last_error}, "
                    f"tentativa {attempt + 1}/{self._max_retries}"
                )
                
            except httpx.PoolTimeout:
                last_error_type = "timeout"
                last_error = "pool de conexões esgotado"
                logger.warning(
                    f"⚠️ Serper PoolTimeout: {last_error}, "
                    f"tentativa {attempt + 1}/{self._max_retries}"
                )
                
            except Exception as e:
                last_error_type = "error"
                last_error = str(e) if str(e) else "erro desconhecido"
                logger.warning(
                    f"⚠️ Serper {type(e).__name__}: {last_error}, "
                    f"tentativa {attempt + 1}/{self._max_retries}"
                )
        
        self._failed_requests += 1
        logger.error(
            f"❌ Serper falhou após {self._max_retries} tentativas: "
            f"[{last_error_type}] {last_error}"
        )
        return [], retries_count
    
    def update_config(
        self,
        rate_per_second: Optional[float] = None,
        max_burst: Optional[int] = None,
        max_concurrent: Optional[int] = None,
        request_timeout: Optional[float] = None,
        max_retries: Optional[int] = None
    ):
        """Atualiza configurações do manager."""
        if rate_per_second is not None:
            self._rate_per_second = rate_per_second
            self._rate_limiter.update_config(rate_per_second=rate_per_second)
        
        if max_burst is not None:
            self._max_burst = max_burst
            self._rate_limiter.update_config(max_burst=max_burst)
        
        if max_concurrent is not None:
            self._max_concurrent = max_concurrent
            self._connection_semaphore = asyncio.Semaphore(max_concurrent)
            
        if request_timeout is not None:
            self._request_timeout = request_timeout
            
        if max_retries is not None:
            self._max_retries = max_retries
        
        logger.info(
            f"SerperManager: Configuração atualizada - "
            f"rate={self._rate_per_second}/s, concurrent={self._max_concurrent}, "
            f"timeout={self._request_timeout}s"
        )
    
    def get_status(self) -> dict:
        """Retorna status e métricas."""
        avg_latency = 0
        if self._successful_requests > 0:
            avg_latency = self._total_latency_ms / self._successful_requests
        
        success_rate = 0
        if self._total_requests > 0:
            success_rate = self._successful_requests / self._total_requests
        
        # Calcular vagas do semáforo
        semaphore_info = {
            "max": self._max_concurrent,
            "available": 0,
            "used": 0,
            "utilization": 0.0
        }
        
        if self._connection_semaphore is not None:
            try:
                available = self._connection_semaphore._value
                used = max(0, self._max_concurrent - available)
                utilization = (used / self._max_concurrent * 100) if self._max_concurrent > 0 else 0.0
                semaphore_info = {
                    "max": self._max_concurrent,
                    "available": available,
                    "used": used,
                    "utilization": round(utilization, 1)
                }
            except Exception:
                pass  # Semáforo pode não estar inicializado ainda
        
        return {
            "total_requests": self._total_requests,
            "successful_requests": self._successful_requests,
            "failed_requests": self._failed_requests,
            "rate_limited_requests": self._rate_limited_requests,
            "success_rate": f"{success_rate:.1%}",
            "avg_latency_ms": round(avg_latency, 2),
            "rate_limiter": self._rate_limiter.get_status(),
            "semaphore": semaphore_info,
            "config": {
                "rate_per_second": self._rate_per_second,
                "max_burst": self._max_burst,
                "max_concurrent": self._max_concurrent,
                "request_timeout": self._request_timeout,
                "max_retries": self._max_retries
            }
        }
    
    def reset_metrics(self):
        """Reseta métricas."""
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._rate_limited_requests = 0
        self._total_latency_ms = 0
        self._rate_limiter.reset_metrics()
        logger.info("SerperManager: Métricas resetadas")


# Instância singleton
serper_manager = SerperManager()


# Função de conveniência
async def search_serper(
    query: str,
    num_results: int = 100
) -> List[Dict[str, str]]:
    """Busca usando Serper API (função de conveniência)."""
    results, _ = await serper_manager.search(query, num_results)
    return results
