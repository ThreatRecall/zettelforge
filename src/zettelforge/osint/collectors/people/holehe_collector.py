"""
Holehe collector — DISABLED for license compliance (AGE-118 / AGE-119).

``holehe`` (megadose) is GPL-3.0. Copying or importing it into MIT-licensed
ZettelForge would force a copyleft relicense, so the AGE-118 supply-chain
review marked it a hard exclusion (it is also abandoned, last release 2021).

This collector is kept as a permanent no-op so the registry shape stays
stable and so no future change re-adds a GPL import here. It NEVER imports
``holehe`` and always returns ``[]``. Email -> account enumeration must be
reimplemented from scratch on a permissive basis (e.g. maigret/sherlock on a
derived username, or the native HIBP REST breach path), not via holehe.
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
    """Disabled per AGE-118 (holehe is GPL-3.0). Always returns ``[]``."""
    if input_entity_type == "EmailAddress":
        _logger.debug("holehe_collector_disabled_gpl", reason="AGE-118 GPL exclusion")
    return []


_METADATA = TransformMetadata(
    name="holehe_collector",
    description="DISABLED (GPL-3.0 exclusion, AGE-118): holehe is not used.",
    input_types=("EmailAddress",),
    output_types=(),
    api_dependencies=(),
    rate_limit=None,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
