"""Rate limiting for API calls using token bucket algorithm."""

import time
from collections import deque
from collections.abc import Callable
from functools import wraps
from threading import Lock
from typing import Any, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])


class RateLimiter:
    """
    Token bucket rate limiter for controlling API call frequency.

    This class implements a thread-safe rate limiter that can be used as a decorator
    to limit the rate of function calls.

    Example:
        >>> @RateLimiter(max_calls=10, period=60)
        ... def api_call():
        ...     return "response"
    """

    def __init__(self, max_calls: int, period: int = 60):
        """
        Initialize the rate limiter.

        Args:
            max_calls: Maximum number of calls allowed per period.
            period: Time period in seconds. Defaults to 60.
        """
        self.max_calls = max_calls
        self.period = period
        self.calls: deque[float] = deque()
        self.lock = Lock()

    def __call__(self, func: F) -> F:
        """
        Decorate a function with rate limiting.

        Args:
            func: The function to rate limit.

        Returns:
            The wrapped function with rate limiting applied.
        """

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with self.lock:
                now = time.time()

                # Remove calls outside the current window
                while self.calls and self.calls[0] < now - self.period:
                    self.calls.popleft()

                # Wait if rate limit exceeded
                if len(self.calls) >= self.max_calls:
                    sleep_time = self.period - (now - self.calls[0])
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                        now = time.time()

                self.calls.append(now)

            return func(*args, **kwargs)

        return cast(F, wrapper)

    def reset(self) -> None:
        """Reset the rate limiter state. Useful for testing."""
        with self.lock:
            self.calls.clear()
