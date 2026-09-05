from __future__ import annotations

import argparse

from limiter.dsa import ShopifyLeakyBucket, SlidingWindow, TokenBucket


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Citadel DSA rate-limit simulator")
    parser.add_argument(
        "--algorithm",
        choices=["token_bucket", "sliding_window", "shopify_leaky_bucket"],
        default="token_bucket",
    )
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--capacity", type=float, default=10)
    parser.add_argument("--rate", type=float, default=2.0)
    parser.add_argument("--window", type=float, default=10.0)
    args = parser.parse_args(argv)

    if args.algorithm == "sliding_window":
        limiter = SlidingWindow(capacity=int(args.capacity), window_seconds=args.window)
    elif args.algorithm == "shopify_leaky_bucket":
        limiter = ShopifyLeakyBucket(capacity=args.capacity, restore_rate=args.rate)
    else:
        limiter = TokenBucket(capacity=args.capacity, refill_rate=args.rate)

    allowed = 0
    for index in range(args.requests):
        decision = limiter.allow(1)
        allowed += int(decision.allowed)
        state = "ALLOW" if decision.allowed else "DENY"
        print(f"{index + 1:03d} {state} remaining={decision.remaining:.2f}")
    print(f"allowed={allowed} denied={args.requests - allowed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
