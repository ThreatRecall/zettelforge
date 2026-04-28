# Hybrid TypeDB + LanceDB Architecture Plan

**Date:** 2026-04-09
**Author:** Patrick Roland + Claude Opus 4.6
**Status:** ALL PHASES COMPLETE (2026-04-09). v2.0.0 released.
**Estimated effort:** 5-6 weeks across 5 phases

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan phase-by-phase. Each phase produces working, testable software.

---

## Vision

Replace ZettelForge's JSONL-based KnowledgeGraph with a **hybrid two-database architecture**:

- **TypeDB** (Apache-2.0) — Authoritative ontology layer. STIX 2.1 schema, typed entities, inference-driven relationship discovery, temporal reasoning, confidence propagation. Owns the *truth* about threat actors, CVEs, tools, campaigns, and their relationships.

- **LanceDB** — Conversational layer. Vector embeddings for semantic search, Zettelkasten note storage, unstructured data (news reports, conversation logs, raw intel). Owns the *context* that agents use for synthesis.

The two layers are bridged: notes in LanceDB reference entities in TypeDB via STIX IDs. Entity extraction feeds TypeDB. `recall()` queries both and blends results.

### Zettelkasten DNA Preserved

The Zettelkasten philosophy — atomic notes, meaningful links, emergent structure — maps naturally to this architecture:

| Zettelkasten Principle | Current (JSONL) | Hybrid (TypeDB + LanceDB) |
|----------------------|-----------------|---------------------------|
| **Atomic notes** | MemoryNote in JSONL | MemoryNote in LanceDB (unchanged) |
| **Meaningful links** | `links.related` list + KG edges | TypeDB typed relations (STIX SROs) with confidence + temporal validity |
| **Emergent structure** | Manual entity co-occurrence | TypeDB inference rules discover indirect relationships automatically |
| **Unique IDs** | `note_YYYYMMDD_HHMMSS_xxxx` | STIX deterministic IDs (`threat-actor--uuid`) + note IDs |
| **Index/register** | EntityIndexer JSON | TypeDB entity index (schema-enforced) |
| **Evolution** | `superseded_by` links | TypeDB temporal edges with `valid_from`/`valid_to` + inference |

---

## Architecture: Before and After

### Current State (v1.5.0)

```
Agent → MemoryManager → Governance
            │
            ├─→ NoteConstructor → EntityExtractor
            │        │
            │        ▼
            ├─→ KnowledgeGraph (JSONL)  ←── kg_nodes.jsonl, kg_edges.jsonl
            │        │                       In-memory caches: _nodes, _edges_from, _node_index
            │        ▼
            ├─→ GraphRetriever (BFS over in-memory dicts)
            │        │
            ├─→ VectorRetriever (LanceDB)
            │        │
            ├─→ BlendedRetriever (merge vector + graph)
            │        │
            └─→ SynthesisGenerator (RAG)
```

### Target State (v2.0.0)

```
Agent → MemoryManager → Governance
            │
            ├─→ NoteConstructor → EntityExtractor
            │        │
            │        ▼
            │   ┌─────────────────────────────────┐
            │   │     TypeDB (Ontology Layer)      │
            │   │  ┌───────────────────────────┐  │
            │   │  │  STIX 2.1 Schema          │  │
            │   │  │  - threat-actor            │  │
            │   │  │  - malware / tool          │  │
            │   │  │  - attack-pattern          │  │
            │   │  │  - vulnerability (CVE)     │  │
            │   │  │  - campaign                │  │
            │   │  │  - indicator / observable   │  │
            │   │  └───────────────────────────┘  │
            │   │  ┌───────────────────────────┐  │
            │   │  │  STIX Relationships (SROs) │  │
            │   │  │  - uses, targets           │  │
            │   │  │  - attributed-to           │  │
            │   │  │  - indicates, mitigates    │  │
            │   │  │  + confidence, valid_from  │  │
            │   │  │  + temporal edges          │  │
            │   │  └───────────────────────────┘  │
            │   │  ┌───────────────────────────┐  │
            │   │  │  Inference Rules           │  │
            │   │  │  - transitive aliases      │  │
            │   │  │  - indirect mitigations    │  │
            │   │  │  - campaign attribution    │  │
            │   │  └───────────────────────────┘  │
            │   └─────────────────────────────────┘
            │        │
            ├─→ GraphRetriever (TypeQL queries, not in-memory BFS)
            │        │
            │   ┌─────────────────────────────────┐
            │   │     LanceDB (Conversational)     │
            │   │  - Zettelkasten notes (raw text) │
            │   │  - Vector embeddings (768-dim)   │
            │   │  - Note metadata + links         │
            │   │  - Unstructured reports/news     │
            │   └─────────────────────────────────┘
            │        │
            ├─→ VectorRetriever (LanceDB — unchanged)
            │        │
            ├─→ BlendedRetriever (merge vector + graph — interface unchanged)
            │        │
            └─→ SynthesisGenerator (RAG — unchanged)
```

### Bridge: How Notes and Entities Connect

```
LanceDB (notes)                         TypeDB (entities)
┌──────────────────┐                    ┌──────────────────┐
│ note_20260409... │                    │ threat-actor     │
│ raw: "APT28 uses │───MENTIONED_IN───→│ name: "APT28"    │
│  Cobalt Strike"  │                    │ stix_id: "threat │
│ vector: [0.1..]  │                    │  -actor--abc..."  │
└──────────────────┘                    └────────┬─────────┘
                                                 │ uses
                                        ┌────────▼─────────┐
                                        │ malware          │
                                        │ name: "Cobalt    │
                                        │  Strike"         │
                                        └──────────────────┘
```

The `MENTIONED_IN` edge lives in TypeDB, pointing from entity to note_id. The note itself (with its raw text and vector) lives in LanceDB. This clean separation means:
- TypeDB answers "what entities exist and how are they related?"
- LanceDB answers "what context exists about this topic?"
- `BlendedRetriever` merges both answers using intent-based policy weights

---

## Migration Impact Summary

### Tier 1: Must Rewrite (5 files)

| File | Current | Target | Breaking? |
|------|---------|--------|-----------|
| `knowledge_graph.py` | JSONL + in-memory dicts | TypeDB client wrapper, same public API | **Internal only** |
| `graph_retriever.py` | BFS over `._nodes`, `._edges_from`, `._node_index` | TypeQL queries | **Internal only** |
| `memory_manager.py` | Calls `kg.add_node()`, `kg.add_edge()`, etc. | Same calls, TypeDB-backed | **Internal only** |
| `ontology.py` | `TypedEntityStore` on JSONL | TypeDB schema + queries | **Internal only** |
| `entity_indexer.py` | `entity_index.json` | TypeDB entity lookups | **Internal only** |

### Tier 2: Verify (3 files)

| File | Why | Expected impact |
|------|-----|-----------------|
| `blended_retriever.py` | Consumes `ScoredResult` from graph_retriever | None if interface preserved |
| `note_constructor.py` | Calls `kg.add_edge()` for causal triples | None if KG API preserved |
| `alias_resolver.py` | Can optionally migrate to TypeDB inference | None (keep as-is initially) |

### Tier 3: No Change (7 files)

`vector_retriever.py`, `vector_memory.py`, `memory_store.py`, `intent_classifier.py`, `fact_extractor.py`, `memory_updater.py`, `cti_integration.py`, `synthesis_generator.py`, `governance_validator.py`

---

## Phase 1: TypeDB Schema + Docker Setup (Week 1)

### Goal
Stand up TypeDB in Docker, define the STIX 2.1 schema, verify it loads, write a Python client wrapper with the same public API as the current `KnowledgeGraph`.

### Prerequisites
```bash
# Docker must be available
docker --version

# TypeDB container
docker run -d --name typedb \
  -p 1729:1729 -p 8000:8000 \
  typedb/typedb:latest

# Python driver
pip install typedb-driver
```

### Tasks

#### Task 1.1: Docker Compose for TypeDB

**Create:** `docker/docker-compose.yml`

```yaml
services:
  typedb:
    image: typedb/typedb:latest
    ports:
      - "1729:1729"
      - "8000:8000"
    volumes:
      - typedb-data:/opt/typedb/server/data
    restart: unless-stopped

volumes:
  typedb-data:
```

**Create:** `scripts/typedb-setup.sh`
```bash
#!/bin/bash
# Start TypeDB and load STIX schema
docker compose -f docker/docker-compose.yml up -d
sleep 5
echo "TypeDB running on localhost:1729"
```

#### Task 1.2: Define STIX 2.1 Schema

**Create:** `src/zettelforge/schema/stix_core.tql`

Core STIX 2.1 entity types relevant to ZettelForge's CTI domain. Based on the `typedb-cti` project but trimmed to what ZettelForge actually uses.

```typeql
define

# ── Base Types ──────────────────────────────────────────────
attribute stix-id, value string;
attribute name, value string;
attribute description, value string;
attribute created, value datetime;
attribute modified, value datetime;
attribute confidence, value double, @range(0.0..1.0);
attribute revoked, value boolean;

# Temporal
attribute valid-from, value datetime;
attribute valid-until, value datetime;
attribute first-observed, value datetime;
attribute last-observed, value datetime;

# Epistemic tier
attribute tier, value string;  # A=authoritative, B=operational, C=support

# Importance (from two-phase pipeline)
attribute importance, value long, @range(1..10);

# ── STIX Domain Objects ────────────────────────────────────
entity stix-domain-object,
  abstract,
  owns stix-id @key,
  owns name,
  owns description,
  owns created,
  owns modified,
  owns confidence,
  owns revoked,
  owns tier;

entity threat-actor sub stix-domain-object,
  owns aliases,
  owns goals,
  owns sophistication,
  owns resource-level;

attribute aliases, value string;
attribute goals, value string;
attribute sophistication, value string;
attribute resource-level, value string;

entity malware sub stix-domain-object,
  owns malware-types,
  owns is-family;

attribute malware-types, value string;
attribute is-family, value boolean;

entity tool sub stix-domain-object,
  owns tool-types;

attribute tool-types, value string;

entity attack-pattern sub stix-domain-object,
  owns external-id;  # MITRE ATT&CK T-code

attribute external-id, value string;

entity vulnerability sub stix-domain-object,
  owns external-id;  # CVE ID

entity campaign sub stix-domain-object,
  owns objective,
  owns first-seen,
  owns last-seen;

attribute objective, value string;
attribute first-seen, value datetime;
attribute last-seen, value datetime;

entity indicator sub stix-domain-object,
  owns pattern,
  owns pattern-type,
  owns valid-from,
  owns valid-until;

attribute pattern, value string;
attribute pattern-type, value string;

entity infrastructure sub stix-domain-object,
  owns infrastructure-types;

attribute infrastructure-types, value string;

# ── Note (Zettelkasten bridge) ─────────────────────────────
# Links TypeDB entities to LanceDB notes
entity zettel-note,
  owns note-id @key,
  owns created,
  owns importance,
  owns tier;

attribute note-id, value string;

# ── STIX Relationships (SROs) ──────────────────────────────
relation stix-relationship,
  abstract,
  owns stix-id,
  owns confidence,
  owns created,
  owns modified,
  owns valid-from,
  owns valid-until,
  owns description;

relation uses sub stix-relationship,
  relates user,
  relates used;

relation targets sub stix-relationship,
  relates source,
  relates target;

relation attributed-to sub stix-relationship,
  relates attributing,
  relates attributed;

relation indicates sub stix-relationship,
  relates indicating,
  relates indicated;

relation mitigates sub stix-relationship,
  relates mitigating,
  relates mitigated;

relation derived-from sub stix-relationship,
  relates deriving,
  relates derived;

relation mentioned-in sub stix-relationship,
  relates entity,
  relates note;

relation supersedes sub stix-relationship,
  relates newer,
  relates older;

relation alias-of,
  relates canonical,
  relates alias,
  owns confidence;

# ── Role assignments ───────────────────────────────────────
threat-actor plays uses:user;
threat-actor plays targets:source;
threat-actor plays attributed-to:attributing;
threat-actor plays alias-of:canonical;
threat-actor plays alias-of:alias;

malware plays uses:used;
malware plays indicates:indicated;
malware plays mitigates:mitigated;

tool plays uses:used;
tool plays mitigates:mitigated;

attack-pattern plays uses:used;
attack-pattern plays mitigates:mitigated;
attack-pattern plays indicates:indicated;

vulnerability plays targets:target;
vulnerability plays mitigates:mitigated;

campaign plays attributed-to:attributed;
campaign plays targets:source;

indicator plays indicates:indicating;
indicator plays derived-from:deriving;
indicator plays derived-from:derived;

infrastructure plays targets:target;
infrastructure plays uses:used;

zettel-note plays mentioned-in:note;
zettel-note plays supersedes:newer;
zettel-note plays supersedes:older;

stix-domain-object plays mentioned-in:entity;
```

**Create:** `src/zettelforge/schema/stix_rules.tql`

Inference rules that discover indirect relationships automatically.

```typeql
define

# Transitive alias resolution
# If A alias-of B and B alias-of C, then A alias-of C
rule transitive-alias:
  when {
    (canonical: $b, alias: $a) isa alias-of;
    (canonical: $c, alias: $b) isa alias-of;
  } then {
    (canonical: $c, alias: $a) isa alias-of;
  };

# Indirect mitigation
# If course-of-action mitigates attack-pattern,
# and threat-actor uses attack-pattern,
# then course-of-action indirectly mitigates threat-actor's capability
rule indirect-mitigation:
  when {
    (mitigating: $coa, mitigated: $ap) isa mitigates;
    (user: $ta, used: $ap) isa uses;
  } then {
    (mitigating: $coa, mitigated: $ta) isa mitigates;
  };

# Campaign attribution propagation
# If campaign attributed-to threat-actor,
# and campaign uses malware,
# then threat-actor uses malware (via campaign)
rule campaign-tool-attribution:
  when {
    (attributed: $c, attributing: $ta) isa attributed-to;
    (user: $c, used: $m) isa uses;
    $c isa campaign;
  } then {
    (user: $ta, used: $m) isa uses;
  };
```

#### Task 1.3: TypeDB Client Wrapper

**Create:** `src/zettelforge/typedb_client.py`

Wraps TypeDB driver with the same public API as the current `KnowledgeGraph` class. This is the key abstraction — all existing code calls `kg.add_node()`, `kg.add_edge()`, etc. and those methods now route to TypeDB instead of JSONL.

```python
"""
TypeDB Client — Drop-in replacement for KnowledgeGraph.

Provides the same public API as knowledge_graph.py but backed by TypeDB
with STIX 2.1 schema. Falls back to in-memory mode if TypeDB is unavailable.
"""
```

**Public API (must match knowledge_graph.py exactly):**
```python
class TypeDBKnowledgeGraph:
    def __init__(self, host="localhost", port=1729, database="zettelforge"):
    def add_node(self, entity_type, entity_value, properties=None) -> str:
    def add_edge(self, from_type, from_value, to_type, to_value, relationship, properties=None) -> str:
    def add_temporal_edge(self, from_type, from_value, to_type, to_value, relationship, timestamp, properties=None) -> str:
    def get_node(self, entity_type, entity_value) -> Optional[Dict]:
    def get_neighbors(self, entity_type, entity_value, relationship=None) -> List[Dict]:
    def traverse(self, start_type, start_value, max_depth=2) -> List[Dict]:
    def get_entity_timeline(self, entity_type, entity_value) -> List[Dict]:
    def get_changes_since(self, timestamp) -> List[Dict]:
    def get_latest_state(self, entity_type, entity_value) -> Optional[Dict]:
```

**Internal methods:**
```python
    def _connect(self):
    def _ensure_schema(self):
    def _typeql_insert_entity(self, entity_type, entity_value, properties):
    def _typeql_insert_relation(self, from_type, from_value, to_type, to_value, rel_type, properties):
    def _typeql_query(self, typeql_string) -> List[Dict]:
    def _stix_id(self, entity_type, entity_value) -> str:  # Deterministic STIX ID generation
```

#### Task 1.4: Tests

**Create:** `tests/test_typedb_client.py`

Tests that verify the TypeDB client has the same behavior as the JSONL KnowledgeGraph. Run against a test database (separate from production).

```python
# Tests should cover:
# - add_node() creates entity, returns ID
# - add_node() with same type+value is idempotent (returns existing)
# - add_edge() creates relationship
# - add_edge() with auto-create nodes
# - get_node() returns entity dict
# - get_neighbors() returns outgoing edges
# - traverse() returns multi-hop paths
# - add_temporal_edge() stores temporal metadata
# - get_entity_timeline() returns chronological events
# - get_changes_since() filters by timestamp
# - STIX ID generation is deterministic
```

#### Task 1.5: Commit

```bash
git add docker/ src/zettelforge/schema/ src/zettelforge/typedb_client.py tests/test_typedb_client.py
git commit -m "feat: TypeDB schema + client wrapper (Phase 1 of hybrid architecture)"
```

---

## Phase 2: Swap KnowledgeGraph Backend (Week 2-3)

### Goal
Replace `get_knowledge_graph()` to return the TypeDB-backed implementation. Update `graph_retriever.py` to use TypeQL queries instead of in-memory dict traversal.

### Tasks

#### Task 2.1: Update get_knowledge_graph() factory

Modify `src/zettelforge/knowledge_graph.py` to try TypeDB first, fall back to JSONL:

```python
def get_knowledge_graph() -> KnowledgeGraph:
    """Get global knowledge graph instance. Tries TypeDB first, falls back to JSONL."""
    global _kg_instance
    if _kg_instance is None:
        try:
            from zettelforge.typedb_client import TypeDBKnowledgeGraph
            _kg_instance = TypeDBKnowledgeGraph()
            _kg_instance._connect()
        except Exception:
            _kg_instance = KnowledgeGraph()  # JSONL fallback
    return _kg_instance
```

#### Task 2.2: Rewrite GraphRetriever for TypeDB

Replace `graph_retriever.py`'s direct access to `._nodes`, `._edges_from`, `._node_index` with method calls that work with both backends:

- `kg.get_node(type, value)` instead of `kg._node_index.get(type, {}).get(value)`
- `kg.get_neighbors(type, value)` instead of `kg._edges_from.get(node_id, [])`
- Keep BFS algorithm but use public API methods

Alternatively, for TypeDB-native traversal:
```typeql
match
  $start isa threat-actor, has name "apt28";
  $start (user) -> uses -> (used: $hop1);
  $hop1 (entity) -> mentioned-in -> (note: $note);
  $note has note-id $nid;
fetch $nid;
```

#### Task 2.3: Update memory_manager.py

The `_update_knowledge_graph()` method already calls `kg.add_node()` and `kg.add_edge()` — if the TypeDB client preserves these signatures, no changes needed. Verify and test.

#### Task 2.4: Integration tests

Run all existing tests against TypeDB backend:
```bash
pytest tests/test_graph_retriever.py tests/test_blended_retriever.py tests/test_recall_integration.py -v
```

#### Task 2.5: Commit

```bash
git commit -m "feat: swap KnowledgeGraph to TypeDB backend (Phase 2)"
```

---

## Phase 3: STIX Entity Migration + Alias Inference (Week 3-4)

### Goal
Migrate entity storage to use proper STIX IDs. Enable TypeDB inference rules for transitive alias resolution and indirect relationship discovery.

### Tasks

#### Task 3.1: STIX ID generation

Add deterministic STIX ID generation to TypeDB client:
```python
def _stix_id(self, entity_type: str, entity_value: str) -> str:
    """Generate deterministic STIX 2.1 ID."""
    import uuid
    namespace = uuid.UUID("00abedb4-aa42-466c-9c01-fed23315a9b7")  # ZettelForge namespace
    return f"{entity_type}--{uuid.uuid5(namespace, entity_value)}"
```

#### Task 3.2: Migrate alias_resolver to TypeDB inference

Replace `entity_aliases.json` with TypeDB `alias-of` relations:
```typeql
insert
  $apt28 isa threat-actor, has name "apt28", has stix-id "threat-actor--...";
  $fancy isa threat-actor, has name "fancy-bear", has stix-id "threat-actor--...";
  (canonical: $apt28, alias: $fancy) isa alias-of, has confidence 1.0;
```

The `transitive-alias` rule then automatically resolves chains.

#### Task 3.3: Update EntityIndexer

Replace `entity_index.json` lookups with TypeDB queries:
```typeql
match
  $entity isa $type, has name $name;
  (entity: $entity, note: $note) isa mentioned-in;
  $note has note-id $nid;
  $name = "apt28";
fetch $nid;
```

#### Task 3.4: Temporal relationship improvements

Add valid_from/valid_until to all STIX relationships:
```typeql
insert
  (user: $apt28, used: $cobalt) isa uses,
    has confidence 0.85,
    has valid-from 2024-01-15T00:00:00,
    has valid-until 2025-06-30T23:59:59,
    has first-observed 2024-01-15T08:30:00,
    has last-observed 2025-03-20T14:22:00;
```

Temporal queries become:
```typeql
match
  (user: $ta, used: $m) isa uses,
    has valid-from $vf, has valid-until $vu;
  $vf <= 2025-01-01T00:00:00;
  $vu >= 2025-01-01T00:00:00;
  $ta has name $n;
  $m has name $mn;
fetch $n, $mn;
```

#### Task 3.5: Commit

```bash
git commit -m "feat: STIX entity migration + alias inference rules (Phase 3)"
```

---

## Phase 4: LanceDB Conversational Layer Hardening (Week 4-5)

### Goal
Formalize LanceDB as the conversational layer. Improve note-to-entity bridging. Add support for news reports and unstructured data alongside Zettelkasten notes.

### Tasks

#### Task 4.1: Formalize note-to-entity bridge

When `remember()` is called:
1. Note is stored in LanceDB (text + vector + metadata) — **unchanged**
2. Entities are extracted — **unchanged**
3. Entity nodes are created in TypeDB — **now TypeDB instead of JSONL**
4. `mentioned-in` relations created in TypeDB linking entity → note_id — **new**
5. Heuristic entity-entity relations created in TypeDB — **now TypeDB**

The bridge is the `mentioned-in` relation: TypeDB stores `(entity: $threat_actor, note: $note) isa mentioned-in` where `$note` has a `note-id` that maps to the LanceDB note.

#### Task 4.2: Add news report ingestion support

Extend `MemoryManager` with a news-optimized ingestion path:

```python
def remember_report(
    self,
    content: str,
    source_url: str = "",
    published_date: str = "",
    domain: str = "cti",
) -> Tuple[MemoryNote, str]:
    """Ingest a news report / threat report. Stores in LanceDB, extracts entities to TypeDB."""
```

This uses the two-phase pipeline (`remember_with_extraction`) under the hood but adds:
- Published date as temporal metadata
- Source URL tracking
- Longer content support (chunking for reports > 4000 chars)

#### Task 4.3: Query cache improvements

Add a simple LRU cache for frequent TypeDB queries (entity lookups, neighbor traversals) to avoid round-tripping for hot entities:

```python
from functools import lru_cache

@lru_cache(maxsize=1024)
def _cached_get_neighbors(self, entity_type, entity_value):
    return self._typeql_query_neighbors(entity_type, entity_value)
```

Cache invalidation on write (add_node/add_edge clears relevant cache entries).

#### Task 4.4: Commit

```bash
git commit -m "feat: LanceDB conversational layer + note-entity bridge (Phase 4)"
```

---

## Phase 5: Integration, Benchmarks, Version Bump (Week 5-6)

### Goal
Full integration testing, re-run all benchmarks against TypeDB backend, document results, bump to v2.0.0.

### Tasks

#### Task 5.1: Full test suite against TypeDB

```bash
# All existing tests must pass
pytest tests/ -v

# New TypeDB-specific tests
pytest tests/test_typedb_client.py -v

# Integration: remember → TypeDB entities → recall with graph
pytest tests/test_recall_integration.py -v
```

#### Task 5.2: Re-run benchmarks

```bash
python benchmarks/locomo_benchmark.py --samples 20
python benchmarks/ctibench_benchmark.py --task ate --samples 50
python benchmarks/ragas_benchmark.py --samples 20
```

Compare to v1.5.0 baselines. Expected improvements:
- **Temporal queries**: TypeDB inference should improve temporal reasoning
- **Multi-hop**: TypeDB path queries replace BFS over in-memory dicts — should find deeper connections
- **Latency**: TypeDB server-based queries vs in-memory may be slightly slower for simple lookups but faster for complex traversals

#### Task 5.3: Update BENCHMARK_REPORT.md

Add v2.0.0 results column to all comparison tables.

#### Task 5.4: Update README.md

Add TypeDB to architecture diagram, installation instructions, configuration.

#### Task 5.5: Version bump to 2.0.0

```python
# src/zettelforge/__init__.py
__version__ = "2.0.0"

# pyproject.toml
version = "2.0.0"

# New dependency
dependencies = [
    ...,
    "typedb-driver>=3.8.0",
]
```

#### Task 5.6: Commit and tag

```bash
git commit -m "feat: hybrid TypeDB+LanceDB architecture v2.0.0 (Phase 5)"
git tag v2.0.0
```

---

## Configuration (Target State)

```bash
# Environment variables
AMEM_DATA_DIR=~/.amem                           # LanceDB data + fallback JSONL
AMEM_EMBEDDING_URL=http://127.0.0.1:8081        # Embedding server
TYPEDB_HOST=localhost                             # TypeDB server
TYPEDB_PORT=1729                                  # TypeDB gRPC port
TYPEDB_DATABASE=zettelforge                       # TypeDB database name
ZETTELFORGE_BACKEND=typedb                        # "typedb" or "jsonl" (fallback)
```

## Dependencies (New)

```toml
[project]
dependencies = [
    # Existing
    "lancedb>=0.5.0",
    "pyarrow>=14.0.0",
    "pydantic>=2.0.0",
    "numpy>=1.24.0",
    "requests>=2.31.0",
    # New
    "typedb-driver>=3.8.0",
]
```

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| TypeDB unavailable (container down) | `get_knowledge_graph()` falls back to JSONL backend transparently |
| TypeDB driver incompatibility | Pin `typedb-driver>=3.8.0,<4.0` in pyproject.toml |
| Schema evolution breaks data | TypeDB supports schema migration; version the schema files |
| Performance regression | LRU cache on hot queries; benchmark comparison gates each phase |
| ARM64 compatibility (homelab) | TypeDB 3.x has ARM64 Docker images |

## Files Created or Modified (Complete List)

### New Files
```
docker/docker-compose.yml                        # TypeDB container
scripts/typedb-setup.sh                          # Setup helper
src/zettelforge/schema/stix_core.tql             # STIX 2.1 schema
src/zettelforge/schema/stix_rules.tql            # Inference rules
src/zettelforge/typedb_client.py                 # TypeDB wrapper (same API as KnowledgeGraph)
tests/test_typedb_client.py                      # TypeDB client tests
```

### Modified Files
```
src/zettelforge/knowledge_graph.py               # get_knowledge_graph() factory updated
src/zettelforge/graph_retriever.py               # Use public API instead of private dicts
src/zettelforge/memory_manager.py                # Verify calls work with new backend
src/zettelforge/ontology.py                      # TypedEntityStore queries TypeDB
src/zettelforge/entity_indexer.py                # get_note_ids() queries TypeDB
src/zettelforge/alias_resolver.py                # Optional: migrate to TypeDB inference
src/zettelforge/__init__.py                      # Export new classes, version bump
pyproject.toml                                   # Add typedb-driver dependency
```

### Unchanged Files
```
src/zettelforge/vector_retriever.py              # LanceDB — no change
src/zettelforge/vector_memory.py                 # LanceDB — no change
src/zettelforge/memory_store.py                  # JSONL notes — no change
src/zettelforge/blended_retriever.py             # Interface unchanged
src/zettelforge/intent_classifier.py             # Pure logic — no change
src/zettelforge/fact_extractor.py                # Ollama — no change
src/zettelforge/memory_updater.py                # Uses MemoryManager API — no change
src/zettelforge/synthesis_generator.py           # RAG — no change
src/zettelforge/cti_integration.py               # Django ORM — no change
src/zettelforge/governance_validator.py          # Validation logic — no change
src/zettelforge/note_constructor.py              # Entity extraction — no change
src/zettelforge/note_schema.py                   # Pydantic model — no change
```
