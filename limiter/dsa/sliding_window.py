"""
Sliding Window rate limiters — hardened implementation.

Two variants:

SlidingWindowCounter  (DEFAULT — Cloudflare O(1))
    Two fixed-window bucket counters.  Wall-clock epoch anchored.
    Thread-safe.  Closed-form retry_after.  Cost-weighted.
    Suitable for any production traffic volume.

    Key correctness properties:
    - Buckets use time.time() so bucket_id is identical across all processes
      and restarts — prerequisite for Phase 2 Redis integration.
    - Multi-window idleness: if >= 2 full windows elapse, both counters are
      zeroed so dormant tenants are not penalised by their old prev_count.
    - NTP rollback guard: if clock moves backward, state is left unchanged
      (conservative: may briefly over-throttle, never under-throttles).
    - Closed-form retry_after solves the exact sub-window decay point instead
      of rounding up to the whole window boundary.

SlidingWindowLog  (exact, O(N) memory)
    Deque of (timestamp, cost) entries.  Evicts on each call.
    100% accurate.  Use only when precision matters and volume is low.

SlidingWindow
    Backward-compatible wrapper.  Default is now ``counter``.

Cloudflare reference:
    https://blog.cloudflare.com/counting-things-a-lot-of-different-things/
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Literal

from limiter.dsa.token_bucket import Decision


# ---------------------------------------------------------------------------
# Cloudflare-style Sliding Window Counter -- O(1), wall-clock anchored
# ---------------------------------------------------------------------------

class SlidingWindowCounter:
    """
    Hardened Cloudflare-style Sliding Window Counter.

    Formula::

        bucket_id = int(unix_time // W)
        delta_t   = unix_time - bucket_id * W
        rate      = prev_count * ((W - delta_t) / W) + curr_count

    A request of *cost* is admitted iff  rate + cost <= capacity.

    Thread safety:
        All mutable state is protected by a threading.Lock().
        No I/O ever occurs inside the lock -- only arithmetic.

    Testability:
        allow() and estimate_rate() accept an optional now (Unix timestamp)
        so tests can inject arbitrary wall-clock values without time.sleep().
    """

    def __init__(self, capacity: int, window_seconds: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.capacity = capacity
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._curr_bucket: int = -1      # -1 = uninitialized sentinel
        self._curr_count: float = 0.0
        self._prev_count: float = 0.0

    # ------------------------------------------------------------------
    # Internals -- all require self._lock to be held by the caller
    # ------------------------------------------------------------------

    def _sync(self, now: float) -> float:
        """
        Align counters to epoch-anchored bucket boundaries.
        Returns delta_t = elapsed seconds inside the current bucket.
        MUST be called with self._lock held.

        bucket_diff semantics:
            0   -> same window, no-op
            1   -> normal rollover: curr -> prev, curr resets to 0
          >= 2  -> multi-window gap: BOTH counters zeroed (full amnesty).
                   Promoting Window1 count into prev for Window3 would
                   penalise a tenant for traffic outside the sliding window.
          < 0   -> NTP clock rollback: no-op (conservative, never under-throttles)
        """
        active = int(now // self.window_seconds)
        delta_t = now - active * self.window_seconds

        if self._curr_bucket == -1:
            self._curr_bucket = active
            return delta_t

        diff = active - self._curr_bucket
        if diff == 0:
            pass
        elif diff == 1:
            self._prev_count = self._curr_count
            self._curr_count = 0.0
            self._curr_bucket = active
        elif diff > 1:
            # Tenant was idle for >= 2 windows: both counters fully reset.
            self._prev_count = 0.0
            self._curr_count = 0.0
            self._curr_bucket = active
        # diff < 0: clock rollback -- leave state untouched

        return delta_t

    def _rate(self, delta_t: float) -> float:
        """Cloudflare weighted estimate. Requires lock."""
        weight = max(0.0, (self.window_seconds - delta_t) / self.window_seconds)
        return self._prev_count * weight + self._curr_count

    def _compute_retry_after(self, delta_t: float, cost: float = 1.0) -> float:
        """
        Closed-form solution: minimum wait until rate + cost drops <= capacity.
        MUST be called with self._lock held.

        Case A -- curr + cost <= capacity (decay within current window is sufficient):
            Solve: prev * (1 - target_dt/W) + curr + cost <= C
            -> target_dt = W * (1 - (C - curr - cost) / prev)
            -> retry_after = max(0, target_dt - delta_t)

        Case B -- curr + cost > capacity (current bucket alone saturates capacity):
            Must wait for full rollover (W - delta_t).  Then curr becomes
            the new prev and begins decaying.  Solve for decay point:
            -> decay_in_next = W * (1 - (C - cost) / curr)
            -> retry_after = (W - delta_t) + max(0, decay_in_next)
        """
        C = float(self.capacity)
        W = self.window_seconds

        if cost > C:
            return float("inf")

        if self._curr_count + cost > C:
            # Case B: wait for full window rollover first.
            wait_rollover = W - delta_t
            if self._curr_count > 0:
                headroom = C - cost
                decay_in_next = W * max(0.0, 1.0 - (headroom / self._curr_count))
                return wait_rollover + decay_in_next
            return wait_rollover

        # Case A: only prev window excess needs to decay.
        if self._prev_count > 0:
            headroom = C - self._curr_count - cost
            if headroom < 0:
                return W - delta_t
            threshold = headroom / self._prev_count  # required prev weight
            if threshold >= 1.0:
                return 0.0   # prev already decayed enough -- allow immediately
            target_dt = W * (1.0 - threshold)
            return max(0.0, target_dt - delta_t)

        return 0.0  # prev == 0 and curr < C -- caller should have been admitted

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def estimate_rate(self, now: float | None = None) -> float:
        """
        Current estimated rolling-window usage without consuming capacity.
        Use for monitoring dashboards and observability tooling.
        """
        if now is None:
            now = time.time()
        with self._lock:
            delta_t = self._sync(now)
            return self._rate(delta_t)

    def allow(self, cost: float = 1.0, now: float | None = None) -> Decision:
        """
        Attempt to consume *cost* units.

        Parameters
        ----------
        cost : float
            Request weight. Use > 1 for expensive endpoints (uploads, etc.).
        now : float | None
            Unix timestamp override. For deterministic tests only.

        Returns
        -------
        Decision(allowed, remaining, limit, retry_after)
        """
        if cost <= 0:
            raise ValueError("cost must be > 0")
        if now is None:
            now = time.time()

        with self._lock:
            delta_t = self._sync(now)
            rate = self._rate(delta_t)

            if rate + cost <= self.capacity:
                self._curr_count += cost
                return Decision(True, max(0.0, self.capacity - (rate + cost)), self.capacity, 0.0)

            remaining = max(0.0, self.capacity - rate)
            retry_after = self._compute_retry_after(delta_t, cost=cost)
            return Decision(False, remaining, self.capacity, retry_after)


# ---------------------------------------------------------------------------
# Exact sliding window log -- O(N) memory, thread-safe
# ---------------------------------------------------------------------------

class SlidingWindowLog:
    """
    Exact sliding window limiter backed by an in-memory (timestamp, cost) deque.
    Thread-safe via threading.Lock(). Uses time.monotonic() (process-local).
    """

    def __init__(self, capacity: int, window_seconds: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.capacity = capacity
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._events: deque[tuple[float, float]] = deque()
        self._used: float = 0.0

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] <= cutoff:
            _, cost = self._events.popleft()
            self._used -= cost
        if self._used < 0:
            self._used = 0.0

    def allow(self, cost: float = 1.0) -> Decision:
        if cost <= 0:
            raise ValueError("cost must be > 0")
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            if self._used + cost <= self.capacity:
                self._events.append((now, cost))
                self._used += cost
                return Decision(True, max(0.0, self.capacity - self._used), self.capacity, 0.0)
            remaining = max(0.0, self.capacity - self._used)
            needed = cost - (self.capacity - self._used)
            freed = 0.0
            retry_after = self.window_seconds
            for ts, ev_cost in self._events:
                freed += ev_cost
                if freed >= needed:
                    retry_after = max(0.0, self.window_seconds - (now - ts))
                    break
            return Decision(False, remaining, self.capacity, retry_after)


# ---------------------------------------------------------------------------
# Backward-compatible wrapper -- default is now ``counter``
# ---------------------------------------------------------------------------

class SlidingWindow:
    """
    Sliding window wrapper used by services.py and the CLI.

    Default variant is now ``counter`` (Cloudflare O(1)) -- the correct
    choice for a system built to handle millions of requests.
    Use ``variant="log"`` only for low-traffic exact-admission use cases.
    """

    def __init__(
        self,
        capacity: int,
        window_seconds: float,
        variant: Literal["counter", "log"] = "counter",
    ) -> None:
        self._variant = variant
        if variant == "log":
            self._impl: SlidingWindowLog | SlidingWindowCounter = SlidingWindowLog(
                capacity=capacity,
                window_seconds=window_seconds,
            )
        else:
            self._impl = SlidingWindowCounter(
                capacity=capacity,
                window_seconds=window_seconds,
            )

    def allow(self, cost: float = 1.0, now: float | None = None) -> Decision:
        if isinstance(self._impl, SlidingWindowCounter):
            return self._impl.allow(cost=cost, now=now)
        return self._impl.allow(cost=cost)

    @property
    def capacity(self) -> int:
        return self._impl.capacity

    @property
    def window_seconds(self) -> float:
        return self._impl.window_seconds
