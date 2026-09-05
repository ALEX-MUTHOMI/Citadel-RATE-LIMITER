from __future__ import annotations

from functools import lru_cache

from limiter.dsa import Decision, ShopifyLeakyBucket, SlidingWindow, TokenBucket
from limiter.models import Algorithm, ClientProject


@lru_cache(maxsize=256)
def _memory_limiter(client_id: int, key: str, algorithm: str, capacity: float, refill_rate: float, window: float):
    if algorithm == Algorithm.SLIDING_WINDOW:
        return SlidingWindow(capacity=int(capacity), window_seconds=window)
    if algorithm == Algorithm.SHOPIFY_LEAKY_BUCKET:
        return ShopifyLeakyBucket(capacity=capacity, restore_rate=refill_rate)
    return TokenBucket(capacity=capacity, refill_rate=refill_rate)


class RateLimiterService:
    def __init__(self, client: ClientProject) -> None:
        self.client = client

    def consume(self, key: str, cost: float = 1.0) -> Decision:
        limiter = _memory_limiter(
            self.client.id,
            key,
            self.client.algorithm,
            float(self.client.capacity),
            float(self.client.refill_rate),
            float(self.client.window_seconds),
        )
        return limiter.allow(cost)
