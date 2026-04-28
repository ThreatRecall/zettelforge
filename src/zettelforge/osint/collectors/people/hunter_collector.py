"""
Hunter.io collector — Phase 2 stub (RFC-016 §5).

Looks up a person record from an email address via Hunter.io. Stub: the
upstream call is gated behind ``HUNTER_API_KEY``; without the key the
collector returns ``[]``. Hardened parsing and rate-limit handling land
with Phase 2.
"""

from __future__ import annotations

import os

from zettelforge.log import get_logger
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.hunter")

API_KEY_ENV = "HUNTER_API_KEY"


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Resolve an EmailAddress to a Person via Hunter.io. Stub: returns ``[]``.

    Returns ``[]`` unless ``HUNTER_API_KEY`` is set AND the upstream call
    succeeds. Phase 2 will fill in the parser + entity emission.
    """
    if input_entity_type != "EmailAddress":
        return []
    if not os.environ.get(API_KEY_ENV):
        _logger.debug("hunter_collector_no_api_key", env=API_KEY_ENV)
        return []
    # Phase 2: real Hunter.io call goes here. For now: fail closed.
    return []


_METADATA = TransformMetadata(
    name="hunter_collector",
    description="Hunter.io: resolve an email address to a person and organization.",
    input_types=("EmailAddress",),
    output_types=(
        ("Person", "has_handle"),
        ("Organization", "affiliated_with"),
    ),
    api_dependencies=("hunter.io",),
    rate_limit=1.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
