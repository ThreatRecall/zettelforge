"""
Tests for TypeDB Knowledge Graph client.
Requires TypeDB running on localhost:1729.
"""
import pytest
import uuid
from zettelforge.typedb_client import TypeDBKnowledgeGraph


@pytest.fixture
def kg():
    """Fresh TypeDB KG with isolated test database."""
    db_name = f"test_{uuid.uuid4().hex[:8]}"
    try:
        kg = TypeDBKnowledgeGraph(database=db_name)
        yield kg
        # Cleanup
        kg._driver.databases.get(db_name).delete()
        kg.close()
    except Exception as e:
        pytest.skip(f"TypeDB not available: {e}")


class TestTypeDBNodes:
    def test_add_node_returns_id(self, kg):
        node_id = kg.add_node("actor", "apt28")
        assert node_id != ""
        assert "node_" in node_id

    def test_add_node_idempotent(self, kg):
        id1 = kg.add_node("actor", "apt28")
        id2 = kg.add_node("actor", "apt28")
        assert id1 == id2

    def test_add_note_node(self, kg):
        node_id = kg.add_node("note", "note_20260409_001")
        assert node_id != ""

    def test_get_node(self, kg):
        kg.add_node("actor", "apt28")
        node = kg.get_node("actor", "apt28")
        assert node is not None
        assert node["entity_type"] == "actor"
        assert node["entity_value"] == "apt28"

    def test_get_node_nonexistent(self, kg):
        node = kg.get_node("actor", "nonexistent")
        assert node is None


class TestTypeDBEdges:
    def test_add_edge_creates_relation(self, kg):
        edge_id = kg.add_edge("actor", "apt28", "malware", "dropbear", "USES_TOOL")
        assert edge_id != ""

    def test_add_edge_auto_creates_nodes(self, kg):
        kg.add_edge("actor", "apt28", "malware", "dropbear", "USES_TOOL")
        assert kg.get_node("actor", "apt28") is not None
        assert kg.get_node("malware", "dropbear") is not None

    def test_add_edge_duplicate_returns_same(self, kg):
        id1 = kg.add_edge("actor", "apt28", "malware", "dropbear", "USES_TOOL")
        id2 = kg.add_edge("actor", "apt28", "malware", "dropbear", "USES_TOOL")
        assert id1 == id2

    def test_mentioned_in_edge(self, kg):
        kg.add_edge("actor", "apt28", "note", "note_001", "MENTIONED_IN")
        neighbors = kg.get_neighbors("actor", "apt28", "MENTIONED_IN")
        note_ids = [n["node"]["entity_value"] for n in neighbors]
        assert "note_001" in note_ids


class TestTypeDBNeighbors:
    def test_get_neighbors(self, kg):
        kg.add_edge("actor", "apt28", "malware", "dropbear", "USES_TOOL")
        kg.add_edge("actor", "apt28", "cve", "cve-2024-1111", "EXPLOITS_CVE")
        neighbors = kg.get_neighbors("actor", "apt28")
        assert len(neighbors) >= 2

    def test_get_neighbors_filtered(self, kg):
        kg.add_edge("actor", "apt28", "malware", "dropbear", "USES_TOOL")
        kg.add_edge("actor", "apt28", "cve", "cve-2024-1111", "EXPLOITS_CVE")
        neighbors = kg.get_neighbors("actor", "apt28", "USES_TOOL")
        assert len(neighbors) == 1
        assert neighbors[0]["node"]["entity_value"] == "dropbear"

    def test_get_neighbors_empty(self, kg):
        neighbors = kg.get_neighbors("actor", "nonexistent")
        assert neighbors == []


class TestTypeDBTraversal:
    def test_traverse_finds_paths(self, kg):
        kg.add_edge("actor", "apt28", "malware", "dropbear", "USES_TOOL")
        kg.add_edge("malware", "dropbear", "note", "note_001", "MENTIONED_IN")
        paths = kg.traverse("actor", "apt28", max_depth=2)
        assert len(paths) >= 1

    def test_traverse_respects_depth(self, kg):
        kg.add_edge("actor", "apt28", "malware", "dropbear", "USES_TOOL")
        kg.add_edge("malware", "dropbear", "note", "note_001", "MENTIONED_IN")
        paths_shallow = kg.traverse("actor", "apt28", max_depth=1)
        paths_deep = kg.traverse("actor", "apt28", max_depth=2)
        assert len(paths_deep) >= len(paths_shallow)

    def test_traverse_empty_for_unknown(self, kg):
        paths = kg.traverse("actor", "nonexistent", max_depth=2)
        assert paths == []


class TestTypeDBTemporal:
    def test_add_temporal_edge(self, kg):
        edge_id = kg.add_temporal_edge(
            "note", "note_002", "note", "note_001",
            "SUPERSEDES", "2026-04-09T10:00:00"
        )
        assert edge_id != ""

    def test_get_entity_timeline(self, kg):
        kg.add_temporal_edge(
            "note", "note_002", "note", "note_001",
            "SUPERSEDES", "2026-04-09T10:00:00"
        )
        timeline = kg.get_entity_timeline("note", "note_002")
        assert len(timeline) >= 1

    def test_get_changes_since(self, kg):
        kg.add_temporal_edge(
            "note", "note_002", "note", "note_001",
            "SUPERSEDES", "2026-04-09T10:00:00"
        )
        changes = kg.get_changes_since("2026-04-09T00:00:00")
        assert len(changes) >= 1


class TestSTIXIDs:
    def test_deterministic_stix_id(self, kg):
        id1 = kg._stix_id("actor", "apt28")
        id2 = kg._stix_id("actor", "apt28")
        assert id1 == id2
        assert id1.startswith("threat-actor--")

    def test_different_entities_different_ids(self, kg):
        id1 = kg._stix_id("actor", "apt28")
        id2 = kg._stix_id("actor", "apt29")
        assert id1 != id2
