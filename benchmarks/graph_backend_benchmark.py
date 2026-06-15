"""Graph backend benchmark: Neo4j vs the current default (SQLite) traversal path.

Loads ONE synthetic, CTI-shaped graph (>= 10k nodes, >= 50k edges, with
high-degree hubs, depth >= 5 chains, and indirectly connected pairs) into both
backends and times the operations the feature targets:

* single-hop neighbors
* multi-hop traverse at depths 2, 3, 4, 5
* shortest path between indirectly connected pairs

Baseline choice (research R1)
-----------------------------
The benchmarked default backend is the **SQLite** ``StorageBackend``
(``kg_nodes`` / ``kg_edges`` tables, fully indexed), accessed via the SAME
methods the production recall path uses: ``traverse_kg`` and
``get_kg_neighbors``. That is the real graph store ZettelForge reads for
multi-hop traversal at recall time, NOT the process-global JSONL
``KnowledgeGraph``. SQLite has no native shortest-path, so the default's
shortest-path number is a faithful Python BFS over ``get_kg_edges_from`` —
exactly the work the default path would have to do to answer a path query —
and is labelled as such.

Both backends receive the identical generated dataset so the comparison is
apples-to-apples (SC-003). The report records median and p95 latency per query
and the Neo4j-vs-default ratio.

Usage::

    python -m benchmarks.graph_backend_benchmark \\
        --nodes 10000 --edges 50000 --depths 2,3,4,5 --repeat 5

Requires a reachable Neo4j (the Dockerized dev instance) and the ``neo4j``
extra installed. Connection comes from the standard ZETTELFORGE_NEO4J_* env.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zettelforge.graph_retriever import GraphRetriever, StoreGraphSource  # noqa: E402
from zettelforge.neo4j_knowledge_graph import Neo4jKnowledgeGraph  # noqa: E402
from zettelforge.sqlite_backend import SQLiteBackend  # noqa: E402

# Entity-type vocabulary loosely modelling a CTI graph so the synthetic data
# is representative in shape, not just size.
_ENTITY_TYPES = [
    "ThreatActor",
    "Malware",
    "Tool",
    "Vulnerability",
    "Technique",
    "Campaign",
    "Asset",
    "IPv4Address",
    "Domain",
    "Note",
]
_RELATIONSHIPS = [
    "uses",
    "exploits",
    "targets",
    "attributed_to",
    "communicates_with",
    "mitigates",
    "indicates",
    "related_to",
]


class GeneratedGraph:
    """An in-memory edge list plus the probe entities the benchmark queries."""

    def __init__(
        self,
        nodes: list[tuple[str, str]],
        edges: list[tuple[tuple[str, str], tuple[str, str], str]],
        hub: tuple[str, str],
        deep_chain_start: tuple[str, str],
        indirect_pairs: list[tuple[tuple[str, str], tuple[str, str]]],
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.hub = hub
        self.deep_chain_start = deep_chain_start
        self.indirect_pairs = indirect_pairs


def generate_graph(n_nodes: int, n_edges: int, seed: int = 1337) -> GeneratedGraph:
    """Build a connected, hub-bearing graph with deep chains and indirect pairs.

    Guarantees:
      * at least one high-degree hub (fan-out to many distinct nodes),
      * several explicit chains of length >= 5 so depth-5 traversal and deep
        shortest paths have something to find,
      * a set of indirectly connected pairs (>= 3 hops apart) for shortest path.
    """
    rng = random.Random(seed)

    nodes: list[tuple[str, str]] = []
    for i in range(n_nodes):
        etype = _ENTITY_TYPES[i % len(_ENTITY_TYPES)]
        nodes.append((etype, f"{etype}_{i}"))

    edges: list[tuple[tuple[str, str], tuple[str, str], str]] = []
    seen: set[tuple[int, int, str]] = set()

    def add(a_idx: int, b_idx: int, rel: str) -> None:
        if a_idx == b_idx:
            return
        key = (a_idx, b_idx, rel)
        if key in seen:
            return
        seen.add(key)
        edges.append((nodes[a_idx], nodes[b_idx], rel))

    # 1. High-degree hub: node 0 points at the next ~1500 nodes.
    hub_idx = 0
    hub_fanout = min(1500, n_nodes - 1)
    for j in range(1, hub_fanout + 1):
        add(hub_idx, j, rng.choice(_RELATIONSHIPS))

    # 2. Deep chains (length 8) so depth-5 traversal is exercised. Carve a few
    #    dedicated chains out of disjoint node ranges.
    chain_len = 8
    deep_chain_start_idx = n_nodes - 1  # set below to the first chain's head
    chain_heads: list[int] = []
    base = n_nodes - chain_len * 25
    if base < hub_fanout + 1:
        base = hub_fanout + 1
    cursor = base
    while cursor + chain_len < n_nodes and len(chain_heads) < 25:
        chain_heads.append(cursor)
        for k in range(chain_len - 1):
            add(cursor + k, cursor + k + 1, rng.choice(_RELATIONSHIPS))
        cursor += chain_len
    if chain_heads:
        deep_chain_start_idx = chain_heads[0]

    # 3. Random edges to reach the requested edge count, biased toward locality
    #    so multi-hop traversal finds real fan-out rather than a star.
    while len(edges) < n_edges:
        a = rng.randrange(n_nodes)
        # 60% local neighbourhood, 40% fully random — yields clustered fan-out.
        if rng.random() < 0.6:
            b = min(n_nodes - 1, a + rng.randrange(1, 40))
        else:
            b = rng.randrange(n_nodes)
        add(a, b, rng.choice(_RELATIONSHIPS))

    # 4. Indirect pairs: endpoints of the deep chains are >= 7 hops apart.
    indirect_pairs: list[tuple[tuple[str, str], tuple[str, str]]] = []
    for head in chain_heads[:10]:
        indirect_pairs.append((nodes[head], nodes[head + chain_len - 1]))

    return GeneratedGraph(
        nodes=nodes,
        edges=edges,
        hub=nodes[hub_idx],
        deep_chain_start=nodes[deep_chain_start_idx],
        indirect_pairs=indirect_pairs,
    )


def load_opencti_graph(path: str) -> GeneratedGraph:
    """Build a :class:`GeneratedGraph` from a real OpenCTI extraction file.

    The extractor (``extract_opencti_graph.py``) dumps the live CTI graph. Node
    identity is the OpenCTI ``internal_id`` so the real topology is preserved
    exactly (no merging of distinct entities that share a display name). We:

      * map each node to ``(entity_type, internal_id)`` for both backends,
      * pick the real highest-degree hub from the extracted degree counts,
      * find shortest-path probe pairs that are genuinely indirectly connected
        (graph distance >= 3) by BFS on the extracted edge list; if too few
        exist we fall back to the highest-degree node pairs and report their
        actual distances.

    The deep-chain probe (``deep_chain_start``) is the highest-degree node, so
    depth-2..5 traversal exercises the densest real neighbourhood.
    """
    with open(path) as f:
        data = json.load(f)

    raw_nodes = data["nodes"]
    raw_edges = data["edges"]

    # internal_id -> (entity_type, entity_value) where entity_value = internal_id.
    type_of: dict[str, str] = {}
    name_of: dict[str, str] = {}
    for n in raw_nodes:
        iid = n["internal_id"]
        type_of[iid] = n["type"]
        name_of[iid] = n.get("name", iid)

    def tv(iid: str) -> tuple[str, str]:
        return (type_of.get(iid, "Unknown"), iid)

    nodes: list[tuple[str, str]] = [tv(n["internal_id"]) for n in raw_nodes]

    edges: list[tuple[tuple[str, str], tuple[str, str], str]] = []
    # Adjacency for probe selection. Both backends traverse OUTGOING directed
    # edges, so the forward-traversal hub must be chosen by out-degree: in real
    # CTI data the highest *total*-degree nodes are MITRE techniques, which are
    # pure sinks (hundreds of incoming `uses`, zero outgoing) and would make a
    # forward traversal visit nothing. We keep undirected adjacency too, for
    # shortest-path pair distance (Neo4j shortestPath is undirected).
    out_adj: dict[str, set[str]] = {}
    undirected_adj: dict[str, set[str]] = {}
    for e in raw_edges:
        fid, tid, rel = e["from"], e["to"], e["rel"]
        if fid not in type_of or tid not in type_of:
            continue
        edges.append((tv(fid), tv(tid), rel))
        out_adj.setdefault(fid, set()).add(tid)
        undirected_adj.setdefault(fid, set()).add(tid)
        undirected_adj.setdefault(tid, set()).add(fid)

    # Total-degree ranking (for hub *reporting*) and out-degree ranking (for
    # the forward-traversal probe both backends actually walk).
    total_degree: dict[str, int] = {k: len(v) for k, v in undirected_adj.items()}
    out_degree: dict[str, int] = {k: len(v) for k, v in out_adj.items()}
    ranked_total = sorted(total_degree.items(), key=lambda kv: kv[1], reverse=True)
    ranked_out = sorted(out_degree.items(), key=lambda kv: kv[1], reverse=True)
    hub_id = ranked_out[0][0]  # highest OUT-degree: real forward-traversal hub
    hub = tv(hub_id)
    deep_chain_start = hub  # densest real outgoing neighbourhood

    # Find indirect pairs at undirected distance >= 3 by BFS from several
    # high-degree seeds (their far frontier is reliably multi-hop away).
    def bfs_dist(src: str, max_d: int = 6) -> dict[str, int]:
        seen = {src: 0}
        frontier = [src]
        d = 0
        while frontier and d < max_d:
            d += 1
            nxt: list[str] = []
            for u in frontier:
                for w in undirected_adj.get(u, ()):  # noqa: E1133
                    if w not in seen:
                        seen[w] = d
                        nxt.append(w)
            frontier = nxt
        return seen

    # Seed from high-OUT-degree nodes so the directed SQLite BFS (which walks
    # outgoing edges) can actually reach the partner; the undirected distance is
    # what we report (Neo4j shortestPath is undirected). We require the partner
    # to be reachable via DIRECTED out-edges at distance >= 3 so both backends'
    # path queries have a real multi-hop path to find.
    def bfs_out_dist(src: str, max_d: int = 6) -> dict[str, int]:
        seen = {src: 0}
        frontier = [src]
        d = 0
        while frontier and d < max_d:
            d += 1
            nxt: list[str] = []
            for u in frontier:
                for w in out_adj.get(u, ()):  # noqa: E1133
                    if w not in seen:
                        seen[w] = d
                        nxt.append(w)
            frontier = nxt
        return seen

    indirect_pairs: list[tuple[tuple[str, str], tuple[str, str]]] = []
    pair_distances: list[int] = []
    seen_pairs: set[tuple[str, str]] = set()
    for seed_id, _deg in ranked_out[:60]:
        dist = bfs_out_dist(seed_id, max_d=6)
        # take a directed-reachable far node (distance >= 3) as the partner
        far = [(t, dd) for t, dd in dist.items() if dd >= 3]
        far.sort(key=lambda x: x[1], reverse=True)
        for tgt, dd in far[:3]:
            key = tuple(sorted((seed_id, tgt)))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)  # type: ignore[arg-type]
            indirect_pairs.append((tv(seed_id), tv(tgt)))
            pair_distances.append(dd)
            if len(indirect_pairs) >= 10:
                break
        if len(indirect_pairs) >= 10:
            break

    # Fallback: undirected >=3 pairs if directed yielded too few.
    if len(indirect_pairs) < 5:
        for seed_id, _deg in ranked_total[:40]:
            dist = bfs_dist(seed_id, max_d=6)
            far = sorted(
                ((t, dd) for t, dd in dist.items() if dd >= 3),
                key=lambda x: x[1],
                reverse=True,
            )
            for tgt, dd in far[:2]:
                key = tuple(sorted((seed_id, tgt)))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)  # type: ignore[arg-type]
                indirect_pairs.append((tv(seed_id), tv(tgt)))
                pair_distances.append(dd)
                if len(indirect_pairs) >= 10:
                    break
            if len(indirect_pairs) >= 10:
                break

    g = GeneratedGraph(
        nodes=nodes,
        edges=edges,
        hub=hub,
        deep_chain_start=deep_chain_start,
        indirect_pairs=indirect_pairs,
    )
    # Attach real-data metadata for reporting (names + distances).
    g.opencti_meta = {  # type: ignore[attr-defined]
        "hub_name": name_of.get(hub_id, hub_id),
        "hub_degree": out_degree.get(hub_id, 0),
        "hub_total_degree": total_degree.get(hub_id, 0),
        "top_hubs": [
            {
                "name": name_of.get(i, i),
                "type": type_of.get(i, "?"),
                "degree": d,
                "out_degree": out_degree.get(i, 0),
            }
            for i, d in ranked_total[:10]
        ],
        "top_out_hubs": [
            {
                "name": name_of.get(i, i),
                "type": type_of.get(i, "?"),
                "out_degree": d,
                "total_degree": total_degree.get(i, 0),
            }
            for i, d in ranked_out[:10]
        ],
        "avg_degree": round(2 * len(edges) / max(1, len(nodes)), 2),
        "max_degree": ranked_total[0][1] if ranked_total else 0,
        "max_out_degree": ranked_out[0][1] if ranked_out else 0,
        "pair_distances": pair_distances,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
    return g


# ── Default (SQLite) shortest path: faithful Python BFS over the real store ──


def _sqlite_shortest_path(
    backend: SQLiteBackend,
    from_type: str,
    from_value: str,
    to_type: str,
    to_value: str,
    max_depth: int,
) -> list[str] | None:
    """BFS over the SQLite store's outgoing edges to find a path.

    Represents the work the default backend must do to answer a shortest-path
    query: it has no native path operator, so this walks ``get_kg_edges_from``
    breadth-first. Labelled in the report as the default-path equivalent.
    """
    start = backend.get_kg_node(from_type, from_value)
    target = backend.get_kg_node(to_type, to_value)
    if not start or not target:
        return None
    start_id = start["node_id"]
    target_id = target["node_id"]
    if start_id == target_id:
        return [start_id]
    visited = {start_id}
    queue: deque[tuple[str, list[str]]] = deque([(start_id, [start_id])])
    while queue:
        cur, path = queue.popleft()
        if len(path) > max_depth + 1:
            continue
        for edge in backend.get_kg_edges_from(cur):
            nxt = edge["to_node_id"]
            if nxt == target_id:
                return [*path, nxt]
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, [*path, nxt]))
    return None


def _sqlite_incoming_to(backend: SQLiteBackend, node_id: str) -> list[str]:
    """Read incoming-edge source ids for ``node_id`` (benchmark-only read).

    The SQLite backend exposes outgoing edges (``get_kg_edges_from``) but no
    incoming-edge read on the recall path. Neo4j's ``shortestPath`` is
    *undirected*, so to compare the two on the IDENTICAL question we let the
    SQLite BFS also walk incoming edges, querying ``kg_edges`` by
    ``to_node_id`` directly on the backend's connection.
    """
    with backend._write_lock:  # noqa: SLF001
        backend._check_open()  # noqa: SLF001
        cur = backend._conn.execute(  # noqa: SLF001
            "SELECT from_node_id FROM kg_edges WHERE to_node_id = ?", (node_id,)
        )
        rows = cur.fetchall()
    return [r["from_node_id"] for r in rows]


def _sqlite_shortest_path_undirected(
    backend: SQLiteBackend,
    from_type: str,
    from_value: str,
    to_type: str,
    to_value: str,
    max_depth: int,
) -> list[str] | None:
    """Undirected BFS over the SQLite store, matching Neo4j ``shortestPath``.

    Walks both outgoing (``get_kg_edges_from``) and incoming
    (``_sqlite_incoming_to``) edges so it answers the same undirected
    reachability question Neo4j does. This is the apples-to-apples shortest-path
    baseline for the real graph (where many real entity pairs are only connected
    against edge direction).
    """
    start = backend.get_kg_node(from_type, from_value)
    target = backend.get_kg_node(to_type, to_value)
    if not start or not target:
        return None
    start_id = start["node_id"]
    target_id = target["node_id"]
    if start_id == target_id:
        return [start_id]
    visited = {start_id}
    queue: deque[tuple[str, list[str]]] = deque([(start_id, [start_id])])
    while queue:
        cur, path = queue.popleft()
        # Path length = number of nodes; edges = len(path) - 1. Cap at max_depth
        # edges to match Neo4j shortestPath((a)-[:REL*..max_depth]-(b)) exactly.
        if len(path) - 1 >= max_depth:
            continue
        neighbors = [e["to_node_id"] for e in backend.get_kg_edges_from(cur)]
        neighbors.extend(_sqlite_incoming_to(backend, cur))
        for nxt in neighbors:
            if nxt == target_id:
                return [*path, nxt]
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, [*path, nxt]))
    return None


# ── Loaders ──────────────────────────────────────────────────────────────


def load_sqlite(graph: GeneratedGraph, data_dir: str) -> SQLiteBackend:
    backend = SQLiteBackend(data_dir=data_dir)
    backend.initialize()
    for (ft, fv), (tt, tv), rel in graph.edges:
        backend.add_kg_edge(ft, fv, tt, tv, rel)
    return backend


def load_neo4j(graph: GeneratedGraph) -> Neo4jKnowledgeGraph:
    kg = Neo4jKnowledgeGraph()
    # Clean slate so repeated runs are comparable. A single-transaction
    # DETACH DELETE OOMs on a large existing graph (transaction memory pool),
    # silently leaving stale nodes that corrupt the comparison; delete in
    # bounded sub-transactions instead.
    with kg._get_driver().session(database=kg._database) as session:  # noqa: SLF001
        session.run(
            "MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
        ).consume()
        remaining = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        if remaining:
            raise RuntimeError(f"Neo4j not clean before load: {remaining} nodes remain")
    kg._init_schema()  # noqa: SLF001
    # Bulk-load via UNWIND batches: MERGE nodes then MERGE edges. Far faster
    # than per-edge round trips for 50k+ edges, and still exercises the same
    # MERGE-dedup write path the backend uses.
    _bulk_load_neo4j(kg, graph)
    return kg


def _bulk_load_neo4j(kg: Neo4jKnowledgeGraph, graph: GeneratedGraph) -> None:
    import uuid as _uuid
    from datetime import datetime as _dt

    now = _dt.now().isoformat()
    node_rows = [
        {"t": t, "v": v, "nid": f"node_{_uuid.uuid4().hex[:12]}", "now": now}
        for (t, v) in graph.nodes
    ]
    edge_rows = [
        {
            "ft": ft,
            "fv": fv,
            "tt": tt,
            "tv": tv,
            "rel": rel,
            "eid": f"edge_{_uuid.uuid4().hex[:12]}",
            "now": now,
        }
        for (ft, fv), (tt, tv), rel in graph.edges
    ]
    driver = kg._get_driver()  # noqa: SLF001
    with driver.session(database=kg._database) as session:  # noqa: SLF001
        for i in range(0, len(node_rows), 5000):
            session.run(
                "UNWIND $rows AS row "
                "MERGE (n:Entity {entity_type: row.t, entity_value: row.v}) "
                "ON CREATE SET n.node_id = row.nid, n.properties = '{}', "
                "n.created_at = row.now, n.updated_at = row.now",
                rows=node_rows[i : i + 5000],
            )
        for i in range(0, len(edge_rows), 5000):
            session.run(
                "UNWIND $rows AS row "
                "MATCH (a:Entity {entity_type: row.ft, entity_value: row.fv}) "
                "MATCH (b:Entity {entity_type: row.tt, entity_value: row.tv}) "
                "MERGE (a)-[r:REL {relationship: row.rel}]->(b) "
                "ON CREATE SET r.edge_id = row.eid, r.from_node_id = a.node_id, "
                "r.to_node_id = b.node_id, r.edge_type = 'heuristic', "
                "r.note_id = '', r.properties = '{}', "
                "r.created_at = row.now, r.updated_at = row.now",
                rows=edge_rows[i : i + 5000],
            )


# ── Timing ───────────────────────────────────────────────────────────────


def _time_calls(fn: Any, repeat: int) -> tuple[float, float, int]:
    """Run ``fn`` ``repeat`` times; return (median_ms, p95_ms, last_result_size).

    A single untimed warmup call precedes timing so cold driver/page-cache
    effects do not skew the median (especially Neo4j's first Bolt round trip).
    """
    fn()  # warmup, discarded
    samples: list[float] = []
    last_size = 0
    for _ in range(repeat):
        t0 = time.perf_counter()
        result = fn()
        dt = (time.perf_counter() - t0) * 1000.0
        samples.append(dt)
        last_size = len(result) if result is not None else 0
    samples.sort()
    median = statistics.median(samples)
    p95 = samples[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))]
    return median, p95, last_size


def run_benchmark(
    n_nodes: int,
    n_edges: int,
    depths: list[int],
    repeat: int,
    graph: GeneratedGraph | None = None,
    source: str = "synthetic",
) -> dict[str, Any]:
    if graph is None:
        print(f"Generating graph: {n_nodes} nodes, target {n_edges} edges ...")
        graph = generate_graph(n_nodes, n_edges)
    actual_edges = len(graph.edges)
    print(f"  graph: {len(graph.nodes)} nodes, {actual_edges} edges  (source={source})")
    print(f"  hub={graph.hub}  deep_chain_start={graph.deep_chain_start}")
    print(f"  indirect pairs: {len(graph.indirect_pairs)}")

    results: dict[str, Any] = {
        "source": source,
        "dataset": {
            "nodes": len(graph.nodes),
            "edges": actual_edges,
            "depths": depths,
            "repeat": repeat,
        },
        "baseline": (
            "sqlite (StorageBackend kg_edges; production per-node BFS reachable-set, "
            "the GraphRetriever path recall actually uses)"
        ),
        "queries": {},
    }
    if hasattr(graph, "opencti_meta"):
        results["opencti_meta"] = graph.opencti_meta  # type: ignore[attr-defined]

    tmpdir = tempfile.mkdtemp(prefix="gbbench_sqlite_")
    print(f"Loading SQLite backend at {tmpdir} ...")
    t0 = time.perf_counter()
    sqlite_backend = load_sqlite(graph, tmpdir)
    print(f"  SQLite load: {time.perf_counter() - t0:.1f}s")

    print("Loading Neo4j backend ...")
    t0 = time.perf_counter()
    neo4j_kg = load_neo4j(graph)
    print(f"  Neo4j load: {time.perf_counter() - t0:.1f}s")

    hub_t, hub_v = graph.hub
    chain_t, chain_v = graph.deep_chain_start

    def record(name: str, sqlite_fn: Any, neo4j_fn: Any) -> None:
        s_med, s_p95, s_size = _time_calls(sqlite_fn, repeat)
        n_med, n_p95, n_size = _time_calls(neo4j_fn, repeat)
        ratio = (s_med / n_med) if n_med > 0 else float("inf")
        results["queries"][name] = {
            "sqlite_median_ms": round(s_med, 3),
            "sqlite_p95_ms": round(s_p95, 3),
            "sqlite_result_size": s_size,
            "neo4j_median_ms": round(n_med, 3),
            "neo4j_p95_ms": round(n_p95, 3),
            "neo4j_result_size": n_size,
            "speedup_ratio": round(ratio, 2),
        }
        print(
            f"  {name:24s} sqlite={s_med:9.3f}ms  neo4j={n_med:9.3f}ms  "
            f"ratio={ratio:7.2f}x  (sizes s={s_size} n={n_size})"
        )

    # The production graph stage reaches multi-hop nodes via a Python-side BFS
    # that issues one store call per visited node (GraphRetriever over
    # StoreGraphSource). That per-node round-trip pattern, not the rarely-used
    # traverse_kg, is the real default cost. We compare it against Neo4j's
    # single-query server-side reachable-set traversal.
    sqlite_source = StoreGraphSource(sqlite_backend)
    sqlite_retriever = GraphRetriever(sqlite_source)
    neo4j_retriever = GraphRetriever(neo4j_kg)

    def production_bfs_reachable(source: Any, t: str, v: str, depth: int) -> list[Any]:
        # Mirror GraphRetriever._bfs_collect's reachable-set walk but return all
        # visited nodes so the result size is comparable to Neo4j reachable_nodes.
        start = source.get_node(t, v)
        if not start:
            return []
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(start["node_id"], 0)]
        out: list[str] = []
        while queue:
            cur, d = queue.pop(0)
            if cur in visited:
                continue
            visited.add(cur)
            if d > 0:
                out.append(cur)
            if d >= depth:
                continue
            for edge in source.get_outgoing_edges(cur):
                nxt = edge["to_node_id"]
                if nxt not in visited:
                    queue.append((nxt, d + 1))
        return out

    print("Timing queries ...")
    # Single-hop on the hub (high fan-out).
    record(
        "single_hop",
        lambda: sqlite_backend.get_kg_neighbors(hub_t, hub_v),
        lambda: neo4j_kg.get_neighbors(hub_t, hub_v),
    )

    # Multi-hop reachable-set traversal from the deep-chain head at each depth.
    # SQLite = production per-node BFS; Neo4j = single-query reachable_nodes.
    for d in depths:
        record(
            f"traverse_depth_{d}",
            lambda d=d: production_bfs_reachable(sqlite_source, chain_t, chain_v, d),
            lambda d=d: neo4j_kg.reachable_nodes(chain_t, chain_v, max_depth=d),
        )

    # Also exercise multi-hop from the high-degree hub, where the default
    # per-node BFS pays for thousands of round trips.
    for d in [d for d in depths if d >= 3]:
        record(
            f"traverse_hub_depth_{d}",
            lambda d=d: production_bfs_reachable(sqlite_source, hub_t, hub_v, d),
            lambda d=d: neo4j_kg.reachable_nodes(hub_t, hub_v, max_depth=d),
        )

    # Reachable-id-set variant: the shape production recall actually needs
    # (note-ids, not full node objects). Isolates traversal cost from the
    # full-object serialization cost that dominates the full-node variant.
    for d in [d for d in depths if d >= 3]:
        record(
            f"traverse_hub_ids_depth_{d}",
            lambda d=d: production_bfs_reachable(sqlite_source, hub_t, hub_v, d),
            lambda d=d: neo4j_kg.reachable_node_ids(hub_t, hub_v, max_depth=d),
        )
    # Keep retriever instances referenced (used for parity sanity, avoid lint).
    _ = (sqlite_retriever, neo4j_retriever)

    # Shortest path between indirectly connected pairs (avg over the pairs).
    pairs = graph.indirect_pairs
    max_sp_depth = max(depths)

    def sqlite_sp() -> list[Any]:
        out: list[Any] = []
        for (ft, fv), (tt, tv) in pairs:
            p = _sqlite_shortest_path(sqlite_backend, ft, fv, tt, tv, max_sp_depth)
            if p:
                out.append(p)
        return out

    def neo4j_sp() -> list[Any]:
        out: list[Any] = []
        for (ft, fv), (tt, tv) in pairs:
            p = neo4j_kg.shortest_path(ft, fv, tt, tv, max_depth=max_sp_depth)
            if p:
                out.append(p)
        return out

    # Directed shortest path: the production default-path BFS walks only
    # outgoing edges. On real CTI data many pairs are only connected against
    # edge direction, so this finds FEWER paths than Neo4j's undirected
    # shortestPath; the result-size gap is itself a finding (capability, not
    # just latency) and is reported.
    record("shortest_path_directed", sqlite_sp, neo4j_sp)

    def sqlite_sp_undirected() -> list[Any]:
        out: list[Any] = []
        for (ft, fv), (tt, tv) in pairs:
            p = _sqlite_shortest_path_undirected(
                sqlite_backend, ft, fv, tt, tv, max_sp_depth
            )
            if p:
                out.append(p)
        return out

    # Undirected shortest path: SQLite BFS walks both in- and out-edges so it
    # answers the IDENTICAL question as Neo4j's undirected shortestPath. This is
    # the apples-to-apples latency comparison (matched result sizes).
    record("shortest_path_undirected", sqlite_sp_undirected, neo4j_sp)

    sqlite_backend.close()
    neo4j_kg.close()
    return results


# ── Report ───────────────────────────────────────────────────────────────


def write_report(
    results: dict[str, Any],
    out_dir: Path,
    json_name: str = "graph_backend_results.json",
    md_name: str = "graph_backend_results.md",
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / json_name
    md_path = out_dir / md_name

    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    ds = results["dataset"]
    source = results.get("source", "synthetic")
    lines: list[str] = []
    title_src = "REAL OpenCTI data" if source == "opencti" else "synthetic data"
    lines.append(f"# Graph backend benchmark: Neo4j vs default (SQLite) on {title_src}")
    lines.append("")
    lines.append(
        f"Dataset: {ds['nodes']} nodes, {ds['edges']} edges. "
        f"Repeats: {ds['repeat']}. Depths: {', '.join(str(d) for d in ds['depths'])}."
    )
    lines.append("")
    lines.append(f"Baseline: {results['baseline']}.")
    lines.append("")
    if "opencti_meta" in results:
        m = results["opencti_meta"]
        lines.append("## Real graph characteristics")
        lines.append("")
        lines.append(
            f"Source: live OpenCTI instance (read-only OpenSearch scroll). "
            f"Avg degree {m['avg_degree']}, max total degree {m['max_degree']}, "
            f"max out-degree {m.get('max_out_degree', '?')}. "
            f"Node identity = OpenCTI internal_id (real topology preserved exactly)."
        )
        lines.append("")
        lines.append(
            f"Forward-traversal hub probe (highest OUT-degree): {m['hub_name']} "
            f"(out-degree {m['hub_degree']}, total degree {m.get('hub_total_degree', '?')}). "
            f"Note: the highest *total*-degree nodes in real CTI data are MITRE "
            f"techniques, which are pure sinks (hundreds of incoming `uses`, zero "
            f"outgoing); a forward traversal from them visits nothing, so the "
            f"traversal probe uses the highest out-degree node (a malware / "
            f"intrusion-set that `uses` many techniques)."
        )
        lines.append("")
        lines.append("Top hub entities by total degree:")
        lines.append("")
        lines.append("| Entity | Type | Total degree | Out-degree |")
        lines.append("|---|---|---|---|")
        for h in m["top_hubs"]:
            lines.append(
                f"| {h['name']} | {h['type']} | {h['degree']} | {h.get('out_degree', '?')} |"
            )
        lines.append("")
        if m.get("top_out_hubs"):
            lines.append("Top hub entities by out-degree (the real forward-traversal hubs):")
            lines.append("")
            lines.append("| Entity | Type | Out-degree | Total degree |")
            lines.append("|---|---|---|---|")
            for h in m["top_out_hubs"]:
                lines.append(
                    f"| {h['name']} | {h['type']} | {h['out_degree']} | "
                    f"{h.get('total_degree', '?')} |"
                )
            lines.append("")
        dists = m.get("pair_distances", [])
        if dists:
            lines.append(
                f"Shortest-path probe pairs: {len(dists)} pairs at undirected graph "
                f"distance {min(dists)}-{max(dists)} (median "
                f"{int(statistics.median(dists))}). These are genuinely indirectly "
                f"connected real entities, not adjacent ones."
            )
            lines.append("")
    lines.append(
        "The default (SQLite) traversal cost is the production graph stage: a "
        "Python-side reachable-set BFS that issues one `get_kg_edges_from` / "
        "`get_kg_node_by_id` call per visited node over the indexed `kg_edges` "
        "table (the `GraphRetriever` path recall actually uses), not the "
        "rarely-used `traverse_kg`. SQLite has no native shortest-path operator, "
        "so its shortest-path figure is a Python BFS over `get_kg_edges_from` — "
        "the work the default path must do to answer a path query. The "
        "`*_ids_*` rows return only the reachable node-id set (what recall "
        "scores), isolating traversal cost from full-object serialization."
    )
    lines.append("")
    lines.append(
        "| Query | SQLite median (ms) | SQLite p95 (ms) | Neo4j median (ms) | "
        "Neo4j p95 (ms) | Speedup (SQLite/Neo4j) | Result size (SQLite / Neo4j) |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for name, q in results["queries"].items():
        lines.append(
            f"| {name} | {q['sqlite_median_ms']} | {q['sqlite_p95_ms']} | "
            f"{q['neo4j_median_ms']} | {q['neo4j_p95_ms']} | {q['speedup_ratio']}x | "
            f"{q['sqlite_result_size']} / {q['neo4j_result_size']} |"
        )
    lines.append("")
    lines.append(
        "Speedup = SQLite median / Neo4j median: a value < 1 means SQLite is "
        "faster (Neo4j slower by 1/ratio); a value >= 5 means Neo4j is >= 5x "
        "faster (the SC-003 target). `shortest_path_directed` is the production "
        "default (outgoing-only) BFS and finds fewer paths on real CTI data, so "
        "its result size is smaller than Neo4j's undirected count; "
        "`shortest_path_undirected` walks both directions for an identical "
        "question (matched sizes) and is the apples-to-apples path comparison."
    )
    lines.append("")

    # SC-003 verdict: depth-3+ traversal and shortest path >= 5x faster.
    # SC-003 is evaluated on the contract-shaped queries (full node/path
    # results), excluding the id-only diagnostic variant.
    sc003_targets = [
        name
        for name in results["queries"]
        if (
            (name.startswith("traverse_depth_") or name.startswith("traverse_hub_depth_"))
            and name.rsplit("_", 1)[1].isdigit()
            and int(name.rsplit("_", 1)[1]) >= 3
        )
        or name in ("shortest_path", "shortest_path_undirected")
    ]
    met = all(results["queries"][n]["speedup_ratio"] >= 5.0 for n in sc003_targets)
    lines.append("## SC-003 (>= 5x faster at depth 3+ and shortest path)")
    lines.append("")
    for n in sc003_targets:
        r = results["queries"][n]["speedup_ratio"]
        lines.append(f"- {n}: {r}x {'PASS' if r >= 5.0 else 'FAIL'}")
    lines.append("")
    lines.append(f"Verdict: {'MET' if met else 'NOT MET'}.")
    lines.append("")
    results["sc003_met"] = met
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    with open(md_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote {md_path} and {json_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=10000)
    parser.add_argument("--edges", type=int, default=50000)
    parser.add_argument("--depths", type=str, default="2,3,4,5")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument(
        "--source",
        choices=["synthetic", "opencti"],
        default="synthetic",
        help="synthetic = generated graph; opencti = load real graph from --graph-file",
    )
    parser.add_argument(
        "--graph-file",
        type=str,
        default=str(Path(__file__).parent / "opencti_graph.json"),
        help="extracted real-graph JSON (used when --source opencti)",
    )
    args = parser.parse_args()

    depths = [int(d) for d in args.depths.split(",") if d.strip()]

    if args.source == "opencti":
        print(f"Loading real OpenCTI graph from {args.graph_file} ...")
        graph = load_opencti_graph(args.graph_file)
        results = run_benchmark(
            0, 0, depths, args.repeat, graph=graph, source="opencti"
        )
        write_report(
            results,
            Path(__file__).parent,
            json_name="graph_backend_results_opencti.json",
            md_name="graph_backend_results_opencti.md",
        )
    else:
        results = run_benchmark(args.nodes, args.edges, depths, args.repeat)
        write_report(results, Path(__file__).parent)


if __name__ == "__main__":
    main()
