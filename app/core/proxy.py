import random
import httpx
import logging
from typing import List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self):
        self.proxies: List[str] = []
        self.list_url = settings.WEBSHARE_PROXY_LIST_URL

    async def _refresh_proxies(self):
        """Downloads and parses the proxy list from Webshare."""
        try:
            if not self.list_url: return
            
            async with httpx.AsyncClient() as client:
                resp = await client.get(self.list_url, timeout=10)
                
                # Check for 429 specifically to avoid error spam
                if resp.status_code == 429:
                    logger.warning("[ProxyManager] Rate limit exceeded (429) while refreshing proxies. Using existing pool if available.")
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
                    logger.info(f"[ProxyManager] Loaded {len(self.proxies)} proxies.")
                    
        except Exception as e:
            logger.error(f"[ProxyManager] Failed to refresh proxies: {e}")

    async def get_next_proxy(self) -> Optional[str]:
        """Returns a random proxy from the pool, refreshing if empty."""
        if not self.proxies:
            await self._refresh_proxies()
            
        if not self.proxies:
            return None
            
        return random.choice(self.proxies)

proxy_manager = ProxyManager()
