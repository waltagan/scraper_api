"""
Controle global de retry budget + jitter para batches de scrape.
"""

import asyncio
import bisect
import random
from typing import Dict, List

from .constants import (
    RETRY_BUDGET_ENABLED,
    RETRY_BUDGET_RATIO,
    RETRY_JITTER_MIN_MS,
    RETRY_JITTER_MAX_MS,
)

_lock = asyncio.Lock()
_enforced: bool = False
_budget_total: int = 0
_budget_used: int = 0
_budget_dropped: int = 0
_jitter_samples_ms: List[float] = []


async def configure_for_batch(total_companies: int) -> None:
    global _enforced, _budget_total, _budget_used, _budget_dropped, _jitter_samples_ms
    async with _lock:
        _enforced = RETRY_BUDGET_ENABLED
        _budget_total = max(0, int(total_companies * RETRY_BUDGET_RATIO))
        _budget_used = 0
        _budget_dropped = 0
        _jitter_samples_ms = []


async def disable_for_batch() -> None:
    global _enforced
    async with _lock:
        _enforced = False


async def consume_retry_token() -> bool:
    global _budget_used, _budget_dropped
    async with _lock:
        if not _enforced:
            return True
        if _budget_used < _budget_total:
            _budget_used += 1
            return True
        _budget_dropped += 1
        return False


async def sleep_retry_jitter() -> float:
    min_ms = max(RETRY_JITTER_MIN_MS, 0)
    max_ms = max(RETRY_JITTER_MAX_MS, min_ms)
    jitter_ms = random.uniform(min_ms, max_ms)
    await asyncio.sleep(jitter_ms / 1000.0)
    async with _lock:
        bisect.insort(_jitter_samples_ms, jitter_ms)
    return jitter_ms


def _pct(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    i = min(len(values) - 1, int(len(values) * p))
    return float(values[i])


def snapshot() -> Dict[str, float]:
    samples = _jitter_samples_ms
    return {
        "enabled": _enforced,
        "ratio": RETRY_BUDGET_RATIO,
        "total": _budget_total,
        "used": _budget_used,
        "remaining": max(0, _budget_total - _budget_used),
        "dropped": _budget_dropped,
        "jitter_count": len(samples),
        "jitter_ms_p50": round(_pct(samples, 0.5), 1),
        "jitter_ms_p90": round(_pct(samples, 0.9), 1),
    }
