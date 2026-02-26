"""
Cache temporário em Redis para raw_content do fluxo unificado.
"""
import json
import os
from typing import Optional

from redis.asyncio import Redis  # type: ignore[reportMissingImports]


class RawContentCache:
    def __init__(self):
        self._redis: Optional[Redis] = None
        self._redis_url = os.getenv("REDIS_URL", "").strip()
        self._prefix = "scrape_unified:raw:"

    async def _get_client(self) -> Redis:
        if not self._redis_url:
            raise RuntimeError("REDIS_URL não configurada para fluxo unificado")
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def _key(self, run_id: str, cnpj_basico: str) -> str:
        return f"{self._prefix}{run_id}:{cnpj_basico}"

    async def set_raw_content(
        self,
        run_id: str,
        cnpj_basico: str,
        website_url: str,
        raw_content: str,
        ttl_seconds: int,
    ) -> None:
        redis = await self._get_client()
        payload = json.dumps(
            {
                "run_id": run_id,
                "cnpj_basico": cnpj_basico,
                "website_url": website_url,
                "raw_content": raw_content,
            },
            ensure_ascii=False,
        )
        await redis.set(self._key(run_id, cnpj_basico), payload, ex=ttl_seconds)

    async def get_raw_content(self, run_id: str, cnpj_basico: str) -> Optional[dict]:
        redis = await self._get_client()
        raw = await redis.get(self._key(run_id, cnpj_basico))
        if not raw:
            return None
        return json.loads(raw)

    async def delete_raw_content(self, run_id: str, cnpj_basico: str) -> None:
        redis = await self._get_client()
        await redis.delete(self._key(run_id, cnpj_basico))


raw_content_cache = RawContentCache()
