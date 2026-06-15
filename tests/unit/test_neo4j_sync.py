"""Unit tests for the Neo4j sync source-read path (no Neo4j needed).

Covers the SQLite bulk KG readers added for the standalone sync job and
``read_source_graph``'s edge dedup / orphan accounting. The Neo4j load itself
is exercised by ``tests/integration/test_neo4j_sync.py`` (requires_neo4j).
"""

from __future__ import annotations

from pathlib import Path

from zettelforge.scripts.neo4j_sync import read_source_graph
from zettelforge.sqlite_backend import SQLiteBackend


def _seeded_backend(tmp_path: Path) -> SQLiteBackend:
    backend = SQLiteBackend(data_dir=str(tmp_path))
    backend.initialize()
    backend.add_kg_node("ThreatActor", "APT28", {"aka": "Fancy Bear"})
    backend.add_kg_edge("ThreatActor", "APT28", "Malware", "X-Agent", "uses")
    backend.add_kg_edge(
        "Malware",
        "X-Agent",
        "Vulnerability",
        "CVE-2017-0144",
        "exploits",
        properties={"edge_type": "causal", "confidence": 0.9},
    )
    return backend


def test_get_all_kg_nodes_returns_parsed_properties(tmp_path: Path) -> None:
    backend = _seeded_backend(tmp_path)
    try:
        nodes = backend.get_all_kg_nodes()
    finally:
        backend.close()
    by_value = {n["entity_value"]: n for n in nodes}
    # Endpoints created by add_kg_edge are present alongside the explicit node.
    assert set(by_value) == {"APT28", "X-Agent", "CVE-2017-0144"}
    assert by_value["APT28"]["properties"] == {"aka": "Fancy Bear"}
    assert by_value["APT28"]["entity_type"] == "ThreatActor"


def test_get_all_kg_edges_resolves_endpoint_identities(tmp_path: Path) -> None:
    backend = _seeded_backend(tmp_path)
    try:
        edges = backend.get_all_kg_edges()
    finally:
        backend.close()
    edges_by_rel = {e["relationship"]: e for e in edges}
    assert edges_by_rel["uses"]["from_type"] == "ThreatActor"
    assert edges_by_rel["uses"]["from_value"] == "APT28"
    assert edges_by_rel["uses"]["to_value"] == "X-Agent"
    # edge_type column surfaced; remaining props in the parsed dict.
    assert edges_by_rel["exploits"]["edge_type"] == "causal"
    assert edges_by_rel["exploits"]["properties"] == {"confidence": 0.9}


def test_count_kg(tmp_path: Path) -> None:
    backend = _seeded_backend(tmp_path)
    try:
        nodes, edges = backend.count_kg()
    finally:
        backend.close()
    assert (nodes, edges) == (3, 2)


def test_read_source_graph_dedups_edges_by_neo4j_identity(tmp_path: Path) -> None:
    backend = SQLiteBackend(data_dir=str(tmp_path))
    backend.initialize()
    # Same (from, to, relationship) but distinct note_id: two SQLite rows
    # (UNIQUE includes note_id) that collapse to ONE Neo4j relationship.
    backend.add_kg_edge("a", "1", "b", "2", "rel", note_id="note_x")
    backend.add_kg_edge("a", "1", "b", "2", "rel", note_id="note_y")
    try:
        src = read_source_graph(backend)
    finally:
        backend.close()
    assert len(src["edges"]) == 1
    assert src["orphan_edges"] == 0


def test_read_source_graph_counts_orphan_edges(tmp_path: Path) -> None:
    backend = SQLiteBackend(data_dir=str(tmp_path))
    backend.initialize()
    backend.add_kg_edge("a", "1", "b", "2", "rel")
    # Inject an edge with a dangling endpoint (no matching kg_nodes row). The
    # INNER JOIN drops it; the orphan count must make that visible.
    with backend._write_lock:
        backend._conn.execute(
            "INSERT INTO kg_edges (edge_id, from_node_id, to_node_id, relationship, "
            "edge_type, note_id, properties, created_at, updated_at) "
            "VALUES ('edge_orphan', 'node_missing', 'node_missing2', 'rel', "
            "'heuristic', '', '{}', '', '')"
        )
        backend._conn.commit()
    try:
        src = read_source_graph(backend)
    finally:
        backend.close()
    assert len(src["edges"]) == 1
    assert src["orphan_edges"] == 1
