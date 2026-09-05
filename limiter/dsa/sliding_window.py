from __future__ import annotations

import time
from collections import deque

from limiter.dsa.token_bucket import Decision


class SlidingWindow:
    def __init__(self, capacity: int, window_seconds: float) -> None:
        self.capacity = capacity
        self.window_seconds = window_seconds
        self.events: deque[float] = deque()

    def allow(self, cost: float = 1.0) -> Decision:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        while self.events and self.events[0] <= cutoff:
            self.events.popleft()
        used = len(self.events)
        if used + cost <= self.capacity:
            for _ in range(int(cost)):
                self.events.append(now)
            remaining = self.capacity - len(self.events)
            return Decision(True, remaining, self.capacity)
        oldest = self.events[0] if self.events else now
        retry_after = max(0.0, self.window_seconds - (now - oldest))
        return Decision(False, self.capacity - used, self.capacity, retry_after)
