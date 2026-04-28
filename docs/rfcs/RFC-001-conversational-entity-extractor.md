# RFC-001: Conversational Entity Extractor

## Metadata

- **Author**: Patrick Roland
- **Status**: Accepted
- **Created**: 2026-04-09
- **Last Updated**: 2026-04-09
- **Reviewers**: Solo dev (self-approved)
- **Related Tickets**: LOCOMO benchmark improvement
- **Related RFCs**: None

## Summary

Replace the regex-based CTI-only entity extractor with an LLM-powered NER pipeline that recognizes conversational entities (persons, locations, organizations, events, activities, temporal references). This enables the knowledge graph to index and traverse the entity types present in the LOCOMO benchmark, targeting 80%+ overall accuracy (up from 15%).

## Motivation

LOCOMO benchmark results at 15% overall accuracy trail the leaderboard by 4x. Root cause analysis (BENCHMARK_REPORT.md) identifies entity extraction mismatch as the #1 blocker: ZettelForge only recognizes CVEs, APT groups, tools, and campaigns. LOCOMO conversations contain person names, locations, hobbies, life events, and temporal references — all invisible to the current `EntityExtractor`.

RAGAS data confirms retrieval finds the right documents (75.9% keyword presence) but the graph retrieval path is dead for LOCOMO queries because no recognized entities match. The keyword-overlap judge scores low because retrieved context is long and unfocused — entity-indexed graph traversal would both boost relevant results and filter noise.

The gap between keyword presence (75.9%) and answer accuracy (15%) also indicates the answer extraction pipeline needs improvement. Adding conversational entities to the graph enables multi-hop traversal which directly addresses the 0% multi-hop and 0% temporal scores.

## Proposed Design

### Architecture Changes

**Replace regex-based `EntityExtractor` with LLM-based NER.** The current `entity_indexer.py:12-28` uses 4 hardcoded regex patterns. The new implementation uses the existing `llm_client.py` to extract typed entities from any text, with regex as a fast-path fallback for CTI entities.

**Unified entity schema** across `entity_indexer.py` and `note_constructor.py`. Currently these two files duplicate patterns. The new design makes `EntityExtractor` the single source of truth — `NoteConstructor` delegates to it.

**New entity types**: `person`, `location`, `organization`, `event`, `activity`, `temporal`. Existing CTI types (`cve`, `actor`, `tool`, `campaign`) are preserved as regex fast-paths.

**Enhanced answer extraction in the benchmark.** The current `locomo_benchmark.py` returns raw context as the "answer" (lines 199-201). Adding `SynthesisGenerator` to distill focused answers will dramatically improve keyword-overlap scoring.

### Data Model Changes

Entity index gains new type keys. The `EntityIndexer.index` dict expands from `{cve, actor, tool, campaign, sector}` to also include `{person, location, organization, event, activity, temporal}`. This is backward-compatible — old indexes simply lack the new keys until rebuilt.

Knowledge graph gains new node types. `NoteConstructor._infer_entity_type()` gets patterns for the new types. The `_update_knowledge_graph()` method gains inferred edge rules for conversational types (e.g., person-attended-event, person-works-at-organization).

### API Changes

No public API changes. `EntityExtractor.extract_all()` still returns `Dict[str, List[str]]` — just with more keys. `MemoryManager.recall_entity()` gains the ability to query by `person`, `location`, etc.

### Security Considerations

LLM-generated entity data enters the knowledge graph. To prevent injection: entities are extracted from note content (already governance-validated on input per GOV-011), and entity values are normalized to lowercase strings with no executable content. No new attack surface.

### Observability

Extraction metrics logged: entity count by type per note, LLM extraction latency, fallback-to-regex rate. Structured logging per GOV-012.

## Alternatives Considered

**Alternative 1: More regex patterns for conversational entities.** Rejected — person names, locations, and events cannot be reliably matched with regex. "Sarah" vs "sarah" vs "SARAH" is tractable but "my friend from college" referring to a person is not. Regex would give maybe 30-40% recall on LOCOMO entities.

**Alternative 2: External NER library (spaCy, GLiNER).** Rejected — adds a heavy dependency (spaCy model ~500MB) or requires a separate model download. The project already has an LLM client; using it for NER keeps the dependency tree minimal and leverages the existing Qwen2.5-3B model.

**Alternative 3: Hybrid approach (LLM NER + regex fast-path).** Selected — use regex for the CTI types where patterns are reliable (CVE, APT groups), and LLM for conversational types where regex fails. Best of both worlds: fast and deterministic for CTI, flexible for everything else.

## Implementation Plan

### Step 1: Refactor EntityExtractor to single source of truth
- Remove duplicated patterns from `note_constructor.py`
- Make `NoteConstructor` delegate to `EntityExtractor`
- Preserve CTI regex as fast-path
- **Files**: `entity_indexer.py`, `note_constructor.py`, `memory_manager.py`

### Step 2: Add LLM-based NER extraction
- New method `extract_llm()` on `EntityExtractor` that uses `llm_client.py`
- Prompt extracts: person, location, organization, event, activity, temporal
- Fallback to regex for CTI types
- Merge results from both paths
- **Files**: `entity_indexer.py`

### Step 3: Expand entity index schema and knowledge graph
- Add new entity types to `EntityIndexer.index` defaults
- Update `_infer_entity_type()` for new types
- Add conversational edge inference rules to `_update_knowledge_graph()`
- Update `_check_supersession()` to include new entity overlap
- **Files**: `entity_indexer.py`, `note_constructor.py`, `memory_manager.py`

### Step 4: Enhance benchmark answer extraction
- Add `SynthesisGenerator` to `locomo_benchmark.py` answer pipeline
- Replace raw-context-as-answer with synthesized focused answers
- **Files**: `locomo_benchmark.py`

### Step 5: Tests and benchmark validation
- Unit tests for each new entity type (per GOV-007: test naming `test_<scenario>_<expected_outcome>`)
- Integration test: ingest LOCOMO sample, verify entity extraction
- Run full LOCOMO benchmark, target 80%+ overall
- **Files**: `tests/test_basic.py`, `tests/test_conversational_entities.py`

## Rollout Strategy

1. Create feature branch `feature/RFC-001-conversational-entity-extractor` from `master`
2. Implement Steps 1-5 on the feature branch
3. Run full benchmark suite to validate target (80%+ LOCOMO)
4. Squash-merge to `main` per GOV-002

## Open Questions

- Should the LLM NER call be cached per note to avoid re-extraction on rebuild? (Decision: yes, cache in note metadata)
- What's the acceptable latency budget for NER per note? Current ingestion is 0.4/s. LLM NER adds ~2-3s per call. (Decision: acceptable for benchmark; add async batching for production later)

## Decision

**Decision**: Accepted
**Date**: 2026-04-09
**Decision Maker**: Patrick Roland
**Rationale**: The hybrid LLM+regex approach is the most practical path to 80%+ LOCOMO. The existing LLM client eliminates new dependencies. RAGAS keyword presence data confirms retrieval is close — entity and synthesis improvements should close the gap.