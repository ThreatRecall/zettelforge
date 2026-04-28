"""
Namechk collector — Phase 2 stub (RFC-016 §5).

Checks whether a username is taken on common social-media platforms.
Stub: returns ``[]`` until the Phase 2 implementation lands.

Note: namechk.com does not expose an official public API. A Phase 2
implementation should use a headless browser or the unofficial JSON
endpoints with rate limiting and retry budgets. This stub returns no data.
"""

from __future__ import annotations

from zettelforge.log import get_logger
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.namechk")


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Check username availability via namechk. Stub: returns ``[]``."""
    if input_entity_type != "Alias":
        return []
    _logger.debug("namechk_collector_stub", username=input_value)
    return []


_METADATA = TransformMetadata(
    name="namechk_collector",
    description="Namechk: check username availability across common platforms.",
    input_types=("Alias",),
    output_types=(("NamechkResult", "verified_on"),),
    api_dependencies=("namechk.com",),
    rate_limit=2.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
