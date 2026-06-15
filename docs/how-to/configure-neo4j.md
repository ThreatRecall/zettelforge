---
title: "Enable the Neo4j graph backend"
description: "Configure the optional open-source Neo4j knowledge-graph backend: start Neo4j with Docker, install the driver extra, select the backend by config, and run a deep relationship query."
diataxis_type: "how-to"
audience: "Operators who want native multi-hop traversal and shortest-path queries"
tags: [neo4j, docker, setup, configuration, knowledge-graph, graph-database]
last_updated: "2026-06-15"
version: "2.7.0"
---

# Enable the Neo4j path-query backend

Neo4j is an optional, open-source path-query backend for the ZettelForge
knowledge graph. It is a scoped, opt-in seam, not a wholesale storage backend:
SQLite stays the storage, recall, and traversal path. Enabling Neo4j routes only
undirected path-finding / relationship-discovery queries (`find_shortest_path`)
to Neo4j, where it is roughly 20x faster than the default backend's Python BFS
on real CTI data. The default backend has no native shortest-path operator; this
seam adds that one capability without changing anything else.

Why scoped and not a full backend swap: on real CTI data (7.5k nodes / 35k
edges) Neo4j regresses the bounded traversal that recall actually uses by ~6x,
while winning undirected shortest-path by ~20x. So storage and traversal stay on
SQLite and only path-finding routes to Neo4j. See `benchmarks/graph_backend_results_opencti.md`.

This is part of the open-source product. It is not an enterprise edition and
requires no license. The separate enterprise TypeDB path is unaffected and is a
different feature.

## Two-product model and dependency footprint

- The storage backend always stays SQLite. Enabling Neo4j does not change where
  notes, entities, edges, or recall live. Deployments that do not opt in gain
  zero new mandatory dependencies and behave exactly as before.
- Opting in adds one dependency: the `neo4j` Python driver, installed as the
  `zettelforge[neo4j]` extra, plus an external Neo4j service you run yourself.
- The enterprise TypeDB backend is a separate, unaffected path. Enabling Neo4j
  does not touch it, and Neo4j does not imply an enterprise edition.

## Prerequisites

- Docker and Docker Compose installed
- ZettelForge installed (`pip install zettelforge`)

## Steps

### 1. Start Neo4j with Docker Compose

The bundled compose file runs Neo4j 5 Community on non-default host ports
(17474 for the browser, 17687 for Bolt) so it does not collide with other
services on the host. It also enables APOC for faster reachable-set traversal.

```bash
NEO4J_PASSWORD=change-me docker compose -f deploy/neo4j/docker-compose.yml up -d
```

Wait for the container to report healthy:

```bash
docker inspect --format '{{.State.Health.Status}}' zettelforge-neo4j
```

### 2. Install the driver extra

```bash
pip install "zettelforge[neo4j]"
```

If the driver is missing when the backend is selected, ZettelForge fails loud
with a clear message telling you to install this extra. It never silently
falls back.

### 3. Enable path-finding and configure the connection

`ZETTELFORGE_BACKEND` stays `sqlite` (the default). The path-query seam is
turned on by its own flag:

```bash
export ZETTELFORGE_NEO4J_PATHFINDING=true    # route path-finding to Neo4j (storage stays sqlite)
export ZETTELFORGE_NEO4J_URI="bolt://localhost:17687"   # the mapped Bolt port
export ZETTELFORGE_NEO4J_USER="neo4j"
export ZETTELFORGE_NEO4J_PASSWORD="change-me"
# optional:
export ZETTELFORGE_NEO4J_DATABASE="neo4j"
export ZETTELFORGE_NEO4J_MAX_DEPTH=5         # path-length cap (default 5)
export ZETTELFORGE_NEO4J_RESULT_LIMIT=10000  # bounds high-degree hub traversal
export ZETTELFORGE_NEO4J_FALLBACK=false      # default: fail loud if unreachable
```

These can also live under a `neo4j:` block in `config.yaml`; the password
supports `${ENV_VAR}` references so it stays out of the file.

### 4. Load the graph into Neo4j

The seam queries Neo4j; it does not dual-write to it from the hot path (that
would put default-path recall at risk). Populate Neo4j from your canonical
SQLite graph using the `Neo4jKnowledgeGraph` write interface, then refresh it
when the graph changes. The benchmark loader (`benchmarks/extract_opencti_graph.py`)
shows the pattern. A standalone sync job is tracked as a follow-up.

### 5. Run a path-finding query

```python
from zettelforge.knowledge_graph import find_shortest_path

# Undirected shortest path between indirectly connected entities (None if none).
# Routes to Neo4j when ZETTELFORGE_NEO4J_PATHFINDING=true; otherwise the default
# backend's BFS answers. Storage and recall are unaffected either way.
path = find_shortest_path("ThreatActor", "APT28", "Vulnerability", "CVE-2017-0144")
print(path)
```

## Populate / sync the graph

The path-query seam **queries** Neo4j but deliberately does **not** dual-write
from the ingest hot path (that regressed the SQLite write/recall path). So with
pathfinding enabled and an unpopulated Neo4j, path queries run against an empty
graph. A standalone job mirrors the SQLite knowledge graph into Neo4j:

```bash
# Preview: read the source graph, connect read-only, report the delta (no writes)
python -m zettelforge.scripts.neo4j_sync --data-dir ~/.zettelforge --dry-run

# Incremental upsert (default) — safe to run repeatedly / on a schedule
python -m zettelforge.scripts.neo4j_sync --data-dir ~/.zettelforge

# Exact mirror: wipe the ZettelForge graph then reload (deletions included)
python -m zettelforge.scripts.neo4j_sync --data-dir ~/.zettelforge --rebuild
```

The job reads `ZETTELFORGE_NEO4J_*` for the connection and emits a JSON report
(node/edge counts before and after, plus a parity verdict); pass `--output` to
also write it to a file. It populates Neo4j regardless of
`ZETTELFORGE_NEO4J_PATHFINDING` (the gate controls query routing, not whether
Neo4j may be loaded).

### Consistency / staleness contract

* **SQLite is the system of record.** Neo4j is a derived read-replica used only
  by the path-query seam. The job is one-way (SQLite to Neo4j) and never writes
  back.
* **Default is incremental upsert.** Every current node/edge is MERGEd
  (idempotent on `(entity_type, entity_value)` for nodes and
  `(from, to, relationship)` for edges). The live graph is never emptied and is
  always a superset-or-equal of SQLite. Upsert does **not** delete: entities or
  edges removed from SQLite remain in Neo4j (the SQLite graph is append-mostly
  and carries no deletion log).
* **`--rebuild` is the exact mirror.** It deletes only `:Entity` nodes and their
  `:REL` edges (in bounded sub-transactions), then reloads, so deletions
  propagate. During a rebuild the graph is transiently partial: prefer it on a
  quiesced window. Incremental upsert is the safe default for a live seam.
* **Staleness.** Neo4j reflects SQLite as of the last successful sync; path
  queries may miss edges added since. Bound staleness by scheduling the job, or
  run it on demand for an immediate refresh. Because SQLite stays the system of
  record, a stale or empty Neo4j only affects the opt-in path-query seam, never
  storage or recall.
* **Fail-loud.** A connection failure during a mutating run exits non-zero
  (never reports a dropped sync as success). After the load, Neo4j counts are
  verified against the source; a mismatch exits non-zero.

### Schedule it

The job is a plain idempotent command, so any scheduler works. Example systemd
timer running an hourly incremental upsert:

```ini
# /etc/systemd/system/zettelforge-neo4j-sync.service
[Service]
Type=oneshot
Environment=ZETTELFORGE_NEO4J_PASSWORD=...
ExecStart=/usr/bin/python -m zettelforge.scripts.neo4j_sync --data-dir /var/lib/zettelforge

# /etc/systemd/system/zettelforge-neo4j-sync.timer
[Timer]
OnCalendar=hourly
Persistent=true
[Install]
WantedBy=timers.target
```

Equivalently as cron: `@hourly python -m zettelforge.scripts.neo4j_sync --data-dir /var/lib/zettelforge`.

## Failure behavior

When Neo4j is unreachable or the credentials are wrong, `find_shortest_path`
raises a clear, logged `Neo4jUnavailableError` and never silently returns an
empty path as if it were real. Fallback to the default backend's BFS path-finding
happens only when you explicitly set `ZETTELFORGE_NEO4J_FALLBACK=true`, and that
fallback is logged. The default is fail-loud.

## Benchmark the backends

A benchmark loads one synthetic dataset into both Neo4j and the default SQLite
path and times single-hop, multi-hop traversal (depths 2-5), and shortest path
on each:

```bash
python -m benchmarks.graph_backend_benchmark --nodes 10000 --edges 50000 \
    --depths 2,3,4,5 --repeat 5
# writes benchmarks/graph_backend_results.{md,json}
```

The report records median and p95 latency per query and the Neo4j-vs-default
ratio. Neo4j's clearest wins are native shortest-path and deep, high-breadth
traversal that does not load the graph into application memory; on a small
single-machine graph the in-process SQLite path can be faster for shallow
traversal because it has no network boundary. See the generated report for the
measured numbers on your hardware.

## Rollback

Unset `ZETTELFORGE_NEO4J_PATHFINDING` (or set it to `false`). Path-finding then
runs on the default backend's BFS again. No data in the default store is touched
by enabling Neo4j; deployments that never opt in are unaffected. To stop Neo4j:

```bash
docker compose -f deploy/neo4j/docker-compose.yml down
```
