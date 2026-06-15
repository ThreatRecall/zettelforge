# Implementation Plan: Neo4j graph backend for the knowledge graph

**Branch**: `001-neo4j-graph-backend` | **Date**: 2026-06-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-neo4j-graph-backend/spec.md`

## Summary

Add Neo4j as an opt-in graph backend for the ZettelForge knowledge graph, selected through the existing `get_knowledge_graph()` factory and `ZETTELFORGE_BACKEND` configuration, parallel to the enterprise-gated TypeDB path but ungated and available in the open-source product. The new `Neo4jKnowledgeGraph` implements the existing `KnowledgeGraph` public interface, so no caller changes. Native Cypher traversal and `shortestPath` replace the Python-side bounded BFS, removing the depth cap and adding path-finding. A benchmark harness loads one dataset into both backends and measures depth 2 to 5 traversal and shortest-path latency and completeness, producing the evidence required to adopt it. SQLite/JSONL remains the zero-dependency default; the Neo4j driver is an optional dependency extra.

## Technical Context

**Language/Version**: Python 3.10+ (per `pyproject.toml` `requires-python`)

**Primary Dependencies**: `neo4j` official Python driver (Bolt), added as an optional extra `zettelforge[neo4j]`. Default install adds nothing.

**Storage**: Neo4j (graph nodes/edges, opt-in) alongside the unchanged defaults: SQLite (relational) and LanceDB (vectors). Neo4j stores only KG nodes and edges; note text and embeddings stay where they are.

**Testing**: pytest. Unit tests for query construction and mapping; integration/parity tests gated by a `requires_neo4j` marker against a Dockerized Neo4j.

**Target Platform**: Linux self-hosted; Neo4j runs as an external service (Docker for dev and benchmarking).

**Project Type**: Single Python library/CLI (`src/zettelforge/`).

**Performance Goals**: Depth-3 and deeper traversal and shortest-path queries at least 5x faster than the current default path on a 10k-node / 50k-edge dataset; support configurable depth of at least 5 (vs the current default-2 cap).

**Constraints**: Zero new mandatory dependencies for non-opt-in users; fail-loud on graph-database outage (no silent fallback); surgical change to `get_knowledge_graph()`; no modification to the TypeDB enterprise path; preserve the existing node/edge model and dedup rule.

**Scale/Scope**: One new backend class, one selection branch, one config block, one optional dependency, one benchmark, parity + unit tests, one how-to doc, one dev Docker compose.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository `.specify/memory/constitution.md` is an unratified stub, so this gate applies the project's governing engineering principles (root `CLAUDE.md`: Simplicity First, Surgical Changes, Schema First, Fail Closed / Fail Loud, two-product model).

| Principle | Assessment |
|-----------|------------|
| Simplicity first | PASS. Reuses the existing `KnowledgeGraph` interface and the existing `ZETTELFORGE_BACKEND` selection seam. No new abstraction layer; one new class implementing an existing contract. |
| Surgical changes | PASS. New file `neo4j_knowledge_graph.py`; a single added branch in `get_knowledge_graph()`; additive config; a `pyproject` optional extra; a new benchmark and tests. No existing backend is edited. |
| Schema first / typed | PASS. Reuses the established node/edge shape; the Cypher mapping is fixed and typed; no new dict-shaped boundary beyond what already exists. |
| Fail closed / fail loud | PASS. Outage and misconfiguration raise clear, logged errors; any fallback is explicit and configured, never silent. Matches FR-008. |
| Two-product model | PASS. Neo4j is ungated and open-source; the enterprise TypeDB path is untouched. No "enterprise edition" implied. |

No violations. Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-neo4j-graph-backend/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (KG interface contract)
│   └── kg-interface.md
└── tasks.md             # Phase 2 output (speckit-tasks)
```

### Source Code (repository root)

```text
src/zettelforge/
├── knowledge_graph.py          # EDIT: add ungated `neo4j` branch in get_knowledge_graph()
├── neo4j_knowledge_graph.py    # NEW: Neo4jKnowledgeGraph implementing the KnowledgeGraph interface
└── config.py                   # EDIT: Neo4j connection settings (uri/user/password/database, depth/limit caps, fallback mode)

pyproject.toml                  # EDIT: [project.optional-dependencies] neo4j = ["neo4j>=5,<6"]

benchmarks/
└── graph_backend_benchmark.py  # NEW: load one dataset into both backends; time depth 2-5 traversal + shortest path; emit report

tests/
├── unit/
│   └── test_neo4j_knowledge_graph.py   # NEW: Cypher construction + result mapping (no live DB)
└── integration/
    └── test_neo4j_parity.py            # NEW: parity vs default backend; gated by `requires_neo4j`

deploy/neo4j/
└── docker-compose.yml          # NEW: local Neo4j for dev and benchmarking

docs/how-to/
└── configure-neo4j.md          # NEW: enable the backend, dependency footprint, two-product note
```

**Structure Decision**: Single-project Python library. The feature is additive: one new backend module mirroring the existing TypeDB selection pattern, behind the unchanged `KnowledgeGraph` interface. The benchmark lives in the existing `benchmarks/` tree alongside the other performance harnesses.

## Complexity Tracking

No constitution violations. Section intentionally empty.
