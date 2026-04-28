"""Tests for GraphRetriever - graph-based note retrieval."""
import pytest
import tempfile
from datetime import datetime

from zettelforge.graph_retriever import GraphRetriever, ScoredResult
from zettelforge.knowledge_graph import KnowledgeGraph


NOW = datetime.now().isoformat()


@pytest.fixture
def kg_with_data():
    """KG with a small graph: actor -> tool -> note, actor -> cve -> note."""
    tmpdir = tempfile.mkdtemp()
    kg = KnowledgeGraph(data_dir=tmpdir)
    kg.add_edge("actor", "apt28", "tool", "cobalt-strike", "USES_TOOL")
    kg.add_edge("actor", "apt28", "cve", "cve-2024-1111", "EXPLOITS_CVE")
    kg.add_edge("tool", "cobalt-strike", "note", "note_001", "MENTIONED_IN")
    kg.add_edge("cve", "cve-2024-1111", "note", "note_002", "MENTIONED_IN")
    kg.add_edge("actor", "apt28", "note", "note_003", "MENTIONED_IN")
    return kg


class TestScoredResult:
    def test_creation(self):
        sr = ScoredResult(note_id="note_001", score=0.5, hops=2, path=["apt28", "cobalt-strike", "note_001"])
        assert sr.note_id == "note_001"
        assert sr.score == 0.5
        assert sr.hops == 2


class TestGraphRetrieverTraverse:
    def test_finds_direct_notes(self, kg_with_data):
        retriever = GraphRetriever(kg_with_data)
        results = retriever.retrieve_note_ids(query_entities={"actor": ["apt28"]}, max_depth=2)
        note_ids = [r.note_id for r in results]
        assert "note_003" in note_ids

    def test_finds_multihop_notes(self, kg_with_data):
        retriever = GraphRetriever(kg_with_data)
        results = retriever.retrieve_note_ids(query_entities={"actor": ["apt28"]}, max_depth=2)
        note_ids = [r.note_id for r in results]
        assert "note_001" in note_ids
        assert "note_002" in note_ids

    def test_direct_notes_score_higher(self, kg_with_data):
        retriever = GraphRetriever(kg_with_data)
        results = retriever.retrieve_note_ids(query_entities={"actor": ["apt28"]}, max_depth=2)
        scores = {r.note_id: r.score for r in results}
        assert scores["note_003"] > scores["note_001"]

    def test_empty_entities_returns_empty(self, kg_with_data):
        retriever = GraphRetriever(kg_with_data)
        results = retriever.retrieve_note_ids(query_entities={}, max_depth=2)
        assert results == []

    def test_unknown_entity_returns_empty(self, kg_with_data):
        retriever = GraphRetriever(kg_with_data)
        results = retriever.retrieve_note_ids(query_entities={"actor": ["nonexistent"]}, max_depth=2)
        assert results == []

    def test_max_depth_limits_hops(self, kg_with_data):
        retriever = GraphRetriever(kg_with_data)
        results = retriever.retrieve_note_ids(query_entities={"actor": ["apt28"]}, max_depth=1)
        note_ids = [r.note_id for r in results]
        assert "note_003" in note_ids
        assert "note_001" not in note_ids
        assert "note_002" not in note_ids

    def test_deduplicates_notes(self, kg_with_data):
        kg_with_data.add_edge("tool", "cobalt-strike", "note", "note_003", "MENTIONED_IN")
        retriever = GraphRetriever(kg_with_data)
        results = retriever.retrieve_note_ids(query_entities={"actor": ["apt28"]}, max_depth=2)
        note_003_results = [r for r in results if r.note_id == "note_003"]
        assert len(note_003_results) == 1
        assert note_003_results[0].hops == 1
