# Changelog

All notable changes to ZettelForge are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/).
Versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.1.1] - Upcoming

Production hardening release targeting P0 blockers identified in the
2026-04-14 architecture review (5 P0 issues, conducted by 3 independent
agent reviewers across 7,193-note production system). Also includes the
Sprint 3 dual-stream write path and updated benchmark results.

### Added

- **Dual-stream write path** — `remember()` now returns in ~45ms (fast
  path) by deferring causal enrichment to a background worker. Callers
  that need enrichment to complete before the next read can pass
  `sync=True` to block until the worker finishes.
- **`sync` parameter on `remember()`** — `bool`, default `False`. When
  `True`, the call blocks until background causal enrichment completes.
  Useful in tests and batch pipelines.
- **LOCOMO benchmark updated to 22.0%** (up from 18.0%) — measured with
  Ollama cloud models via the LLM judge evaluation path.

### Fixed

- **P0-1** — `_check_supersession` was O(n) on every `remember()` call,
  re-extracting entities and scanning all notes linearly. Replaced with
  entity-index lookup and vector pre-filter, reducing supersession check
  from ~500 ms at 7K notes to sub-millisecond. Usable writes now viable
  past 50K notes.
- **P0-2** — No file locking on JSONL or entity index writes allowed
  concurrent processes to corrupt data. Added `fcntl.flock()` guards on
  all JSONL and entity index write paths.
- **P0-3** — SQL injection in `VectorMemory.search()` and
  `VectorMemory.delete()` via string interpolation in LanceDB queries.
  Parameterized all LanceDB query expressions.
- **P0-4** — 378 ghost rows in LanceDB (7,571 rows vs 7,193 JSONL notes)
  caused stale embeddings to be returned. Added dedup guard in
  `_index_in_lance()` to prevent duplicate row creation on re-indexing.
  Existing ghost rows cleared by a one-time rebuild. Closes #26.
- **P0-5** — 3 orphaned temp files (206 MB total) from crashed
  `_rewrite_note()` calls had no cleanup routine. Added startup sweep to
  remove `*.tmp` files left in the notes directory.
- **P1-10** — Entity index was not invalidated on supersession, so
  superseded notes remained queryable by entity lookup. Entity index
  entries are now removed when a note is superseded.

### Security

- Parameterized LanceDB queries eliminate the SQL injection surface in
  `VectorMemory` (see P0-3 above).

---

## [2.1.0] - 2026-04-12

GOV-012 logging and observability compliance, CI/CD pipeline, and memory
evolution support.

### Added

- **GOV-012 compliance** — Structured logging via `structlog` with JSON
  output throughout all production code paths. Eliminates all bare
  `print()` calls from production code.
- **OCSF v1.3 audit events** — New `ocsf.py` module emits typed
  OCSF-schema events for all auditable operations:
  - `remember()` → OCSF API Activity (class 6003), Create activity
  - `recall()` → OCSF API Activity with query, result_count, duration_ms
  - `synthesize()` → OCSF API Activity with source_count, duration_ms
  - `GovernanceValidator.enforce()` → OCSF Authorization (class 3003)
    with `status_id` 1 (allowed) or 2 (denied) and triggering rule
  - `_index_in_lance()` → OCSF File Activity (class 1001) with
    table_name, note_id, status, duration_ms
- **Audit trail** — All OCSF events include required base fields:
  `class_uid`, `class_name`, `severity_id`, `time` (UTC ISO 8601),
  `metadata.version` ("1.3.0"), `metadata.product.name` ("zettelforge"),
  `metadata.product.version`
- **Memory evolution** — `remember()` and `remember_with_extraction()`
  accept `evolve=True` parameter to trigger supersession checks and
  knowledge graph updates rather than treating the note as additive
- **CI/CD pipeline** — Lint, test, and governance jobs added; `ruff
  format` compliance enforced on all Python source files
- **Open-core edition system** — Community (MIT) + Enterprise (BSL-1.1)
  with `EditionError` for clear upgrade messaging and `/api/edition`
  endpoint
- **Edition detection** — via `THREATENGRAM_LICENSE_KEY` or enterprise
  package presence
- `LICENSE-ENTERPRISE` (BSL-1.1) for enterprise feature set
- GitHub issue/PR templates and CODE_OF_CONDUCT.md

### Fixed

- **LanceDB single-row bug (#26)** — Silent exception swallowing in
  `_index_in_lance()` masked indexing failures for single-note writes,
  causing the 378-row ghost row accumulation later measured at production
  scale. Structured logging and explicit error propagation prevent this
  class of silent data loss going forward.

### Changed

- All bare `print()` calls replaced with `structlog` structured logger
  instances (`get_logger("zettelforge.*")`)
- Silent `except Exception: pass` blocks replaced with logged,
  re-raised, or explicitly handled exceptions
- Dependencies split: core (MIT) vs `pip install zettelforge[enterprise]`
- Enterprise-only features: TypeDB STIX ontology, temporal KG queries,
  advanced synthesis formats, report ingestion, multi-hop traversal,
  OpenCTI integration, Sigma generation, multi-tenant auth
- Community gets full memory pipeline: blended retrieval, two-phase
  extraction, intent routing, causal triples, cross-encoder reranking

---

## [2.0.0] - 2026-04-09

### Added

- Hybrid TypeDB + LanceDB architecture
- STIX 2.1 schema with 9 entity types, 8 relationship types
- TypeDB alias inference (36 CTI aliases: APT28/Fancy Bear/Strontium, etc.)
- Report ingestion with auto-chunking (`remember_report()`)
- In-process embeddings via fastembed (no Ollama needed for embeddings)
- Local LLM via llama-cpp-python (Qwen 2.5 3B)
- Conversational entity extraction (person, location, org, event, activity, temporal)
- Multi-tenant OAuth/JWT authentication
- ThreatRecall web UI (FastAPI)
- MCP server for Claude Code integration
- OpenCTI continuous sync
- MemoryAgentBench (ICLR 2026) benchmark
- Configuration system with layered resolution (env > yaml > defaults)
- Documentation suite (Diataxis framework)

### Changed

- Knowledge graph backend: TypeDB-first with JSONL fallback
- Embedding provider: fastembed (in-process ONNX) replaces Ollama HTTP
- Bumped all benchmarks: CTI 75%, LOCOMO 18%, RAGAS 78.1%

---

## [1.5.0] - 2026-04-08

### Added

- GraphRetriever for multi-hop note discovery via knowledge graph
- BlendedRetriever combining vector + graph results with policy weights
- Rewritten `recall()` with blended vector + graph retrieval
- CTIBench (NeurIPS 2024) benchmark adapter
- RAGAS retrieval quality benchmark

---

## [1.4.0] - 2026-04-07

### Added

- FactExtractor (Phase 1): LLM-based salient fact extraction with importance scoring
- MemoryUpdater (Phase 2): ADD/UPDATE/DELETE/NOOP decision engine
- `remember_with_extraction()` two-phase pipeline

---

## [1.3.0] - 2026-04-07

### Added

- Sigma rule generation from IOCs
- Microsoft Sentinel rule conversion

---

## [1.2.0] - 2026-04-07

### Added

- CTI platform integration (Django CTI database connector)
- Proactive context injection for agent workflows

---

## [1.0.0] - 2026-04-06

### Added

- Core memory pipeline (remember, recall, vector search)
- Knowledge graph with JSONL persistence
- Entity extraction (CVE, actor, tool, campaign)
- Causal triple extraction (LLM-powered)
- Temporal graph indexing
- RAG synthesis (direct_answer format)
- Intent classification and query routing
- Cross-encoder reranking
