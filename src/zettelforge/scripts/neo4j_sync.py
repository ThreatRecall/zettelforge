#!/usr/bin/env python3
"""Standalone Neo4j sync/population job for the path-query backend (AGE-121).

Follow-up to the AGE-117 path-query seam. ``find_shortest_path()`` routes
undirected path-finding to Neo4j when ``ZETTELFORGE_NEO4J_PATHFINDING=true``,
but the seam deliberately does NOT dual-write from the hot path (that regressed
the SQLite write/recall path). So with pathfinding enabled and an unpopulated
Neo4j, path queries run against an empty graph. This job populates/syncs the
Neo4j graph from the default backend's knowledge graph (entities + edges).

Consistency / staleness contract
---------------------------------
* SQLite (``kg_nodes`` / ``kg_edges``) is the system of record. Neo4j is a
  DERIVED read-replica used only by the path-query seam. This job is one-way:
  SQLite -> Neo4j. It never writes back to SQLite.
* Default mode is INCREMENTAL UPSERT: every current node/edge is MERGEd into
  Neo4j (idempotent on ``(entity_type, entity_value)`` for nodes and
  ``(from, to, relationship)`` for edges, matching the backend's own write
  identity). The live graph is never emptied and is always a superset-or-equal
  of SQLite. Upsert does NOT delete: entities/edges removed from SQLite remain
  in Neo4j (the SQLite graph is append-mostly and carries no deletion log).
* ``--rebuild`` does a scoped clean-slate (deletes only ``:Entity`` nodes and
  their ``:REL`` edges, in bounded sub-transactions) then re-loads. Use it for
  an EXACT mirror including deletions. Note: during a rebuild the graph is
  transiently partial, so prefer it on a quiesced window; incremental upsert is
  the safe default for a live seam.
* Staleness: Neo4j reflects SQLite as of the last successful sync. Path queries
  may miss edges added since. Schedule this job (cron / systemd timer) to bound
  staleness, or run on demand for an immediate refresh. SQLite stays the system
  of record either way, so a stale or empty Neo4j only affects the opt-in
  path-query seam, never storage or recall.

Fail-loud (Law 4): a connection/auth failure raises ``Neo4jUnavailableError``
and the job exits non-zero (never reports a dropped sync as success). After a
mutating load the Neo4j node/edge counts are verified against the source; a
mismatch exits non-zero.

Usage::

    # Preview: read source, connect read-only, report the delta (no writes)
    python -m zettelforge.scripts.neo4j_sync --data-dir ~/.zettelforge --dry-run

    # Incremental upsert (default) — safe to run repeatedly / on a schedule
    python -m zettelforge.scripts.neo4j_sync --data-dir ~/.zettelforge

    # Exact mirror: wipe the ZettelForge graph then reload (deletions included)
    python -m zettelforge.scripts.neo4j_sync --data-dir ~/.zettelforge --rebuild

Connection settings come from the standard ``ZETTELFORGE_NEO4J_*`` environment
(``ZETTELFORGE_NEO4J_URI`` / ``_USER`` / ``_PASSWORD`` / ``_DATABASE``); this
job populates Neo4j regardless of ``ZETTELFORGE_NEO4J_PATHFINDING`` (the gate
controls whether queries are routed to Neo4j, not whether it may be populated).

A JSON report is emitted to stdout and, with ``--output``, to a file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any

from zettelforge.log import get_logger

if TYPE_CHECKING:
    from zettelforge.neo4j_knowledge_graph import Neo4jKnowledgeGraph
    from zettelforge.sqlite_backend import SQLiteBackend

_logger = get_logger("zettelforge.scripts.neo4j_sync")


# ── Source read ────────────────────────────────────────────────────────────


def read_source_graph(backend: SQLiteBackend) -> dict[str, Any]:
    """Read the full KG from the SQLite system of record.

    Returns a dict with the node rows, the edge rows DEDUPED to the Neo4j
    write identity ``(from, to, relationship)``, and the orphan-edge count
    (edges dropped because an endpoint node is missing). Deduping here means
    the reported ``edges`` count equals the number of ``:REL`` relationships
    the load will produce, so the post-load parity check is exact.
    """
    nodes = backend.get_all_kg_nodes()
    raw_edges = backend.get_all_kg_edges()
    _, total_edges = backend.count_kg()

    deduped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for e in raw_edges:
        key = (e["from_type"], e["from_value"], e["to_type"], e["to_value"], e["relationship"])
        # Last writer wins, mirroring the backend's MERGE-on-identity semantics.
        deduped[key] = e

    return {
        "nodes": nodes,
        "edges": list(deduped.values()),
        # Edges whose endpoints are missing from kg_nodes: dropped by the INNER
        # JOIN. Surfaced so a graph with dangling edges is visible, not silent.
        "orphan_edges": total_edges - len(raw_edges),
    }


# ── Neo4j load ──────────────────────────────────────────────────────────────


def _wipe_entity_graph(kg: Neo4jKnowledgeGraph, batch_size: int) -> None:
    """Delete only ``:Entity`` nodes and their ``:REL`` edges, in batches.

    Scoped so the job never nukes unrelated data sharing the database. A single
    ``DETACH DELETE`` can exhaust the transaction memory pool on a large graph
    (silently leaving stale nodes), so deletion runs in bounded sub-transactions.
    """
    driver = kg._get_driver()
    with driver.session(database=kg._database) as session:
        session.run(
            "MATCH (n:Entity) CALL { WITH n DETACH DELETE n } "
            f"IN TRANSACTIONS OF {int(batch_size)} ROWS"
        ).consume()
        rec = session.run("MATCH (n:Entity) RETURN count(n) AS c").single()
        remaining = rec["c"] if rec else 0
        if remaining:
            raise RuntimeError(
                f"Neo4j not clean after rebuild wipe: {remaining} :Entity nodes remain"
            )


def _load_graph(kg: Neo4jKnowledgeGraph, source: dict[str, Any], batch_size: int) -> None:
    """UNWIND-batch MERGE the source nodes then edges into Neo4j (idempotent).

    Node ids / edge ids and ``created_at`` come from the source so re-runs are
    deterministic and cross-store traceable; ``updated_at`` stamps this sync.
    Properties are JSON-encoded to match the backend's on-graph encoding.
    """
    now = datetime.now().isoformat()
    node_rows = [
        {
            "t": n["entity_type"],
            "v": n["entity_value"],
            "nid": n["node_id"],
            "props": json.dumps(n.get("properties") or {}),
            "created": n.get("created_at") or now,
            "now": now,
        }
        for n in source["nodes"]
    ]
    edge_rows = [
        {
            "ft": e["from_type"],
            "fv": e["from_value"],
            "tt": e["to_type"],
            "tv": e["to_value"],
            "rel": e["relationship"],
            "eid": e["edge_id"],
            "etype": e.get("edge_type") or "heuristic",
            "note_id": e.get("note_id") or "",
            "props": json.dumps(e.get("properties") or {}),
            "now": now,
        }
        for e in source["edges"]
    ]

    bs = max(1, int(batch_size))
    driver = kg._get_driver()
    with driver.session(database=kg._database) as session:
        for i in range(0, len(node_rows), bs):
            session.run(
                "UNWIND $rows AS row "
                "MERGE (n:Entity {entity_type: row.t, entity_value: row.v}) "
                "ON CREATE SET n.node_id = row.nid, n.properties = row.props, "
                "n.created_at = row.created, n.updated_at = row.now "
                "ON MATCH SET n.properties = row.props, n.updated_at = row.now",
                rows=node_rows[i : i + bs],
            ).consume()
        for i in range(0, len(edge_rows), bs):
            session.run(
                "UNWIND $rows AS row "
                "MATCH (a:Entity {entity_type: row.ft, entity_value: row.fv}) "
                "MATCH (b:Entity {entity_type: row.tt, entity_value: row.tv}) "
                "MERGE (a)-[r:REL {relationship: row.rel}]->(b) "
                "ON CREATE SET r.edge_id = row.eid, r.from_node_id = a.node_id, "
                "r.to_node_id = b.node_id, r.edge_type = row.etype, r.note_id = row.note_id, "
                "r.properties = row.props, r.created_at = row.now, r.updated_at = row.now "
                "ON MATCH SET r.edge_type = row.etype, r.note_id = row.note_id, "
                "r.properties = row.props, r.updated_at = row.now",
                rows=edge_rows[i : i + bs],
            ).consume()


def _count_neo4j(kg: Neo4jKnowledgeGraph) -> tuple[int, int]:
    """Return ``(entity_node_count, rel_edge_count)`` currently in Neo4j."""
    driver = kg._get_driver()
    with driver.session(database=kg._database) as session:
        n_rec = session.run("MATCH (n:Entity) RETURN count(n) AS c").single()
        e_rec = session.run("MATCH ()-[r:REL]->() RETURN count(r) AS c").single()
    return int(n_rec["c"]) if n_rec else 0, int(e_rec["c"]) if e_rec else 0


# ── Orchestration ────────────────────────────────────────────────────────────


def sync(
    *,
    data_dir: str | None,
    rebuild: bool,
    dry_run: bool,
    batch_size: int,
) -> dict[str, Any]:
    """Run the sync and return a JSON-serializable report.

    Raises ``Neo4jUnavailableError`` on a connection failure during a mutating
    run, or ``RuntimeError`` if post-load verification fails.
    """
    from zettelforge.neo4j_knowledge_graph import Neo4jKnowledgeGraph, Neo4jUnavailableError
    from zettelforge.sqlite_backend import SQLiteBackend

    backend = SQLiteBackend(data_dir=data_dir)
    backend.initialize()
    try:
        source = read_source_graph(backend)
    finally:
        backend.close()

    report: dict[str, Any] = {
        "mode": "dry-run" if dry_run else ("rebuild" if rebuild else "incremental"),
        "data_dir": data_dir,
        "source": {
            "nodes": len(source["nodes"]),
            "edges": len(source["edges"]),
            "orphan_edges": source["orphan_edges"],
        },
        "neo4j": {},
        "ok": False,
    }
    if source["orphan_edges"]:
        _logger.warning("neo4j_sync_orphan_edges_dropped", count=source["orphan_edges"])

    # Skip schema init at construction; we control connect/init explicitly so a
    # dry-run can connect read-only without writing constraints.
    kg = Neo4jKnowledgeGraph(_skip_init_schema=True)
    try:
        if dry_run:
            # Read-only preview: report the current Neo4j state and the delta.
            try:
                before_nodes, before_edges = _count_neo4j(kg)
                report["neo4j"] = {
                    "reachable": True,
                    "before": {"nodes": before_nodes, "edges": before_edges},
                    "would_upsert": {
                        "nodes": len(source["nodes"]),
                        "edges": len(source["edges"]),
                    },
                }
            except Neo4jUnavailableError as exc:
                # Preview is informational; surface unreachability without failing.
                report["neo4j"] = {"reachable": False, "error": str(exc)}
            report["ok"] = True
            return report

        # Mutating run: a connection failure here is fail-loud (propagates).
        kg._init_schema()
        before_nodes, before_edges = _count_neo4j(kg)
        if rebuild:
            _wipe_entity_graph(kg, batch_size)
        _load_graph(kg, source, batch_size)
        after_nodes, after_edges = _count_neo4j(kg)

        expected_nodes = len(source["nodes"])
        expected_edges = len(source["edges"])
        if rebuild:
            verified = after_nodes == expected_nodes and after_edges == expected_edges
        else:
            # Upsert never deletes, so Neo4j must hold at least the source set.
            verified = after_nodes >= expected_nodes and after_edges >= expected_edges

        report["neo4j"] = {
            "reachable": True,
            "before": {"nodes": before_nodes, "edges": before_edges},
            "after": {"nodes": after_nodes, "edges": after_edges},
            "expected": {"nodes": expected_nodes, "edges": expected_edges},
            "verified": verified,
        }
        if not verified:
            raise RuntimeError(
                f"Neo4j sync verification failed (mode={report['mode']}): "
                f"after={after_nodes} nodes / {after_edges} edges, "
                f"expected={expected_nodes} / {expected_edges}"
            )
        report["ok"] = True
        _logger.info(
            "neo4j_sync_complete",
            mode=report["mode"],
            nodes=after_nodes,
            edges=after_edges,
        )
        return report
    finally:
        kg.close()


# ── CLI ──────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Populate/sync the Neo4j path-query graph from the SQLite knowledge graph.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--data-dir",
        default=None,
        help="ZettelForge data directory (the SQLite store). Defaults to the standard data dir.",
    )
    p.add_argument(
        "--rebuild",
        action="store_true",
        help="Scoped clean-slate (delete :Entity/:REL) then reload — exact mirror including deletions.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Read source and report the delta vs Neo4j without writing anything.",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="UNWIND batch size for load and wipe sub-transactions.",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Optional path to also write the JSON report to.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from zettelforge.neo4j_knowledge_graph import Neo4jUnavailableError

    args = _parse_args(argv)
    if args.rebuild and args.dry_run:
        print("--rebuild and --dry-run are mutually exclusive.", file=sys.stderr)
        return 2

    try:
        report = sync(
            data_dir=args.data_dir,
            rebuild=args.rebuild,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
        )
    except Neo4jUnavailableError as exc:
        print(f"Neo4j unavailable: {exc}", file=sys.stderr)
        return 3
    except RuntimeError as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.output:
        try:
            with open(args.output, "w") as f:
                f.write(text + "\n")
        except OSError as exc:
            print(f"warning: could not write report to {args.output}: {exc}", file=sys.stderr)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
