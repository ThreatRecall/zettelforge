"""
Phase 1 OSINT entity / edge / canonicalization tests (RFC-016).

These tests do not touch the network or the disk. They exercise:

- The new OSINT entity types validate against ``OntologyValidator`` once
  ``merge_into_global_ontology()`` has run (the ``zettelforge.osint``
  package import handles that as a side effect).
- The new edge types validate via ``validate_relation``.
- The canonicalization helpers produce the documented canonical forms.
- The merge helper is idempotent under repeated import.
"""

from __future__ import annotations

import pytest

# Importing the osint package also runs merge_into_global_ontology() and
# registers Phase 1 collectors. Tests that follow rely on those side effects.
from zettelforge import osint as _osint  # noqa: F401
from zettelforge.ontology import ENTITY_TYPES, RELATION_TYPES, OntologyValidator
from zettelforge.osint.ontology import (
    OSINT_ENTITY_TYPES,
    OSINT_RELATION_TYPES,
    canonicalize_asn,
    canonicalize_cidr,
    canonicalize_domain,
    canonicalize_ipv6,
    canonicalize_mx,
    canonicalize_port,
    canonicalize_url,
    canonicalize_web_title,
    merge_into_global_ontology,
)


@pytest.fixture
def validator() -> OntologyValidator:
    return OntologyValidator()


# ---------------------------------------------------------------------------
# Ontology merge
# ---------------------------------------------------------------------------


PHASE_1_ENTITIES = (
    "ASNumber",
    "Netblock",
    "MXRecord",
    "NSRecord",
    "Port",
    "Website",
    "WebTitle",
    "IPv6Address",
)

PHASE_1_EDGES = (
    "resolves_to",
    "hosts",
    "ns_for",
    "mx_for",
    "owned_by",
    "part_of_as",
    "delegated_to",
    "receives_mail_on",
    "listens_on",
    "associated_with",
)


def test_all_phase1_entities_present_in_global_entity_types() -> None:
    for name in PHASE_1_ENTITIES:
        assert name in ENTITY_TYPES, f"{name} not merged into global ENTITY_TYPES"


def test_all_phase1_edges_present_in_global_relation_types() -> None:
    for name in PHASE_1_EDGES:
        assert name in RELATION_TYPES, f"{name} not merged into global RELATION_TYPES"


def test_merge_is_idempotent() -> None:
    # Calling merge again must not duplicate or alter existing entries.
    snapshot_entities = dict(ENTITY_TYPES)
    snapshot_relations = dict(RELATION_TYPES)
    merge_into_global_ontology()
    merge_into_global_ontology()
    assert snapshot_entities == ENTITY_TYPES
    assert snapshot_relations == RELATION_TYPES


# ---------------------------------------------------------------------------
# Entity validation
# ---------------------------------------------------------------------------


def test_asnumber_requires_number(validator: OntologyValidator) -> None:
    ok, errs = validator.validate_entity("ASNumber", {"number": 15169})
    assert ok and errs == []
    ok, errs = validator.validate_entity("ASNumber", {})
    assert not ok and any("number" in e for e in errs)


def test_netblock_requires_cidr(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_entity("Netblock", {"cidr": "8.8.8.0/24"})
    assert ok
    ok, errs = validator.validate_entity("Netblock", {})
    assert not ok and any("cidr" in e for e in errs)


def test_mxrecord_requires_priority_and_exchange(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_entity("MXRecord", {"priority": 10, "exchange": "mail.example.com"})
    assert ok
    ok, errs = validator.validate_entity("MXRecord", {"priority": 10})
    assert not ok and any("exchange" in e for e in errs)


def test_nsrecord_requires_nsdname(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_entity("NSRecord", {"nsdname": "ns1.example.com"})
    assert ok
    ok, errs = validator.validate_entity("NSRecord", {})
    assert not ok and any("nsdname" in e for e in errs)


def test_port_requires_number_and_protocol(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_entity("Port", {"number": 443, "protocol": "tcp"})
    assert ok


def test_port_protocol_enum_rejects_invalid(validator: OntologyValidator) -> None:
    ok, errs = validator.validate_entity("Port", {"number": 53, "protocol": "icmp"})
    assert not ok
    assert any("protocol" in e for e in errs)


def test_website_requires_url(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_entity("Website", {"url": "https://example.com/"})
    assert ok
    ok, errs = validator.validate_entity("Website", {})
    assert not ok and any("url" in e for e in errs)


def test_webtitle_requires_title_and_url(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_entity("WebTitle", {"title": "Hello", "url": "https://example.com/"})
    assert ok
    ok, errs = validator.validate_entity("WebTitle", {"title": "Hello"})
    assert not ok and any("url" in e for e in errs)


def test_ipv6address_requires_value(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_entity("IPv6Address", {"value": "2001:db8::1"})
    assert ok
    ok, errs = validator.validate_entity("IPv6Address", {})
    assert not ok and any("value" in e for e in errs)


# ---------------------------------------------------------------------------
# Edge validation
# ---------------------------------------------------------------------------


def test_resolves_to_accepts_ipv4_and_ipv6(validator: OntologyValidator) -> None:
    ok4, _ = validator.validate_relation("DomainName", "resolves_to", "IPv4Address")
    ok6, _ = validator.validate_relation("DomainName", "resolves_to", "IPv6Address")
    assert ok4 and ok6


def test_resolves_to_rejects_non_domain_source(validator: OntologyValidator) -> None:
    ok, errs = validator.validate_relation("Person", "resolves_to", "IPv4Address")
    assert not ok and errs


def test_owned_by_points_to_organization(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_relation("Netblock", "owned_by", "Organization")
    assert ok
    ok, errs = validator.validate_relation("Netblock", "owned_by", "Person")
    assert not ok and errs


def test_listens_on_targets_port(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_relation("IPv4Address", "listens_on", "Port")
    assert ok


def test_part_of_as_targets_asnumber(validator: OntologyValidator) -> None:
    ok, _ = validator.validate_relation("IPv4Address", "part_of_as", "ASNumber")
    assert ok
    ok, _ = validator.validate_relation("Netblock", "part_of_as", "ASNumber")
    assert ok


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AS15169", "15169"),
        ("as15169", "15169"),
        (15169, "15169"),
        ("15169 ", "15169"),
    ],
)
def test_canonicalize_asn(raw: str | int, expected: str) -> None:
    assert canonicalize_asn(raw) == expected


def test_canonicalize_asn_rejects_negative() -> None:
    with pytest.raises(ValueError):
        canonicalize_asn("-1")


def test_canonicalize_asn_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        canonicalize_asn("AS abc")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8.8.8.0/24", "8.8.8.0/24"),
        ("8.8.8.5/24", "8.8.8.0/24"),  # host bits trimmed
        ("2001:db8::/32", "2001:db8::/32"),
    ],
)
def test_canonicalize_cidr(raw: str, expected: str) -> None:
    assert canonicalize_cidr(raw) == expected


def test_canonicalize_domain_strips_dot_and_lowercases() -> None:
    assert canonicalize_domain("Example.COM.") == "example.com"
    assert canonicalize_domain("  Foo.example.com.  ") == "foo.example.com"


def test_canonicalize_ipv6_uses_compressed_form() -> None:
    assert canonicalize_ipv6("2001:0db8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"


def test_canonicalize_mx_combines_priority_and_exchange() -> None:
    assert canonicalize_mx(10, "Mail.Example.com.") == "10 mail.example.com"


@pytest.mark.parametrize(
    ("number", "protocol", "expected"),
    [
        (80, "TCP", "80/tcp"),
        ("443", "udp", "443/udp"),
    ],
)
def test_canonicalize_port_valid(number: int | str, protocol: str, expected: str) -> None:
    assert canonicalize_port(number, protocol) == expected


@pytest.mark.parametrize("bad", [(0, "tcp"), (65536, "tcp"), (53, "icmp")])
def test_canonicalize_port_invalid(bad: tuple[int, str]) -> None:
    with pytest.raises(ValueError):
        canonicalize_port(*bad)


def test_canonicalize_url_lowercases_and_defaults_root_path() -> None:
    assert canonicalize_url("HTTPS://Example.COM") == "https://example.com/"
    assert canonicalize_url("http://Example.com/Path") == "http://example.com/Path"


def test_canonicalize_web_title_truncates() -> None:
    long_title = "x" * 1000
    canon = canonicalize_web_title("https://example.com/", long_title, max_len=64)
    assert len(canon) == 64
    assert canon.startswith("https://example.com/::")


def test_osint_entity_types_dict_includes_phase1() -> None:
    # The OSINT layer declares Phase 1-5 entities; Phase 1 must be present
    # but additional later-phase types are expected.
    assert set(PHASE_1_ENTITIES) <= set(OSINT_ENTITY_TYPES)


def test_osint_relation_types_dict_includes_phase1() -> None:
    assert set(PHASE_1_EDGES) <= set(OSINT_RELATION_TYPES)
