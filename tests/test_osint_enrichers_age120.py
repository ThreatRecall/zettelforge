"""
AGE-120 live-enricher tests: whois email, reverse DNS, maigret, HIBP, wallet.

Fully mocked — no network, no disk beyond a tmp KG. Each collector is driven
through its single network seam so the pure mapping logic is exercised while
the live backend is never contacted. Also covers the new seed types in the
executor and the new ontology entities/edges.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from zettelforge import osint as _osint  # noqa: F401 — registers collectors
from zettelforge.knowledge_graph import KnowledgeGraph
from zettelforge.ontology import ENTITY_TYPES, OntologyValidator
from zettelforge.osint.collectors.breach import hibp_collector
from zettelforge.osint.collectors.financial import wallet_collector
from zettelforge.osint.collectors.infrastructure import dns_collector, whois_collector
from zettelforge.osint.collectors.people import maigret_collector
from zettelforge.osint.entity_resolver import canonicalise_value
from zettelforge.osint.executor import SUPPORTED_SEED_TYPES, run_osint_collection


# ---------------------------------------------------------------------------
# Ontology additions
# ---------------------------------------------------------------------------


def test_breach_entity_registered() -> None:
    assert "Breach" in ENTITY_TYPES


@pytest.mark.parametrize(
    ("from_type", "edge", "to_type"),
    [
        ("DomainName", "registered_by", "EmailAddress"),
        ("EmailAddress", "appeared_in_breach", "Breach"),
        ("Alias", "has_account", "SocialAccount"),
        ("CryptoWallet", "sent_transaction", "Transaction"),
        ("Transaction", "received_transaction", "CryptoWallet"),
    ],
)
def test_new_edges_validate(from_type: str, edge: str, to_type: str) -> None:
    ok, errs = OntologyValidator().validate_relation(from_type, edge, to_type)
    assert ok, f"{from_type} -{edge}-> {to_type} rejected: {errs}"


def test_appeared_in_breach_rejects_wrong_source() -> None:
    ok, _ = OntologyValidator().validate_relation("DomainName", "appeared_in_breach", "Breach")
    assert not ok


# ---------------------------------------------------------------------------
# entity_resolver canonicalization for the new seed / output types
# ---------------------------------------------------------------------------


def test_canonicalise_value_new_types() -> None:
    assert canonicalise_value("EmailAddress", " Alice@Example.COM ") == "alice@example.com"
    assert canonicalise_value("Alias", " BobZ ") == "bobz"
    assert (
        canonicalise_value("CryptoWallet", "0xABCdef0000000000000000000000000000000001")
        == "0xabcdef0000000000000000000000000000000001"
    )
    assert canonicalise_value("Transaction", " 0xDEADBEEF ") == "0xdeadbeef"
    assert canonicalise_value("SocialAccount", "AliceB@Twitter") == "aliceb@twitter"
    assert canonicalise_value("Breach", " Adobe ") == "adobe"


def test_new_seed_types_supported() -> None:
    for seed in ("EmailAddress", "Alias", "CryptoWallet"):
        assert seed in SUPPORTED_SEED_TYPES


# ---------------------------------------------------------------------------
# whois — registrant EmailAddress branch
# ---------------------------------------------------------------------------


def test_whois_domain_emits_registrant_email() -> None:
    fake = SimpleNamespace(
        org="Evil Corp",
        organization=None,
        registrant=None,
        name=None,
        emails=["Abuse@Evil.example"],
    )
    with patch.object(whois_collector, "_lookup_domain", return_value=fake):
        out = whois_collector.collect("DomainName", "evil.example")

    emails = [t for t in out if t.output_entity_type == "EmailAddress"]
    assert len(emails) == 1
    tup = emails[0]
    assert tup.edge_type == "registered_by"
    assert tup.from_entity_type == "DomainName"
    assert tup.output_value == "abuse@evil.example"  # canonicalized


def test_whois_domain_no_email_field_emits_only_org() -> None:
    fake = SimpleNamespace(org="Evil Corp", organization=None, registrant=None, name=None)
    with patch.object(whois_collector, "_lookup_domain", return_value=fake):
        out = whois_collector.collect("DomainName", "evil.example")
    assert {t.output_entity_type for t in out} == {"Organization"}


# ---------------------------------------------------------------------------
# DNS — reverse PTR for IP seeds
# ---------------------------------------------------------------------------


def test_dns_reverse_ptr_emits_hosts_domain() -> None:
    resolver = MagicMock()
    resolver.resolve.return_value = ["dns.google."]
    with (
        patch.object(dns_collector, "_make_resolver", return_value=resolver),
        patch.object(dns_collector, "_reverse_pointer", return_value="8.8.8.8.in-addr.arpa"),
    ):
        out = dns_collector.collect("IPv4Address", "8.8.8.8")

    assert len(out) == 1
    tup = out[0]
    assert tup.output_entity_type == "DomainName"
    assert tup.edge_type == "hosts"
    assert tup.from_entity_type == "IPv4Address"
    assert tup.output_value == "dns.google"


def test_dns_reverse_ptr_skips_non_global_ip() -> None:
    # Reserved/private IPs are skipped before any resolver is built.
    with patch.object(dns_collector, "_make_resolver", side_effect=AssertionError):
        assert dns_collector.collect("IPv4Address", "192.0.2.1") == []
        assert dns_collector.collect("IPv4Address", "10.0.0.1") == []


# ---------------------------------------------------------------------------
# maigret — username -> SocialAccount
# ---------------------------------------------------------------------------


def test_maigret_emits_social_accounts() -> None:
    rows = [
        {"platform": "GitHub", "url": "https://github.com/bobz"},
        {"platform": "Twitter", "url": "https://twitter.com/bobz"},
    ]
    with patch.object(maigret_collector, "_search_username", return_value=rows):
        out = maigret_collector.collect("Alias", "BobZ")

    assert {t.output_entity_type for t in out} == {"SocialAccount"}
    assert all(t.edge_type == "has_account" for t in out)
    assert all(t.from_entity_type == "Alias" for t in out)
    ids = {t.output_value for t in out}
    assert ids == {"bobz@github", "bobz@twitter"}


def test_maigret_rejects_non_alias() -> None:
    assert maigret_collector.collect("EmailAddress", "x@y.com") == []


# ---------------------------------------------------------------------------
# HIBP — email -> Breach
# ---------------------------------------------------------------------------


def test_hibp_emits_breaches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIBP_API_KEY", "test-key")
    breaches = [
        {
            "Name": "Adobe",
            "Title": "Adobe",
            "Domain": "adobe.com",
            "PwnCount": 153000000,
            "DataClasses": ["Email addresses", "Passwords"],
            "IsVerified": True,
        },
        {"Name": "LinkedIn", "Domain": "linkedin.com"},
    ]
    with patch.object(hibp_collector, "_fetch_breaches", return_value=breaches) as fetch:
        out = hibp_collector.collect("EmailAddress", "Victim@Example.com")
        # key passed to the seam, email canonicalized
        fetch.assert_called_once()
        assert fetch.call_args.args[0] == "victim@example.com"
        assert fetch.call_args.args[1] == "test-key"

    assert {t.output_entity_type for t in out} == {"Breach"}
    assert all(t.edge_type == "appeared_in_breach" for t in out)
    assert {t.output_value for t in out} == {"Adobe", "LinkedIn"}


def test_hibp_fail_closed_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIBP_API_KEY", raising=False)
    assert hibp_collector.collect("EmailAddress", "x@y.com") == []


# ---------------------------------------------------------------------------
# Wallet — CryptoWallet -> Transaction
# ---------------------------------------------------------------------------


def _wallet() -> str:
    return "0x" + "ab" * 20  # 40 hex chars


def test_wallet_emits_sent_and_received(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    wallet = _wallet()
    other = "0x" + "cd" * 20
    txs = [
        {"hash": "0xAAA", "from": wallet, "to": other, "value": "10", "blockNumber": "1"},
        {"hash": "0xBBB", "from": other, "to": wallet, "value": "20", "blockNumber": "2"},
    ]
    with patch.object(wallet_collector, "_fetch_transactions", return_value=txs):
        out = wallet_collector.collect("CryptoWallet", wallet.upper())  # checksummed input

    by_edge = {t.edge_type for t in out}
    assert by_edge == {"sent_transaction", "received_transaction"}
    assert all(t.output_entity_type == "Transaction" for t in out)
    sent = next(t for t in out if t.edge_type == "sent_transaction")
    assert sent.from_entity_type == "CryptoWallet"
    assert sent.to_entity_type == "Transaction"
    assert sent.output_value == "0xaaa"


def test_wallet_rejects_non_evm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    assert wallet_collector.collect("CryptoWallet", "1BoatSLRHtKNngkdXEeobR76b53LETtpyT") == []


def test_wallet_fail_closed_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    assert wallet_collector.collect("CryptoWallet", _wallet()) == []


# ---------------------------------------------------------------------------
# Executor end-to-end: a new seed type persists through the full path
# ---------------------------------------------------------------------------


def test_executor_persists_wallet_transactions(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    kg = KnowledgeGraph(data_dir=str(tmp_path))
    wallet = _wallet()
    txs = [{"hash": "0xAAA", "from": wallet, "to": "0x" + "cd" * 20, "value": "1"}]

    with patch.object(wallet_collector, "_fetch_transactions", return_value=txs):
        result = run_osint_collection(
            "CryptoWallet",
            wallet,
            kg=kg,
            collector_names=["wallet_collector"],
        )

    assert result.error_count == 0
    assert result.persisted_count == 1
    persisted = result.persisted[0]
    assert persisted.edge_type == "sent_transaction"
    assert kg.get_node("Transaction", "0xaaa") is not None
    assert kg.get_node("CryptoWallet", wallet) is not None


def test_executor_accepts_email_seed_without_keys(tmp_path) -> None:
    # No API keys set: every EmailAddress collector fails closed, but the seed
    # still validates and persists and the run does not raise.
    kg = KnowledgeGraph(data_dir=str(tmp_path))
    result = run_osint_collection("EmailAddress", "Person@Example.com", kg=kg)
    assert result.canonical_input_value == "person@example.com"
    assert result.seed_node_id is not None
