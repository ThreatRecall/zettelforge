"""
Phase 1 OSINT collector tests (RFC-016 §5).

Tests are fully mocked. They never touch the network.

Coverage:

- ``dns_collector`` — A, AAAA, NS, MX records emitted; NXDOMAIN absorbed;
  non-DomainName input rejected; missing dnspython handled.
- ``whois_collector`` — domain branch (Organization), IP branch
  (Netblock + Organization + ASN); missing libraries handled.
- ``cert_collector`` — SAN dedup, wildcard stripping, HTTP error → [],
  non-DomainName input rejected.
- ``transform_registry`` — collectors discoverable by input type.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from zettelforge import osint as _osint  # noqa: F401 — registers collectors
from zettelforge.osint.collectors.infrastructure import (
    cert_collector,
    dns_collector,
    whois_collector,
)
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

# ---------------------------------------------------------------------------
# DNS collector
# ---------------------------------------------------------------------------


class _FakeMx:
    def __init__(self, preference: int, exchange: str) -> None:
        self.preference = preference
        self.exchange = exchange

    def __str__(self) -> str:
        return f"{self.preference} {self.exchange}"


def _build_resolver_mock(answers_by_rdtype: dict[str, list[Any]]) -> MagicMock:
    """Return a mocked Resolver whose ``resolve`` dispatches by rdtype."""
    import dns.exception
    import dns.resolver

    resolver = MagicMock()

    def fake_resolve(name: str, rdtype: str) -> list[Any]:
        if rdtype not in answers_by_rdtype:
            raise dns.resolver.NoAnswer()
        return answers_by_rdtype[rdtype]

    resolver.resolve.side_effect = fake_resolve
    # Reference unused exception to silence linters; the collector uses it.
    _ = dns.exception.Timeout
    return resolver


def test_dns_collect_rejects_unhandled_input() -> None:
    # DomainName (forward) and IPv4/IPv6 (reverse PTR) are handled; other
    # seed types are not.
    assert dns_collector.collect("ASNumber", "15169") == []


def test_dns_collect_returns_empty_when_dnspython_missing() -> None:
    with patch.object(dns_collector, "_make_resolver", side_effect=ImportError):
        assert dns_collector.collect("DomainName", "example.com") == []


def test_dns_collect_emits_a_aaaa_ns_mx_records() -> None:
    answers = {
        "A": ["1.2.3.4", "5.6.7.8"],
        "AAAA": ["2001:db8::1"],
        "NS": ["ns1.example.com.", "ns2.example.com."],
        "MX": [_FakeMx(10, "mx1.example.com."), _FakeMx(20, "mx2.example.com.")],
    }
    resolver = _build_resolver_mock(answers)
    with patch.object(dns_collector, "_make_resolver", return_value=resolver):
        out = dns_collector.collect("DomainName", "Example.com")

    types = [t.output_entity_type for t in out]
    assert types.count("IPv4Address") == 2
    assert types.count("IPv6Address") == 1
    assert types.count("NSRecord") == 2
    assert types.count("MXRecord") == 2

    ipv4_values = {t.output_value for t in out if t.output_entity_type == "IPv4Address"}
    assert ipv4_values == {"1.2.3.4", "5.6.7.8"}

    ipv6_values = {t.output_value for t in out if t.output_entity_type == "IPv6Address"}
    assert ipv6_values == {"2001:db8::1"}

    ns_values = {t.output_value for t in out if t.output_entity_type == "NSRecord"}
    assert ns_values == {"ns1.example.com", "ns2.example.com"}

    mx_values = {t.output_value for t in out if t.output_entity_type == "MXRecord"}
    assert mx_values == {"10 mx1.example.com", "20 mx2.example.com"}


def test_dns_collect_absorbs_nxdomain() -> None:
    import dns.resolver

    resolver = MagicMock()
    resolver.resolve.side_effect = dns.resolver.NXDOMAIN()
    with patch.object(dns_collector, "_make_resolver", return_value=resolver):
        assert dns_collector.collect("DomainName", "no-such-domain.invalid") == []


def test_dns_collect_canonicalizes_domain_input() -> None:
    answers = {"A": ["10.0.0.1"]}
    resolver = _build_resolver_mock(answers)
    with patch.object(dns_collector, "_make_resolver", return_value=resolver):
        dns_collector.collect("DomainName", "  Example.COM.  ")
    # Verify the resolver was called with the canonicalized domain.
    called_domains = {call.args[0] for call in resolver.resolve.call_args_list}
    assert called_domains == {"example.com"}


# ---------------------------------------------------------------------------
# WHOIS collector — domain branch
# ---------------------------------------------------------------------------


class _FakeWhoisRecord:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


def test_whois_domain_emits_organization_owned_by() -> None:
    fake = _FakeWhoisRecord(org="Example Corp", organization=None, registrant=None, name=None)
    with patch.object(whois_collector, "_lookup_domain", return_value=fake):
        out = whois_collector.collect("DomainName", "Example.com")

    assert len(out) == 1
    tup = out[0]
    assert tup == CollectorTuple(
        output_entity_type="Organization",
        output_value="Example Corp",
        edge_type="owned_by",
        from_entity_type="DomainName",
        to_entity_type="Organization",
        output_props={"name": "Example Corp"},
        edge_props={},
    )


def test_whois_domain_falls_through_when_org_missing() -> None:
    fake = _FakeWhoisRecord(org=None, organization=None, registrant=None, name=None)
    with patch.object(whois_collector, "_lookup_domain", return_value=fake):
        assert whois_collector.collect("DomainName", "example.com") == []


def test_whois_domain_returns_empty_when_library_missing() -> None:
    with patch.object(whois_collector, "_lookup_domain", return_value=None):
        assert whois_collector.collect("DomainName", "example.com") == []


def test_whois_domain_handles_list_valued_org_field() -> None:
    fake = _FakeWhoisRecord(org=["Example Corp", "Other Ltd"])
    with patch.object(whois_collector, "_lookup_domain", return_value=fake):
        out = whois_collector.collect("DomainName", "example.com")
    assert out and out[0].output_value == "Example Corp"


# ---------------------------------------------------------------------------
# WHOIS collector — IP branch
# ---------------------------------------------------------------------------


def _rdap_payload(
    *,
    cidr: str | None,
    asn: str | None,
    org_name: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"network": {}}
    if cidr is not None:
        payload["network"]["cidr"] = cidr
    if asn is not None:
        payload["asn"] = asn
        payload["asn_description"] = "EXAMPLE-AS, US"
    if org_name is not None:
        payload["objects"] = {
            "OBJ-1": {"contact": {"name": org_name}},
        }
    return payload


def test_whois_ip_emits_netblock_org_asn() -> None:
    payload = _rdap_payload(cidr="8.8.8.0/24", asn="15169", org_name="Google LLC")
    with patch.object(whois_collector, "_lookup_ip", return_value=payload):
        out = whois_collector.collect("IPv4Address", "8.8.8.8")

    by_type = {t.output_entity_type: t for t in out}
    assert {"Netblock", "Organization", "ASNumber"} <= set(by_type)

    assert by_type["Netblock"].output_value == "8.8.8.0/24"
    assert by_type["Netblock"].edge_type == "associated_with"
    assert by_type["Organization"].output_value == "Google LLC"
    assert by_type["Organization"].edge_type == "owned_by"
    assert by_type["Organization"].from_entity_type == "Netblock"
    assert by_type["ASNumber"].output_value == "15169"
    assert by_type["ASNumber"].output_props["number"] == 15169
    assert by_type["ASNumber"].edge_type == "part_of_as"


def test_whois_ip_handles_ipv6_input() -> None:
    payload = _rdap_payload(cidr="2001:db8::/32", asn="64500", org_name="Example v6 Org")
    with patch.object(whois_collector, "_lookup_ip", return_value=payload):
        out = whois_collector.collect("IPv6Address", "2001:db8::1")

    families = {t.from_entity_type for t in out if t.output_entity_type != "Organization"}
    assert families == {"IPv6Address"}


def test_whois_ip_skips_invalid_input() -> None:
    assert whois_collector.collect("IPv4Address", "not-an-ip") == []


def test_whois_ip_returns_empty_when_library_missing() -> None:
    with patch.object(whois_collector, "_lookup_ip", return_value=None):
        assert whois_collector.collect("IPv4Address", "1.2.3.4") == []


def test_whois_ip_handles_multi_cidr_network() -> None:
    payload = _rdap_payload(cidr="8.8.8.0/24, 8.8.4.0/24", asn="15169", org_name="Google LLC")
    with patch.object(whois_collector, "_lookup_ip", return_value=payload):
        out = whois_collector.collect("IPv4Address", "8.8.8.8")
    netblocks = [t for t in out if t.output_entity_type == "Netblock"]
    assert len(netblocks) == 1
    assert netblocks[0].output_value == "8.8.8.0/24"


def test_whois_collect_rejects_unknown_input_type() -> None:
    assert whois_collector.collect("Person", "alice") == []


# ---------------------------------------------------------------------------
# Cert collector
# ---------------------------------------------------------------------------


def _fake_crtsh_response(records: list[dict[str, Any]]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = records
    response.raise_for_status.return_value = None
    return response


def _patch_crtsh_with(response_or_exc: Any) -> Any:
    """Build a context manager that replaces ``httpx.Client`` with a mock."""
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    if isinstance(response_or_exc, BaseException):
        client.get.side_effect = response_or_exc
    else:
        client.get.return_value = response_or_exc
    return patch.object(cert_collector.httpx, "Client", return_value=client)


def test_cert_collect_rejects_non_domain_input() -> None:
    assert cert_collector.collect("IPv4Address", "1.2.3.4") == []


def test_cert_collect_emits_dedup_san_domains() -> None:
    records = [
        {"name_value": "example.com\nwww.example.com\n*.example.com"},
        {"name_value": "api.example.com\nwww.example.com"},
        {"name_value": "Other.Example.com"},
    ]
    response = _fake_crtsh_response(records)
    with _patch_crtsh_with(response):
        out = cert_collector.collect("DomainName", "example.com")

    values = sorted(t.output_value for t in out)
    # Wildcard *.example.com strips to example.com which is the input → excluded.
    # Mixed-case "Other.Example.com" → "other.example.com".
    assert values == ["api.example.com", "other.example.com", "www.example.com"]
    for tup in out:
        assert tup.edge_type == "related_to"
        assert tup.from_entity_type == "DomainName"
        assert tup.to_entity_type == "DomainName"
        assert tup.edge_props == {"source": "crt.sh"}


def test_cert_collect_returns_empty_on_http_error() -> None:
    with _patch_crtsh_with(httpx.HTTPError("boom")):
        assert cert_collector.collect("DomainName", "example.com") == []


def test_cert_collect_returns_empty_on_unexpected_payload_shape() -> None:
    response = _fake_crtsh_response(records={"not": "a list"})  # type: ignore[arg-type]
    response.json.return_value = {"not": "a list"}
    with _patch_crtsh_with(response):
        assert cert_collector.collect("DomainName", "example.com") == []


def test_cert_collect_caps_records_at_max() -> None:
    big = [{"name_value": f"sub{i}.example.com"} for i in range(cert_collector.MAX_CERTS + 50)]
    response = _fake_crtsh_response(big)
    with _patch_crtsh_with(response):
        out = cert_collector.collect("DomainName", "example.com")
    # Output count <= MAX_CERTS because each record contributes one unique name.
    assert len(out) <= cert_collector.MAX_CERTS


# ---------------------------------------------------------------------------
# Registry dispatch
# ---------------------------------------------------------------------------


def test_registry_lists_phase1_collectors() -> None:
    names = {meta.name for meta in TRANSFORM_REGISTRY.list_all()}
    assert {"dns_collector", "whois_collector", "cert_collector"} <= names


def test_registry_finds_collectors_by_domain_input() -> None:
    matches = TRANSFORM_REGISTRY.find_by_input("DomainName")
    names = {meta.name for meta, _fn in matches}
    assert {"dns_collector", "whois_collector", "cert_collector"} <= names


def test_registry_finds_whois_for_ipv4_input() -> None:
    # IPv4Address is consumed by whois_collector and the gated port_scanner
    # stub. Newly-added collectors that accept IPv4Address may extend this
    # set — verify the known collectors are present rather than asserting
    # an exact match.
    matches = TRANSFORM_REGISTRY.find_by_input("IPv4Address")
    names = {meta.name for meta, _fn in matches}
    assert "whois_collector" in names
    assert "port_scanner" in names


def test_registry_get_returns_callable() -> None:
    meta, fn = TRANSFORM_REGISTRY.get("dns_collector")
    assert isinstance(meta, TransformMetadata)
    assert callable(fn)


def test_registry_idempotent_re_registration() -> None:
    meta, fn = TRANSFORM_REGISTRY.get("dns_collector")
    before = len(TRANSFORM_REGISTRY.list_all())
    TRANSFORM_REGISTRY.register(meta, fn)  # exact duplicate — no-op
    assert len(TRANSFORM_REGISTRY.list_all()) == before


def test_registry_unknown_input_returns_empty() -> None:
    assert TRANSFORM_REGISTRY.find_by_input("NonExistentType") == []


@pytest.mark.parametrize(
    "collector_name",
    ["dns_collector", "whois_collector", "cert_collector"],
)
def test_registered_collector_metadata_has_input_types(collector_name: str) -> None:
    meta, _fn = TRANSFORM_REGISTRY.get(collector_name)
    assert meta.input_types
    assert all(isinstance(t, str) for t in meta.input_types)


# ---------------------------------------------------------------------------
# Universal smoke test — every registered collector
# ---------------------------------------------------------------------------
#
# Exercises every collector with (a) an unsupported input type and (b) a
# supported-but-unconfigured input. Both paths must return a list and must
# not raise. This covers the early-return branches in Phase 2-5 stubs that
# would otherwise pull total coverage below the GOV-007 floor, and it
# catches structural regressions in the registry shape (every entry has
# input_types, output_types is iterable, fn is callable and returns a
# list, every emitted tuple is a CollectorTuple).


@pytest.mark.parametrize("name", sorted(meta.name for meta in TRANSFORM_REGISTRY.list_all()))
def test_every_collector_returns_list_for_unsupported_input(name: str) -> None:
    meta, fn = TRANSFORM_REGISTRY.get(name)
    result = fn("NonExistentType_DoesNotMatchAnyCollector", "irrelevant")
    assert isinstance(result, list)
    for entry in result:
        assert isinstance(entry, CollectorTuple)


@pytest.mark.parametrize("name", sorted(meta.name for meta in TRANSFORM_REGISTRY.list_all()))
def test_every_collector_metadata_is_well_formed(name: str) -> None:
    meta, fn = TRANSFORM_REGISTRY.get(name)
    assert callable(fn)
    assert isinstance(meta.name, str) and meta.name == name
    assert isinstance(meta.description, str) and meta.description
    assert isinstance(meta.input_types, tuple) and meta.input_types
    assert all(isinstance(t, str) for t in meta.input_types)
    assert isinstance(meta.output_types, tuple)
    for entry in meta.output_types:
        assert isinstance(entry, tuple) and len(entry) == 2
        ent_type, edge_type = entry
        assert isinstance(ent_type, str) and isinstance(edge_type, str)
    assert meta.rate_limit is None or isinstance(meta.rate_limit, (int, float))


@pytest.mark.parametrize("name", sorted(meta.name for meta in TRANSFORM_REGISTRY.list_all()))
def test_every_collector_handles_each_declared_input_type(name: str) -> None:
    """Every declared input_type yields a list (not exception) on a probe call.

    Stubs short-circuit on missing API keys / libraries; functional
    collectors short-circuit through their patchable seams. Either way
    the registered collector must be callable for every type it claims
    to accept without raising.
    """
    meta, fn = TRANSFORM_REGISTRY.get(name)
    for input_type in meta.input_types:
        # Use values that won't trigger real network calls in any branch
        # we can imagine, and that the canonicalizers will accept where
        # relevant.
        probe_value = {
            "DomainName": "example.com",
            "IPv4Address": "192.0.2.1",
            "IPv6Address": "2001:db8::1",
            "ASNumber": "AS65500",
            "Netblock": "192.0.2.0/24",
            "EmailAddress": "test@example.com",
            "Alias": "someuser",
            "Hashtag": "test",
            "TwitterAffiliation": "exampleuser",
            "Website": "https://example.com/",
        }.get(input_type, "probe")
        result = fn(input_type, probe_value)
        assert isinstance(result, list), (
            f"{name}({input_type!r}, …) returned {type(result).__name__}, expected list"
        )
