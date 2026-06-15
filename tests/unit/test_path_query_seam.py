"""Unit tests for the scoped Neo4j path-query seam (AGE-117), no live DB.

Covers the default-backend undirected BFS ``shortest_path`` (the fallback /
pathfinding-disabled path) and the ``find_shortest_path`` router when Neo4j
pathfinding is disabled. The Neo4j-routed path and fail-loud behavior need a
real driver and live in the integration suite behind ``requires_neo4j``.
"""

from __future__ import annotations

import zettelforge.knowledge_graph as kg_mod
from zettelforge.knowledge_graph import KnowledgeGraph


def _diamond(data_dir: object) -> KnowledgeGraph:
    """A -> B -> D and A -> C -> D: two length-2 paths, one shortest each way.

    Also adds a stray E off to the side (unconnected to D) to confirm no-path.
    """
    kg = KnowledgeGraph(data_dir=str(data_dir))
    kg.add_edge("Actor", "a", "Tool", "b", "uses")
    kg.add_edge("Tool", "b", "CVE", "d", "exploits")
    kg.add_edge("Actor", "a", "Tool", "c", "uses")
    kg.add_edge("Tool", "c", "CVE", "d", "exploits")
    kg.add_node("Asset", "e")
    return kg


def test_shortest_path_finds_two_hop(tmp_path: object) -> None:
    kg = _diamond(tmp_path)
    path = kg.shortest_path("Actor", "a", "CVE", "d")
    assert path is not None
    assert len(path) == 2
    # Steps are ordered start -> goal and report stored edge orientation.
    assert path[0]["from_value"] == "a"
    assert path[-1]["to_value"] == "d"


def test_shortest_path_is_undirected(tmp_path: object) -> None:
    """Querying d -> a (against edge direction) still finds the path."""
    kg = _diamond(tmp_path)
    path = kg.shortest_path("CVE", "d", "Actor", "a")
    assert path is not None
    assert len(path) == 2


def test_shortest_path_no_path_returns_none(tmp_path: object) -> None:
    kg = _diamond(tmp_path)
    assert kg.shortest_path("Actor", "a", "Asset", "e") is None


def test_shortest_path_unknown_endpoint_returns_none(tmp_path: object) -> None:
    kg = _diamond(tmp_path)
    assert kg.shortest_path("Actor", "a", "CVE", "missing") is None


def test_shortest_path_same_node_is_empty(tmp_path: object) -> None:
    kg = _diamond(tmp_path)
    assert kg.shortest_path("Actor", "a", "Actor", "a") == []


def test_shortest_path_respects_max_depth(tmp_path: object) -> None:
    """A linear chain longer than max_depth yields no path."""
    kg = KnowledgeGraph(data_dir=str(tmp_path))
    kg.add_edge("N", "1", "N", "2", "r")
    kg.add_edge("N", "2", "N", "3", "r")
    kg.add_edge("N", "3", "N", "4", "r")
    assert kg.shortest_path("N", "1", "N", "4", max_depth=2) is None
    assert kg.shortest_path("N", "1", "N", "4", max_depth=3) is not None


def test_find_shortest_path_routes_to_default_when_disabled(
    tmp_path: object, monkeypatch: object
) -> None:
    """pathfinding disabled => the default backend answers, Neo4j is untouched."""
    from zettelforge.config import reload_config

    monkeypatch.delenv("ZETTELFORGE_NEO4J_PATHFINDING", raising=False)  # type: ignore[attr-defined]
    monkeypatch.setenv("ZETTELFORGE_BACKEND", "sqlite")  # type: ignore[attr-defined]
    reload_config()
    kg_mod._kg_instance = _diamond(tmp_path)
    kg_mod._neo4j_path_backend = None
    try:
        path = kg_mod.find_shortest_path("Actor", "a", "CVE", "d")
        assert path is not None and len(path) == 2
    finally:
        kg_mod._kg_instance = None
