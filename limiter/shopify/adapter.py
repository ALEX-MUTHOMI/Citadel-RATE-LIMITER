from limiter.dsa.token_bucket import Decision


def to_shopify_headers(decision: Decision) -> dict:
    used = int(decision.limit - decision.remaining)
    limit = int(decision.limit)
    return {
        "X-Shopify-Shop-Api-Call-Limit": f"{used}/{limit}",
        "allowed": decision.allowed,
        "remaining": decision.remaining,
        "restore_hint_seconds": decision.retry_after,
    }
