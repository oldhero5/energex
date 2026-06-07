"""Characterization tests for the (currently un-wired) RateLimiter utility."""

import time

from energex.rate_limiter import RateLimiter


def test_allows_calls_up_to_limit_without_blocking():
    limiter = RateLimiter(max_calls=3, period=2)

    @limiter
    def f() -> float:
        return time.monotonic()

    start = time.monotonic()
    results = [f() for _ in range(3)]

    assert len(results) == 3
    assert time.monotonic() - start < 0.5


def test_blocks_once_limit_exceeded_within_period():
    limiter = RateLimiter(max_calls=2, period=1)

    @limiter
    def f() -> None:
        return None

    start = time.monotonic()
    for _ in range(3):
        f()

    # The third call must wait for the 1s window to free a slot.
    assert time.monotonic() - start >= 0.9


def test_reset_clears_recorded_calls():
    limiter = RateLimiter(max_calls=1, period=10)

    @limiter
    def f() -> None:
        return None

    f()
    limiter.reset()

    start = time.monotonic()
    f()  # Without reset this would block for ~10s.
    assert time.monotonic() - start < 0.5
