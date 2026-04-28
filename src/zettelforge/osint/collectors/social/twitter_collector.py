"""
Twitter / X collector — Phase 4 stub (RFC-016 §5).

Fetches recent posts for a TwitterAffiliation handle. Stub: requires
``TWITTER_BEARER_TOKEN`` and returns ``[]`` without it. Phase 4 will
deliver the parser + Tweet emission.
"""

from __future__ import annotations

import os

from zettelforge.log import get_logger
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.twitter")

API_KEY_ENV = "TWITTER_BEARER_TOKEN"


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Fetch recent tweets for a TwitterAffiliation. Stub: returns ``[]``."""
    if input_entity_type != "TwitterAffiliation":
        return []
    if not os.environ.get(API_KEY_ENV):
        _logger.debug("twitter_collector_no_api_key", env=API_KEY_ENV)
        return []
    # Phase 4: real Twitter API call goes here. For now: fail closed.
    return []


_METADATA = TransformMetadata(
    name="twitter_collector",
    description="Twitter/X: fetch recent tweets for a handle.",
    input_types=("TwitterAffiliation",),
    output_types=(
        ("Tweet", "posted_by"),
        ("Hashtag", "contains_hashtag"),
    ),
    api_dependencies=("twitter-api",),
    rate_limit=1.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
