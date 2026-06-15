# Phase 1 Data Model: Neo4j graph backend

The Neo4j backend preserves the existing knowledge-graph model. No new conceptual entities are introduced; this maps the current node/edge shape onto Neo4j.

## Node (label `:Entity`)

| Field | Type | Notes |
|-------|------|-------|
| `entity_type` | string | Part of identity. Examples: ThreatActor, Malware, Vulnerability, IPv4Address, Note. |
| `entity_value` | string | Part of identity. The entity's canonical value. |
| `node_id` | string | Stable id (`node_<hex>`), preserved for `get_node_by_id`. |
| `properties` | map | Arbitrary key/values; complex values JSON-encoded. |
| `created_at` / `updated_at` | ISO-8601 string | Timestamps. |

**Identity / uniqueness**: `(entity_type, entity_value)`. Enforced by `MERGE` and a node key/uniqueness constraint:
`CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (n:Entity) REQUIRE (n.entity_type, n.entity_value) IS NODE KEY` (Community edition: a uniqueness constraint on a composite is enforced via MERGE plus an index `FOR (n:Entity) ON (n.entity_type, n.entity_value)`).

## Edge (relationship type `:REL`)

| Field | Type | Notes |
|-------|------|-------|
| `relationship` | string | The semantic label (uses, exploits, targets, attributed_to, TEMPORAL_BEFORE, SUPERSEDES, ...). Part of edge identity. |
| `edge_type` | string | `causal` \| `heuristic` \| `temporal`. Defaults to `heuristic`; promoted to a more specific type on update. |
| `confidence` | float | 0.0-1.0 when provided. |
| `note_id` | string \| null | Provenance: the note that asserted the edge. |
| `properties` | map | Remaining arbitrary properties, JSON-encoded as needed. |
| `edge_id` | string | Stable id (`edge_<hex>`). |
| `created_at` / `updated_at` | ISO-8601 string | Timestamps. |

**Direction**: from-node to to-node, directional, matching `add_edge(from_*, to_*)`.

**Uniqueness / dedup**: `(from_node, to_node, relationship)` via `MERGE (a)-[r:REL {relationship:$rel}]->(b)`. Re-asserting updates `properties`/timestamps and promotes `edge_type`, never creates a duplicate (FR-006). The existing model also keys on originating note for multi-note assertions; the implementer confirms whether note id participates in dedup identity and matches current `add_kg_edge` semantics.

## Indexes / constraints created at init

- Node key/uniqueness on `(:Entity entity_type, entity_value)`.
- Index on `:REL(relationship)` for filtered traversal.
- Index on `:REL(edge_type)` for causal/temporal filters.

## Validation rules (from requirements)

- Entity type and value are required and non-empty (mirrors current `add_node`).
- `edge_type` defaults to `heuristic` when not supplied (FR-005).
- Temporal relationships (`TEMPORAL_*`, `SUPERSEDES`) remain queryable for timeline operations (FR-003).
- Traversal depth is bounded by a configured maximum (default raised to at least 5) and results by a configured limit; limit hits are reported, never silently truncated (edge case).

## Out of scope (unchanged stores)

- Note text: remains in the relational store (SQLite default).
- Vector embeddings and similarity: remain in LanceDB.
- Enterprise TypeDB schema: separate and unaffected.
