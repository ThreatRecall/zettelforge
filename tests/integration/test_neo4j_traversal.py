"""Deep traversal and shortest-path tests (SC-002), gated by ``requires_neo4j``.

Verifies the capability the default backend lacks: complete multi-hop
traversal beyond depth 2, shortest-path between indirectly connected entities,
and an explicit no-path result.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_neo4j


def _build_chain(kg: object, length: int) -> list[str]:
    """Build a linear chain n0 -> n1 -> ... and return the node values."""
    values = [f"N{i}" for i in range(length)]
    for i in range(length - 1):
        kg.add_edge("Chain", values[i], "Chain", values[i + 1], "next")
    return values


def test_traverse_reaches_depth_5(neo4j_kg: object) -> None:
    values = _build_chain(neo4j_kg, 7)  # n0..n6, depth-6 chain
    paths = neo4j_kg.traverse("Chain", values[0], max_depth=5)
    # The deepest path must include the depth-5 node (N5).
    deepest = max(paths, key=len)
    assert len(deepest) == 5
    reached = {step["to_value"] for path in paths for step in path}
    assert "N5" in reached  # beyond the old depth-2 cap


def test_reachable_nodes_complete_at_depth_4(neo4j_kg: object) -> None:
    values = _build_chain(neo4j_kg, 6)  # n0..n5
    reachable = neo4j_kg.reachable_node_ids("Chain", values[0], max_depth=4)
    # N1..N4 reachable within 4 hops (4 distinct downstream nodes).
    assert len(reachable) == 4


def test_shortest_path_indirect(neo4j_kg: object) -> None:
    neo4j_kg.add_edge("ThreatActor", "APT28", "Malware", "X-Agent", "uses")
    neo4j_kg.add_edge("Malware", "X-Agent", "Vulnerability", "CVE-2017-0144", "exploits")
    neo4j_kg.add_edge("Vulnerability", "CVE-2017-0144", "Asset", "SMBv1", "affects")
    path = neo4j_kg.shortest_path("ThreatActor", "APT28", "Asset", "SMBv1")
    assert path is not None
    assert len(path) == 3
    assert [s["relationship"] for s in path] == ["uses", "exploits", "affects"]


def test_shortest_path_no_path_returns_none(neo4j_kg: object) -> None:
    neo4j_kg.add_edge("A", "a", "B", "b", "rel")
    neo4j_kg.add_edge("C", "c", "D", "d", "rel")  # disjoint component
    # Explicit no-path result, not an error.
    assert neo4j_kg.shortest_path("A", "a", "D", "d") is None


def test_traverse_result_limit_is_reported_not_silent(neo4j_kg: object) -> None:
    # Fan out a hub to many nodes, set a small limit, and confirm the cap is
    # surfaced via last_limit_hit rather than silently truncating.
    for i in range(30):
        neo4j_kg.add_edge("Hub", "h", "Leaf", f"L{i}", "rel")
    neo4j_kg._result_limit = 5
    paths = neo4j_kg.traverse("Hub", "h", max_depth=2)
    assert len(paths) == 5
    assert neo4j_kg.last_limit_hit is True
