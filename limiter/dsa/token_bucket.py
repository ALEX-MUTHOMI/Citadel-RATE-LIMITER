from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Decision:
    allowed: bool
    remaining: float
    limit: float
    retry_after: float = 0.0


class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def allow(self, cost: float = 1.0) -> Decision:
        now = time.monotonic()
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= cost:
            self.tokens -= cost
            return Decision(True, self.tokens, self.capacity)
        missing = cost - self.tokens
        retry_after = missing / self.refill_rate if self.refill_rate else 0.0
        return Decision(False, self.tokens, self.capacity, retry_after)
