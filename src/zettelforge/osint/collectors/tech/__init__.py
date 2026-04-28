"""
Technical-tier collectors (RFC-016 Phase 3 stubs).

Wappalyzer (tech stack detection) and BuiltWith (technology relationships).
The collectors register their metadata at import time but return ``[]``
until the Phase 3 integration ships.
"""

from zettelforge.osint.collectors.tech import (
    builtwith_collector,
    wappalyzer_collector,
)

__all__ = [
    "builtwith_collector",
    "wappalyzer_collector",
]
