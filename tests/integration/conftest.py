"""Fixtures for Neo4j integration tests.

Tests here are gated by the ``requires_neo4j`` marker and skipped unless a
Neo4j connection is configured (``ZETTELFORGE_NEO4J_PASSWORD`` set) and
reachable. They run against the Dockerized dev instance from
``deploy/neo4j/docker-compose.yml`` (Bolt on the mapped host port).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


def _neo4j_configured() -> bool:
    return bool(os.environ.get("ZETTELFORGE_NEO4J_PASSWORD"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``requires_neo4j`` tests when Neo4j is not configured."""
    if _neo4j_configured():
        return
    skip = pytest.mark.skip(reason="Neo4j not configured (set ZETTELFORGE_NEO4J_PASSWORD)")
    for item in items:
        if "requires_neo4j" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def neo4j_kg() -> Iterator[object]:
    """A clean Neo4jKnowledgeGraph against a wiped database.

    Reloads config so ZETTELFORGE_NEO4J_* env set in the test session is
    picked up, wipes the graph before yielding, and closes the driver after.
    """
    from zettelforge.config import reload_config
    from zettelforge.neo4j_knowledge_graph import Neo4jKnowledgeGraph, Neo4jUnavailableError

    reload_config()
    try:
        kg = Neo4jKnowledgeGraph()
        with kg._get_driver().session(database=kg._database) as session:
            session.run(
                "MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS"
            ).consume()
    except Neo4jUnavailableError as exc:
        pytest.skip(f"Neo4j unreachable: {exc}")
    yield kg
    kg.close()


@pytest.fixture
def sqlite_backend(tmp_path: object) -> Iterator[object]:
    """A fresh initialized SQLite backend for parity comparison."""
    from zettelforge.sqlite_backend import SQLiteBackend

    backend = SQLiteBackend(data_dir=str(tmp_path))
    backend.initialize()
    yield backend
    backend.close()
