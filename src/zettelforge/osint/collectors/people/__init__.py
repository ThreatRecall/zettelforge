"""
People & Communications collectors (RFC-016 Phase 2 stubs).

Importing this package imports each Phase 2 collector module so the
modules can self-register with ``TRANSFORM_REGISTRY`` at load time. The
collectors themselves are stubs that return ``[]`` until their upstream
APIs are wired up.
"""

from zettelforge.osint.collectors.people import (
    holehe_collector,
    hunter_collector,
    maigret_collector,
    namechk_collector,
)

__all__ = [
    "holehe_collector",
    "hunter_collector",
    "maigret_collector",
    "namechk_collector",
]
