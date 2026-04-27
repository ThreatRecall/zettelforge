---
title: "Knowledge Graph Edge Schema Reference"
description: "Knowledge graph edge types, node types, relationship semantics, temporal indexing, causal edges, and traversal API for the ZettelForge knowledge graph."
diataxis_type: "reference"
audience: "CTI analysts querying the knowledge graph, developers building graph-aware integrations"
tags:
  - knowledge-graph
  - edge-schema
  - relationships
  - ontology
  - temporal
  - causal
last_updated: "2026-04-27"
version: "2.7.0"
---

# Knowledge Graph Edge Schema Reference

Module: `zettelforge.knowledge_graph`

```python
from zettelforge.knowledge_graph import KnowledgeGraph, get_knowledge_graph
```

---

## Overview

ZettelForge's knowledge graph is a Neo4j-inspired in-memory graph with JSONL
persistence. It stores entity nodes and typed relationship edges with
temporal indexing for time-based queries.

**Storage**: JSONL files (`kg_nodes.jsonl`, `kg_edges.jsonl`) in the data directory  
**Backends**: JSONL (community), TypeDB (enterprise, fallback to JSONL)  
**Thread safety**: All write operations use `threading.RLock`

---

## Node Types

Nodes are created automatically when edges reference them. Each node has a
unique `node_id`, entity type, entity value, and optional properties.

### Core Entity Types

| Entity Type | Description | Created By |
|:------------|:------------|:-----------|
| `Note` | A memory note stored via `remember()` | MemoryManager |
| `CVE` | Vulnerability identifier | Entity extraction |
| `Actor` | Threat actor (e.g., `apt28`) | Entity extraction |
| `Tool` | Malware/tool (e.g., `cobalt strike`) | Entity extraction |
| `Campaign` | Campaign identifier | Entity extraction |
| `Asset` | Target asset or sector | Entity extraction |
| `AttackPattern` | MITRE ATT&CK technique (e.g., `T1059`) | Sigma/YARA tag resolution |
| `Vulnerability` | CVE reference (e.g., `CVE-2024-3094`) | Sigma/YARA tag resolution |
| `SigmaRule` | Sigma detection rule | Sigma ingest |
| `YaraRule` | YARA detection rule | YARA ingest |
| `SigmaTag` | Raw Sigma tag | Sigma ingest |
| `YaraTag` | Raw YARA tag | YARA ingest |
| `LogSource` | Sigma logsource facet | Sigma ingest |
| `IntrusionSet` | MITRE ATT&CK group (e.g., `G0007`) | Sigma tag resolution |
| `Malware` | MITRE ATT&CK software (e.g., `S0027`) | Sigma tag resolution |
| `ThreatActor` | Named threat actor | YARA metadata |

### Node Dataclass Shape

```python
{
    "node_id": "node_<uuid12>",
    "entity_type": str,       # e.g., "Actor", "CVE", "Note"
    "entity_value": str,      # e.g., "apt28", "CVE-2024-3094"
    "properties": dict,       # Application-specific metadata
    "created_at": str,        # ISO 8601
    "updated_at": str,        # ISO 8601
}
```

---

## Edge Schema

Each edge is a directed relationship between two nodes with a semantic type.

### Edge Dataclass Shape

```python
{
    "edge_id": "edge_<uuid12>",
    "from_node_id": str,          # Source node ID
    "to_node_id": str,            # Target node ID
    "relationship": str,          # Semantic relationship type
    "edge_type": str,             # "heuristic" | "causal" | "detection"
    "properties": dict,           # Edge-specific metadata
    "created_at": str,            # ISO 8601
    "updated_at": str,            # ISO 8601
}
```

### Edge Type Taxonomy

The `edge_type` field classifies how the edge was created:

| Edge Type | Description | Source |
|:----------|:------------|:-------|
| `heuristic` | Default — simple co-occurrence or heuristic extraction | Entity co-occurrence, basic extraction |
| `causal` | LLM-generated causal triple (MAGMA-style) | Causal triple extraction in enrichment pipeline |
| `detection` | Detection rule relationship | Sigma/YARA ingest |

---

## Relationship Types

### CTI Entity Relationships (auto-extracted)

Created during `remember()` with `domain="cti"`:

| Relationship | From | To | Description |
|:-------------|:-----|:---|:------------|
| `USES_TOOL` | Actor | Tool | Threat actor uses a specific tool |
| `EXPLOITS_CVE` | Actor, Tool | CVE | Entity exploits a vulnerability |
| `TARGETS_ASSET` | Actor, Tool | Asset | Entity targets a specific asset or sector |
| `CONDUCTS_CAMPAIGN` | Actor | Campaign | Actor runs a campaign |
| `MENTIONED_IN` | Actor, Tool, CVE, Campaign, Asset | Note | Entity was mentioned in a note |

### Detection Rule Relationships

Created during Sigma/YARA ingest:

| Relationship | From | To | Description |
|:-------------|:-----|:---|:------------|
| `applies_to` | SigmaRule | LogSource | Rule applies to a log source facet |
| `tagged_with` | SigmaRule, YaraRule | SigmaTag, YaraTag | Rule has a tag |
| `detects` | SigmaRule, YaraRule | AttackPattern | Rule detects a MITRE ATT&CK technique |
| `references_cve` | SigmaRule, YaraRule | Vulnerability | Rule references a CVE |
| `attributed_to` | SigmaRule, YaraRule | IntrusionSet, Malware, ThreatActor | Rule attributed to a group or actor |
| `superseded_by` | SigmaRule | SigmaRule | Rule superseded by another |
| `related_to` | SigmaRule | SigmaRule | Generic rule relationship |

### Temporal Relationships

For tracking entity state over time:

| Relationship | From | To | Description |
|:-------------|:-----|:---|:------------|
| `TEMPORAL_BEFORE` | Entity | Entity | State or event happened before another |
| `TEMPORAL_AFTER` | Entity | Entity | State or event happened after another |
| `SUPERSEDES` | Entity | Entity | New state supersedes an old one |

---

## Temporal Indexing

The knowledge graph maintains a temporal index for time-ordered queries.

### Index Structure

```python
_temporal_index: dict[str, list[dict]]   # timestamp -> temporal edges
_entity_timeline: dict[str, list[dict]]  # "entity_type:entity_value" -> timeline of states
```

### add_temporal_edge()

```python
def add_temporal_edge(
    self,
    from_type: str,
    from_value: str,
    to_type: str,
    to_value: str,
    relationship: str,    # TEMPORAL_BEFORE, TEMPORAL_AFTER, SUPERSEDES
    timestamp: str,
    properties: dict | None = None,
) -> str
```

Creates a temporal edge with a timestamp property. The edge is automatically
indexed in both `_temporal_index` and `_entity_timeline`.

### get_entity_timeline()

```python
def get_entity_timeline(self, entity_type: str, entity_value: str) -> list[dict]
```

Returns the timeline of state changes for an entity, sorted by timestamp.

### get_changes_since()

```python
def get_changes_since(self, timestamp: str) -> list[dict]
```

Returns all entity changes since a given timestamp string. Results are sorted
chronologically.

### Timestamp Parsing

The `_parse_timestamp()` function supports multiple formats:

- ISO 8601 (with `Z` suffix converted to `+00:00`)
- `%Y-%m-%d`
- `%Y-%m-%d %H:%M:%S`
- `%d %b %Y`
- `%B %d, %Y`

---

## Legacy Schema Normalization

Edges persisted by pre-v2.5.1 writers used legacy key names. The
`_normalize_edge_schema()` function rewrites these on load:

| Legacy Key | Canonical Key |
|:-----------|:--------------|
| `source_id` | `from_node_id` |
| `target_id` | `to_node_id` |
| `relation_type` | `relationship` |

Entries without an `edge_id` or missing the required canonical fields are
silently dropped during load. Malformed JSON lines are also skipped.

---

## Core Graph API

### add_node()

```python
def add_node(self, entity_type: str, entity_value: str, properties: dict | None = None) -> str
```

Creates or updates a node. Returns `node_id`. If the node already exists,
updates its properties and `updated_at`.

### add_edge()

```python
def add_edge(
    self,
    from_type: str,
    from_value: str,
    to_type: str,
    to_value: str,
    relationship: str,
    properties: dict | None = None,
) -> str
```

Creates or updates a directed edge. Auto-creates nodes for both endpoints.
If a duplicate edge exists (same `from`/`to`/`relationship`), properties are
merged and `updated_at` is refreshed. The `edge_type` property can be promoted
from `heuristic` to a more specific type when a newer call provides one.

### get_node()

```python
def get_node(self, entity_type: str, entity_value: str) -> dict | None
```

Looks up a node by its type and value. Returns `None` if not found.

### get_neighbors()

```python
def get_neighbors(
    self, entity_type: str, entity_value: str, relationship: str | None = None
) -> list[dict]
```

Returns all adjacent nodes (outgoing edges) with optional relationship filter.

### get_outgoing_edges()

```python
def get_outgoing_edges(self, node_id: str) -> list[dict]
```

Returns all outgoing edges for a given node ID.

### traverse()

```python
def traverse(self, start_type: str, start_value: str, max_depth: int = 2) -> list[dict]
```

BFS traversal up to `max_depth` from a starting node. Returns a list of path
steps, each containing `from_type`, `from_value`, `relationship`, `to_type`,
and `to_value`.

---

## Causal Edge Queries

Causal edges (those with `edge_type: "causal"`) represent LLM-extracted
cause-and-effect relationships. Two dedicated methods support causal graph
traversal:

### get_causal_edges()

```python
def get_causal_edges(
    self, entity_type: str, entity_value: str,
    max_depth: int = 3, max_visited: int = 50,
) -> list[dict]
```

BFS over **outgoing** causal edges only — traces forward from cause to effects.
Useful for "what does this entity cause?" queries.

### get_incoming_causal()

```python
def get_incoming_causal(
    self, entity_type: str, entity_value: str,
    max_depth: int = 3, max_visited: int = 50,
) -> list[dict]
```

BFS over **incoming** causal edges only — traces back to root causes. Useful
for "why did this happen?" queries.

### get_latest_state()

```python
def get_latest_state(self, entity_type: str, entity_value: str) -> dict | None
```

Returns the most recent temporal edge for an entity. Returns `None` if no
temporal data exists.

---

## Global Singleton

```python
def get_knowledge_graph() -> KnowledgeGraph
```

Returns the global `KnowledgeGraph` singleton. Enterprise edition tries TypeDB
first and falls back to JSONL on failure. Community edition always uses JSONL.

---

## Minimal Example

```python
from zettelforge.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# Add nodes and edge
node_a = kg.add_node("Actor", "apt28")
node_b = kg.add_node("Tool", "cobalt strike")
edge_id = kg.add_edge("Actor", "apt28", "Tool", "cobalt strike", "USES_TOOL")

# Query
neighbors = kg.get_neighbors("Actor", "apt28")
for n in neighbors:
    print(f"{n['relationship']} -> {n['node']['entity_type']}:{n['node']['entity_value']}")

# Traverse
paths = kg.traverse("Actor", "apt28", max_depth=2)
for path in paths:
    print(" -> ".join(
        f"{p['from_type']}:{p['from_value']} [{p['relationship']}] {p['to_type']}:{p['to_value']}"
        for p in path
    ))
```

## Full Example

```python
from zettelforge.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# Add temporal edge
kg.add_temporal_edge(
    from_type="Actor", from_value="apt28",
    to_type="Campaign", to_value="NATO-phishing-2026-Q1",
    relationship="TEMPORAL_BEFORE",
    timestamp="2026-01-15",
)

# Query changes since
changes = kg.get_changes_since("2026-01-01")
for c in changes:
    print(f"[{c['timestamp']}] {c['from']} {c['relationship']} {c['to']}")

# Causal chain: forward
causes = kg.get_causal_edges("Actor", "apt28", max_depth=3)
for edge in causes:
    print(f"Causal: {edge['relationship']}")

# Causal chain: backward (root cause analysis)
root_causes = kg.get_incoming_causal("Campaign", "NATO-phishing-2026-Q1", max_depth=3)
for edge in root_causes:
    print(f"Root cause: {edge['relationship']}")
```

---

## Legacy Compatibility

The `_normalize_edge_schema()` function handles mixed-schema edge files where
pre-v2.5.1 and v2.5.1+ rows coexist. On load:

- Entries with `edge_id` + either canonical or legacy keys are normalized
- Entries missing `edge_id` are dropped
- Entries missing the relationship field (canonical or legacy) are dropped
- Malformed JSON lines are skipped with a warning count logged

This was a production hotfix (v2.5.1) for long-running deployments where
pre-v2.5.x writers left ~80k+ legacy entries in `kg_edges.jsonl`.
