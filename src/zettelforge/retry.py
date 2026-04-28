"""
Retry Logic & Resilience for ZettelForge
Implements resilient patterns per GOV-011 (Security & Reliability)
"""

import random
import time
from functools import wraps
from typing import Callable, TypeVar

from zettelforge.log import get_logger
from zettelforge.observability import Observability

logger = get_logger("zettelforge.retry")


T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(self, max_attempts: int = 5, base_delay: float = 0.5, max_delay: float = 30.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay


def with_retry(config: RetryConfig = None, observability: Observability = None):
    """
    Decorator that adds retry logic with exponential backoff and jitter.
    """
    if config is None:
        config = RetryConfig()
    if observability is None:
        observability = Observability()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    start = time.perf_counter()
                    result = func(*args, **kwargs)
                    duration_ms = (time.perf_counter() - start) * 1000

                    if attempt > 1:
                        observability.log_operation(
                            func.__name__, duration_ms, success=True, retry_attempt=attempt - 1
                        )
                    return result

                except Exception as e:
                    last_exception = e
                    delay = min(config.base_delay * (2 ** (attempt - 1)), config.max_delay)
                    jitter = random.uniform(0, 0.1 * delay)
                    sleep_time = delay + jitter

                    observability.log_operation(
                        func.__name__,
                        0,
                        success=False,
                        attempt=attempt,
                        max_attempts=config.max_attempts,
                        error=type(e).__name__,
                        retry_in=round(sleep_time, 2),
                    )

                    if attempt == config.max_attempts:
                        logger.error("all_retry_attempts_failed", func_name=func.__name__)
                        break

                    time.sleep(sleep_time)

            raise last_exception or RuntimeError("Retry logic failed")

        return wrapper

    return decorator


# Example usage:
# @with_retry()
# def risky_lancedb_operation():
#     ...
