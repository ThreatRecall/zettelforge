# Quickstart: enable the Neo4j path-query backend

This is the operator path the feature must make possible in under 15 minutes (SC-005).
Neo4j is a scoped, opt-in path-query seam: SQLite stays the storage and
recall/traversal path; only undirected path-finding routes to Neo4j.

## 1. Start Neo4j (dev/bench)

`NEO4J_PASSWORD` is required (no baked default; `up` fails fast if it is unset):

```bash
NEO4J_PASSWORD=your-password docker compose -f deploy/neo4j/docker-compose.yml up -d
# Neo4j browser on the mapped host port (17474); Bolt on the mapped bolt port (17687).
```

## 2. Install the optional dependency

```bash
pip install "zettelforge[neo4j]"
```

## 3. Enable path-finding and configure the connection

`ZETTELFORGE_BACKEND` stays `sqlite`. The path-query seam has its own flag:

```bash
export ZETTELFORGE_NEO4J_PATHFINDING=true   # route path-finding to Neo4j (storage stays sqlite)
export ZETTELFORGE_NEO4J_URI="bolt://localhost:17687"   # use the mapped host port
export ZETTELFORGE_NEO4J_USER="neo4j"
export ZETTELFORGE_NEO4J_PASSWORD="$NEO4J_PASSWORD"
# optional:
export ZETTELFORGE_NEO4J_DATABASE="neo4j"
export ZETTELFORGE_NEO4J_FALLBACK=false   # default: fail loud if Neo4j is unreachable
```

## 4. Run a path-finding query

```python
from zettelforge.knowledge_graph import find_shortest_path

# Undirected shortest path between indirectly connected entities (None if no path).
# Routes to Neo4j when pathfinding is enabled; otherwise the default backend's BFS
# answers. Load your graph into Neo4j first (see docs/how-to/configure-neo4j.md).
print(find_shortest_path("ThreatActor", "APT28", "Vulnerability", "CVE-2017-0144"))
```

## 5. Run the benchmark (evidence)

```bash
python -m benchmarks.graph_backend_benchmark --nodes 10000 --edges 50000 --depths 2,3,4,5 --repeat 5
# writes benchmarks/graph_backend_results.{md,json}: per-query median/p95 latency and
# the Neo4j-vs-default ratio for traversal depths 2-5 and shortest path.
```

## Rollback

Unset `ZETTELFORGE_NEO4J_PATHFINDING` (or set it to `false`). Path-finding then
runs on the default backend's BFS again. Storage and recall stay on SQLite
throughout; deployments that never opt in are unaffected.
