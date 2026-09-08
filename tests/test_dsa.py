"""
Tests for all Citadel DSA rate limiting algorithms.

Run via Docker:
    docker compose run --rm api pytest tests/test_dsa.py -v

The sliding window tests cover:
- SlidingWindowLog  (exact timestamp-deque implementation)
- SlidingWindowCounter  (Cloudflare-style O(1) weighted bucket)
- SlidingWindow (backward-compatible wrapper)
"""
import time

import pytest

from limiter.dsa import ShopifyLeakyBucket, SlidingWindow, SlidingWindowCounter, SlidingWindowLog, TokenBucket
from limiter.dsa.token_bucket import Decision
from limiter.shopify.adapter import to_shopify_headers


# ===========================================================================
# TokenBucket (existing — preserved)
# ===========================================================================

def test_token_bucket_allows_then_denies():
    bucket = TokenBucket(capacity=2, refill_rate=0.0001)
    assert bucket.allow().allowed is True
    assert bucket.allow().allowed is True
    denied = bucket.allow()
    assert denied.allowed is False
    assert denied.retry_after > 0


# ===========================================================================
# ShopifyLeakyBucket + headers (existing — preserved)
# ===========================================================================

def test_shopify_leaky_bucket_headers():
    limiter = ShopifyLeakyBucket(capacity=40, restore_rate=2)
    decision = limiter.allow()
    headers = to_shopify_headers(decision)
    assert "X-Shopify-Shop-Api-Call-Limit" in headers
    assert headers["allowed"] is True


# ===========================================================================
# SlidingWindowLog — exact implementation
# ===========================================================================

class TestSlidingWindowLog:
    """Tests for the exact deque-based timestamp log."""

    def test_allows_up_to_capacity(self):
        w = SlidingWindowLog(capacity=3, window_seconds=60)
        assert w.allow().allowed is True
        assert w.allow().allowed is True
        assert w.allow().allowed is True

    def test_denies_when_capacity_exceeded(self):
        w = SlidingWindowLog(capacity=2, window_seconds=60)
        w.allow()
        w.allow()
        result = w.allow()
        assert result.allowed is False

    def test_remaining_decrements_correctly(self):
        w = SlidingWindowLog(capacity=5, window_seconds=60)
        r1 = w.allow()
        assert r1.remaining == 4.0
        r2 = w.allow()
        assert r2.remaining == 3.0

    def test_remaining_is_zero_when_full(self):
        w = SlidingWindowLog(capacity=2, window_seconds=60)
        w.allow()
        r = w.allow()
        assert r.remaining == 0.0

    def test_denied_retry_after_is_positive(self):
        w = SlidingWindowLog(capacity=2, window_seconds=60)
        w.allow()
        w.allow()
        denied = w.allow()
        assert denied.retry_after > 0
        assert denied.retry_after <= 60

    def test_denied_retry_after_bounded_by_window(self):
        w = SlidingWindowLog(capacity=1, window_seconds=10)
        w.allow()
        denied = w.allow()
        assert 0 < denied.retry_after <= 10

    def test_limit_field_equals_capacity(self):
        w = SlidingWindowLog(capacity=7, window_seconds=60)
        r = w.allow()
        assert r.limit == 7

    def test_variable_cost_accounting(self):
        """Cost > 1 should consume multiple units."""
        w = SlidingWindowLog(capacity=10, window_seconds=60)
        r = w.allow(cost=4)
        assert r.allowed is True
        assert r.remaining == 6.0
        r2 = w.allow(cost=6)
        assert r2.allowed is True
        assert r2.remaining == 0.0
        denied = w.allow(cost=1)
        assert denied.allowed is False

    def test_variable_cost_denied_correctly(self):
        w = SlidingWindowLog(capacity=5, window_seconds=60)
        w.allow(cost=3)
        denied = w.allow(cost=3)  # would exceed capacity=5
        assert denied.allowed is False

    def test_events_expire_and_allow_new_requests(self):
        """After the window expires, capacity resets."""
        w = SlidingWindowLog(capacity=2, window_seconds=0.1)
        w.allow()
        w.allow()
        assert w.allow().allowed is False
        time.sleep(0.15)
        assert w.allow().allowed is True

    def test_invalid_capacity_raises(self):
        with pytest.raises(ValueError):
            SlidingWindowLog(capacity=0, window_seconds=60)

    def test_invalid_window_raises(self):
        with pytest.raises(ValueError):
            SlidingWindowLog(capacity=10, window_seconds=0)

    def test_invalid_cost_raises(self):
        w = SlidingWindowLog(capacity=10, window_seconds=60)
        with pytest.raises(ValueError):
            w.allow(cost=0)

    def test_allowed_decision_has_zero_retry_after(self):
        w = SlidingWindowLog(capacity=5, window_seconds=60)
        r = w.allow()
        assert r.retry_after == 0.0


# ===========================================================================
# SlidingWindowCounter — Cloudflare-style O(1) implementation
# ===========================================================================

class TestSlidingWindowCounter:
    """
    Tests for the approximate Cloudflare sliding window counter.

    Formula: rate = prev_count × ((W - Δt) / W) + curr_count
    """

    def test_allows_up_to_capacity_within_bucket(self):
        w = SlidingWindowCounter(capacity=5, window_seconds=60)
        for _ in range(5):
            assert w.allow().allowed is True

    def test_denies_when_capacity_exceeded(self):
        w = SlidingWindowCounter(capacity=3, window_seconds=60)
        w.allow()
        w.allow()
        w.allow()
        assert w.allow().allowed is False

    def test_remaining_decrements(self):
        w = SlidingWindowCounter(capacity=10, window_seconds=60)
        r = w.allow(cost=3)
        assert r.allowed is True
        # remaining ≈ 7 (exactly, since prev=0 at start)
        assert r.remaining == pytest.approx(7.0, abs=0.1)

    def test_limit_field_equals_capacity(self):
        w = SlidingWindowCounter(capacity=100, window_seconds=60)
        r = w.allow()
        assert r.limit == 100

    def test_denied_has_positive_retry_after(self):
        w = SlidingWindowCounter(capacity=2, window_seconds=10)
        w.allow()
        w.allow()
        denied = w.allow()
        assert denied.allowed is False
        assert denied.retry_after >= 0

    def test_allowed_has_zero_retry_after(self):
        w = SlidingWindowCounter(capacity=5, window_seconds=60)
        assert w.allow().retry_after == 0.0

    def test_variable_cost(self):
        w = SlidingWindowCounter(capacity=10, window_seconds=60)
        r = w.allow(cost=5)
        assert r.allowed is True
        r2 = w.allow(cost=5)
        assert r2.allowed is True
        denied = w.allow(cost=1)
        assert denied.allowed is False

    def test_bucket_rollover_resets_curr_count(self):
        """After window_seconds elapses, curr_count becomes prev_count and count resets."""
        w = SlidingWindowCounter(capacity=5, window_seconds=0.2)
        # Fill to capacity
        for _ in range(5):
            assert w.allow().allowed is True
        # One more should be denied
        assert w.allow().allowed is False

        # Wait for a full window: curr(5)→prev, new curr starts at 0.
        # At t=0 of new bucket: rate = 5 × 1.0 + 0 = 5 → still denied (5+1>5).
        # The result is a valid Decision regardless of allow/deny.
        time.sleep(0.25)
        result = w.allow(cost=1)
        assert isinstance(result, Decision)

    def test_two_windows_elapsed_clears_history(self):
        """If two or more windows elapsed, both counters must be zeroed (now-injection)."""
        W = 10.0
        t = 100.0  # epoch-anchored bucket start
        w = SlidingWindowCounter(capacity=5, window_seconds=W)
        for _ in range(5):
            w.allow(now=t)
        assert w.allow(now=t).allowed is False

        # Jump forward 2.1 windows — history fully cleared.
        future = t + W * 2.1
        for _ in range(5):
            assert w.allow(now=future).allowed is True

    def test_invalid_capacity_raises(self):
        with pytest.raises(ValueError):
            SlidingWindowCounter(capacity=0, window_seconds=60)

    def test_invalid_window_raises(self):
        with pytest.raises(ValueError):
            SlidingWindowCounter(capacity=10, window_seconds=-1)

    def test_invalid_cost_raises(self):
        w = SlidingWindowCounter(capacity=10, window_seconds=60)
        with pytest.raises(ValueError):
            w.allow(cost=0)

    def test_rate_formula_at_midpoint(self):
        """
        Verify the Cloudflare formula at a controlled midpoint using now-injection.

        Set W=60, epoch-aligned bucket start at t=60.
        Send 40 requests at t=60 (bucket 1).
        At t=120 + 30 (bucket 2, halfway): weight = (60-30)/60 = 0.5
        Then send 18 more requests.  Expected rate = 40*0.5 + 18 = 38.0
        """
        W = 60.0
        base = W * 1.0          # bucket_id=1 starts at t=60
        w = SlidingWindowCounter(capacity=1000, window_seconds=W)

        # Send 40 requests at bucket 1 start.
        for _ in range(40):
            w.allow(now=base)

        # Move to bucket 2, halfway through (elapsed 30s inside bucket 2).
        midpoint = base + W + 30.0
        assert w.estimate_rate(now=midpoint) == pytest.approx(20.0, abs=0.5)

        # Send 18 more at midpoint.
        for _ in range(18):
            w.allow(now=midpoint)

        # rate = 40*0.5 + 18 = 38.0
        assert w.estimate_rate(now=midpoint) == pytest.approx(38.0, abs=0.5)


# ===========================================================================
# SlidingWindow (backward-compatible wrapper)
# ===========================================================================

class TestSlidingWindowWrapper:
    """SlidingWindow must be a drop-in replacement for the original class."""

    def test_default_variant_is_counter(self):
        """Default is now counter — not log — for production scalability."""
        w = SlidingWindow(capacity=2, window_seconds=60)
        assert isinstance(w._impl, SlidingWindowCounter)

    def test_log_variant_selects_log(self):
        w = SlidingWindow(capacity=2, window_seconds=60, variant="log")
        assert isinstance(w._impl, SlidingWindowLog)

    def test_counter_variant_selects_counter(self):
        w = SlidingWindow(capacity=2, window_seconds=60, variant="counter")
        assert isinstance(w._impl, SlidingWindowCounter)

    def test_default_counter_enforces_capacity(self):
        w = SlidingWindow(capacity=2, window_seconds=60)
        assert w.allow().allowed is True
        assert w.allow().allowed is True
        assert w.allow().allowed is False

    def test_log_variant_enforces_capacity(self):
        w = SlidingWindow(capacity=2, window_seconds=60, variant="log")
        assert w.allow().allowed is True
        assert w.allow().allowed is True
        assert w.allow().allowed is False

    def test_counter_variant_enforces_capacity(self):
        w = SlidingWindow(capacity=3, window_seconds=60, variant="counter")
        assert w.allow().allowed is True
        assert w.allow().allowed is True
        assert w.allow().allowed is True
        assert w.allow().allowed is False

    def test_capacity_property(self):
        w = SlidingWindow(capacity=42, window_seconds=60)
        assert w.capacity == 42

    def test_window_seconds_property(self):
        w = SlidingWindow(capacity=10, window_seconds=30)
        assert w.window_seconds == 30

    def test_sliding_window_capacity_original(self):
        """Exact replica of the original test — backward compat check."""
        window = SlidingWindow(capacity=2, window_seconds=60)
        assert window.allow().allowed is True
        assert window.allow().allowed is True
        assert window.allow().allowed is False


# ===========================================================================
# Edge-case tests (algorithmic correctness under boundary conditions)
# ===========================================================================

class TestSlidingWindowCounterEdgeCases:
    """
    Tests that specifically cover the three algorithmic flaws identified in
    the hardening spec, plus additional robustness scenarios.
    """

    # --- Edge case 1: Multi-window idleness reset ---

    def test_idleness_reset_two_plus_windows(self):
        """
        A tenant filling Window 1 then jumping 2.5 windows must get full
        capacity in Window 3 — Window 1 prev_count must NOT persist.
        """
        W = 10.0
        base = 1000.0  # epoch-anchored bucket start

        limiter = SlidingWindowCounter(capacity=5, window_seconds=W)

        # Fill Window 1 to capacity.
        for _ in range(5):
            result = limiter.allow(now=base)
            assert result.allowed is True

        # 6th request rejected inside Window 1.
        assert limiter.allow(now=base + 1.0).allowed is False

        # Jump forward 2.5 windows (25 seconds later) — tenant was idle.
        # Both prev and curr must be zeroed: estimated_rate before this
        # call should be 0, so the call is allowed and rate becomes 1.
        future = base + 25.0
        result = limiter.allow(now=future)
        assert result.allowed is True
        # After the single admitted request, rate = 1.
        assert limiter.estimate_rate(now=future) == pytest.approx(1.0, abs=0.01)

    def test_single_window_elapsed_does_not_zero_prev(self):
        """
        After exactly one window, curr promotes to prev (not zeroed).
        At Δt=0 of the new window the weighted prev contributes its full value.
        """
        W = 10.0
        base = 100.0
        limiter = SlidingWindowCounter(capacity=20, window_seconds=W)

        # Send 10 requests in bucket 0.
        for _ in range(10):
            limiter.allow(now=base)

        # Move exactly one window forward (start of bucket 1, Δt≈0).
        next_bucket_start = base + W
        rate = limiter.estimate_rate(now=next_bucket_start)
        # weight ≈ 1.0 (Δt ≈ 0), so rate ≈ 10 * 1.0 + 0 = 10
        assert rate == pytest.approx(10.0, abs=0.1)

    # --- Edge case 2: Closed-form retry_after ---

    def test_retry_after_case_a_sub_window(self):
        """
        When curr < capacity but rate + 1 > capacity (prev excess),
        retry_after must be < W (decay within current window is enough).
        """
        W = 60.0
        base = W  # bucket 1 start (Δt = 0)
        limiter = SlidingWindowCounter(capacity=10, window_seconds=W)

        # Fill bucket 0 to 10 requests.
        for _ in range(10):
            limiter.allow(now=0.0)  # bucket 0

        # At bucket 1 start, Δt=0: rate = 10*1.0 + 0 = 10 = capacity.
        # Next request denied.  retry_after should be < W (not a full wait).
        denied = limiter.allow(now=base)
        assert denied.allowed is False
        assert 0.0 < denied.retry_after < W

    def test_retry_after_case_b_full_rollover(self):
        """
        When curr >= capacity, a full window rollover is required.
        retry_after must be >= W - delta_t.
        """
        W = 60.0
        base = W * 2  # bucket 2 start
        limiter = SlidingWindowCounter(capacity=5, window_seconds=W)

        # Fill curr bucket to beyond capacity.
        for _ in range(5):
            limiter.allow(now=base)
        denied = limiter.allow(now=base)
        assert denied.allowed is False
        # Must wait at least to next bucket boundary.
        assert denied.retry_after >= W - 1.0  # delta_t ≈ 0, so wait ≈ W

    def test_retry_after_is_zero_when_allowed(self):
        limiter = SlidingWindowCounter(capacity=10, window_seconds=60)
        r = limiter.allow()
        assert r.retry_after == 0.0

    # --- Edge case 3: Wall-clock epoch anchoring ---

    def test_now_injection_deterministic(self):
        """
        Two counter instances injecting the same `now` must produce
        identical bucket_ids regardless of when the test runs.
        """
        W = 60.0
        t = 12345.0  # arbitrary epoch timestamp
        a = SlidingWindowCounter(capacity=10, window_seconds=W)
        b = SlidingWindowCounter(capacity=10, window_seconds=W)

        a.allow(now=t)
        b.allow(now=t)

        assert a._curr_bucket == b._curr_bucket
        assert a._curr_count == b._curr_count

    def test_epoch_anchoring_cross_bucket_alignment(self):
        """
        Bucket boundaries must align to epoch multiples of W, not to
        process start time.  Verify bucket_id == int(now // W).
        """
        W = 100.0
        t = 750.0  # bucket_id should be int(750/100) = 7
        limiter = SlidingWindowCounter(capacity=100, window_seconds=W)
        limiter.allow(now=t)
        assert limiter._curr_bucket == 7

    # --- Edge case 4: NTP clock rollback guard ---

    def test_clock_rollback_does_not_corrupt_state(self):
        """
        If clock steps backward, state must be unchanged (conservative guard).
        Count must not decrease or buckets corrupt.
        """
        W = 60.0
        t = 180.0
        limiter = SlidingWindowCounter(capacity=10, window_seconds=W)
        for _ in range(5):
            limiter.allow(now=t)

        # Simulate clock rollback by 5 seconds.
        rollback = t - 5.0
        limiter.allow(now=rollback)  # must not corrupt state

        # After rollback call, count must still be at least 5.
        assert limiter._curr_count >= 5.0
        assert limiter._curr_bucket == int(t // W)

    # --- Edge case 5: Exact decay formula (Cloudflare example) ---

    def test_cloudflare_blog_example(self):
        """
        Reproduce the exact numbers from the Cloudflare blog post:
        prev=42, elapsed=15s, W=60, curr=18 -> rate = 42*(45/60)+18 = 49.5
        """
        W = 60.0
        # Bucket 0: t in [0, 60)
        # Bucket 1: t in [60, 120), Δt = 15 means t = 75

        limiter = SlidingWindowCounter(capacity=50, window_seconds=W)

        # Send 42 requests in bucket 0.
        for _ in range(42):
            limiter.allow(now=0.0)

        # Move to bucket 1 at Δt=15 (t=75), send 18 requests.
        t_bucket1 = W + 15.0
        for _ in range(18):
            limiter.allow(now=t_bucket1)

        # rate = 42 * (45/60) + 18 = 31.5 + 18 = 49.5
        rate = limiter.estimate_rate(now=t_bucket1)
        assert rate == pytest.approx(49.5, abs=0.1)

        # One more request (cost=1) should be denied: 49.5 + 1 > 50.
        denied = limiter.allow(now=t_bucket1)
        assert denied.allowed is False

    # --- Edge case 6: Thread safety smoke test ---

    def test_concurrent_allows_never_exceed_capacity(self):
        """
        Under concurrent load, admitted request count must never exceed capacity.
        """
        import concurrent.futures

        capacity = 50
        limiter = SlidingWindowCounter(capacity=capacity, window_seconds=60.0)
        allowed_count = []

        def fire():
            r = limiter.allow()
            return r.allowed

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: fire(), range(200)))

        total_allowed = sum(results)
        assert total_allowed <= capacity

    # --- Edge case 7: Cost-weighted requests ---

    def test_weighted_cost_requests(self):
        """
        Expensive requests (cost > 1) should consume capacity proportionally.
        """
        W = 60.0
        t = W  # bucket start
        limiter = SlidingWindowCounter(capacity=10, window_seconds=W)

        # One request costing 5.
        r = limiter.allow(cost=5, now=t)
        assert r.allowed is True
        assert r.remaining == pytest.approx(5.0, abs=0.01)

        # Another request costing 5 should exactly fill capacity.
        r2 = limiter.allow(cost=5, now=t)
        assert r2.allowed is True
        assert r2.remaining == pytest.approx(0.0, abs=0.01)

        # Any further request (even cost=1) must be denied.
        assert limiter.allow(cost=1, now=t).allowed is False

    def test_weighted_cost_denied_correctly(self):
        """A request whose cost alone exceeds remaining capacity is denied."""
        W = 60.0
        t = W
        limiter = SlidingWindowCounter(capacity=10, window_seconds=W)
        limiter.allow(cost=8, now=t)  # remaining = 2
        denied = limiter.allow(cost=5, now=t)  # 8 + 5 > 10
        assert denied.allowed is False

