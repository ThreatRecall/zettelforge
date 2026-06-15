# Contract: KnowledgeGraph interface

`Neo4jKnowledgeGraph` MUST implement the public interface of `KnowledgeGraph`
(`src/zettelforge/knowledge_graph.py`) with identical signatures and return shapes,
so it is a drop-in replacement returned by `get_knowledge_graph()`. No caller may
need to change.

## Required methods

| Method | Signature | Returns | Behavior |
|--------|-----------|---------|----------|
| `add_node` | `(entity_type: str, entity_value: str, properties: dict \| None = None)` | `str` node_id | Idempotent on `(entity_type, entity_value)`. |
| `add_edge` | `(from_type, from_value, to_type, to_value, relationship, properties=None)` | `str` edge_id | Auto-creates nodes; dedup on `(from, to, relationship)`; `edge_type` from `properties` (default `heuristic`), promoted on update; indexes temporal edges. |
| `add_temporal_edge` | `(...)` matching current signature | `str` | Temporal relationship write. |
| `get_node` | `(entity_type, entity_value)` | `dict \| None` | |
| `get_node_by_id` | `(node_id)` | `dict \| None` | |
| `get_outgoing_edges` | `(node_id)` | `list[dict]` | |
| `get_neighbors` | `(entity_type, entity_value, relationship=None)` | `list[dict]` | Single-hop; optional relationship filter. |
| `traverse` | `(start_type, start_value, max_depth=2)` | `list[dict]` | Multi-hop. Neo4j removes the practical depth cap (configurable, >=5). |
| `get_causal_edges` | `(...)` matching current signature | `list[dict]` | Filter `edge_type='causal'`. |
| `get_incoming_causal` | `(...)` matching current signature | `list[dict]` | Reverse causal. |
| `get_entity_timeline` | `(entity_type, entity_value)` | `list[dict]` | Temporal ordering. |
| `get_changes_since` | `(timestamp)` | `list[dict]` | |
| `get_latest_state` | `(entity_type, entity_value)` | `dict \| None` | |

## New capability (beyond current interface)

| Method | Signature | Returns | Behavior |
|--------|-----------|---------|----------|
| `shortest_path` | `(from_type, from_value, to_type, to_value, max_depth=None)` | `list[dict] \| None` | Ordered path of nodes/edges, or `None` when no path. New method; additive, does not break callers. |

## Return-shape parity

Node dicts and edge dicts MUST carry the same keys the default backend returns
(`node_id`, `entity_type`, `entity_value`, `properties`; and `edge_id`,
`from_node_id`, `to_node_id`, `relationship`, `edge_type`, `properties`,
`created_at`, `updated_at`). The parity test suite asserts this field-by-field.

## Selection contract

`get_knowledge_graph()` returns `Neo4jKnowledgeGraph` when `ZETTELFORGE_BACKEND == "neo4j"`,
with no enterprise-extension requirement. Any other value preserves current behavior.
