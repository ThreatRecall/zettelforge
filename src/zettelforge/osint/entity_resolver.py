"""
OSINT Entity Resolver -- canonical key normalisation and alias index.

Phase 1.5 utility scaffold. Provides merge-when-duplicate semantics for
the OSINT layer:

- Canonical key: ``(entity_type, normalised_value)``
- Alias index: alternate representations -> canonical node ID
- Merge strategy: LWW for properties, accumulate for edges

The passive OSINT executor wires these helpers into KG ingest; later
workflow orchestration can reuse the same canonicalisation and aliasing
logic.

Note on canonical key conventions: this module mirrors the conventions
in ``zettelforge.osint.ontology`` (``DomainName`` not ``Domain``,
ASN-as-bare-integer-string not ``AS12345``). Future helpers should add
to those rather than diverge.
"""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING

from zettelforge.osint.ontology import (
    canonicalize_asn,
    canonicalize_cidr,
    canonicalize_domain,
    canonicalize_mx,
    canonicalize_port,
    canonicalize_url,
    canonicalize_web_title,
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
    ``ValueError`` on hex (``0x3039``) or other non-decimal input --
    earlier scaffold versions silently stripped non-digits which turned
    ``0x3039`` into ``0339`` instead of the hex value 12345.
    """
    return canonicalize_asn(value)


def canonicalise_netblock(value: str) -> str:
    """Return the canonical CIDR form (host bits dropped, IPv4 or IPv6)."""
    return canonicalize_cidr(value)


def canonicalise_url(value: str) -> str:
    """Return the canonical URL form used by ``URL`` and ``Website`` nodes."""
    return canonicalize_url(value)


def canonicalise_organization(value: str) -> str:
    """Return a stable canonical form for organization names.

    WHOIS and RDAP sources vary in case and spacing. Normalising to a
    lowercased, whitespace-collapsed form keeps duplicates from being
    reinserted under cosmetic variations.
    """
    return re.sub(r"\s+", " ", value).strip().casefold()


# Global alias index: canonical_key -> node_id. This bucket is the default
# scope used when callers do not pass a KnowledgeGraph explicitly.
_ALIAS_INDEX: dict[str, str] = {}
# Reverse: alternate representation -> canonical key
_ALIAS_REVERSE: dict[str, str] = {}
_KG_ALIAS_INDEX_ATTR = "_osint_alias_index"
_KG_ALIAS_REVERSE_ATTR = "_osint_alias_reverse"


def _alias_maps(kg: KnowledgeGraph | None) -> tuple[dict[str, str], dict[str, str]]:
    if kg is None:
        return _ALIAS_INDEX, _ALIAS_REVERSE
    index = getattr(kg, _KG_ALIAS_INDEX_ATTR, None)
    if index is None:
        index = {}
        setattr(kg, _KG_ALIAS_INDEX_ATTR, index)
    reverse = getattr(kg, _KG_ALIAS_REVERSE_ATTR, None)
    if reverse is None:
        reverse = {}
        setattr(kg, _KG_ALIAS_REVERSE_ATTR, reverse)
    return index, reverse


def resolve(entity_type: str, value: str, *, kg: KnowledgeGraph | None = None) -> str | None:
    """Return the canonical node ID for an entity if already indexed, else None."""
    canonical = _canonical_key(entity_type, value)
    alias_index, _ = _alias_maps(kg)
    return alias_index.get(canonical)


def register_alias(
    canonical_key: str,
    alternate: str,
    node_id: str,
    *,
    kg: KnowledgeGraph | None = None,
) -> None:
    """Record an alternate representation that maps to the canonical node."""
    alias_index, alias_reverse = _alias_maps(kg)
    alias_reverse[alternate] = canonical_key
    alias_index[canonical_key] = node_id


def _canonical_key(entity_type: str, value: str) -> str:
    """Build a normalised ``"<entity_type>:<canonical-value>"`` string.

    The entity type names match the global ``ENTITY_TYPES`` table --
    ``DomainName`` and not ``Domain``. Unknown types fall through to a
    whitespace-trimmed value so callers don't have to special-case
    every possible type.
    """
    if entity_type == "IPv4Address":
        return f"{entity_type}:{canonicalise_ipv4(value)}"
    if entity_type == "IPv6Address":
        return f"{entity_type}:{ipaddress.IPv6Address(value.strip())}"
    if entity_type == "DomainName":
        return f"{entity_type}:{canonicalise_domain(value)}"
    if entity_type in ("URL", "Website"):
        return f"{entity_type}:{canonicalise_url(value)}"
    if entity_type == "PhoneNumber":
        return f"{entity_type}:{canonicalise_phone(value)}"
    if entity_type == "ASNumber":
        return f"{entity_type}:{canonicalise_asn(value)}"
    if entity_type == "Netblock":
        return f"{entity_type}:{canonicalise_netblock(value)}"
    if entity_type == "NSRecord":
        return f"{entity_type}:{canonicalise_domain(value)}"
    if entity_type == "Organization":
        return f"{entity_type}:{canonicalise_organization(value)}"
    if entity_type == "MXRecord":
        raw = value.strip()
        if " " not in raw:
            raise ValueError(f"MXRecord must be 'priority exchange', got {value!r}")
        priority, exchange = raw.split(None, 1)
        return f"{entity_type}:{canonicalize_mx(priority, exchange)}"
    if entity_type == "Port":
        raw = value.strip()
        if "/" not in raw:
            raise ValueError(f"Port must be 'number/protocol', got {value!r}")
        number, protocol = raw.split("/", 1)
        return f"{entity_type}:{canonicalize_port(number, protocol)}"
    if entity_type == "WebTitle":
        raw = value.strip()
        if "::" not in raw:
            raise ValueError(f"WebTitle must be 'url::title', got {value!r}")
        url, title = raw.split("::", 1)
        return f"{entity_type}:{canonicalize_web_title(url, title)}"
    return f"{entity_type}:{value.strip()}"


def canonicalise_value(entity_type: str, value: str) -> str:
    """Return the canonical value portion for an entity type.

    This is the public counterpart to ``_canonical_key`` for callers that
    need to pass the same value to ``KnowledgeGraph.add_node()`` and
    ``KnowledgeGraph.add_edge()``. Keeping KG values canonical avoids creating
    duplicate nodes for equivalent OSINT entities such as ``AS15169`` and
    ``15169``.
    """
    canonical = _canonical_key(entity_type, value)
    return canonical.split(":", 1)[1]


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
    canonical_value = canonical.split(":", 1)[1]
    alias_index, alias_reverse = _alias_maps(kg)
    existing_id = alias_index.get(canonical)
    if existing_id:
        if properties:
            kg.add_node(entity_type, canonical_value, properties)
        if canonical_value != entity_value:
            alias_reverse[entity_value] = canonical
        return existing_id, False

    node_id = kg.add_node(entity_type, canonical_value, properties)
    alias_index[canonical] = node_id
    if canonical_value != entity_value:
        alias_reverse[entity_value] = canonical
    return node_id, True


__all__ = [
    "add_resolved",
    "canonicalise_asn",
    "canonicalise_domain",
    "canonicalise_ipv4",
    "canonicalise_netblock",
    "canonicalise_organization",
    "canonicalise_phone",
    "canonicalise_url",
    "canonicalise_value",
    "register_alias",
    "resolve",
]
