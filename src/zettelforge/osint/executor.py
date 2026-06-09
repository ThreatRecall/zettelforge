"""
OSINT collector executor and KG ingestion path (RFC-016 Phase 1.5).

This module turns registered collector functions into an end-to-end passive
OSINT enrichment API:

1. Resolve matching collectors from ``TRANSFORM_REGISTRY``.
2. Run them fail-closed.
3. Validate emitted ``CollectorTuple`` rows against the ontology.
4. Canonicalize/dedupe entities via ``entity_resolver``.
5. Persist nodes and edges through ``KnowledgeGraph.add_node`` / ``add_edge``.

Collectors remain synchronous and directly testable. The executor owns the
cross-cutting concerns that would otherwise be duplicated by every caller.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from zettelforge.knowledge_graph import KnowledgeGraph, get_knowledge_graph
from zettelforge.log import get_logger
from zettelforge.ontology import OntologyValidator
from zettelforge.osint.entity_resolver import add_resolved, canonicalise_value
from zettelforge.osint.ontology import merge_into_global_ontology
from zettelforge.osint.transform_registry import (
    CollectorTuple,
    TransformMetadata,
    TransformRegistry,
    get_transform_registry,
)

_logger = get_logger("zettelforge.osint.executor")

SUPPORTED_SEED_TYPES = ("DomainName", "IPv4Address", "IPv6Address", "ASNumber", "Netblock")


@dataclass(frozen=True)
class OSINTExecutionError:
    """Non-fatal executor error for a collector or tuple."""

    collector_name: str
    message: str
    tuple_index: int | None = None


@dataclass(frozen=True)
class PersistedOSINTTuple:
    """A validated collector tuple after KG persistence."""

    collector_name: str
    output_entity_type: str
    output_value: str
    output_node_id: str
    edge_id: str
    from_entity_type: str
    from_value: str
    to_entity_type: str
    to_value: str
    edge_type: str


@dataclass
class OSINTCollectionResult:
    """Structured return value from ``run_osint_collection``."""

    input_entity_type: str
    input_value: str
    canonical_input_value: str
    seed_node_id: str | None
    collectors_run: list[str] = field(default_factory=list)
    tuples_collected: int = 0
    persisted: list[PersistedOSINTTuple] = field(default_factory=list)
    errors: list[OSINTExecutionError] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str | None = None

    @property
    def persisted_count(self) -> int:
        return len(self.persisted)

    @property
    def error_count(self) -> int:
        return len(self.errors)


_ENDPOINT_PROP_KEYS: dict[str, tuple[str, ...]] = {
    "ASNumber": ("asn", "number"),
    "DomainName": ("domain", "value"),
    "IPv4Address": ("ip", "address", "value"),
    "IPv6Address": ("ip", "address", "value"),
    "MXRecord": ("mx", "value", "exchange"),
    "NSRecord": ("ns", "nsdname", "value"),
    "Netblock": ("cidr", "netblock", "prefix"),
    "Organization": ("organization", "org", "name"),
    "Port": ("port", "value"),
    "Website": ("url", "website", "value"),
}


def run_osint_collection(
    input_entity_type: str,
    input_value: str,
    *,
    kg: KnowledgeGraph | None = None,
    registry: TransformRegistry | None = None,
    validator: OntologyValidator | None = None,
    collector_names: Sequence[str] | None = None,
    persist: bool = True,
) -> OSINTCollectionResult:
    """Run registered OSINT collectors for one seed entity.

    Parameters
    ----------
    input_entity_type:
        Seed type. Phase 1.5 supports DomainName, IPv4Address, IPv6Address,
        ASNumber, and Netblock.
    input_value:
        Seed value. It is canonicalized before KG writes.
    kg:
        Optional ``KnowledgeGraph`` instance. Defaults to the global KG.
    registry:
        Optional collector registry. Defaults to ``TRANSFORM_REGISTRY``.
    validator:
        Optional ontology validator.
    collector_names:
        Optional allow-list of collector names to run for this seed.
    persist:
        When false, collectors and validation run but no KG writes occur.
    """
    merge_into_global_ontology()

    if input_entity_type not in SUPPORTED_SEED_TYPES:
        raise ValueError(
            f"unsupported OSINT seed type {input_entity_type!r}; "
            f"expected one of {', '.join(SUPPORTED_SEED_TYPES)}"
        )

    registry = registry or get_transform_registry()
    validator = validator or OntologyValidator()
    kg = kg or get_knowledge_graph()
    allowed_collectors = None if collector_names is None else set(collector_names)

    canonical_input_value = canonicalise_value(input_entity_type, input_value)
    seed_props = _entity_properties(input_entity_type, canonical_input_value)
    _validate_entity_or_raise(validator, input_entity_type, seed_props)

    seed_node_id: str | None = None
    if persist:
        seed_node_id, _ = add_resolved(kg, input_entity_type, canonical_input_value, seed_props)

    result = OSINTCollectionResult(
        input_entity_type=input_entity_type,
        input_value=input_value,
        canonical_input_value=canonical_input_value,
        seed_node_id=seed_node_id,
    )

    matches = registry.find_by_input(input_entity_type)
    if allowed_collectors is not None:
        matches = [(meta, fn) for meta, fn in matches if meta.name in allowed_collectors]

    for meta, fn in matches:
        result.collectors_run.append(meta.name)
        try:
            tuples = fn(input_entity_type, canonical_input_value)
        except Exception as exc:  # fail-closed; one bad collector cannot abort the run
            _logger.warning("osint_collector_failed", collector=meta.name, error=str(exc))
            result.errors.append(OSINTExecutionError(meta.name, str(exc)))
            continue

        result.tuples_collected += len(tuples)
        for index, tup in enumerate(tuples):
            try:
                _validate_tuple(meta, tup, validator)
                if persist:
                    persisted = _persist_tuple(
                        kg=kg,
                        validator=validator,
                        collector=meta,
                        tup=tup,
                        input_entity_type=input_entity_type,
                        canonical_input_value=canonical_input_value,
                    )
                    result.persisted.append(persisted)
            except ValueError as exc:
                result.errors.append(OSINTExecutionError(meta.name, str(exc), tuple_index=index))

    result.finished_at = datetime.now().isoformat()
    return result


def collect_osint(*args: Any, **kwargs: Any) -> OSINTCollectionResult:
    """Compatibility alias for agents that prefer verb-first naming."""
    return run_osint_collection(*args, **kwargs)


def _validate_tuple(
    collector: TransformMetadata,
    tup: CollectorTuple,
    validator: OntologyValidator,
) -> None:
    output_props = _entity_properties(tup.output_entity_type, tup.output_value, tup.output_props)
    _validate_entity_or_raise(validator, tup.output_entity_type, output_props)

    ok, errors = validator.validate_relation(
        tup.from_entity_type, tup.edge_type, tup.to_entity_type
    )
    if not ok:
        raise ValueError(
            f"{collector.name} emitted invalid relation "
            f"{tup.from_entity_type} -[{tup.edge_type}]-> {tup.to_entity_type}: "
            + "; ".join(errors)
        )


def _persist_tuple(
    *,
    kg: KnowledgeGraph,
    validator: OntologyValidator,
    collector: TransformMetadata,
    tup: CollectorTuple,
    input_entity_type: str,
    canonical_input_value: str,
) -> PersistedOSINTTuple:
    output_value = canonicalise_value(tup.output_entity_type, tup.output_value)
    output_props = _entity_properties(tup.output_entity_type, output_value, tup.output_props)

    from_value = _derive_endpoint_value(tup, "from", input_entity_type, canonical_input_value)
    to_value = _derive_endpoint_value(tup, "to", input_entity_type, canonical_input_value)

    from_props = _endpoint_properties(tup.from_entity_type, from_value, tup, input_entity_type)
    to_props = _endpoint_properties(tup.to_entity_type, to_value, tup, input_entity_type)
    _validate_entity_or_raise(validator, tup.from_entity_type, from_props)
    _validate_entity_or_raise(validator, tup.to_entity_type, to_props)

    output_node_id, _ = add_resolved(kg, tup.output_entity_type, output_value, output_props)
    add_resolved(kg, tup.from_entity_type, from_value, from_props)
    add_resolved(kg, tup.to_entity_type, to_value, to_props)

    edge_props = dict(tup.edge_props)
    edge_props.setdefault("collector", collector.name)
    edge_props.setdefault("source", collector.name)
    edge_props.setdefault("osint", True)
    edge_props.setdefault("edge_type", "osint")

    edge_id = kg.add_edge(
        tup.from_entity_type,
        from_value,
        tup.to_entity_type,
        to_value,
        tup.edge_type,
        edge_props,
    )

    return PersistedOSINTTuple(
        collector_name=collector.name,
        output_entity_type=tup.output_entity_type,
        output_value=output_value,
        output_node_id=output_node_id,
        edge_id=edge_id,
        from_entity_type=tup.from_entity_type,
        from_value=from_value,
        to_entity_type=tup.to_entity_type,
        to_value=to_value,
        edge_type=tup.edge_type,
    )


def _derive_endpoint_value(
    tup: CollectorTuple,
    side: str,
    input_entity_type: str,
    canonical_input_value: str,
) -> str:
    if side == "from":
        endpoint_type = tup.from_entity_type
        if endpoint_type == input_entity_type:
            return canonical_input_value
        if endpoint_type == tup.output_entity_type:
            return canonicalise_value(endpoint_type, tup.output_value)
    elif side == "to":
        endpoint_type = tup.to_entity_type
        if endpoint_type == tup.output_entity_type:
            return canonicalise_value(endpoint_type, tup.output_value)
        if endpoint_type == input_entity_type:
            return canonical_input_value
    else:
        raise ValueError(f"unknown endpoint side {side!r}")

    for key in _ENDPOINT_PROP_KEYS.get(endpoint_type, ("value",)):
        raw = tup.edge_props.get(key) or tup.output_props.get(key)
        if raw not in (None, ""):
            return canonicalise_value(endpoint_type, str(raw))

    raise ValueError(
        f"cannot derive {side} endpoint value for {endpoint_type} from collector tuple "
        f"{tup!r}; add an explicit edge property such as cidr/asn/value"
    )


def _endpoint_properties(
    entity_type: str,
    value: str,
    tup: CollectorTuple,
    input_entity_type: str,
) -> dict[str, Any]:
    if entity_type == tup.output_entity_type:
        return _entity_properties(entity_type, value, tup.output_props)
    return _entity_properties(entity_type, value)


def _entity_properties(
    entity_type: str,
    value: str,
    incoming: dict[str, Any] | None = None,
) -> dict[str, Any]:
    props = dict(incoming or {})
    canonical = canonicalise_value(entity_type, value)

    if entity_type in ("DomainName", "IPv4Address", "IPv6Address", "URL"):
        props.setdefault("value", canonical)
    elif entity_type == "ASNumber":
        props.setdefault("number", int(canonical))
    elif entity_type == "Netblock":
        props.setdefault("cidr", canonical)
    elif entity_type == "Organization":
        props.setdefault("name", canonical)
    elif entity_type == "NSRecord":
        props.setdefault("nsdname", canonical)
    elif entity_type == "MXRecord":
        if "priority" not in props or "exchange" not in props:
            priority, _, exchange = canonical.partition(" ")
            if priority and exchange:
                props.setdefault("priority", int(priority))
                props.setdefault("exchange", exchange)
    elif entity_type == "Port":
        if "number" not in props or "protocol" not in props:
            number, _, protocol = canonical.partition("/")
            if number and protocol:
                props.setdefault("number", int(number))
                props.setdefault("protocol", protocol)
    elif entity_type == "Website":
        props.setdefault("url", canonical)

    return props


def _validate_entity_or_raise(
    validator: OntologyValidator,
    entity_type: str,
    properties: dict[str, Any],
) -> None:
    ok, errors = validator.validate_entity(entity_type, properties)
    if not ok:
        raise ValueError(f"invalid {entity_type} properties: " + "; ".join(errors))


__all__ = [
    "SUPPORTED_SEED_TYPES",
    "OSINTCollectionResult",
    "OSINTExecutionError",
    "PersistedOSINTTuple",
    "collect_osint",
    "run_osint_collection",
]
