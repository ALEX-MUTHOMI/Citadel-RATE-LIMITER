from limiter.dsa import ShopifyLeakyBucket, SlidingWindow, TokenBucket
from limiter.shopify.adapter import to_shopify_headers


def test_token_bucket_allows_then_denies():
    bucket = TokenBucket(capacity=2, refill_rate=0.0001)
    assert bucket.allow().allowed is True
    assert bucket.allow().allowed is True
    denied = bucket.allow()
    assert denied.allowed is False
    assert denied.retry_after > 0


def test_sliding_window_capacity():
    window = SlidingWindow(capacity=2, window_seconds=60)
    assert window.allow().allowed is True
    assert window.allow().allowed is True
    assert window.allow().allowed is False


def test_shopify_leaky_bucket_headers():
    limiter = ShopifyLeakyBucket(capacity=40, restore_rate=2)
    decision = limiter.allow()
    headers = to_shopify_headers(decision)
    assert "X-Shopify-Shop-Api-Call-Limit" in headers
    assert headers["allowed"] is True
