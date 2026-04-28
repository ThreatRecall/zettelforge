"""
HaveIBeenPwned collector — Phase 4 stub (RFC-016 §5).

Looks up breach exposure for an email address via the HIBP API. Stub:
requires ``HIBP_API_KEY`` and returns ``[]`` without it. Phase 4 will
ship the live lookup and breach-record emission.
"""

from __future__ import annotations

import os

from zettelforge.log import get_logger
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.hibp")

API_KEY_ENV = "HIBP_API_KEY"


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Look up breaches associated with an EmailAddress. Stub: returns ``[]``."""
    if input_entity_type != "EmailAddress":
        return []
    if not os.environ.get(API_KEY_ENV):
        _logger.debug("hibp_collector_no_api_key", env=API_KEY_ENV)
        return []
    # Phase 4: real HIBP call goes here. For now: fail closed.
    return []


_METADATA = TransformMetadata(
    name="hibp_collector",
    description="HaveIBeenPwned: enumerate breach exposures for an email.",
    input_types=("EmailAddress",),
    output_types=(),
    api_dependencies=("haveibeenpwned.com",),
    rate_limit=2.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
