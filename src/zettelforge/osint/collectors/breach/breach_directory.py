"""
Breach Directory collector — Phase 4 stub (RFC-016 §5).

Looks up breach records via Breach Directory's API. Stub: requires
``BREACH_DIRECTORY_API_KEY`` and returns ``[]`` without it. Phase 4
ships the live lookup.
"""

from __future__ import annotations

import os

from zettelforge.log import get_logger
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.breach_directory")

API_KEY_ENV = "BREACH_DIRECTORY_API_KEY"


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Query Breach Directory for an EmailAddress. Stub: returns ``[]``."""
    if input_entity_type != "EmailAddress":
        return []
    if not os.environ.get(API_KEY_ENV):
        _logger.debug("breach_directory_no_api_key", env=API_KEY_ENV)
        return []
    # Phase 4: real Breach Directory call goes here. For now: fail closed.
    return []


_METADATA = TransformMetadata(
    name="breach_directory",
    description="Breach Directory: look up breach records for an email address.",
    input_types=("EmailAddress",),
    output_types=(),
    api_dependencies=("breachdirectory.org",),
    rate_limit=2.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
