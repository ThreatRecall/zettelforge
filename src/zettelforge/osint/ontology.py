"""
OSINT ontology — RFC-016 (RFC-0001 in some references).

Defines the entity and edge types added by the OSINT layer and merges them
into the global ZettelForge ontology so the existing ``OntologyValidator``
picks them up without core changes.

Phase coverage:

- **Phase 1 (Infrastructure)** — implemented end-to-end: ASNumber, Netblock,
  MXRecord, NSRecord, Port, Website, WebTitle, plus IPv6Address (parity
  with the existing IPv4Address). Phase 1 collectors are wired and tested.
- **Phases 2-5 (People, Technical, Social/Financial, Physical)** — entity
  and edge types are declared so future collectors register against them
  cleanly. The corresponding collectors ship as stubs (graceful no-ops)
  until those phases land.

Schema notes
------------
All edge definitions use ``from_types`` / ``to_types`` lists and a
``cardinality`` string, matching the existing ``RELATION_TYPES`` shape.
This is what ``OntologyValidator.validate_relation()`` expects; deviating
from it (as the original Phase 1-5 scaffold did with ``from`` / ``to``
strings and ``|`` syntax) means the validator silently treats the relation
as unknown and waves it through, which defeats the purpose of declaring it.

Canonicalization helpers convert raw collector input into the canonical
``entity_value`` used as the KG dedup key (single ``kg_nodes`` table —
see SCOPING_DOC.md §0). Multi-field types (MXRecord, Port, WebTitle) build
a composite canonical value so ``(entity_type, entity_value)`` stays unique.
"""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse, urlunparse

# ---------------------------------------------------------------------------
# Phase 1 entity definitions (functional)
# ---------------------------------------------------------------------------

OSINT_ENTITY_TYPES: dict[str, dict[str, Any]] = {
    # ── Phase 1: Infrastructure ─────────────────────────────────────────────
    "ASNumber": {
        "required": ["number"],
        "optional": ["name", "description", "org"],
        "properties": {},
    },
    "Netblock": {
        "required": ["cidr"],
        "optional": ["description", "org", "country"],
        "properties": {},
    },
    "MXRecord": {
        "required": ["priority", "exchange"],
        "optional": ["ttl"],
        "properties": {},
    },
    "NSRecord": {
        "required": ["nsdname"],
        "optional": ["ttl"],
        "properties": {},
    },
    "Port": {
        "required": ["number", "protocol"],
        "optional": ["service", "banner"],
        "properties": {},
        "enum_properties": {"protocol": ["tcp", "udp"]},
    },
    "Website": {
        "required": ["url"],
        "optional": ["title", "status_code", "server"],
        "properties": {},
    },
    "WebTitle": {
        "required": ["title", "url"],
        "optional": ["snippet"],
        "properties": {},
    },
    # Parity with the existing IPv4Address. Symmetric shape so resolves_to,
    # part_of_as, listens_on, associated_with work uniformly across families.
    "IPv6Address": {
        "required": ["value"],
        "optional": ["belongs_to_ref", "resolves_to_refs"],
        "properties": {},
    },
    # ── Phase 2: People & Communications (stubs — collectors deferred) ──────
    "PhoneNumber": {
        "required": ["e164"],
        "optional": ["countrycode", "citycode", "areacode", "lastnumbers", "type"],
        "properties": {},
    },
    "TwitterAffiliation": {
        "required": ["handle"],
        "optional": ["follower_count", "following_count", "verified", "location", "description"],
        "properties": {},
    },
    "Hashtag": {
        "required": ["namespace", "name"],
        "optional": ["post_count"],
        "properties": {},
    },
    "Alias": {
        "required": ["value"],
        "optional": ["platform", "confidence"],
        "properties": {},
    },
    "NamechkResult": {
        "required": ["platform", "username"],
        "optional": ["available", "url_if_taken"],
        "properties": {},
    },
    # ── Phase 3: Technical Fingerprinting (stubs — collectors deferred) ─────
    "BuiltWithTechnology": {
        "required": ["technology", "category"],
        "optional": ["version", "confidence"],
        "properties": {},
    },
    "BuiltWithRelationship": {
        "required": ["from_tech", "to_tech", "relationship_type"],
        "optional": ["confidence"],
        "properties": {},
        "enum_properties": {"relationship_type": ["uses", "extends", "depends_on"]},
    },
    "CertificateSubject": {
        "required": ["common_name", "organization", "issuer"],
        "optional": ["serial_number", "not_before", "not_after", "sans"],
        "properties": {},
    },
    "SSLPoint": {
        "required": ["ip", "port", "protocol", "certificate_hash"],
        "optional": ["cipher_suite", "tls_version"],
        "properties": {},
        "enum_properties": {"protocol": ["tls", "ssl"]},
    },
    # ── Phase 4: Social & Financial (stubs — collectors deferred) ───────────
    "Tweet": {
        "required": ["tweet_id", "text", "author", "timestamp"],
        "optional": ["hashtags", "mentions", "retweet_count", "favorite_count", "lang"],
        "properties": {},
    },
    "StockSymbol": {
        "required": ["ticker", "exchange", "company_name"],
        "optional": ["currency", "market_cap"],
        "properties": {},
    },
    "Sentiment": {
        "required": ["score", "source", "timestamp"],
        "optional": ["confidence", "language"],
        "properties": {},
    },
    # ── Phase 4 gap types ported from flowsint-types (AGE-119) ──────────────
    # Adopted (not duplicated) from reconurge/flowsint `flowsint-types`
    # v1.2.8 @ 2a4878c8 (Apache-2.0). ASN/CIDR were NOT ported: they already
    # exist here as ASNumber / Netblock. See THIRD_PARTY/PROVENANCE.md.
    "CryptoWallet": {
        # canonical value: see ``canonicalize_wallet`` (hex -> lowercased).
        "required": ["address"],
        "optional": ["chain", "node_id", "label"],
        "properties": {},
    },
    "Transaction": {
        # Blockchain transaction. canonical value: ``canonicalize_tx_hash``.
        "required": ["tx_hash"],
        "optional": ["chain", "from_address", "to_address", "value", "timestamp", "block"],
        "properties": {},
    },
    "SocialAccount": {
        # The "home" of a username on a platform. canonical value:
        # ``canonicalize_social_account`` -> ``username@platform``.
        "required": ["id"],
        "optional": [
            "username",
            "platform",
            "display_name",
            "profile_url",
            "bio",
            "location",
            "verified",
        ],
        "properties": {},
    },
    # ── Phase 4 breach exposure (AGE-120) ───────────────────────────────────
    # A named data breach an email address appeared in. Sourced from the
    # native HIBP REST path (breach/hibp_collector.py). canonical value:
    # ``canonicalize_breach`` -> lowercased breach name (HIBP "Name" field).
    "Breach": {
        "required": ["name"],
        "optional": [
            "title",
            "domain",
            "breach_date",
            "added_date",
            "pwn_count",
            "data_classes",
            "is_verified",
            "description",
        ],
        "properties": {},
    },
    # ── Phase 5: Physical (stubs — collectors deferred) ─────────────────────
    "GPS": {
        "required": ["latitude", "longitude"],
        "optional": ["altitude", "accuracy"],
        "properties": {},
    },
    "CircularArea": {
        "required": ["center_lat", "center_lon", "radius_km"],
        "optional": ["description"],
        "properties": {},
    },
}


# ---------------------------------------------------------------------------
# Edge definitions
# ---------------------------------------------------------------------------

# All edges follow the ``from_types`` / ``to_types`` / ``cardinality`` shape
# expected by ``OntologyValidator.validate_relation``. Cardinality strings
# match the existing core ontology vocabulary.

OSINT_RELATION_TYPES: dict[str, dict[str, Any]] = {
    # ── Phase 1: Infrastructure ─────────────────────────────────────────────
    "resolves_to": {
        "from_types": ["DomainName"],
        "to_types": ["IPv4Address", "IPv6Address"],
        "cardinality": "many_to_many",
    },
    "hosts": {
        "from_types": ["IPv4Address", "IPv6Address"],
        "to_types": ["DomainName"],
        "cardinality": "many_to_many",
    },
    "ns_for": {
        "from_types": ["DomainName"],
        "to_types": ["NSRecord"],
        "cardinality": "many_to_many",
    },
    "mx_for": {
        "from_types": ["DomainName"],
        "to_types": ["MXRecord"],
        "cardinality": "many_to_many",
    },
    "owned_by": {
        "from_types": ["Netblock", "DomainName"],
        "to_types": ["Organization"],
        "cardinality": "many_to_one",
    },
    "part_of_as": {
        "from_types": ["IPv4Address", "IPv6Address", "Netblock"],
        "to_types": ["ASNumber"],
        "cardinality": "many_to_one",
    },
    "delegated_to": {
        "from_types": ["NSRecord"],
        "to_types": ["IPv4Address", "IPv6Address"],
        "cardinality": "many_to_many",
    },
    "receives_mail_on": {
        "from_types": ["MXRecord"],
        "to_types": ["DomainName"],
        "cardinality": "many_to_many",
    },
    "listens_on": {
        "from_types": ["IPv4Address", "IPv6Address"],
        "to_types": ["Port"],
        "cardinality": "many_to_many",
    },
    "associated_with": {
        "from_types": ["IPv4Address", "IPv6Address"],
        "to_types": ["Netblock"],
        "cardinality": "many_to_one",
    },
    # ── Phase 2: People & Communications ────────────────────────────────────
    "has_phone": {
        "from_types": ["Person"],
        "to_types": ["PhoneNumber"],
        "cardinality": "many_to_many",
    },
    "affiliated_with": {
        "from_types": ["Person"],
        "to_types": ["Organization"],
        "cardinality": "many_to_many",
    },
    "located_at": {
        "from_types": ["Person", "Device"],
        "to_types": ["Location", "GPS"],
        "cardinality": "many_to_one",
    },
    "has_handle": {
        "from_types": ["Person"],
        "to_types": ["Alias"],
        "cardinality": "many_to_many",
    },
    "verified_on": {
        "from_types": ["Alias"],
        "to_types": ["TwitterAffiliation"],
        "cardinality": "many_to_one",
    },
    "uses_platform": {
        "from_types": ["Person"],
        "to_types": ["TwitterAffiliation"],
        "cardinality": "many_to_many",
    },
    "hashtags": {
        "from_types": ["Tweet"],
        "to_types": ["Hashtag"],
        "cardinality": "many_to_many",
    },
    "mentions": {
        "from_types": ["Tweet"],
        "to_types": ["Person", "Alias", "URL"],
        "cardinality": "many_to_many",
    },
    # ── Phase 3: Technical ──────────────────────────────────────────────────
    "powered_by": {
        "from_types": ["DomainName"],
        "to_types": ["BuiltWithTechnology"],
        "cardinality": "many_to_many",
    },
    "powered_by_relationship": {
        "from_types": ["BuiltWithTechnology"],
        "to_types": ["BuiltWithTechnology"],
        "cardinality": "many_to_many",
    },
    "issued_cert": {
        "from_types": ["Organization"],
        "to_types": ["CertificateSubject"],
        "cardinality": "one_to_many",
    },
    "terminates_tls": {
        "from_types": ["IPv4Address", "IPv6Address"],
        "to_types": ["SSLPoint"],
        "cardinality": "many_to_many",
    },
    "has_certificate": {
        "from_types": ["DomainName"],
        "to_types": ["CertificateSubject"],
        "cardinality": "many_to_many",
    },
    # ── Phase 4: Social & Financial ─────────────────────────────────────────
    "posted_by": {
        "from_types": ["Tweet"],
        "to_types": ["Person"],
        "cardinality": "many_to_one",
    },
    "contains_hashtag": {
        "from_types": ["Tweet"],
        "to_types": ["Hashtag"],
        "cardinality": "many_to_many",
    },
    "links_to": {
        "from_types": ["Tweet"],
        "to_types": ["URL"],
        "cardinality": "many_to_many",
    },
    "traded_as": {
        "from_types": ["Organization"],
        "to_types": ["StockSymbol"],
        "cardinality": "one_to_many",
    },
    "exhibits_sentiment": {
        # ``exhibits_sentiment`` is intentionally narrow: any Phase-aware
        # collector should target a real entity type rather than relying on
        # a wildcard. Add types here as they come online.
        "from_types": ["Person", "Organization", "DomainName", "StockSymbol"],
        "to_types": ["Sentiment"],
        "cardinality": "many_to_many",
    },
    # ── Phase 4 gap edges for ported types (AGE-119) ────────────────────────
    "sent_transaction": {
        "from_types": ["CryptoWallet"],
        "to_types": ["Transaction"],
        "cardinality": "many_to_many",
    },
    "received_transaction": {
        "from_types": ["CryptoWallet"],
        "to_types": ["Transaction"],
        "cardinality": "many_to_many",
    },
    "controls_wallet": {
        "from_types": ["Person", "Organization", "SocialAccount"],
        "to_types": ["CryptoWallet"],
        "cardinality": "many_to_many",
    },
    "has_account": {
        "from_types": ["Person", "Alias", "EmailAddress"],
        "to_types": ["SocialAccount"],
        "cardinality": "many_to_many",
    },
    # ── AGE-120 enricher edges ──────────────────────────────────────────────
    # WHOIS registrant email for a domain (domain_to_whois EmailAddress branch).
    "registered_by": {
        "from_types": ["DomainName"],
        "to_types": ["EmailAddress"],
        "cardinality": "many_to_one",
    },
    # HIBP breach exposure for an email (email_to_breaches).
    "appeared_in_breach": {
        "from_types": ["EmailAddress"],
        "to_types": ["Breach"],
        "cardinality": "many_to_many",
    },
    # ── Phase 5: Physical ───────────────────────────────────────────────────
    "located_near": {
        "from_types": ["Device", "Person"],
        "to_types": ["GPS"],
        "cardinality": "many_to_many",
    },
    "within_radius": {
        "from_types": ["GPS"],
        "to_types": ["CircularArea"],
        "cardinality": "many_to_one",
    },
}


# Combined view for legacy callers that imported ``ONTOLOGY`` from the
# scaffold version of this module.
ONTOLOGY: dict[str, dict[str, Any]] = {
    "entity_types": OSINT_ENTITY_TYPES,
    "edge_types": OSINT_RELATION_TYPES,
}


# ---------------------------------------------------------------------------
# Canonicalization helpers (Phase 1)
# ---------------------------------------------------------------------------


def canonicalize_asn(raw: str | int) -> str:
    """Strip any leading 'AS'/'as' prefix and return a bare integer string.

    Raises ``ValueError`` if the remainder is not a non-negative integer.
    """
    s = str(raw).strip()
    if s.lower().startswith("as"):
        s = s[2:].strip()
    n = int(s)
    if n < 0:
        raise ValueError(f"ASN must be non-negative, got {n}")
    return str(n)


def canonicalize_cidr(raw: str) -> str:
    """Return the canonical CIDR form via ``ipaddress.ip_network``.

    Accepts both IPv4 and IPv6. ``strict=False`` lets host bits ride; the
    canonical form drops them.
    """
    return str(ipaddress.ip_network(raw.strip(), strict=False))


def canonicalize_domain(raw: str) -> str:
    """Lowercase, strip whitespace, drop a trailing dot."""
    s = raw.strip().lower()
    if s.endswith("."):
        s = s[:-1]
    return s


def canonicalize_ipv6(raw: str) -> str:
    """Return the RFC 5952 compressed form for an IPv6 address."""
    return str(ipaddress.IPv6Address(raw.strip()))


def canonicalize_mx(priority: int | str, exchange: str) -> str:
    """``f'{priority} {exchange}'`` with the exchange canonicalized as a domain.

    Mirrors DNS zone-file MX syntax.
    """
    return f"{int(priority)} {canonicalize_domain(exchange)}"


def canonicalize_port(number: int | str, protocol: str) -> str:
    """Return ``f'{number}/{protocol}'`` after validating range and protocol."""
    n = int(number)
    if not (1 <= n <= 65535):
        raise ValueError(f"Port number out of range 1-65535: {n}")
    proto = str(protocol).strip().lower()
    if proto not in ("tcp", "udp"):
        raise ValueError(f"Port protocol must be 'tcp' or 'udp', got {protocol!r}")
    return f"{n}/{proto}"


def canonicalize_url(raw: str) -> str:
    """Lowercase scheme + host; ensure a path of '/' for root URLs."""
    parsed = urlparse(raw.strip())
    scheme = parsed.scheme.lower() or "http"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, parsed.fragment))


def canonicalize_web_title(url: str, title: str, max_len: int = 256) -> str:
    """Composite canonical value for a (URL, title) pair, length-bounded."""
    canon = f"{canonicalize_url(url)}::{title.strip()}"
    return canon[:max_len]


# ---------------------------------------------------------------------------
# Canonicalization helpers (Phase 4 gap types — AGE-119)
# ---------------------------------------------------------------------------


def canonicalize_wallet(raw: str) -> str:
    """Canonical form for a crypto wallet address.

    Hex addresses (``0x...``, EVM chains, case-insensitive checksums) are
    lowercased so a checksummed and a lowercase form dedupe to one node.
    Non-hex addresses (Bitcoin base58 is case-sensitive) are returned with
    surrounding whitespace stripped only.

    ponytail: case-fold only hex; folding base58 would corrupt BTC
    addresses. Per-chain validation lands with the wallet collector.
    """
    s = raw.strip()
    if s.lower().startswith("0x"):
        return s.lower()
    return s


def canonicalize_tx_hash(raw: str) -> str:
    """Canonical form for a blockchain transaction hash: stripped, lowercased.

    Transaction hashes are hex on every supported chain, so lowercasing is
    always safe and makes ``(Transaction, tx_hash)`` dedupe correctly.
    """
    return raw.strip().lower()


def canonicalize_social_account(username: str, platform: str) -> str:
    """Composite canonical value ``username@platform`` (both lowercased).

    Mirrors flowsint-types ``SocialAccount.id``. Keeps
    ``(SocialAccount, id)`` unique across platforms for the same handle.
    """
    return f"{username.strip().lower()}@{platform.strip().lower()}"


def canonicalize_email(raw: str) -> str:
    """Lowercase and strip an email address for stable dedup.

    Email addresses are treated case-insensitively for the providers the
    OSINT layer targets, so ``Alice@Example.com`` and ``alice@example.com``
    fold to one node. No syntactic validation here: the collector that
    produces the address owns that.
    """
    return raw.strip().lower()


def canonicalize_breach(raw: str) -> str:
    """Canonical form for a breach name: stripped and lowercased.

    HIBP breach names (the ``Name`` field, e.g. ``Adobe``) are stable
    identifiers; lowercasing keeps ``(Breach, name)`` deduped regardless of
    source casing.
    """
    return raw.strip().lower()


def canonicalize_alias(raw: str) -> str:
    """Canonical form for an Alias / username: stripped and lowercased.

    Usernames are matched case-insensitively across the social platforms the
    enrichers target, so folding case keeps one node per handle.
    """
    return raw.strip().lower()


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

# Track whether merge has been performed so re-imports are idempotent.
_MERGED = False


def merge_into_global_ontology() -> None:
    """Add OSINT entity / edge types and IPv6Address to the global ontology.

    Idempotent: safe to call multiple times. Re-importing this module from
    multiple test files will not double-register anything.
    """
    global _MERGED
    if _MERGED:
        return

    from zettelforge.ontology import ENTITY_TYPES, RELATION_TYPES

    # IPv6Address belongs in the core ontology alongside IPv4Address. Add
    # only if not already present so a future core update that introduces
    # it natively does not collide.
    if "IPv6Address" not in ENTITY_TYPES:
        ENTITY_TYPES["IPv6Address"] = OSINT_ENTITY_TYPES["IPv6Address"]

    for name, defn in OSINT_ENTITY_TYPES.items():
        if name == "IPv6Address":
            continue  # already handled above
        if name not in ENTITY_TYPES:
            ENTITY_TYPES[name] = defn

    for name, defn in OSINT_RELATION_TYPES.items():
        if name not in RELATION_TYPES:
            RELATION_TYPES[name] = defn

    _MERGED = True


__all__ = [
    "ONTOLOGY",
    "OSINT_ENTITY_TYPES",
    "OSINT_RELATION_TYPES",
    "canonicalize_alias",
    "canonicalize_asn",
    "canonicalize_breach",
    "canonicalize_cidr",
    "canonicalize_domain",
    "canonicalize_email",
    "canonicalize_ipv6",
    "canonicalize_mx",
    "canonicalize_port",
    "canonicalize_social_account",
    "canonicalize_tx_hash",
    "canonicalize_url",
    "canonicalize_wallet",
    "canonicalize_web_title",
    "merge_into_global_ontology",
]
