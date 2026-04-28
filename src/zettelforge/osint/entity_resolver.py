"""
OSINT Entity Resolver — canonical key normalisation and alias index.

Phase 1.5 utility scaffold. Provides merge-when-duplicate semantics for
the OSINT layer:

- Canonical key: ``(entity_type, normalised_value)``
- Alias index: alternate representations → canonical node ID
- Merge strategy: LWW for properties, accumulate for edges

Phase 1 collectors don't yet route through this module; the Phase 1.5
work that wires it in lives behind the same RFC-016 umbrella.

Note on canonical key conventions: this module mirrors the conventions
in ``zettelforge.osint.ontology`` (``DomainName`` not ``Domain``,
ASN-as-bare-integer-string not ``AS12345``). Future helpers should add
to those rather than diverge.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import TYPE_CHECKING

from zettelforge.osint.ontology import (
    canonicalize_asn,
    canonicalize_cidr,
    canonicalize_domain,
)

if TYPE_CHECKING:
    from zettelforge.knowledge_graph import KnowledgeGraph


def canonicalise_ipv4(value: str) -> str:
    """Strip leading zeros; return dotted-quad string.

    ``ipaddress.IPv4Address`` rejects octets with leading zeros (e.g.
    ``001.002.003.004``) on Python 3.10+, so we parse octets explicitly
    before re-joining. Raises ``ValueError`` for inputs that aren't
    four 0-255 octets.
    """
    parts = value.strip().split(".")
    if len(parts) != 4:
        raise ValueError(f"IPv4 address must have 4 octets, got {value!r}")
    octets: list[int] = []
    for raw in parts:
        if not raw.isdigit():
            raise ValueError(f"non-numeric octet in {value!r}")
        n = int(raw)
        if not (0 <= n <= 255):
            raise ValueError(f"octet out of range 0-255 in {value!r}")
        octets.append(n)
    return ".".join(str(n) for n in octets)


def canonicalise_domain(value: str) -> str:
    """Lowercase, strip whitespace, drop trailing dot.

    Thin wrapper around :func:`zettelforge.osint.ontology.canonicalize_domain`
    so the resolver stays a one-stop import for callers.
    """
    return canonicalize_domain(value)


def canonicalise_phone(value: str) -> str:
    """Return a best-effort E.164 string (digits only, leading ``+``).

    Heuristic: strip non-digits; if the result is exactly 10 digits,
    assume NANP and prefix ``1``. Returns the original string unchanged
    when the input has no digits at all (so callers can surface the
    failure rather than swallow it).
    """
    digits = re.sub(r"\D", "", value)
    if not digits:
        return value
    if len(digits) == 10:
        digits = "1" + digits
    return f"+{digits}"


def canonicalise_asn(value: str) -> str:
    """Return a bare integer string for an ASN.

    Mirrors :func:`zettelforge.osint.ontology.canonicalize_asn`. Accepts
    ``AS12345``, ``as12345``, ``"12345"``, or an int. Raises
    ``ValueError`` on hex (``0x3039``) or other non-decimal input —
    earlier scaffold versions silently stripped non-digits which turned
    ``0x3039`` into ``0339`` instead of the hex value 12345.
    """
    return canonicalize_asn(value)


def canonicalise_netblock(value: str) -> str:
    """Return the canonical CIDR form (host bits dropped, IPv4 or IPv6)."""
    return canonicalize_cidr(value)


# Global alias index: canonical_key → node_id
_ALIAS_INDEX: dict[str, str] = {}
# Reverse: alternate representation → canonical key
_ALIAS_REVERSE: dict[str, str] = {}


def resolve(entity_type: str, value: str) -> str | None:
    """Return the canonical key for an entity if already indexed, else None."""
    canonical = _canonical_key(entity_type, value)
    return _ALIAS_INDEX.get(canonical)


def register_alias(canonical_key: str, alternate: str, node_id: str) -> None:
    """Record an alternate representation that maps to the canonical node."""
    _ALIAS_REVERSE[alternate] = canonical_key
    _ALIAS_INDEX[canonical_key] = node_id


def _canonical_key(entity_type: str, value: str) -> str:
    """Build a normalised ``"<entity_type>:<canonical-value>"`` string.

    The entity type names match the global ``ENTITY_TYPES`` table —
    ``DomainName`` and not ``Domain``. Unknown types fall through to a
    whitespace-trimmed value so callers don't have to special-case
    every possible type.
    """
    if entity_type == "IPv4Address":
        return f"{entity_type}:{canonicalise_ipv4(value)}"
    if entity_type == "IPv6Address":
        return f"{entity_type}:{ipaddress.IPv6Address(value.strip())}"
    if entity_type in ("DomainName", "Website"):
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
    """Add a node to the KG using canonical normalisation.

    Returns ``(node_id, is_new)``. Existing nodes are updated with LWW
    on properties.
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
