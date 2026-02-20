"""
Prober de URLs para encontrar a melhor variação acessível.
Testa http/https, www/non-www em paralelo.
"""

import asyncio
import time
import logging
import subprocess
import socket
from typing import List, Tuple, Optional
from urllib.parse import urlparse
from enum import Enum

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    AsyncSession = None

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from .constants import DEFAULT_HEADERS, build_headers

logger = logging.getLogger(__name__)


class ProbeErrorType(Enum):
    """Tipos de erro no probe de URL."""
    DNS_ERROR = "dns_error"
    CONNECTION_REFUSED = "connection_refused"
    CONNECTION_TIMEOUT = "connection_timeout"
    SSL_ERROR = "ssl_error"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    HTTP_ERROR = "http_error"
    SERVER_ERROR = "server_error"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


def _classify_probe_error(error: Exception, url: str) -> Tuple[ProbeErrorType, str]:
    """
    Classifica um erro de probe em um tipo específico.
    
    Returns:
        Tuple de (tipo_erro, mensagem_descritiva)
    """
    error_str = str(error).lower()
    error_type = type(error).__name__
    
    # DNS errors
    if any(x in error_str for x in ['nodename nor servname', 'name or service not known', 
                                      'getaddrinfo failed', 'dns', 'resolve']):
        return ProbeErrorType.DNS_ERROR, f"DNS não resolve - domínio pode estar expirado ou incorreto"
    
    if isinstance(error, socket.gaierror):
        return ProbeErrorType.DNS_ERROR, f"Falha na resolução DNS: {error}"
    
    # Connection errors
    if any(x in error_str for x in ['connection refused', 'errno 111', 'errno 61']):
        return ProbeErrorType.CONNECTION_REFUSED, f"Conexão recusada - servidor pode estar offline"
    
    if any(x in error_str for x in ['timeout', 'timed out', 'time out']):
        return ProbeErrorType.CONNECTION_TIMEOUT, f"Timeout - servidor não respondeu a tempo"
    
    if any(x in error_str for x in ['connection reset', 'broken pipe', 'connection aborted']):
        return ProbeErrorType.CONNECTION_REFUSED, f"Conexão interrompida pelo servidor"
    
    # SSL errors
    if any(x in error_str for x in ['ssl', 'certificate', 'cert', 'handshake']):
        return ProbeErrorType.SSL_ERROR, f"Erro de SSL/TLS - certificado inválido ou expirado"
    
    # Redirect errors
    if any(x in error_str for x in ['redirect', 'too many', '47']):
        return ProbeErrorType.TOO_MANY_REDIRECTS, f"Loop de redirects - configuração problemática do servidor"
    
    # HTTP errors based on type name
    if 'http' in error_type.lower():
        return ProbeErrorType.HTTP_ERROR, f"Erro HTTP: {error}"
    
    return ProbeErrorType.UNKNOWN, str(error)


class URLProber:
    """
    Testa variações de URL em paralelo para encontrar a melhor.
    Retorna a primeira URL que responde com sucesso.
    
    Otimizado para alta concorrência (500 empresas simultâneas).
    """
    
    def __init__(self, timeout: float = 7.0, max_concurrent: int = 500):
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._cache: dict = {}  # Cache de URLs já validadas
        self._last_errors: dict = {}  # Armazena últimos erros para diagnóstico
    
    async def probe(self, base_url: str) -> Tuple[str, float]:
        """
        Testa variações de URL em paralelo.
        Otimizado: testa URL original primeiro, só testa variações se falhar.
        
        Args:
            base_url: URL base para gerar variações
        
        Returns:
            Tuple de (melhor_url, tempo_resposta_ms)
        
        Raises:
            URLNotReachable: Se nenhuma variação responder (com detalhes do erro)
        """
        # Verificar cache
        if base_url in self._cache:
            cached = self._cache[base_url]
            return cached['url'], cached['time']
        
        # Normalizar URL
        if not base_url.startswith(('http://', 'https://')):
            base_url = 'https://' + base_url
        
        # Coletar erros para diagnóstico
        collected_errors: List[Tuple[str, ProbeErrorType, str]] = []
        
        # OTIMIZAÇÃO: Tentar URL original primeiro (mais rápido)
        result, error_info = await self._test_url_with_error(base_url)
        if result and result[1] < 400:
            self._cache[base_url] = {'url': base_url, 'time': result[0]}
            return base_url, result[0]
        
        if error_info:
            collected_errors.append((base_url, error_info[0], error_info[1]))
        
        # Se falhou, tentar variações
        variations = self._generate_variations(base_url)
        # Remover a URL original já testada
        variations = [v for v in variations if v != base_url]
        
        if not variations:
            error_type, error_msg = self._get_best_error_diagnosis(collected_errors, base_url)
            raise URLNotReachable(
                f"{error_msg}",
                error_type=error_type,
                url=base_url
            )
        
        # Criar tasks para variações restantes
        tasks = [self._test_url_with_error(url) for url in variations]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filtrar resultados bem-sucedidos e coletar erros
        successful = []
        for url, result in zip(variations, results):
            if isinstance(result, Exception):
                err_type, err_msg = _classify_probe_error(result, url)
                collected_errors.append((url, err_type, err_msg))
                continue
            if result is not None:
                resp_result, error_info = result
                if resp_result:
                    response_time, status = resp_result
                    if status < 400:
                        successful.append((url, response_time, status))
                    elif status >= 500:
                        collected_errors.append((url, ProbeErrorType.SERVER_ERROR, f"Servidor retornou erro {status}"))
                    elif status == 403:
                        collected_errors.append((url, ProbeErrorType.BLOCKED, f"Acesso bloqueado (403)"))
                if error_info:
                    collected_errors.append((url, error_info[0], error_info[1]))
        
        if not successful:
            error_type, error_msg = self._get_best_error_diagnosis(collected_errors, base_url)
            raise URLNotReachable(
                f"{error_msg}",
                error_type=error_type,
                url=base_url
            )
        
        # Ordenar por status (2xx primeiro) e depois por tempo
        successful.sort(key=lambda x: (x[2] >= 300, x[1]))
        
        best_url, best_time, best_status = successful[0]
        
        # Cachear resultado
        self._cache[base_url] = {'url': best_url, 'time': best_time}
        
        logger.info(f"🎯 Melhor URL: {best_url} ({best_time:.0f}ms, status {best_status})")
        
        return best_url, best_time
    
    def _get_best_error_diagnosis(
        self, 
        errors: List[Tuple[str, ProbeErrorType, str]], 
        base_url: str
    ) -> Tuple[ProbeErrorType, str]:
        """
        Determina o melhor diagnóstico baseado nos erros coletados.
        Prioriza erros mais específicos/informativos.
        """
        if not errors:
            return ProbeErrorType.UNKNOWN, f"Nenhuma variação de {base_url} respondeu"
        
        # Prioridade de erros (mais específico primeiro)
        priority = {
            ProbeErrorType.DNS_ERROR: 1,
            ProbeErrorType.SSL_ERROR: 2,
            ProbeErrorType.CONNECTION_REFUSED: 3,
            ProbeErrorType.CONNECTION_TIMEOUT: 4,
            ProbeErrorType.TOO_MANY_REDIRECTS: 5,
            ProbeErrorType.BLOCKED: 6,
            ProbeErrorType.SERVER_ERROR: 7,
            ProbeErrorType.HTTP_ERROR: 8,
            ProbeErrorType.UNKNOWN: 9,
        }
        
        # Ordenar por prioridade
        errors.sort(key=lambda x: priority.get(x[1], 99))
        
        best_error = errors[0]
        return best_error[1], best_error[2]
    
    async def _test_url_with_error(
        self, 
        url: str
    ) -> Tuple[Optional[Tuple[float, int]], Optional[Tuple[ProbeErrorType, str]]]:
        """
        Testa URL e retorna resultado ou informação de erro detalhada.
        
        Returns:
            Tuple de (resultado, erro_info)
            - resultado: (tempo_ms, status_code) ou None
            - erro_info: (tipo_erro, mensagem) ou None
        """
        async with self.semaphore:
            last_error = None
            
            # Tentar curl_cffi primeiro
            if HAS_CURL_CFFI:
                result = await self._test_with_curl_cffi(url)
                if result:
                    return result, None
            
            # Fallback para httpx
            if HAS_HTTPX:
                result = await self._test_with_httpx(url)
                if result:
                    return result, None
            
            # Fallback para system curl
            result = await self._test_with_system_curl(url)
            if result:
                return result, None
            
            # Se chegou aqui, todos falharam - tentar detectar o tipo de erro
            error_info = await self._diagnose_connection_error(url)
            return None, error_info
    
    async def _diagnose_connection_error(
        self,
        url: str
    ) -> Tuple[ProbeErrorType, str]:
        """Diagnóstico simplificado (sem testes diretos de DNS/TCP via IP local)."""
        return ProbeErrorType.UNKNOWN, f"Todas tentativas via proxy falharam para {url}"
    
    def _generate_variations(self, base_url: str) -> List[str]:
        """
        Gera variações de uma URL (http/https, www/non-www).
        
        Args:
            base_url: URL base
        
        Returns:
            Lista de variações únicas
        """
        # Normalizar URL
        if not base_url.startswith(('http://', 'https://')):
            base_url = 'https://' + base_url
        
        parsed = urlparse(base_url)
        domain = parsed.netloc
        path = parsed.path or '/'
        
        # Remover www. se existir para ter a versão base
        base_domain = domain.replace('www.', '')
        
        variations = set()
        
        # Gerar todas as combinações
        for scheme in ['https', 'http']:
            for prefix in ['', 'www.']:
                full_domain = prefix + base_domain
                # Evitar www.www.
                if not full_domain.startswith('www.www.'):
                    url = f"{scheme}://{full_domain}{path}"
                    variations.add(url.rstrip('/'))
        
        # Adicionar URL original se não estiver
        original = f"{parsed.scheme}://{domain}{path}".rstrip('/')
        variations.add(original)
        
        # Ordenar: https primeiro, www primeiro
        sorted_vars = sorted(variations, key=lambda x: (
            not x.startswith('https'),
            'www.' not in x
        ))
        
        return sorted_vars
    
    async def _test_url(self, url: str) -> Optional[Tuple[float, int]]:
        """
        Testa uma URL específica.
        Usa curl_cffi se disponível, senão httpx, senão system curl.
        
        Args:
            url: URL para testar
        
        Returns:
            Tuple de (tempo_ms, status_code) ou None se falhar
        """
        result, _ = await self._test_url_with_error(url)
        return result
    
    async def _test_with_curl_cffi(self, url: str) -> Optional[Tuple[float, int]]:
        """Testa URL com curl_cffi via proxy."""
        try:
            from app.services.scraper_manager.proxy_manager import proxy_pool
            proxy = proxy_pool.get_next_proxy()

            headers, impersonate = build_headers()

            async with AsyncSession(
                impersonate=impersonate,
                proxy=proxy,
                timeout=self.timeout,
                verify=False,
                max_redirects=5
            ) as session:
                start = time.perf_counter()
                try:
                    resp = await session.head(url, headers=headers, allow_redirects=True)
                    elapsed = (time.perf_counter() - start) * 1000

                    if resp.status_code == 403:
                        start = time.perf_counter()
                        resp = await session.get(url, headers=headers, allow_redirects=True)
                        elapsed = (time.perf_counter() - start) * 1000

                    return elapsed, resp.status_code

                except Exception as head_error:
                    error_str = str(head_error).lower()
                    if "redirect" in error_str or "47" in error_str:
                        start = time.perf_counter()
                        resp = await session.get(url, headers=headers, allow_redirects=True)
                        elapsed = (time.perf_counter() - start) * 1000
                        return elapsed, resp.status_code
                    raise

        except Exception as e:
            logger.debug(f"curl_cffi falhou para {url}: {e}")
            return None
    
    async def _test_with_httpx(self, url: str) -> Optional[Tuple[float, int]]:
        """Testa URL com httpx via proxy."""
        try:
            from app.services.scraper_manager.proxy_manager import proxy_pool
            proxy = proxy_pool.get_next_proxy()

            headers = {k: v for k, v in DEFAULT_HEADERS.items()}
            proxy_url = f"http://{proxy}" if proxy and "://" not in proxy else proxy

            async with httpx.AsyncClient(
                timeout=self.timeout,
                verify=False,
                follow_redirects=True,
                max_redirects=5,
                proxy=proxy_url if proxy else None,
            ) as client:
                start = time.perf_counter()
                try:
                    resp = await client.head(url, headers=headers)
                    elapsed = (time.perf_counter() - start) * 1000

                    if resp.status_code == 403:
                        start = time.perf_counter()
                        resp = await client.get(url, headers=headers)
                        elapsed = (time.perf_counter() - start) * 1000

                    return elapsed, resp.status_code

                except httpx.TooManyRedirects:
                    start = time.perf_counter()
                    resp = await client.get(url, headers=headers)
                    elapsed = (time.perf_counter() - start) * 1000
                    return elapsed, resp.status_code

        except Exception as e:
            logger.debug(f"httpx falhou para {url}: {e}")
            return None
    
    async def _test_with_system_curl(self, url: str) -> Optional[Tuple[float, int]]:
        """Testa URL com system curl via proxy (último recurso)."""
        try:
            from app.services.scraper_manager.proxy_manager import proxy_pool
            proxy = proxy_pool.get_next_proxy()

            proxy_args = ["--proxy", f"http://{proxy}"] if proxy else []

            cmd = [
                "curl", "-I", "-L", "-k", "-s",
                *proxy_args,
                "--max-time", str(int(self.timeout)),
                "--max-redirs", "5",
                "-o", "/dev/null", "-w", "%{http_code}",
                "-A", "Mozilla/5.0",
                url
            ]

            start = time.perf_counter()
            res = await asyncio.to_thread(
                subprocess.run, cmd,
                capture_output=True, text=True, timeout=self.timeout + 2
            )
            elapsed = (time.perf_counter() - start) * 1000

            if res.returncode == 0 and res.stdout.strip():
                status_code = int(res.stdout.strip())

                if status_code == 403:
                    cmd_get = [
                        "curl", "-L", "-k", "-s",
                        *proxy_args,
                        "--max-time", str(int(self.timeout)),
                        "--max-redirs", "5",
                        "-o", "/dev/null", "-w", "%{http_code}",
                        "-A", "Mozilla/5.0",
                        url
                    ]
                    start = time.perf_counter()
                    res = await asyncio.to_thread(
                        subprocess.run, cmd_get,
                        capture_output=True, text=True, timeout=self.timeout + 2
                    )
                    elapsed = (time.perf_counter() - start) * 1000
                    if res.returncode == 0 and res.stdout.strip():
                        status_code = int(res.stdout.strip())

                return elapsed, status_code

            if res.returncode == 47:
                cmd_get = [
                    "curl", "-L", "-k", "-s",
                    *proxy_args,
                    "--max-time", str(int(self.timeout)),
                    "--max-redirs", "10",
                    "-o", "/dev/null", "-w", "%{http_code}",
                    "-A", "Mozilla/5.0",
                    url
                ]
                start = time.perf_counter()
                res = await asyncio.to_thread(
                    subprocess.run, cmd_get,
                    capture_output=True, text=True, timeout=self.timeout + 2
                )
                elapsed = (time.perf_counter() - start) * 1000
                if res.returncode == 0 and res.stdout.strip():
                    return elapsed, int(res.stdout.strip())

            return None
        except Exception as e:
            logger.debug(f"system curl falhou para {url}: {e}")
            return None
    
    async def find_best_variation(
        self, 
        urls: List[str]
    ) -> Tuple[str, float]:
        """
        Encontra a melhor URL de uma lista.
        
        Args:
            urls: Lista de URLs para testar
        
        Returns:
            Tuple de (melhor_url, tempo_ms)
        """
        tasks = [self._test_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception) or result is None:
                continue
            response_time, status = result
            if status < 400:
                successful.append((url, response_time, status))
        
        if not successful:
            raise URLNotReachable("Nenhuma URL da lista respondeu")
        
        successful.sort(key=lambda x: (x[2] >= 300, x[1]))
        return successful[0][0], successful[0][1]


class URLNotReachable(Exception):
    """
    Exceção quando nenhuma variação de URL responde.
    Inclui informações detalhadas sobre o tipo de erro.
    """
    def __init__(
        self, 
        message: str, 
        error_type: ProbeErrorType = ProbeErrorType.UNKNOWN,
        url: str = ""
    ):
        self.error_type = error_type
        self.url = url
        self.message = message
        super().__init__(message)
    
    def get_log_message(self) -> str:
        """Retorna mensagem formatada para log."""
        type_labels = {
            ProbeErrorType.DNS_ERROR: "🌐 DNS_ERROR",
            ProbeErrorType.CONNECTION_REFUSED: "🚫 CONNECTION_REFUSED",
            ProbeErrorType.CONNECTION_TIMEOUT: "⏱️ TIMEOUT",
            ProbeErrorType.SSL_ERROR: "🔒 SSL_ERROR",
            ProbeErrorType.TOO_MANY_REDIRECTS: "🔄 REDIRECT_LOOP",
            ProbeErrorType.HTTP_ERROR: "📡 HTTP_ERROR",
            ProbeErrorType.SERVER_ERROR: "💥 SERVER_ERROR",
            ProbeErrorType.BLOCKED: "🛡️ BLOCKED",
            ProbeErrorType.UNKNOWN: "❓ UNKNOWN",
        }
        label = type_labels.get(self.error_type, "❓ UNKNOWN")
        return f"[{label}] {self.message}"


# Instância singleton
url_prober = URLProber()

