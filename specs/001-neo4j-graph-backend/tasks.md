# Tasks: Neo4j graph backend for the knowledge graph

**Feature**: `001-neo4j-graph-backend` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

Tests are included because behavioral parity (SC-001) and benchmarked evidence (FR-009) are core acceptance criteria.

## Productionization delta (AGE-117, VP Engineering scoped approval)

The spike below explored Neo4j as a selectable whole backend (`ZETTELFORGE_BACKEND=neo4j`). The real-OpenCTI benchmark showed that swap regresses the traversal recall actually uses by ~6x and only wins undirected shortest-path (~20x). VP Engineering approved merge scoped to a path-query seam, not the swap (see AGE-116 decision). The productionized shape, implemented in this branch:

- SQLite stays the storage, recall, and traversal backend. The `backend == "neo4j"` branch was removed from `get_knowledge_graph()` (no wholesale swap).
- A new gate `ZETTELFORGE_NEO4J_PATHFINDING` (`config.neo4j.pathfinding`) routes only undirected path-finding to Neo4j via the new module function `find_shortest_path()`. Everything else stays on the default backend.
- Fail-loud + explicit-fallback (`ZETTELFORGE_NEO4J_FALLBACK`) preserved at the seam. The default backend gained an undirected-BFS `KnowledgeGraph.shortest_path()` as the disabled/fallback path.
- Supersedes T010 (ungated full-backend branch) and the `get_knowledge_graph()` part of T021; both are replaced by the seam. The `Neo4jKnowledgeGraph` class is retained in full for parity tests, benchmarking, and population.

Population note: the seam queries Neo4j and does not dual-write from the hot path (keeps default-path recall zero-risk). Loading/sync of the canonical graph into Neo4j is a documented follow-up.

## Phase 1: Setup

- [ ] T001 Add optional dependency extra `neo4j = ["neo4j>=5,<6"]` under `[project.optional-dependencies]` in `pyproject.toml`
- [ ] T002 [P] Add Neo4j settings to `src/zettelforge/config.py`: `ZETTELFORGE_NEO4J_URI`, `_USER`, `_PASSWORD`, `_DATABASE`, `ZETTELFORGE_NEO4J_MAX_DEPTH` (default 5), `ZETTELFORGE_NEO4J_RESULT_LIMIT`, `ZETTELFORGE_NEO4J_FALLBACK` (default false)
- [ ] T003 [P] Add `deploy/neo4j/docker-compose.yml` for Neo4j 5 Community on non-default host ports (avoid colliding with the running OpenCTI stack), with env-based credentials

## Phase 2: Foundational (blocks all user stories)

- [ ] T004 Create `src/zettelforge/neo4j_knowledge_graph.py` with the `Neo4jKnowledgeGraph` class: lazy module-level `Driver`, per-operation managed sessions, clear ImportError if the `neo4j` extra is missing, and schema init (NODE KEY / uniqueness + index on `:Entity(entity_type, entity_value)`, index on `:REL(relationship)` and `:REL(edge_type)`)
- [ ] T005 Confirm the canonical KG read/write path per research R1 (whether `memory_manager` reads from `get_knowledge_graph()` or `StorageBackend.get_kg_neighbors`); record the finding in a module docstring and ensure the selected backend receives the canonical writes in `src/zettelforge/neo4j_knowledge_graph.py`

## Phase 3: User Story 1 - Drop-in selection with parity (Priority: P1) 🎯 MVP

**Goal**: An operator selects the Neo4j backend by config and every existing KG operation behaves identically through the unchanged interface.

**Independent test**: Run the existing KG operations against a known dataset on both backends; results match field-by-field.

- [ ] T006 [US1] Implement `add_node`, `get_node`, `get_node_by_id` with `MERGE` on `(entity_type, entity_value)` and return-shape parity in `src/zettelforge/neo4j_knowledge_graph.py`
- [ ] T007 [US1] Implement `add_edge` (MERGE dedup on (from,to,relationship), `edge_type` default `heuristic` + promotion on update, temporal indexing for `TEMPORAL_*`/`SUPERSEDES`) and `add_temporal_edge` in `src/zettelforge/neo4j_knowledge_graph.py`
- [ ] T008 [US1] Implement `get_neighbors` (optional relationship filter) and `get_outgoing_edges` with parity in `src/zettelforge/neo4j_knowledge_graph.py`
- [ ] T009 [US1] Implement `get_causal_edges`, `get_incoming_causal`, `get_entity_timeline`, `get_changes_since`, `get_latest_state` in `src/zettelforge/neo4j_knowledge_graph.py`
- [ ] T010 [US1] Add the ungated `backend == "neo4j"` branch to `get_knowledge_graph()` in `src/zettelforge/knowledge_graph.py` (no `has_extension` check); leave the TypeDB branch untouched
- [ ] T011 [P] [US1] Unit tests for Cypher construction and result mapping (no live DB) in `tests/unit/test_neo4j_knowledge_graph.py`
- [ ] T012 [US1] Parity integration test vs the default backend, gated by `requires_neo4j`, in `tests/integration/test_neo4j_parity.py`

## Phase 4: User Story 2 - Deep traversal and shortest path (Priority: P1)

**Goal**: Multi-hop traversal to depth >=5 and shortest-path queries return complete results the default backend cannot.

**Independent test**: On a connected dataset, traverse depth 3-5 from a seed and find the shortest path between two indirectly connected entities.

- [ ] T013 [US2] Implement `traverse(start_type, start_value, max_depth)` via variable-length Cypher `(*1..$depth)`, bounded by configured max depth and result limit (report limit hits) in `src/zettelforge/neo4j_knowledge_graph.py`
- [ ] T014 [US2] Implement new additive `shortest_path(from_type, from_value, to_type, to_value, max_depth=None)` via `shortestPath`, returning an ordered node/edge path or `None` when no path, in `src/zettelforge/neo4j_knowledge_graph.py`
- [ ] T015 [P] [US2] Integration tests: depth 3-5 completeness, shortest path, and the no-path edge case, gated by `requires_neo4j`, in `tests/integration/test_neo4j_traversal.py`

## Phase 5: User Story 3 - Benchmark evidence (Priority: P2)

**Goal**: Measured comparison of multi-hop and shortest-path performance, Neo4j vs the default backend.

**Independent test**: Run the harness; it loads identical data into both backends and emits a report with per-query latency and the ratio.

- [ ] T016 [US3] Synthetic dataset generator (>=10k nodes, >=50k edges, hubs, depth>=5 chains, indirectly connected pairs) in `benchmarks/graph_backend_benchmark.py`
- [ ] T017 [US3] Benchmark runner: load identical data into both backends; time single-hop, `traverse` depths 2-5, and shortest path; N repeats; median + p95 in `benchmarks/graph_backend_benchmark.py`
- [ ] T018 [US3] Report emitter writing `benchmarks/graph_backend_results.md` and `.json` with the Neo4j-vs-default ratio per query
- [ ] T019 [US3] Run the benchmark against the Dockerized Neo4j and capture `benchmarks/graph_backend_results.*`

## Phase 6: User Story 4 - Fail-loud on outage (Priority: P3)

**Goal**: Graph-database outage surfaces clearly; no silent write loss or silent backend switch.

**Independent test**: Make Neo4j unreachable; confirm a clear logged error on write and at startup; confirm fallback only when explicitly configured.

- [ ] T020 [US4] Raise a clear, logged error on connection/auth failure and never report a dropped write as successful, in `src/zettelforge/neo4j_knowledge_graph.py`
- [ ] T021 [US4] Implement explicit `ZETTELFORGE_NEO4J_FALLBACK` behavior (default false = fail loud; true = logged fallback to default backend) in `get_knowledge_graph()` / backend init
- [ ] T022 [P] [US4] Tests for unreachable DB at write-time and at startup in `tests/integration/test_neo4j_failure.py`

## Phase 7: Polish & cross-cutting

- [ ] T023 [P] Write `docs/how-to/configure-neo4j.md` (enable, dependency footprint, two-product note, no enterprise edition implied)
- [ ] T024 [P] Verify `quickstart.md` steps end to end and align env var names with `config.py`
- [ ] T025 Run `ruff` and `mypy` on new files; confirm the default backend path is byte-for-byte unchanged in behavior (no regressions)

## Dependencies & execution order

- Setup (T001-T003) → Foundational (T004-T005) → US1 (T006-T012) → US2 (T013-T015) → US3 (T016-T019) → US4 (T020-T022) → Polish (T023-T025).
- US2 depends on US1 (node/edge writes must exist). US3 depends on US1 + US2 (both query types must work). US4 is largely independent but touches backend init, so sequence after US1.
- [P] tasks within a phase touch different files and can run in parallel.

## MVP scope

User Story 1 (T001-T012) is the MVP: config-selectable Neo4j backend with full parity. User Story 2 delivers the core value (deep traversal + shortest path). User Story 3 produces the adoption evidence the owner requires.
