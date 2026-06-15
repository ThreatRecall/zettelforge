"""
Financial-tier collectors (RFC-016 Phase 4, AGE-120).

Blockchain wallet -> transaction enrichment via a block-explorer API. The
collector registers its metadata at import time and fails closed (returns
``[]``) without an explorer API key.
"""

from zettelforge.osint.collectors.financial import (
    wallet_collector,
)

__all__ = [
    "wallet_collector",
]
