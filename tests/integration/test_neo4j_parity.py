"""Parity tests: Neo4jKnowledgeGraph vs the SQLite default backend (SC-001).

Loads the same nodes/edges into both backends and asserts the Neo4j backend
returns the same data, in the same return shapes, for the operations the
public interface covers. Gated by ``requires_neo4j``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_neo4j


_EDGES = [
    ("ThreatActor", "APT28", "Malware", "X-Agent", "uses"),
    ("Malware", "X-Agent", "Vulnerability", "CVE-2017-0144", "exploits"),
    ("Vulnerability", "CVE-2017-0144", "Asset", "SMBv1", "affects"),
    ("ThreatActor", "APT28", "Tool", "Mimikatz", "uses"),
]


def _load_both(neo4j_kg: object, sqlite_backend: object) -> None:
    for ft, fv, tt, tv, rel in _EDGES:
        neo4j_kg.add_edge(ft, fv, tt, tv, rel)
        sqlite_backend.add_kg_edge(ft, fv, tt, tv, rel)


def test_add_node_returns_id_and_is_idempotent(neo4j_kg: object) -> None:
    nid1 = neo4j_kg.add_node("ThreatActor", "APT29")
    nid2 = neo4j_kg.add_node("ThreatActor", "APT29")
    assert nid1 == nid2
    assert nid1.startswith("node_")


def test_get_node_shape_parity(neo4j_kg: object, sqlite_backend: object) -> None:
    _load_both(neo4j_kg, sqlite_backend)
    n_node = neo4j_kg.get_node("ThreatActor", "APT28")
    s_node = sqlite_backend.get_kg_node("ThreatActor", "APT28")
    assert n_node is not None and s_node is not None
    # Same keys and same identity fields (node_id values differ by design).
    assert set(n_node.keys()) >= {"node_id", "entity_type", "entity_value", "properties"}
    assert n_node["entity_type"] == s_node["entity_type"]
    assert n_node["entity_value"] == s_node["entity_value"]


def test_get_node_missing_returns_none(neo4j_kg: object) -> None:
    assert neo4j_kg.get_node("ThreatActor", "DoesNotExist") is None


def test_neighbors_parity(neo4j_kg: object, sqlite_backend: object) -> None:
    _load_both(neo4j_kg, sqlite_backend)
    n_neigh = neo4j_kg.get_neighbors("ThreatActor", "APT28")
    s_neigh = sqlite_backend.get_kg_neighbors("ThreatActor", "APT28")
    assert len(n_neigh) == len(s_neigh) == 2
    # Same neighbor set (by entity_value), same result shape.
    n_vals = {x["node"]["entity_value"] for x in n_neigh}
    s_vals = {x["node"]["entity_value"] for x in s_neigh}
    assert n_vals == s_vals == {"X-Agent", "Mimikatz"}
    for x in n_neigh:
        assert set(x.keys()) == {"node", "relationship", "edge_properties"}


def test_neighbors_relationship_filter(neo4j_kg: object) -> None:
    neo4j_kg.add_edge("A", "a", "B", "b", "uses")
    neo4j_kg.add_edge("A", "a", "C", "c", "targets")
    only_uses = neo4j_kg.get_neighbors("A", "a", relationship="uses")
    assert len(only_uses) == 1
    assert only_uses[0]["node"]["entity_value"] == "b"


def test_edge_dedup_and_type_promotion(neo4j_kg: object) -> None:
    e1 = neo4j_kg.add_edge("X", "x", "Y", "y", "causes")  # heuristic default
    e2 = neo4j_kg.add_edge("X", "x", "Y", "y", "causes", {"edge_type": "causal"})
    assert e1 == e2  # dedup on (from, to, relationship)
    node = neo4j_kg.get_node("X", "x")
    edges = neo4j_kg.get_outgoing_edges(node["node_id"])
    assert len(edges) == 1
    assert edges[0]["edge_type"] == "causal"  # promoted from heuristic


def test_causal_edges(neo4j_kg: object) -> None:
    neo4j_kg.add_edge("Cause", "c1", "Effect", "e1", "leads_to", {"edge_type": "causal"})
    neo4j_kg.add_edge("Effect", "e1", "Effect", "e2", "leads_to", {"edge_type": "causal"})
    out = neo4j_kg.get_causal_edges("Cause", "c1", max_depth=3)
    assert len(out) >= 2
    incoming = neo4j_kg.get_incoming_causal("Effect", "e2", max_depth=3)
    assert len(incoming) >= 1


def test_temporal_timeline_and_changes(neo4j_kg: object) -> None:
    neo4j_kg.add_temporal_edge("Host", "h1", "State", "patched", "SUPERSEDES", "2026-01-01T00:00:00")
    neo4j_kg.add_temporal_edge(
        "Host", "h1", "State", "compromised", "TEMPORAL_AFTER", "2026-02-01T00:00:00"
    )
    timeline = neo4j_kg.get_entity_timeline("Host", "h1")
    assert len(timeline) == 2
    # Ordered by timestamp ascending.
    assert timeline[0]["timestamp"] <= timeline[1]["timestamp"]
    # get_changes_since filters on created_at (wall-clock insert time), matching
    # the SQLite backend: both edges were just written, so both are returned for
    # any past cutoff and none for a future one.
    assert len(neo4j_kg.get_changes_since("2026-01-15T00:00:00")) == 2
    assert len(neo4j_kg.get_changes_since("2099-01-01T00:00:00")) == 0
    latest = neo4j_kg.get_latest_state("Host", "h1")
    assert latest is not None
