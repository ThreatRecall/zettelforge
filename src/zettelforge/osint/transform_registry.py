"""
OSINT transform/collector registry.

Holds metadata for every collector and lets callers look up collectors by
input entity type. Phase 1 collectors register themselves at import time via
the ``infrastructure`` subpackage's ``__init__.py``.

The registry is intentionally tiny: a dict keyed by collector name plus a
secondary index by input type. No threading guards — Phase 1 is single
process. Multi-tenant / concurrent execution is a Phase 4 concern (workflow
engine), at which point ``KnowledgeGraph._lock`` shows the pattern to follow.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from zettelforge.log import get_logger

_logger = get_logger("zettelforge.osint.registry")


class CollectorTuple(NamedTuple):
    """Single output row from a collector, matching RFC-016 §5.

    Fields kept positional so collectors can build tuples ergonomically while
    callers (and tests) get attribute access for clarity.
    """

    output_entity_type: str
    output_value: str
    edge_type: str
    from_entity_type: str
    to_entity_type: str
    output_props: dict[str, Any]
    edge_props: dict[str, Any]


CollectorFn = Callable[[str, str], list[CollectorTuple]]


@dataclass(frozen=True)
class TransformMetadata:
    """Static description of a collector. Frozen so registrations are immutable."""

    name: str
    description: str
    input_types: tuple[str, ...]
    # Each entry: (output_entity_type, edge_type) the collector can emit.
    output_types: tuple[tuple[str, str], ...]
    api_dependencies: tuple[str, ...] = field(default_factory=tuple)
    rate_limit: float | None = None  # calls per second; None = unbounded


class TransformRegistry:
    """In-memory registry. Idempotent re-registration."""

    def __init__(self) -> None:
        self._collectors: dict[str, tuple[TransformMetadata, CollectorFn]] = {}

    def register(self, metadata: TransformMetadata, fn: CollectorFn) -> None:
        """Register a collector. Re-registering the same name is a no-op.

        Idempotency matters for tests: pytest collects modules once but the
        registry's enclosing import may run multiple times across test files.
        """
        if metadata.name in self._collectors:
            existing_meta, _ = self._collectors[metadata.name]
            if existing_meta == metadata:
                return  # exact duplicate registration, nothing to do
            # Different metadata under the same name is a developer error,
            # not silent corruption. Log and replace so the latest wins.
            _logger.warning(
                "transform_registry_overwrite",
                name=metadata.name,
                old_description=existing_meta.description,
                new_description=metadata.description,
            )
        self._collectors[metadata.name] = (metadata, fn)

    def find_by_input(self, input_type: str) -> list[tuple[TransformMetadata, CollectorFn]]:
        """Return all collectors that accept ``input_type``."""
        return [
            (meta, fn) for meta, fn in self._collectors.values() if input_type in meta.input_types
        ]

    def get(self, name: str) -> tuple[TransformMetadata, CollectorFn]:
        """Return the (metadata, fn) tuple for a named collector.

        Raises KeyError if the collector is not registered.
        """
        return self._collectors[name]

    def list_all(self) -> list[TransformMetadata]:
        """All registered collector metadata, in registration order."""
        return [meta for meta, _ in self._collectors.values()]

    def clear(self) -> None:
        """Drop all registrations. Test-only — production code never calls this."""
        self._collectors.clear()


# Module-level singleton. Collectors call ``TRANSFORM_REGISTRY.register(...)``
# at import time. Tests that need isolation can swap the singleton via
# monkeypatch on this module attribute.
TRANSFORM_REGISTRY = TransformRegistry()


def get_transform_registry() -> TransformRegistry:
    """Accessor for the module-level singleton."""
    return TRANSFORM_REGISTRY


__all__ = [
    "TRANSFORM_REGISTRY",
    "CollectorFn",
    "CollectorTuple",
    "TransformMetadata",
    "TransformRegistry",
    "get_transform_registry",
]
