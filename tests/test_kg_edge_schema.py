"""Regression test for v2.5.1 hotfix: KnowledgeGraph._cache_edge crashed
with KeyError on legacy edges that used {source_id, target_id, relation_type}
instead of {from_node_id, to_node_id, relationship}.

Tickled in production by long-running deployments where pre-v2.5.x writers
left ~80k+ legacy entries in kg_edges.jsonl alongside canonical-shape rows.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from zettelforge.knowledge_graph import KnowledgeGraph, _normalize_edge_schema


def test_normalize_edge_schema_passes_canonical_shape_through():
    edge = {
        "edge_id": "edge_1",
        "from_node_id": "node_a",
        "to_node_id": "node_b",
        "relationship": "MENTIONED_IN",
    }
    normalized = _normalize_edge_schema(edge)
    assert normalized == edge


def test_normalize_edge_schema_remaps_legacy_keys():
    legacy = {
        "edge_id": "edge_2",
        "source_id": "node_a",
        "target_id": "node_b",
        "relation_type": "MENTIONED_IN",
    }
    normalized = _normalize_edge_schema(legacy)
    assert normalized is not None
    assert normalized["from_node_id"] == "node_a"
    assert normalized["to_node_id"] == "node_b"
    assert normalized["relationship"] == "MENTIONED_IN"
    # Legacy keys preserved alongside the canonical ones (we don't drop them
    # on load — write path will overwrite if needed).
    assert normalized["source_id"] == "node_a"


def test_normalize_edge_schema_returns_none_when_unrecoverable():
    # Missing both legacy and canonical id keys — cannot cache without them.
    assert _normalize_edge_schema({"edge_id": "edge_3"}) is None
    # Missing edge_id — cannot index even if we had the rest.
    assert (
        _normalize_edge_schema({"from_node_id": "a", "to_node_id": "b", "relationship": "R"})
        is None
    )
    # Missing relationship (and no legacy relation_type to remap from).
    # Downstream code does direct subscripting on edge["relationship"], so
    # entries without it must be rejected at load time, not deferred.
    assert (
        _normalize_edge_schema(
            {"edge_id": "edge_4", "from_node_id": "a", "to_node_id": "b"}
        )
        is None
    )


def test_normalize_edge_schema_handles_non_dict():
    assert _normalize_edge_schema("not a dict") is None
    assert _normalize_edge_schema(None) is None


def test_load_all_tolerates_mixed_schema_kg_edges():
    """KnowledgeGraph._load_all() must not crash when kg_edges.jsonl contains
    both canonical and legacy edge entries."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # Two canonical edges + one legacy + one totally broken.
        edges = [
            {
                "edge_id": "edge_1",
                "from_node_id": "node_a",
                "to_node_id": "node_b",
                "relationship": "MENTIONED_IN",
                "properties": {},
            },
            {
                "edge_id": "edge_2",
                "source_id": "node_c",
                "target_id": "node_d",
                "relation_type": "MENTIONED_IN",
                "properties": {},
            },
            {"edge_id": "edge_3"},  # malformed — no nodes
            {
                "edge_id": "edge_4",
                "from_node_id": "node_e",
                "to_node_id": "node_f",
                "relationship": "TEMPORAL_BEFORE",
                "properties": {"timestamp": "2026-04-25T00:00:00Z"},
            },
        ]
        edges_file = data_dir / "kg_edges.jsonl"
        with open(edges_file, "w") as f:
            for edge in edges:
                f.write(json.dumps(edge) + "\n")

        # Even with a broken entry mixed in, construction must succeed and the
        # cache must contain the three salvageable edges.
        kg = KnowledgeGraph(data_dir=str(data_dir))
        assert "edge_1" in kg._edges
        assert "edge_2" in kg._edges  # legacy schema normalized in
        assert "edge_4" in kg._edges
        assert "edge_3" not in kg._edges  # dropped — no node ids

        # The legacy entry's normalized from_node_id wires into the index.
        assert "node_c" in kg._edges_from
        assert "node_d" in kg._edges_to


def test_load_all_skips_corrupt_json_lines():
    """Pre-existing tolerance for malformed JSON should still hold."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        edges_file = data_dir / "kg_edges.jsonl"
        with open(edges_file, "w") as f:
            f.write(
                '{"edge_id": "ok", "from_node_id": "a", "to_node_id": "b", "relationship": "R"}\n'
            )
            f.write("{not valid json\n")
            f.write(
                '{"edge_id": "ok2", "from_node_id": "c", "to_node_id": "d", "relationship": "R"}\n'
            )

        kg = KnowledgeGraph(data_dir=str(data_dir))
        assert "ok" in kg._edges
        assert "ok2" in kg._edges
        assert len(kg._edges) == 2
