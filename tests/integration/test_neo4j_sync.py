"""Integration tests for the standalone Neo4j sync job (AGE-121).

Round-trips a small SQLite knowledge graph into Neo4j via the sync job and
asserts parity, idempotency, and that the populated graph answers path queries.
Gated by ``requires_neo4j``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zettelforge.scripts.neo4j_sync import sync
from zettelforge.sqlite_backend import SQLiteBackend

pytestmark = pytest.mark.requires_neo4j


_EDGES = [
    ("ThreatActor", "APT28", "Malware", "X-Agent", "uses"),
    ("Malware", "X-Agent", "Vulnerability", "CVE-2017-0144", "exploits"),
    ("Vulnerability", "CVE-2017-0144", "Asset", "SMBv1", "affects"),
]


def _seed(data_dir: Path) -> None:
    backend = SQLiteBackend(data_dir=str(data_dir))
    backend.initialize()
    for ft, fv, tt, tv, rel in _EDGES:
        backend.add_kg_edge(ft, fv, tt, tv, rel)
    backend.close()


def test_rebuild_populates_and_verifies(neo4j_kg: object, tmp_path: Path) -> None:
    _seed(tmp_path)
    report = sync(data_dir=str(tmp_path), rebuild=True, dry_run=False, batch_size=5000)
    assert report["ok"] is True
    assert report["neo4j"]["verified"] is True
    # 4 distinct entities, 3 edges.
    assert report["neo4j"]["after"] == {"nodes": 4, "edges": 3}
    # The populated graph answers an undirected path query end-to-end.
    path = neo4j_kg.shortest_path("ThreatActor", "APT28", "Asset", "SMBv1")  # type: ignore[attr-defined]
    assert path is not None and len(path) == 3


def test_incremental_is_idempotent(neo4j_kg: object, tmp_path: Path) -> None:
    _seed(tmp_path)
    first = sync(data_dir=str(tmp_path), rebuild=False, dry_run=False, batch_size=5000)
    second = sync(data_dir=str(tmp_path), rebuild=False, dry_run=False, batch_size=5000)
    assert first["ok"] and second["ok"]
    # Re-running the upsert must not duplicate nodes or edges.
    assert second["neo4j"]["after"] == {"nodes": 4, "edges": 3}


def test_dry_run_writes_nothing(neo4j_kg: object, tmp_path: Path) -> None:
    _seed(tmp_path)
    report = sync(data_dir=str(tmp_path), rebuild=False, dry_run=True, batch_size=5000)
    assert report["ok"] is True
    assert report["neo4j"]["reachable"] is True
    assert report["neo4j"]["before"] == {"nodes": 0, "edges": 0}
    assert report["neo4j"]["would_upsert"] == {"nodes": 4, "edges": 3}
