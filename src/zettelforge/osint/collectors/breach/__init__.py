"""
Breach-data collectors (RFC-016 Phase 4 stubs).

HaveIBeenPwned (k-anon password / breach lookup) and Breach Directory
collectors. Both register their metadata at import time but return ``[]``
until their integrations land.
"""

from zettelforge.osint.collectors.breach import (
    breach_directory,
    hibp_collector,
)

__all__ = [
    "breach_directory",
    "hibp_collector",
]
