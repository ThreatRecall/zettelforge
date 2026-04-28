"""
Observability for ZettelForge
Implements GOV-012 (Observability & Logging Standards)
"""

import time
from functools import wraps
from typing import Callable, Dict

from zettelforge.log import get_logger

logger = get_logger("zettelforge.observability")


class Observability:
    """
    Observability wrapper for ZettelForge operations.
    Provides structured logging, metrics, and tracing.
    """

    def __init__(self):
        self.metrics = {
            "operations": 0,
            "errors": 0,
            "total_latency_ms": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    def log_operation(self, operation: str, duration_ms: float, success: bool = True, **kwargs):
        """Log operation with structured data."""
        self.metrics["operations"] += 1
        if not success:
            self.metrics["errors"] += 1
        self.metrics["total_latency_ms"] += duration_ms

        log_data = {
            "operation": operation,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            **kwargs,
        }

        if success:
            logger.info("operation_completed", **log_data)
        else:
            logger.error("operation_failed", **log_data)

    def record_cache_event(self, hit: bool):
        if hit:
            self.metrics["cache_hits"] += 1
        else:
            self.metrics["cache_misses"] += 1

    def get_metrics(self) -> Dict:
        total_ops = self.metrics["operations"]
        avg_latency = self.metrics["total_latency_ms"] / total_ops if total_ops > 0 else 0
        return {
            **self.metrics,
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate": round(self.metrics["errors"] / total_ops * 100, 2)
            if total_ops > 0
            else 0,
        }


def timed_operation(obs: Observability):
    """Decorator to automatically time and log operations."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                obs.log_operation(func.__name__, duration_ms, success=True, **kwargs)
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                obs.log_operation(func.__name__, duration_ms, success=False, error=str(e))
                raise

        return wrapper

    return decorator
