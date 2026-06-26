"""
AGE-119 gap-type tests: CryptoWallet, Transaction, SocialAccount.

These observable models were adopted from flowsint-types v1.2.8 (Apache-2.0,
see osint/THIRD_PARTY/PROVENANCE.md) because ZettelForge lacked them. ASN and
CIDR were deliberately NOT added (ASNumber / Netblock already cover them).

No network, no disk beyond a tmp KG. Verifies the three new entity types and
their edges validate against the ontology and persist through the same
KnowledgeGraph.add_edge path the OSINT executor uses, plus the new
canonicalization helpers.
"""

from __future__ import annotations

import pytest

# Importing the osint package runs merge_into_global_ontology() as a side
# effect, registering the gap types into the global ontology.
from zettelforge import osint as _osint  # noqa: F401
from zettelforge.knowledge_graph import KnowledgeGraph
from zettelforge.ontology import ENTITY_TYPES, OntologyValidator
from zettelforge.osint.ontology import (
    canonicalize_social_account,
    canonicalize_tx_hash,
    canonicalize_wallet,
)

GAP_ENTITIES = ("CryptoWallet", "Transaction", "SocialAccount")


@pytest.fixture
def validator() -> OntologyValidator:
    return OntologyValidator()


def test_gap_entities_registered() -> None:
    for name in GAP_ENTITIES:
        assert name in ENTITY_TYPES, f"{name} not merged into global ontology"


@pytest.mark.parametrize(
    ("from_type", "edge", "to_type"),
    [
        ("CryptoWallet", "sent_transaction", "Transaction"),
        ("CryptoWallet", "received_transaction", "Transaction"),
        ("Person", "controls_wallet", "CryptoWallet"),
        ("EmailAddress", "has_account", "SocialAccount"),
    ],
)
def test_gap_edges_validate(
    validator: OntologyValidator, from_type: str, edge: str, to_type: str
) -> None:
    ok, errs = validator.validate_relation(from_type, edge, to_type)
    assert ok, f"{from_type} -{edge}-> {to_type} rejected: {errs}"


def test_gap_edge_rejects_wrong_endpoints(validator: OntologyValidator) -> None:
    # has_account does not start at a DomainName.
    ok, _ = validator.validate_relation("DomainName", "has_account", "SocialAccount")
    assert not ok


def test_wallet_transaction_persists_to_kg(tmp_path) -> None:
    kg = KnowledgeGraph(data_dir=str(tmp_path))
    wallet = canonicalize_wallet("0xAbC0000000000000000000000000000000000001")
    tx = canonicalize_tx_hash("0xDEADBEEF")

    edge_id = kg.add_edge(
        "CryptoWallet",
        wallet,
        "Transaction",
        tx,
        "sent_transaction",
        {"chain": "eth"},
    )
    assert edge_id

    node = kg.get_node("CryptoWallet", wallet)
    assert node is not None
    assert kg.get_node("Transaction", tx) is not None


def test_canonicalization_helpers() -> None:
    # EVM hex address: checksummed and lowercase fold to one canonical node.
    assert canonicalize_wallet("0xABCdef0000000000000000000000000000000001") == (
        "0xabcdef0000000000000000000000000000000001"
    )
    # Bitcoin base58 is case-sensitive: not folded, only stripped.
    assert canonicalize_wallet("  1BoatSLRHtKNngkdXEeobR76b53LETtpyT ") == (
        "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
    )
    assert canonicalize_tx_hash("  0xDEADBEEF ") == "0xdeadbeef"
    assert canonicalize_social_account("AliceB", "Twitter") == "aliceb@twitter"
