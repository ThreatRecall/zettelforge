"""
Intelligent caching layer for ZettelForge
Complies with GOV-003 (Python standards) and GOV-012 (observability)
"""

import time
from typing import Any, Dict, Optional


class SmartCache:
    """
    LRU Cache with TTL and observability for embeddings and query results.
    """

    def __init__(self, maxsize: int = 10000, ttl_seconds: int = 3600):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._cache: Dict = {}
        self._hits = 0
        self._misses = 0
        self._last_cleanup = time.time()

    def get(self, key: str) -> Optional[Any]:
        """Get item from cache with TTL check."""
        self._cleanup_if_needed()

        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self.ttl_seconds:
                self._hits += 1
                return value
            else:
                del self._cache[key]
                self._misses += 1
                return None
        self._misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        """Set item in cache."""
        self._cleanup_if_needed()
        self._cache[key] = (value, time.time())

        # Simple LRU eviction if over limit
        if len(self._cache) > self.maxsize:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

    def _cleanup_if_needed(self):
        """Periodic cleanup of expired entries."""
        now = time.time()
        if now - self._last_cleanup > 300:  # every 5 minutes
            self._cleanup()
            self._last_cleanup = now

    def _cleanup(self):
        """Remove expired entries."""
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts > self.ttl_seconds]
        for k in expired:
            del self._cache[k]

    def get_stats(self) -> Dict:
        """Return cache performance metrics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        return {
            "size": len(self._cache),
            "maxsize": self.maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
            "ttl_seconds": self.ttl_seconds,
        }
