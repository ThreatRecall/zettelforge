---
title: "Module Inventory"
description: "Complete inventory of all ZettelForge modules with purpose, key functions, and relationships."
diataxis_type: "reference"
audience: "Senior CTI Practitioner"
tags: [reference, modules, inventory]
last_updated: "2026-04-20"
version: "2.4.0"
---

# Module Inventory

Complete reference of all 57 core modules in ZettelForge v2.4.0.

## Core API Layer

### `memory_manager.py`
**Purpose:** Primary interface for all memory operations.

**Key Classes:**
- `MemoryManager` — Main entry point
- `_EnrichmentJob` — Background work items

**Key Methods:**
- `remember()` — Store content with entity extraction
- `recall()` — Retrieve via hybrid search
- `recall_actor()` — Entity-based retrieval
- `synthesize()` — RAG answer generation
- `stats()` — System statistics

**Dependencies:** All other modules

### `__init__.py`
**Purpose:** Public API exports.

**Exports:** 24 items in `__all__` including:
- Core: `MemoryManager`, `MemoryNote`
- Retrieval: `VectorRetriever`, `BlendedRetriever`
- Knowledge Graph: `KnowledgeGraph`, `ENTITY_TYPES`
- Synthesis: `SynthesisGenerator`, `SynthesisValidator`

## Storage Layer

### `storage_backend.py`
**Purpose:** Abstract base class for all storage backends.

**Key Class:** `StorageBackend` (ABC)

**Methods:** 25 abstract methods including:
- Note operations: `write_note()`, `get_note_by_id()`, `iterate_notes()`
- KG operations: `add_kg_node()`, `add_kg_edge()`, `traverse_kg()`
- Entity operations: `add_entity_mapping()`, `search_entities()`

### `sqlite_backend.py` (33K lines)
**Purpose:** SQLite implementation with WAL mode.

**Key Features:**
- WAL mode for concurrent reads
- 35-column notes table
- Full-text search indexes
- ACID transactions

**Tables:**
- `notes` — Primary storage
- `kg_nodes` — Knowledge graph entities
- `kg_edges` — Knowledge graph relationships

### `memory_store.py` (14K lines)
**Purpose:** JSONL + LanceDB hybrid storage.

**Key Class:** `MemoryStore`

**Features:**
- JSONL persistence for notes
- LanceDB vector indexing
- Lazy connection handling
- Access count tracking

### `vector_memory.py`
**Purpose:** Cross-session semantic memory.

**Key Functions:**
- `get_embedding()` — Generate embeddings (fastembed/Ollama)
- `get_embedding_batch()` — Batch processing

**Key Class:** `VectorMemory`
- Chunking: 512 tokens, 128 overlap
- Deduplication: SHA256 content hash

## Retrieval Layer

### `vector_retriever.py` (14K lines)
**Purpose:** Vector similarity search.

**Key Class:** `VectorRetriever`

**Features:**
- LanceDB vector search (IVF_FLAT)
- In-memory cosine similarity fallback
- Entity boost (2.5x)
- Similarity threshold: 0.15
- Embedding validation & regeneration

### `graph_retriever.py`
**Purpose:** Knowledge graph traversal.

**Key Classes:**
- `GraphRetriever` — BFS traversal
- `ScoredResult` — Result with score, hops, path

**Algorithm:**
```python
score = 1.0 / (1.0 + hop_distance)
max_depth = 2
```

### `blended_retriever.py`
**Purpose:** Fuse vector and graph results.

**Key Class:** `BlendedRetriever`

**Fusion Methods:**
- `blend()` — Normalized score fusion (default)
- `blend_rrf()` — Reciprocal Rank Fusion

**Formula:**
```python
combined = (vector_norm * w_v) + (graph_norm * w_g)
```

## Knowledge Graph Layer

### `knowledge_graph.py` (18K lines)
**Purpose:** JSONL-based knowledge graph.

**Key Class:** `KnowledgeGraph`

**Features:**
- Node/edge storage in JSONL
- Temporal indexing
- BFS traversal
- In-memory caching

**Files:**
- `kg_nodes.jsonl` — Entity nodes
- `kg_edges.jsonl` — Relationships

### `ontology.py` (20K lines)
**Purpose:** STIX 2.1 ontology definitions.

**Key Constants:**
- `ENTITY_TYPES` — 15+ entity type schemas
- `RELATION_TYPES` — 8 relationship types

**Key Classes:**
- `OntologyValidator` — Schema validation
- `TypedEntityStore` — Type-aware storage

### `entity_indexer.py` (18K lines)
**Purpose:** Entity extraction and indexing.

**Key Class:** `EntityExtractor`

**Features:**
- 12 regex patterns for CTI entities
- LLM NER for conversational entities
- 19 total entity types
- Code context filtering for hash extraction

**Entity Types:**
- CTI: CVE, intrusion_set, actor, tool, campaign, attack_pattern
- IOCs: IPv4, domain, URL, MD5, SHA1, SHA256, email
- Conversational: person, location, organization, event, activity, temporal

### `alias_resolver.py`
**Purpose:** Resolve entity aliases.

**Key Class:** `AliasResolver`

**Examples:**
- APT28 = Fancy Bear = STRONTIUM = Sofacy

## Synthesis Layer

### `synthesis_generator.py`
**Purpose:** RAG answer generation.

**Key Class:** `SynthesisGenerator`

**Formats:**
- `direct_answer` — Quick facts
- `synthesized_brief` — Executive summary
- `timeline_analysis` — Chronological events
- `relationship_map` — Entity connections

**Context:**
- Max 10 notes
- 500 chars per note
- 3000 tokens total

### `synthesis_validator.py`
**Purpose:** Validate synthesis outputs.

**Key Functions:**
- Schema validation
- Confidence threshold checking
- Source attribution verification

## LLM Integration Layer

### `llm_client.py` (10K lines)
**Purpose:** Unified LLM interface.

**Key Functions:**
- `generate()` — Text generation
- `generate_structured()` — JSON output

**Providers:** local, ollama, mock

### `llm_providers/` (directory)
**Files:**
- `base.py` — Provider ABC
- `local_provider.py` — llama-cpp-python
- `ollama_provider.py` — Ollama HTTP
- `mock_provider.py` — Test responses
- `registry.py` — Provider registration

### `intent_classifier.py`
**Purpose:** Classify query intent.

**Key Class:** `IntentClassifier`

**Intents:**
- `FACTUAL` — Entity lookup
- `TEMPORAL` — Time-based
- `RELATIONAL` — Graph traversal
- `CAUSAL` — Cause-effect
- `EXPLORATORY` — General research

**Method:** Keyword matching + LLM fallback

## Processing Layer

### `note_constructor.py`
**Purpose:** Build MemoryNote objects.

**Key Class:** `NoteConstructor`

**Features:**
- ID generation
- Timestamp management
- Content hashing
- Entity extraction delegation

### `note_schema.py`
**Purpose:** Pydantic schemas for notes.

**Key Classes:**
- `MemoryNote` — Complete note schema
- `Content` — Raw content + source
- `Semantic` — LLM enrichment
- `Embedding` — Vector metadata
- `Metadata` — Lifecycle + access
- `Links` — Relationships
- `VulnerabilityMeta` — CVE scoring

### `fact_extractor.py`
**Purpose:** Extract facts for two-phase pipeline.

**Key Classes:**
- `FactExtractor`
- `ExtractedFact`

### `memory_updater.py`
**Purpose:** Update existing notes.

**Key Classes:**
- `MemoryUpdater`
- `UpdateOperation` (ADD, UPDATE, DELETE, NOOP)

### `memory_evolver.py` (9K lines)
**Purpose:** Evolve memory over time.

**Key Class:** `MemoryEvolver`

**Features:**
- Compare new intel to existing
- Decide ADD/UPDATE/DELETE/NOOP
- Handle contradictions
- Supersession tracking

## Detection Rules Layer

### `sigma/` (directory)
**Files:**
- `__init__.py` — Package exports
- `parser.py` — Rule parsing
- `ingest.py` — Rule ingestion
- `entities.py` — Entity extraction
- `tags.py` — Tag handling
- `cli.py` — Command-line interface
- `schemas/` — Sigma JSON schemas

### `yara/` (directory)
**Files:**
- `__init__.py` — Package exports
- `parser.py` — plyara integration
- `ingest.py` — Rule ingestion
- `entities.py` — Entity extraction
- `tags.py` — Tag handling
- `cli.py` — Command-line interface
- `cccs_metadata.py` — CCCS metadata handling

### `detection/` (directory)
**Files:**
- `base.py` — DetectionRule superclass
- `explainer.py` — LLM rule explanation
- `consumers.py` — Rule consumers

## Utility Modules

### `config.py` (15K lines)
**Purpose:** Configuration management.

**Key Classes:**
- `StorageConfig`, `TypeDBConfig`
- `EmbeddingConfig`, `LLMConfig`

**Resolution Order:**
1. Environment variables
2. config.yaml (working dir)
3. config.yaml (project root)
4. config.default.yaml
5. Hardcoded defaults

### `log.py`
**Purpose:** Structured logging.

**Key Function:** `get_logger()`

**Most imported module** (19 imports)

### `ocsf.py` (10K lines)
**Purpose:** OCSF-compliant audit logging.

**Key Functions:**
- `log_api_activity()`
- `log_authorization()`
- `log_file_activity()`

### `cache.py`
**Purpose:** In-memory caching.

**Features:**
- TTL support
- Max entry limits
- TypeDB result caching

### `retry.py`
**Purpose:** Retry logic with backoff.

### `json_parse.py`
**Purpose:** Safe JSON extraction.

**Key Function:** `extract_json()`

### `observability.py`
**Purpose:** Metrics and monitoring.

## MCP Server Layer

### `mcp/` (directory)
**Files:**
- `server.py` — MCP server implementation
- `__init__.py`

**Tools:**
- `zettelforge_remember`
- `zettelforge_recall`
- `zettelforge_synthesize`
- `zettelforge_entity`
- `zettelforge_graph`
- `zettelforge_stats`

## Integration Layer

### `integrations/` (directory)
**Files:**
- `langchain_retriever.py` — LangChain integration
- `__init__.py`

## Web Frontend Layer

### `web/app.py`

**Purpose:** FastAPI server serving the SPA and all REST API endpoints.

**Endpoints (existing):** recall, remember, synthesize, stats, edition, sync
**Endpoints (RFC-015):** health, config (GET+PUT), graph/nodes, graph/edges, entities, history, ingest, telemetry, storage, logs, logs/stream (SSE), telemetry/stream (SSE)

**Authentication:** API key via `X-API-Key` header or `Authorization: Bearer`, with loopback allowlist for local-only deployments.

### `web/ui/` (23 files)

**Purpose:** Vanilla JS single-page application (no React, no npm, no build step).

**Library layer:**
- `js/lib/state.js` — Reactive pub/sub state store
- `js/lib/api.js` — Fetch wrapper with auth headers

**Components (6):**
- `header.js` — Top bar with shield-neuron SVG mark, Neuropol wordmark, stats
- `sidebar.js` — 220px nav with Lucide icons, active accent
- `result-card.js` — Memory note row styled per design system
- `tabs.js`, `toast.js`, `spinner.js` — Reusable UI primitives

**Views (8):**
- `dashboard.js` — System health tiles, telemetry stats, intent bar chart
- `search.js` — Recall/synthesize/remember with format selector
- `knowledge-graph.js` — 2D SVG force-directed graph, color-coded by type
- `logs.js` — Filterable log table with auto-refresh and expandable detail
- `ingest.js` — Manual/bulk ingestion with file upload
- `entities.js` — Paginated entity browser with filters and sort
- `history.js` — Session activity timeline with re-run and export
- `configuration.js` — Feature flag toggles + YAML editor

**Design System:** `colors_and_type.css` (286 lines of CSS custom properties), `fonts/Neuropol.otf`, SVG logo marks from the ZettelForge Design System archive.

## Other Modules

### `consolidation.py` (18K lines)
**Purpose:** Memory consolidation.

**Key Class:** `ConsolidationMiddleware`

### `governance_validator.py`
**Purpose:** Data governance validation.

**Key Class:** `GovernanceValidator`

**Checks:**
- Content length
- TLP markings
- Retention policies

### `edition.py`
**Purpose:** Edition detection (community vs enterprise).

**Key Functions:**
- `is_community()`
- `is_enterprise()`
- `edition_name()`

### `demo.py`
**Purpose:** Interactive demonstration.

### `extensions.py`
**Purpose:** Extension loading.

### `backend_factory.py`
**Purpose:** Storage backend factory.

**Key Function:** `get_storage_backend()`

## Module Dependency Graph

```
memory_manager
├── storage_backend
│   └── sqlite_backend
├── vector_retriever
│   ├── vector_memory
│   └── entity_indexer
├── graph_retriever
│   └── knowledge_graph
├── blended_retriever
│   ├── vector_retriever
│   └── graph_retriever
├── synthesis_generator
│   ├── vector_retriever
│   └── llm_client
├── entity_indexer
│   └── note_schema
├── note_constructor
│   └── entity_indexer
└── intent_classifier
```

## Statistics

| Category | Count |
|----------|-------|
| Core modules | 57 |
| Test files | 44 |
| Detection rule modules | 12 |
| LLM provider modules | 5 |
| Web UI views | 8 |
| Web UI components | 6 |
| Most lines | memory_manager.py (52K) |
| Most imported | log.py (19 imports) |
