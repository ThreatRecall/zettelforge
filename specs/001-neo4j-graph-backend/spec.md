# Feature Specification: Neo4j graph backend for the knowledge graph

**Feature Branch**: `001-neo4j-graph-backend`

**Created**: 2026-06-15

**Status**: Draft

**Input**: User description: "Add Neo4j as an optional graph storage backend for ZettelForge's knowledge graph, implementing the existing knowledge-graph interface and selectable via config alongside the current SQLite default. Replace the primitive flat-table kg_nodes/kg_edges graph with a real graph database supporting native multi-hop traversal and path-finding. Architecture informed by Flowsint's Apache-2.0 Neo4j integration. Include a benchmark harness comparing multi-hop and shortest-path queries (depth 2 to 5) between the Neo4j backend and the existing SQLite backend. Keep SQLite as the zero-dependency default; gate Neo4j behind config so existing deployments are unaffected; preserve the two-product model."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator selects a real graph backend without touching application code (Priority: P1)

A ZettelForge operator wants stronger relationship capability than the default flat-table graph. They set a single configuration value to select the graph-database backend. Every part of the system that reads or writes the knowledge graph keeps working through the same interface, with no code changes and no change to how notes or vector recall behave.

**Why this priority**: This is the minimum viable product. Without drop-in selection and full behavioral parity through the existing interface, nothing else can ship. It also protects every existing deployment: if the operator does not opt in, behavior is unchanged.

**Independent Test**: Point a test deployment at the graph backend via config, run the existing knowledge-graph operations (add node, add edge, single-hop neighbors, bounded traverse, causal and temporal queries) against a known dataset, and confirm results match the default backend for the same inputs.

**Acceptance Scenarios**:

1. **Given** a config value selecting the graph backend, **When** the system stores nodes and edges, **Then** the same node and edge data is retrievable through the unchanged knowledge-graph interface.
2. **Given** no opt-in to the graph backend, **When** the system runs, **Then** it uses the default backend with zero new mandatory dependencies and identical behavior to today.
3. **Given** the graph backend is selected, **When** any existing caller queries relationships, **Then** the caller needs no modification and receives results in the same shape as the default backend.

---

### User Story 2 - Analyst or agent uncovers deep, indirect relationships (Priority: P1)

An LLM agent or analyst needs to find connections that are more than two hops away, and to find the shortest path between two entities (for example, from a threat actor to a CVE through malware and techniques). The default backend cannot answer these efficiently or completely. With the graph backend, deep multi-hop traversal and shortest-path queries return complete results quickly.

**Why this priority**: This is the actual value the feature exists to deliver: uncovering new relationships between entities. It is the capability the default backend lacks and the reason to add a real graph database.

**Independent Test**: On a representative dataset, request all entities connected to a seed entity within depth 3 to 5, and request the shortest path between two entities known to be connected indirectly. Confirm the graph backend returns complete, correct results where the default backend is capped or incomplete.

**Acceptance Scenarios**:

1. **Given** entities connected through 4 intermediate relationships, **When** an analyst requests connections up to depth 5 from a seed entity, **Then** the system returns the full connected set including the depth-4 entities.
2. **Given** two entities connected only indirectly, **When** an analyst requests the shortest path between them, **Then** the system returns an ordered path of entities and relationships.
3. **Given** the same query on the default backend, **When** depth exceeds the default cap, **Then** the limitation is observable and documented, establishing the capability gap the graph backend closes.

---

### User Story 3 - Maintainer proves the capability and performance gain with evidence (Priority: P2)

A maintainer needs verifiable evidence, not assertion, that the graph backend is worth adopting. They run a benchmark that loads a representative dataset into both backends and measures multi-hop traversal (depth 2 to 5) and shortest-path query latency and completeness on each, producing a comparison report.

**Why this priority**: The owner requires evidence-bound decisions. The benchmark turns "should be faster" into a measured result and guards against regressions. It is required for the adoption decision but not for the backend to function.

**Independent Test**: Run the benchmark harness end to end; confirm it loads the same dataset into both backends, executes the same query set against each, and writes a report with per-query latency and result-size for both backends.

**Acceptance Scenarios**:

1. **Given** a representative dataset, **When** the benchmark runs, **Then** it reports latency and result completeness for depth-2 through depth-5 traversal and for shortest-path queries on both backends.
2. **Given** the benchmark output, **When** a maintainer reviews it, **Then** the relative performance and capability difference between the two backends is stated as measured numbers.

---

### User Story 4 - Graph database outage does not corrupt or silently degrade memory (Priority: P3)

When the selected graph database is unreachable, the system surfaces the failure clearly rather than silently losing writes or returning empty results as if they were real.

**Why this priority**: Correctness and trust. A memory system that silently drops relationships is worse than one that stops loudly. This hardens the opt-in path but is not needed to demonstrate the core capability.

**Independent Test**: Select the graph backend, make the graph database unreachable, and confirm the system raises a clear, logged error (or performs the configured fallback) without reporting success on a dropped write.

**Acceptance Scenarios**:

1. **Given** the graph backend is selected and the database is unreachable, **When** a write is attempted, **Then** the system raises a clear, logged error and does not report the write as successful.
2. **Given** the database is unreachable at startup, **When** the system initializes, **Then** it reports the misconfiguration clearly instead of silently using a different backend.

### Edge Cases

- A query requests a path between two entities that are not connected: the system returns an explicit "no path" result, not an error.
- Traversal originates at a very high-degree hub entity: results are bounded by a configurable result limit and the limit is reported, never silently truncated.
- The same relationship is asserted by multiple notes: storage deduplicates consistently with the existing uniqueness rule and does not create duplicate edges.
- Credentials for the graph database are missing or wrong: the system fails loud with a clear message and never proceeds as if connected.
- A dataset larger than memory is loaded: traversal and path queries still operate without loading the whole graph into application memory.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST offer a graph-database backend for the knowledge graph that is selected by a single configuration value, alongside the existing default backend.
- **FR-002**: The system MUST keep the existing zero-dependency default backend as the default, with unchanged behavior, for any deployment that does not opt in to the graph backend.
- **FR-003**: The graph backend MUST implement the complete existing knowledge-graph interface (add node, add edge, single-hop neighbors, bounded multi-hop traverse, causal-chain queries, temporal queries) so that no calling code requires modification.
- **FR-004**: The graph backend MUST support native multi-hop traversal to a configurable maximum depth of at least 5, and MUST support shortest-path queries between two entities.
- **FR-005**: The graph backend MUST preserve the existing entity and relationship model: entity types and values, typed and directional relationships, and edge metadata (edge type, confidence, properties, and originating-note provenance).
- **FR-006**: Relationship writes to the graph backend MUST be idempotent and deduplicated consistent with the existing uniqueness rule (origin entity, target entity, relationship, originating note).
- **FR-007**: The graph backend MUST be available without any paid or enterprise extension; opt-in is by configuration only. The separate enterprise graph option MUST remain unaffected.
- **FR-008**: When the selected graph database is unreachable or misconfigured, the system MUST fail loud with a clear, logged error and MUST NOT silently lose writes; any fallback MUST be explicit and configured, never silent.
- **FR-009**: The system MUST provide a benchmark that loads one representative dataset into both the graph backend and the default backend and measures, for each, the latency and result completeness of multi-hop traversal at depths 2 through 5 and of shortest-path queries, emitting a comparison report.
- **FR-010**: The system MUST provide a way to load existing knowledge-graph data into the graph backend so the two backends can be compared on identical data.
- **FR-011**: Documentation MUST explain how to enable the graph backend, its added dependency footprint, and that it is part of the open-source product (no enterprise edition implied), consistent with the two-product model.

### Key Entities *(include if feature involves data)*

- **Knowledge graph node**: An entity in the graph. Has an entity type, an entity value, and arbitrary properties. Identity is the (entity type, entity value) pair.
- **Knowledge graph edge**: A typed, directional relationship from one node to another. Carries a relationship label, an edge type (for example causal, heuristic, temporal), a confidence value, arbitrary properties, and the identifier of the note that asserted it.
- **Graph backend selection**: The configuration that determines which backend stores and serves the knowledge graph for a deployment.
- **Benchmark result**: A measured record per query and per backend, capturing query kind (traversal depth or shortest path), latency, and result size, used to compare backends.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the graph backend selected, every existing knowledge-graph operation returns results that match the default backend for the same dataset across a parity test suite (100 percent parity on covered operations).
- **SC-002**: Depth-3 through depth-5 traversal and shortest-path queries return complete, correct results on the graph backend for cases where the default backend is capped or returns incomplete results.
- **SC-003**: On a representative dataset of at least 10,000 nodes and 50,000 edges, depth-3-or-deeper traversal and shortest-path queries complete at least 5 times faster on the graph backend than on the default backend, with the measured ratio recorded by the benchmark.
- **SC-004**: Switching the backend on or off requires only a configuration change and no application code change; a deployment that does not opt in shows zero behavioral difference from today.
- **SC-005**: A new operator can enable the graph backend and run a deep relationship query by following the documentation in under 15 minutes.

## Assumptions

- The graph backend stores the knowledge graph (nodes and edges) only. Note text remains in the existing relational store and vector embeddings remain in the existing vector store. Moving notes or vector search into the graph database is out of scope.
- The default backend remains SQLite. Opt-in users accept an added dependency on a graph database service; non-opt-in users gain zero new mandatory dependencies.
- The chosen graph database is Neo4j, selected as the reference architecture validated by Flowsint (Apache-2.0) and for its native traversal and shortest-path support. The graph database runs as an external service; embedding it in-process is out of scope.
- The representative benchmark dataset may be synthesized or loaded from an existing fixture or export; it need not be production data, only representative in size and connectivity.
- The existing enterprise graph option (TypeDB) is a separate, unaffected path. This feature does not modify, replace, or depend on it.
- Fallback behavior on graph-database outage defaults to fail-loud; an explicit configured fallback to the default backend is allowed but never silent.
- This feature does not add a user interface and does not change how relationships are extracted from notes; it changes only where the graph is stored and how it is queried.
