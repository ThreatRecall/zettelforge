"""
OSINT Entity Resolver — canonical key normalisation and alias index.

Provides merge-when-duplicate semantics for the OSINT layer:
- Canonical key: (entity_type, normalised_value)
- Alias index: alternate representations → canonical node ID
- Merge strategy: LWW for properties, accumulate for edges
"""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zettelforge.knowledge_graph import KnowledgeGraph


def canonicalise_ipv4(value: str) -> str:
    """Strip leading zeros; return dotted-quad string."""
    return str(ipaddress.IPv4Address(value))


def canonicalise_domain(value: str) -> str:
    """Lowercase, strip trailing dot."""
    return value.lower().rstrip(".")


def canonicalise_phone(value: str) -> str:
    """Return E.164 format (digits only, leading +)."""
    digits = re.sub(r"\D", "", value)
    if not digits:
        return value
    if len(digits) == 10:
        digits = "1" + digits
    return f"+{digits}"


def canonicalise_asn(value: str) -> str:
    """Return 'AS12345' from various ASN representations."""
    num = re.sub(r"\D", "", value)
    return f"AS{num}"


def canonicalise_netblock(value: str) -> str:
    """Return the CIDR string as-is (IPv6/IPv4)."""
    return value.strip()


# Global alias index: canonical_key → node_id
_ALIAS_INDEX: dict[str, str] = {}
# Reverse: alternate representation → canonical key
_ALIAS_REVERSE: dict[str, str] = {}


def resolve(entity_type: str, value: str) -> str | None:
    """Return the canonical key for an entity if already indexed, else None."""
    canonical = _canonical_key(entity_type, value)
    return _ALIAS_INDEX.get(canonical)


def register_alias(canonical_key: str, alternate: str, node_id: str):
    """Record an alternate representation that maps to the canonical node."""
    _ALIAS_REVERSE[alternate] = canonical_key
    _ALIAS_INDEX[canonical_key] = node_id


def _canonical_key(entity_type: str, value: str) -> str:
    """Build a normalised (entity_type, value) tuple string."""
    if entity_type == "IPv4Address":
        return f"{entity_type}:{canonicalise_ipv4(value)}"
    if entity_type in ("Domain", "Website"):
        return f"{entity_type}:{canonicalise_domain(value)}"
    if entity_type == "PhoneNumber":
        return f"{entity_type}:{canonicalise_phone(value)}"
    if entity_type == "ASNumber":
        return f"{entity_type}:{canonicalise_asn(value)}"
    if entity_type == "Netblock":
        return f"{entity_type}:{canonicalise_netblock(value)}"
    return f"{entity_type}:{value.strip()}"


def add_resolved(
    kg: KnowledgeGraph,
    entity_type: str,
    entity_value: str,
    properties: dict | None = None,
) -> tuple[str, bool]:
    """
    Add a node to the KG using canonical normalisation.

    Returns (node_id, is_new).
    Existing nodes are updated with LWW on properties.
    """
    canonical = _canonical_key(entity_type, entity_value)
    existing_id = _ALIAS_INDEX.get(canonical)
    if existing_id:
        node = kg.get_node_by_id(existing_id)
        if node and properties:
            node["properties"].update(properties)
            node["updated_at"] = datetime.now().isoformat()
        return existing_id, False

    node_id = kg.add_node(entity_type, entity_value, properties)
    _ALIAS_INDEX[canonical] = node_id
    return node_id, True


from datetime import datetime
