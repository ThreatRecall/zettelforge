"""Tests for BlendedRetriever - combines vector + graph results."""
import pytest
from datetime import datetime

from zettelforge.blended_retriever import BlendedRetriever
from zettelforge.graph_retriever import ScoredResult
from zettelforge.note_schema import MemoryNote, Content, Semantic, Embedding, Metadata

NOW = datetime.now().isoformat()


def _make_note(note_id: str, raw: str) -> MemoryNote:
    return MemoryNote(
        id=note_id, created_at=NOW, updated_at=NOW,
        content=Content(raw=raw, source_type="test", source_ref=""),
        semantic=Semantic(context=raw[:50], keywords=[], tags=[], entities=[]),
        embedding=Embedding(vector=[0.1] * 768), metadata=Metadata(),
    )


class TestBlendedRetriever:
    def test_vector_only_when_no_graph_results(self):
        vector_notes = [_make_note("v1", "vector result 1"), _make_note("v2", "vector result 2")]
        policy = {"vector": 0.5, "graph": 0.5, "entity_index": 0.0, "temporal": 0.0, "top_k": 10}
        blended = BlendedRetriever()
        results = blended.blend(vector_results=vector_notes, graph_results=[], policy=policy, note_lookup=lambda nid: None, k=10)
        assert len(results) == 2
        assert results[0].id == "v1"

    def test_graph_only_when_no_vector_results(self):
        note_g1 = _make_note("g1", "graph result 1")
        graph_scored = [ScoredResult(note_id="g1", score=0.8, hops=1, path=[])]
        policy = {"vector": 0.5, "graph": 0.5, "entity_index": 0.0, "temporal": 0.0, "top_k": 10}
        blended = BlendedRetriever()
        results = blended.blend(vector_results=[], graph_results=graph_scored, policy=policy, note_lookup=lambda nid: note_g1 if nid == "g1" else None, k=10)
        assert len(results) == 1
        assert results[0].id == "g1"

    def test_blending_merges_and_deduplicates(self):
        shared_note = _make_note("shared", "appears in both")
        vector_notes = [shared_note, _make_note("v_only", "vector only")]
        graph_scored = [ScoredResult(note_id="shared", score=0.9, hops=1, path=[]), ScoredResult(note_id="g_only", score=0.5, hops=2, path=[])]
        note_g_only = _make_note("g_only", "graph only")
        policy = {"vector": 0.5, "graph": 0.5, "entity_index": 0.0, "temporal": 0.0, "top_k": 10}
        def lookup(nid):
            return {"g_only": note_g_only, "shared": shared_note}.get(nid)
        blended = BlendedRetriever()
        results = blended.blend(vector_results=vector_notes, graph_results=graph_scored, policy=policy, note_lookup=lookup, k=10)
        ids = [r.id for r in results]
        assert ids.count("shared") == 1
        assert "v_only" in ids
        assert "g_only" in ids

    def test_shared_note_ranks_higher(self):
        shared_note = _make_note("shared", "appears in both")
        v_only = _make_note("v_only", "vector only")
        g_only_note = _make_note("g_only", "graph only")
        vector_notes = [shared_note, v_only]
        graph_scored = [ScoredResult(note_id="shared", score=0.8, hops=1, path=[]), ScoredResult(note_id="g_only", score=0.3, hops=2, path=[])]
        policy = {"vector": 0.5, "graph": 0.5, "entity_index": 0.0, "temporal": 0.0, "top_k": 10}
        def lookup(nid):
            return {"g_only": g_only_note, "shared": shared_note}.get(nid)
        blended = BlendedRetriever()
        results = blended.blend(vector_results=vector_notes, graph_results=graph_scored, policy=policy, note_lookup=lookup, k=10)
        assert results[0].id == "shared"

    def test_respects_k_limit(self):
        vector_notes = [_make_note(f"v{i}", f"note {i}") for i in range(10)]
        policy = {"vector": 1.0, "graph": 0.0, "entity_index": 0.0, "temporal": 0.0, "top_k": 10}
        blended = BlendedRetriever()
        results = blended.blend(vector_results=vector_notes, graph_results=[], policy=policy, note_lookup=lambda nid: None, k=3)
        assert len(results) == 3

    def test_policy_weights_affect_ranking(self):
        v_note = _make_note("v_only", "vector only")
        g_note = _make_note("g_only", "graph only")
        vector_notes = [v_note]
        graph_scored = [ScoredResult(note_id="g_only", score=0.9, hops=1, path=[])]
        policy = {"vector": 0.1, "graph": 0.9, "entity_index": 0.0, "temporal": 0.0, "top_k": 10}
        blended = BlendedRetriever()
        results = blended.blend(vector_results=vector_notes, graph_results=graph_scored, policy=policy, note_lookup=lambda nid: g_note if nid == "g_only" else None, k=10)
        assert results[0].id == "g_only"
