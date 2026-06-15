# Phase 0 Research: Neo4j graph backend

## R1: Where Neo4j plugs into the existing code

**Decision**: Implement `Neo4jKnowledgeGraph` to the public interface of `KnowledgeGraph` (in `src/zettelforge/knowledge_graph.py`) and select it inside the existing `get_knowledge_graph()` factory via a new `ZETTELFORGE_BACKEND == "neo4j"` branch, ungated (no `has_extension("enterprise")` check).

**Rationale**: `get_knowledge_graph()` is already the single selection point and already branches for `typedb`. Mirroring that branch is the most surgical change and keeps every caller untouched. The traversal and path operations the feature targets (`traverse`, `get_neighbors`, `get_causal_edges`) live on this interface.

**Alternatives considered**:
- A new `StorageBackend` subclass (full storage incl. notes/vectors) in `backend_factory.py`: rejected, far larger blast radius and out of scope (notes/vectors stay put).
- A standalone Neo4j service the app calls over HTTP: rejected, adds a network/service contract the project does not need; the Bolt driver in-process is simpler.

**Open item for the implementer**: Confirm whether the production traversal read path is the `KnowledgeGraph` instance from `get_knowledge_graph()` or the `StorageBackend.get_kg_neighbors`/SQLite `kg_edges` path used by `memory_manager`. If both feed the graph, ensure edges written through `memory_manager` also reach Neo4j (route the canonical write path to the selected `KnowledgeGraph`). The parity suite must cover whichever path `memory_manager` actually reads.

## R2: Neo4j driver and connection management

**Decision**: Use the official `neo4j` Python driver (Bolt), pinned `neo4j>=5,<6`, as an optional dependency extra `zettelforge[neo4j]`. Hold one module-level `Driver` (thread-safe, pooled) created lazily on first use; open a short-lived `session` per operation; use `execute_read` / `execute_write` managed transactions.

**Rationale**: The official driver is the supported path, has built-in connection pooling, and managed transactions give automatic retry on transient errors. One driver per process is the documented pattern; sessions are cheap and not thread-safe, so per-operation sessions are correct.

**Alternatives considered**: `py2neo` (community, less maintained, no managed-transaction retry) rejected; raw HTTP API rejected (slower, no pooling).

## R3: Mapping the interface to Cypher

**Decision**:
- Node identity is `(entity_type, entity_value)`. Use `MERGE (n:Entity {entity_type:$t, entity_value:$v})` so node creation is idempotent. Store `properties` as node properties (flattened) plus a `node_id`.
- Edge write: `MATCH` both nodes, then `MERGE (a)-[r:REL {relationship:$rel}]->(b)` and set `r.edge_type`, `r.confidence`, `r.note_id`, timestamps, and JSON-encoded `properties`. `MERGE` enforces the existing uniqueness rule (from, to, relationship). Promote `edge_type` from `heuristic` to a more specific type on update, matching current `add_edge` behavior.
- `get_neighbors`: single-hop `MATCH (a)-[r]->(b)` with optional `WHERE r.relationship = $rel`.
- `traverse(max_depth)`: variable-length `MATCH p = (a)-[*1..$depth]->(b)` (depth bound parameterized; default raised from 2, capped by config result-limit).
- shortest path: `MATCH p = shortestPath((a)-[*..$depth]-(b)) RETURN p`.
- causal/temporal queries: filter on `r.edge_type = 'causal'` and on `TEMPORAL_*` / `SUPERSEDES` relationship labels, mirroring the current implementation.

**Rationale**: `MERGE` gives idempotency for free; variable-length patterns and `shortestPath` are the native capabilities that the Python BFS cannot match and are the whole point of the feature. Relationship type stored as a property keeps a single edge label and avoids a label explosion while still allowing typed filtering.

**Alternatives considered**: one Neo4j relationship type per `relationship` label (e.g. `:USES`, `:EXPLOITS`): rejected for v1, complicates dynamic relationship labels and migration; revisit if query planning needs it.

## R4: Dependency packaging

**Decision**: Add `[project.optional-dependencies] neo4j = ["neo4j>=5,<6"]`. Import the driver lazily inside `Neo4jKnowledgeGraph.__init__`; if missing, raise a clear error telling the operator to `pip install "zettelforge[neo4j]"`.

**Rationale**: Preserves the zero-dependency default (FR-002) and the lightweight positioning. Opt-in users explicitly accept the dependency.

## R5: Failure handling

**Decision**: On connection or auth failure, raise a clear, logged error (`structlog`/project logger) and do not report writes as successful. Fallback to the default backend happens only when `ZETTELFORGE_NEO4J_FALLBACK=true` is set, and the fallback is logged loudly. Default is fail-loud.

**Rationale**: Matches FR-008 and the project's fail-closed governance. The current TypeDB path silently falls back to JSONL; this feature intentionally improves on that by defaulting to fail-loud and making fallback explicit and logged.

## R6: Benchmark dataset and method

**Decision**: Generate a synthetic but representative CTI-shaped graph: at least 10k nodes and 50k edges with realistic fan-out (a few high-degree hubs, chains of depth >=5, and indirectly connected entity pairs). Load the identical dataset into both the default backend and Neo4j. For each backend, time: single-hop neighbors, `traverse` at depths 2, 3, 4, 5, and shortest-path between known indirectly connected pairs. Run N repetitions, report median and p95 latency, result counts, and the Neo4j-vs-default ratio. Emit a markdown/JSON report under `benchmarks/`.

**Rationale**: Synthetic data is reproducible, avoids licensing concerns with upstream feeds, and lets us control connectivity to exercise depth and path queries. Identical data into both backends keeps the comparison apples-to-apples (SC-003).

**Alternatives considered**: an OpenCTI export as the dataset: viable later for realism, but adds setup and licensing considerations; kept as an optional second dataset.

## R7: Neo4j version and local runtime

**Decision**: Neo4j 5 Community via Docker for dev and benchmarking, mapped to non-default host ports to avoid colliding with the existing local service stack (OpenCTI etc. already run on this host). Provide `deploy/neo4j/docker-compose.yml` and document credentials via env.

**Rationale**: Neo4j 5 matches the driver pin and is the version Flowsint validates. Community edition (GPLv3 server) is acceptable for self-hosted dev/bench; the SaaS licensing question is tracked separately and is out of scope for this spike.
