"""
BuiltWith collector — Phase 3 stub (RFC-016 §5).

Looks up a domain's technology profile via BuiltWith's API. Stub: returns
``[]`` unless ``BUILTWITH_API_KEY`` is set. Phase 3 will fill in the
parser + entity emission.
"""

from __future__ import annotations

import os

from zettelforge.log import get_logger
from zettelforge.osint.ontology import canonicalize_domain
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.builtwith")

API_KEY_ENV = "BUILTWITH_API_KEY"


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Resolve a DomainName to BuiltWithTechnology entries. Stub: ``[]``."""
    if input_entity_type != "DomainName":
        return []
    domain = canonicalize_domain(input_value)
    if not domain:
        return []
    if not os.environ.get(API_KEY_ENV):
        _logger.debug("builtwith_collector_no_api_key", env=API_KEY_ENV)
        return []
    # Phase 3: real BuiltWith call goes here. For now: fail closed.
    return []


_METADATA = TransformMetadata(
    name="builtwith_collector",
    description="BuiltWith: enumerate detected technologies for a domain.",
    input_types=("DomainName",),
    output_types=(
        ("BuiltWithTechnology", "powered_by"),
        ("BuiltWithRelationship", "powered_by_relationship"),
    ),
    api_dependencies=("builtwith.com",),
    rate_limit=1.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
