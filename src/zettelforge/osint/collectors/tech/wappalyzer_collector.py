"""
Wappalyzer collector — Phase 3 stub (RFC-016 §5).

Detects the tech stack of a website by inspecting its responses with the
``python-Wappalyzer`` library. Stub: returns ``[]`` when the library is
not importable. Phase 3 ships the live detection.
"""

from __future__ import annotations

from zettelforge.log import get_logger
from zettelforge.osint.ontology import canonicalize_domain, canonicalize_url
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.wappalyzer")


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Detect technologies on a Website / DomainName. Stub: ``[]``."""
    if input_entity_type == "DomainName":
        target = canonicalize_domain(input_value)
        if not target:
            return []
    elif input_entity_type == "Website":
        try:
            target = canonicalize_url(input_value)
        except ValueError:
            return []
    else:
        return []

    try:
        import Wappalyzer  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        _logger.debug("wappalyzer_collector_missing_library")
        return []
    # Phase 3: real Wappalyzer detection goes here. For now: fail closed.
    _logger.debug("wappalyzer_collector_stub", target=target)
    return []


_METADATA = TransformMetadata(
    name="wappalyzer_collector",
    description="Wappalyzer: detect frameworks, CMSes, and libraries on a site.",
    input_types=("DomainName", "Website"),
    output_types=(("BuiltWithTechnology", "powered_by"),),
    api_dependencies=("python-Wappalyzer",),
    rate_limit=2.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
