"""
Social-tier collectors (RFC-016 Phase 4 stubs).

Twitter/X recent-post fetching and hashtag activity tracking. The
collectors register their metadata at import time but return ``[]`` until
the Phase 4 integration ships.
"""

from zettelforge.osint.collectors.social import (
    hashtag_tracker,
    twitter_collector,
)

__all__ = [
    "hashtag_tracker",
    "twitter_collector",
]
