import random
import httpx
import logging
import time
from typing import List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self):
        self.proxies: List[str] = []
        self.list_url = settings.WEBSHARE_PROXY_LIST_URL
        self._last_refresh_attempt: float = 0.0
        self._last_successful_refresh: float = 0.0
        self._consecutive_failures: int = 0
        self._refresh_lock = False  # Simple lock to prevent concurrent refreshes
        
        # Backoff: 60s após 3 falhas, 300s após 5 falhas
        self._BACKOFF_DELAYS = [0, 0, 0, 60, 60, 300]
        self._MAX_BACKOFF = 300

    async def _refresh_proxies(self, force: bool = False):
        """Downloads and parses the proxy list from Webshare with backoff."""
        if self._refresh_lock:
            return

        now = time.time()
        if not force and self._consecutive_failures > 0:
            backoff_delay = self._BACKOFF_DELAYS[min(self._consecutive_failures, len(self._BACKOFF_DELAYS) - 1)]
            time_since_last = now - self._last_refresh_attempt
            if time_since_last < backoff_delay:
                return

        if not force and self.proxies and (now - self._last_successful_refresh) < 300:
            return
        
        self._refresh_lock = True
        self._last_refresh_attempt = now
        
        try:
            if not self.list_url:
                self._refresh_lock = False
                return
            
            async with httpx.AsyncClient() as client:
                resp = await client.get(self.list_url, timeout=10)
                
                # Check for 429 specifically to avoid error spam
                if resp.status_code == 429:
                    self._consecutive_failures += 1
                    logger.warning(f"[ProxyManager] Rate limit exceeded (429). Using existing pool. Backoff: {self._consecutive_failures} failures.")
                    self._refresh_lock = False
                    return
                
                # Check for 404 - URL inválida ou token expirado
                if resp.status_code == 404:
                    self._consecutive_failures += 1
                    logger.error(f"[ProxyManager] URL inválida ou token expirado (404). Verifique WEBSHARE_PROXY_LIST_URL. Backoff: {self._consecutive_failures} failures.")
                    self._refresh_lock = False
                    return
                
                resp.raise_for_status()
                
                # Format: IP:PORT:USERNAME:PASSWORD
                # Target: http://USERNAME:PASSWORD@IP:PORT
                lines = resp.text.strip().splitlines()
                new_proxies = []
                for line in lines:
                    if ":" in line:
                        parts = line.strip().split(":")
                        if len(parts) == 4:
                            ip, port, user, pw = parts
                            new_proxies.append(f"http://{user}:{pw}@{ip}:{port}")
                
                if new_proxies:
                    self.proxies = new_proxies
                    self._last_successful_refresh = now
                    self._consecutive_failures = 0  # Reset on success
                    logger.info(f"[ProxyManager] Loaded {len(self.proxies)} proxies.")
                else:
                    self._consecutive_failures += 1
                    logger.warning(f"[ProxyManager] Lista de proxies vazia. Backoff: {self._consecutive_failures} failures.")
                    
        except httpx.HTTPStatusError as e:
            self._consecutive_failures += 1
            if e.response.status_code not in [404, 429]:  # Don't log 404/429 again
                logger.error(f"[ProxyManager] HTTP error {e.response.status_code} ao buscar proxies. Backoff: {self._consecutive_failures} failures.")
        except Exception as e:
            self._consecutive_failures += 1
            # Only log error details if it's not a common network error
            if "404" not in str(e) and "429" not in str(e):
                logger.error(f"[ProxyManager] Erro ao buscar proxies: {type(e).__name__}. Backoff: {self._consecutive_failures} failures.")
        finally:
            self._refresh_lock = False

    async def get_next_proxy(self) -> Optional[str]:
        """Returns a random proxy from the pool, refreshing if empty."""
        if not self.proxies:
            await self._refresh_proxies()
            
        if not self.proxies:
            return None
            
        return random.choice(self.proxies)

proxy_manager = ProxyManager()
