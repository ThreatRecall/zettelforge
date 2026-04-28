"""
Hashtag tracker — Phase 4 stub (RFC-016 §5).

Aggregates recent posts for a hashtag across Twitter/X (and, eventually,
other platforms). Stub: requires ``TWITTER_BEARER_TOKEN`` for the
Twitter/X half and returns ``[]`` without it.
"""

from __future__ import annotations

import os

from zettelforge.log import get_logger
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.hashtag_tracker")

API_KEY_ENV = "TWITTER_BEARER_TOKEN"


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Track recent posts for a Hashtag. Stub: returns ``[]``."""
    if input_entity_type != "Hashtag":
        return []
    if not os.environ.get(API_KEY_ENV):
        _logger.debug("hashtag_tracker_no_api_key", env=API_KEY_ENV)
        return []
    # Phase 4: real cross-platform tracker goes here. For now: fail closed.
    return []


_METADATA = TransformMetadata(
    name="hashtag_tracker",
    description="Hashtag tracker: aggregate recent posts for a hashtag.",
    input_types=("Hashtag",),
    output_types=(("Tweet", "contains_hashtag"),),
    api_dependencies=("twitter-api",),
    rate_limit=1.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
