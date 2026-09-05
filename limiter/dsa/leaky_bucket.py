from limiter.dsa.token_bucket import TokenBucket


class ShopifyLeakyBucket(TokenBucket):
    """Shopify REST-style leaky bucket: default 40 capacity, 2 restores per second."""

    def __init__(self, capacity: float = 40.0, restore_rate: float = 2.0) -> None:
        super().__init__(capacity=capacity, refill_rate=restore_rate)
