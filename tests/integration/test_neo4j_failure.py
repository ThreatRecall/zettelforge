"""Fail-loud-on-outage tests (FR-008 / SC US4).

Confirms that an unreachable or misconfigured Neo4j raises a clear, logged
error rather than silently dropping writes or returning empty results, and
that fallback to the default backend happens only when explicitly configured.

The unreachable-endpoint tests run in the standard suite (no Neo4j required):
they point at a dead Bolt endpoint, so the fail-loud + explicit-fallback
contract has standing automated coverage even in Neo4j-less CI. Only
``test_wrong_credentials_fail_loud`` needs a reachable host and stays gated by
``requires_neo4j``.
"""

from __future__ import annotations

import os

import pytest


def _bad_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    # Point at an unreachable Bolt endpoint by default.
    monkeypatch.setenv("ZETTELFORGE_NEO4J_URI", "bolt://127.0.0.1:1")
    monkeypatch.setenv("ZETTELFORGE_NEO4J_USER", "neo4j")
    monkeypatch.setenv("ZETTELFORGE_NEO4J_PASSWORD", "wrong")
    monkeypatch.setenv("ZETTELFORGE_NEO4J_DATABASE", "neo4j")
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)


def test_unreachable_db_raises_on_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from zettelforge.config import reload_config
    from zettelforge.neo4j_knowledge_graph import Neo4jKnowledgeGraph, Neo4jUnavailableError

    _bad_env(monkeypatch)
    reload_config()
    kg = Neo4jKnowledgeGraph(_skip_init_schema=True)
    with pytest.raises(Neo4jUnavailableError):
        kg.add_edge("A", "a", "B", "b", "rel")


def test_unreachable_db_raises_at_schema_init(monkeypatch: pytest.MonkeyPatch) -> None:
    from zettelforge.config import reload_config
    from zettelforge.neo4j_knowledge_graph import Neo4jKnowledgeGraph, Neo4jUnavailableError

    _bad_env(monkeypatch)
    reload_config()
    # Schema init connects eagerly; an unreachable DB must surface at startup.
    with pytest.raises(Neo4jUnavailableError):
        Neo4jKnowledgeGraph()


def test_pathfinding_fails_loud_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Path-query seam: unreachable Neo4j with pathfinding on must raise, not
    silently fall back to the default backend."""
    import zettelforge.knowledge_graph as kg_mod
    from zettelforge.config import reload_config
    from zettelforge.neo4j_knowledge_graph import Neo4jUnavailableError

    _bad_env(monkeypatch)
    monkeypatch.setenv("ZETTELFORGE_NEO4J_PATHFINDING", "true")
    monkeypatch.delenv("ZETTELFORGE_NEO4J_FALLBACK", raising=False)
    reload_config()
    kg_mod._neo4j_path_backend = None  # reset cached path backend
    with pytest.raises(Neo4jUnavailableError):
        kg_mod.find_shortest_path("Actor", "apt28", "CVE", "cve-2021-1234")
    kg_mod._neo4j_path_backend = None


def test_pathfinding_explicit_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Path-query seam: unreachable Neo4j with fallback on degrades to the
    default backend's BFS (explicit, logged, never raises)."""
    import zettelforge.knowledge_graph as kg_mod
    from zettelforge.config import reload_config

    _bad_env(monkeypatch)
    monkeypatch.setenv("ZETTELFORGE_NEO4J_PATHFINDING", "true")
    monkeypatch.setenv("ZETTELFORGE_NEO4J_FALLBACK", "true")
    reload_config()
    kg_mod._neo4j_path_backend = None
    kg_mod._kg_instance = None
    # Reaching the assert at all proves no raise: the fallback path was taken.
    result = kg_mod.find_shortest_path("Actor", "apt28", "CVE", "cve-2021-1234")
    assert result is None or isinstance(result, list)
    kg_mod._neo4j_path_backend = None
    kg_mod._kg_instance = None


@pytest.mark.requires_neo4j
def test_wrong_credentials_fail_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reachable host, wrong password: must fail loud, not pretend success.

    Gated by ``requires_neo4j``: this one genuinely needs a reachable host to
    distinguish auth failure from unreachability.
    """
    from zettelforge.config import reload_config
    from zettelforge.neo4j_knowledge_graph import Neo4jKnowledgeGraph, Neo4jUnavailableError

    uri = os.environ.get("ZETTELFORGE_NEO4J_URI", "bolt://localhost:17687")
    monkeypatch.setenv("ZETTELFORGE_NEO4J_URI", uri)
    monkeypatch.setenv("ZETTELFORGE_NEO4J_USER", "neo4j")
    monkeypatch.setenv("ZETTELFORGE_NEO4J_PASSWORD", "definitely-wrong-password")
    reload_config()
    with pytest.raises(Neo4jUnavailableError):
        Neo4jKnowledgeGraph()
