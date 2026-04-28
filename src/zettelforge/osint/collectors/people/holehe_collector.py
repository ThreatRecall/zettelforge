"""
Holehe collector — Phase 2 stub (RFC-016 §5).

Enumerates the social-media accounts associated with an email address
using the ``holehe`` library. Stub: returns ``[]`` when ``holehe`` is not
importable. Phase 2 ships the live enumeration.
"""

from __future__ import annotations

from zettelforge.log import get_logger
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.holehe")


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Enumerate accounts tied to an EmailAddress via holehe. Stub: ``[]``."""
    if input_entity_type != "EmailAddress":
        return []
    try:
        import holehe  # noqa: F401  — Phase 2 will use this
    except ImportError:
        _logger.debug("holehe_collector_missing_holehe")
        return []
    # Phase 2: real holehe enumeration goes here. For now: fail closed.
    return []


_METADATA = TransformMetadata(
    name="holehe_collector",
    description="Holehe: enumerate social-media accounts tied to an email address.",
    input_types=("EmailAddress",),
    output_types=(
        ("Alias", "has_handle"),
        ("NamechkResult", "verified_on"),
    ),
    api_dependencies=("holehe",),
    rate_limit=2.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
