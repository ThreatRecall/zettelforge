"""Unit tests for Neo4jKnowledgeGraph mapping/encoding logic (no live DB).

These cover the pure, deterministic parts of the backend: property
encode/decode, node/edge result mapping to the default-backend shape, the
ImportError surface when the driver extra is missing, and the depth-bound
inlining that the variable-length Cypher requires. Anything needing a real
Neo4j lives in the integration suite behind the ``requires_neo4j`` marker.
"""

from __future__ import annotations

import builtins

import pytest

from zettelforge.neo4j_knowledge_graph import Neo4jKnowledgeGraph, Neo4jUnavailableError


@pytest.fixture
def kg() -> Neo4jKnowledgeGraph:
    # _skip_init_schema avoids any connection attempt; we only exercise the
    # pure classmethods/staticmethods here.
    return Neo4jKnowledgeGraph(_skip_init_schema=True)


def test_encode_decode_roundtrip() -> None:
    props = {"a": 1, "nested": {"x": [1, 2, 3]}, "s": "v"}
    encoded = Neo4jKnowledgeGraph._encode_props(props)
    assert isinstance(encoded, str)
    assert Neo4jKnowledgeGraph._decode_props(encoded) == props


def test_encode_none_props() -> None:
    assert Neo4jKnowledgeGraph._encode_props(None) == "{}"


def test_decode_handles_dict_and_garbage() -> None:
    assert Neo4jKnowledgeGraph._decode_props({"already": "dict"}) == {"already": "dict"}
    assert Neo4jKnowledgeGraph._decode_props(None) == {}
    assert Neo4jKnowledgeGraph._decode_props("not json") == {}
    assert Neo4jKnowledgeGraph._decode_props("") == {}


def test_node_out_shape_matches_default_backend() -> None:
    raw = {
        "node_id": "node_abc",
        "entity_type": "ThreatActor",
        "entity_value": "APT28",
        "properties": '{"k": "v"}',
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-02T00:00:00",
    }
    out = Neo4jKnowledgeGraph._node_out(raw)
    assert set(out.keys()) == {
        "node_id",
        "entity_type",
        "entity_value",
        "properties",
        "created_at",
        "updated_at",
    }
    assert out["properties"] == {"k": "v"}
    assert out["entity_value"] == "APT28"


def test_edge_out_shape_matches_default_backend() -> None:
    raw = {
        "edge_id": "edge_xyz",
        "from_node_id": "node_a",
        "to_node_id": "node_b",
        "relationship": "uses",
        "edge_type": "causal",
        "note_id": "note_1",
        "properties": '{"confidence": 0.9}',
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    out = Neo4jKnowledgeGraph._edge_out(raw)
    assert set(out.keys()) == {
        "edge_id",
        "from_node_id",
        "to_node_id",
        "relationship",
        "edge_type",
        "note_id",
        "properties",
        "created_at",
        "updated_at",
    }
    assert out["edge_type"] == "causal"
    assert out["properties"] == {"confidence": 0.9}


def test_edge_out_defaults_edge_type_heuristic() -> None:
    raw = {
        "edge_id": "e1",
        "from_node_id": "a",
        "to_node_id": "b",
        "relationship": "rel",
        "properties": "{}",
    }
    out = Neo4jKnowledgeGraph._edge_out(raw)
    assert out["edge_type"] == "heuristic"


def test_missing_driver_raises_clear_error(
    kg: Neo4jKnowledgeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "neo4j":
            raise ImportError("No module named 'neo4j'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(Neo4jUnavailableError) as exc:
        kg._get_driver()
    assert "zettelforge[neo4j]" in str(exc.value)


def test_traverse_caps_depth_to_config(
    kg: Neo4jKnowledgeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    kg._max_depth = 5
    captured: dict[str, object] = {}

    def fake_execute_read(fn: object, **kwargs: object) -> tuple[list, bool]:
        captured.update(kwargs)
        return [], False

    monkeypatch.setattr(kg, "_execute_read", fake_execute_read)
    kg.traverse("ThreatActor", "APT28", max_depth=99)
    # max_depth is clamped to the configured cap (5), never exceeded.
    assert captured["depth"] == 5


def test_shortest_path_defaults_depth_to_config_cap(
    kg: Neo4jKnowledgeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    kg._max_depth = 7
    captured: dict[str, object] = {}

    def fake_execute_read(fn: object, **kwargs: object) -> None:
        captured.update(kwargs)
        return None

    monkeypatch.setattr(kg, "_execute_read", fake_execute_read)
    kg.shortest_path("A", "a", "B", "b")  # max_depth=None -> config cap
    assert captured["depth"] == 7
