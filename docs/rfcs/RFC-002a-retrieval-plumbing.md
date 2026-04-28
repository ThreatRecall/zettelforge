---
title: "RFC-002a: Retrieval Policy & CTI Plumbing Prerequisites"
description: "Prerequisite plumbing work that must land before RFC-002b (cascading synthesis) can be built: retrieval policy object, MITRE/CVE validators, 9B baseline model normalization, and schema-validated prompt chain harness. (Note: VulnerabilityMeta originally proposed here shipped under RFC-009.)"
diataxis_type: "reference"
audience: "Senior Backend / AI Engineer"
tags: [rfc, plumbing, retrieval, cti, prerequisite]
last_updated: "2026-04-27"
version: "2.7.1-proposed"
status: "DRAFT"
---

# RFC-002a: Retrieval Policy & CTI Plumbing Prerequisites

**Author:** Nexus (Roland Fleet)
**Date:** 2026-04-20 (refreshed 2026-04-27 against v2.6.2)
**Status:** DRAFT
**Target Version:** 2.7.1 (post v2.7.0 LLM-budget hardening; v2.7.0 scope is frozen at issues #125/#73/#72 per ROADMAP.md)
**Supersedes:** part of RFC-002 (split per reviewer feedback; the superseded original was deleted from the tree to resolve a number collision with `RFC-002-universal-llm-provider.md` — supersession trail preserved in this header and in git)
**Enables:** RFC-002b (Cascading Synthesis)
**Overlap:** RFC-003 (Read-Path Depth Routing) touches the same retrieval-pipeline surface — see Dependencies below before either can advance.

## Summary

Four pieces of plumbing must land before cascading synthesis (RFC-002b) can be built. These are valuable independent of the cascade — they fix a pre-existing silent-drop bug in `BlendedRetriever`, align the LLM model across the code, and introduce the schema-validation harness every future LLM chain will depend on. (A fifth prerequisite, `VulnerabilityMeta`, was proposed in the 2026-04-20 draft and has since shipped under RFC-009; see Prerequisite 2 for the pointer.)

## Motivation

RFC-002 review (2026-04-20) found that the cascade spec assumed infrastructure that does not exist in v2.4.0. Rather than inline those fixes into the cascade RFC, they belong as a prerequisite slice that can ship and be validated first. A v2.6.2 audit (2026-04-27) re-confirmed that four of the five prerequisites are still net-new work — only `VulnerabilityMeta` shipped in the interim.

## Scope

This RFC covers plumbing only. No user-facing synthesis behavior changes here.

### Prerequisite 1 — Retrieval Policy Object

**Problem.** `BlendedRetriever.blend()` (`src/zettelforge/blended_retriever.py:59-60`, verified v2.6.2) reads only `policy["vector"]` and `policy["graph"]`. `IntentClassifier.get_traversal_policy()` (`src/zettelforge/intent_classifier.py:183-233`, verified v2.6.2) produces additional keys (`entity_index`, `temporal`, `depth`, `recency_boost`) that are silently dropped. Any future policy knob added to the classifier is a no-op at the retriever. The bug is unchanged across v2.5.x and v2.6.x.

**Fix.** Introduce a typed `RetrievalPolicy` dataclass that the retriever consumes and validates:

```python
# src/zettelforge/retrieval_policy.py  (new module)

@dataclass(frozen=True)
class RetrievalPolicy:
    vector: float = 0.5
    graph: float = 0.5
    entity_index: float = 0.0
    temporal: float = 0.0
    max_graph_depth: int = 2
    traverse_relations: tuple[str, ...] = ()
    entity_boost: tuple[str, ...] = ()  # Entity types to prefer
    keyword_boost: tuple[str, ...] = ()
    recency_boost: bool = False
    start_entities: tuple[str, ...] = ()  # For graph-traversal stages
    k: int = 10

    def normalized_weights(self) -> dict[str, float]:
        """Sum-to-1 normalization across signal weights."""
```

`BlendedRetriever.blend()` grows to accept `RetrievalPolicy` (with a dict-shim for backwards compatibility during migration) and honor `entity_index` / `temporal` signals as first-class contributors. `MemoryManager.recall()` gains a `policy_override: Optional[RetrievalPolicy]` parameter so callers (including the future cascade) can bypass the classifier.

**Backwards compatibility.** Current dict-based callers keep working via a `RetrievalPolicy.from_dict()` adapter. Migration is additive.

### Prerequisite 2 — `VulnerabilityMeta` Schema (SHIPPED under RFC-009)

**Status (2026-04-27 audit):** Done. `VulnerabilityMeta` exists at `src/zettelforge/note_schema.py:47-59`, is persisted via `src/zettelforge/sqlite_backend.py`, and is referenced by `src/zettelforge/ontology.py`. It landed during the RFC-009 enrichment pipeline work.

**Field-name drift to note for RFC-002b consumers:**

| Originally proposed (2026-04-20) | Shipped (v2.6.2) |
|---|---|
| `cvss_v31: Optional[float]` | `cvss_v3_score: float \| None` |
| `cvss_vector: Optional[str]` | `cvss_v3_vector: str \| None` |
| `kev_listed: bool` | `cisa_kev: bool` |
| `published_at`, `last_modified`, `source` | not present (deferred) |

`epss_score` and `epss_percentile` shipped as proposed. `cve_id` is carried on the note's entity list rather than as a dedicated `VulnerabilityMeta` field; resolve via `MemoryNote.semantic.entities`.

**Action for downstream RFCs:** RFC-002b's S4 (Prioritization) should reference the shipped field names verbatim. No further work in this RFC.

### Prerequisite 3 — MITRE / CVE Validator

**Problem.** CTI-critical identifiers (MITRE technique IDs, CVE IDs) are trivially hallucinated by LLMs. The RFC-002 review flagged this as a safety-critical gap. The repo already vendors MITRE ATT&CK enterprise data (`benchmarks/enterprise-attack.json`) — it just isn't productionized yet.

**Fix.** New module `src/zettelforge/cti_validators.py`:

```python
class MitreAttackValidator:
    """Loads ATT&CK once, answers validity queries fast."""
    def is_valid_technique(self, technique_id: str) -> bool: ...
    def get_technique(self, technique_id: str) -> Optional[dict]: ...
    def canonicalize(self, technique_id: str) -> Optional[str]:
        """T1566.1 → T1566.001, handles variant formats."""

class CVEValidator:
    """Format + optional NVD-mirror validation."""
    def is_well_formed(self, cve_id: str) -> bool: ...
    def exists(self, cve_id: str) -> bool:
        """Requires NVD mirror; falls back to format-only when offline."""
```

Consumed by any LLM-generated output containing MITRE/CVE claims. RFC-002b will require S1 and S3 outputs to be post-validated; unvalidated IDs get flagged with `verified: False` and excluded from downstream prompts.

### Prerequisite 4 — Baseline Model Shift to 9B

**Problem (re-verified v2.6.2).** Per-class defaults remain inconsistent and too small for reliable structured output:

| File | Line | Default |
|------|------|---------|
| `config.py` | 102 | `qwen3.5:9b` (single source-of-truth, already 9B) |
| `synthesis_generator.py` | 27 | `qwen2.5:3b` |
| `fact_extractor.py` | 29 | `qwen2.5:3b` |
| `memory_updater.py` | 25 | `qwen2.5:3b` |
| `llm_providers/ollama_provider.py` | 15 | `qwen2.5:3b` |
| `llm_providers/local_provider.py` | 23 | `qwen2.5-3b-instruct-q4_k_m.gguf` |
| `llm_client.py` | 33-34 | `Qwen/Qwen2.5-3B-Instruct-GGUF` / `qwen2.5-3b-instruct-q4_k_m.gguf` |

3B lacks the firepower for reliable JSON in a 5-stage chain (review finding). Shift the baseline to a 9B-class model across the board.

**Fix.** Normalize all per-class defaults to read from `config.py`, eliminating hardcoded model strings. Target: `qwen3.5:9b` (Ollama tag) and a matching GGUF filename for local llama-cpp. No new model choice is being introduced — just aligning what already exists in config.

Side benefit: single source of truth for model choice, easing future swaps.

**Future model option.** A purpose-tuned 7B model is being fine-tuned in a separate project and may land before RFC-002a is implemented. The fine-tune does not change this prerequisite: the work here is *normalization* (a single config-driven default), not model choice. If the 7B FT is ready when this RFC enters implementation, the normalization landing target becomes the FT artifact rather than `qwen3.5:9b` — same code change, different default value. RFC-002b's spike protocol (`benchmarks/cascade_spike.py`) is the gate that decides which artifact wins. Sequencing risk: do not delay this RFC waiting on the FT.

### Prerequisite 5 — Schema-Validated Prompt Chain Harness

**Problem.** RFC-002 chains 5 LLM calls where each feeds the next via JSON. Current `SynthesisGenerator` uses best-effort `extract_json()` and silently falls back to `_fallback_synthesis()` on parse failure — tolerable for one stage, fatal in a cascade.

**Fix.** New module `src/zettelforge/prompt_chain.py`:

```python
class PromptStage(Generic[T]):
    """One stage of a prompt chain with schema validation + repair."""
    name: str
    prompt_template: str
    output_schema: Type[T]        # Pydantic or dataclass
    max_repair_attempts: int = 2

    def execute(
        self,
        context: dict,
        llm_client,
    ) -> StageOutput[T]:
        """Render prompt, call LLM with json_mode=True, validate,
        repair-retry on failure, return typed result + status."""

@dataclass
class StageOutput(Generic[T]):
    status: Literal["ok", "partial", "failed"]
    result: Optional[T]
    raw_response: str
    repair_attempts: int
    latency_ms: float
    error: Optional[str]
```

Key requirements:

- Uses existing `llm_client.generate(json_mode=True)` support.
- On validation failure, feeds the Pydantic/dataclass error back into a repair prompt (max 2 retries).
- Never silently falls through — callers always see `StageOutput.status`.
- Per-stage latency and attempt metrics emitted for observability.

This harness is what RFC-002b's five stages will be built on. It is also reusable for any future multi-step LLM feature.

## Non-Goals

- Does not implement the cascading synthesis stages themselves (RFC-002b).
- Does not change any existing `recall()` / `synthesize()` public behavior.
- Does not introduce caching (separate RFC if warranted).

## Acceptance Criteria

1. `RetrievalPolicy` exists; `BlendedRetriever` honors all documented signals; `IntentClassifier` policy output no longer silently drops keys. Regression test demonstrates `entity_index=1.0, vector=0.0` actually produces entity-dominated results.
2. `VulnerabilityMeta` is available on notes; `MitreAttackValidator` and `CVEValidator` pass unit tests on canned inputs; MITRE ATT&CK load time <500ms.
3. All per-class default models read from `config.py`; no hardcoded `qwen2.5:3b` strings remain in `src/zettelforge/*.py`. Full test suite passes against a 9B model.
4. `PromptStage` harness: given a stage that returns invalid JSON, repair loop recovers in ≥90% of seeded-failure unit tests; `StageOutput.status="failed"` is reachable and observable.
5. Public API surface of `MemoryManager` unchanged; existing callers of `recall()`/`synthesize()` unaffected (regression suite green).

## Implementation Plan

| Phase | Work | Estimate |
|-------|------|----------|
| 1 | `RetrievalPolicy` + `BlendedRetriever` migration + regression tests | 6h |
| 2 | `VulnerabilityMeta` + MITRE/CVE validators + ATT&CK loader | 4h |
| 3 | Model-default normalization + CI green on 9B | 2h |
| 4 | `PromptStage` / `StageOutput` harness + repair-loop tests | 6h |
| **Total** | | **~18h** |

## Open Questions

1. CVE validator — ship offline-format-only first, add NVD mirror later? (Proposed: yes.)
2. Should `RetrievalPolicy` be frozen/immutable? (Proposed: yes, for caching safety.)
3. MITRE ATT&CK data — vendor it in the package, or fetch at install? (Proposed: vendor, it's <10MB combined.)

## Dependencies

- **RFC-003 (Read-Path Depth Routing)** competes for the same retrieval-pipeline surface area. Both touch `BlendedRetriever`, the policy plumbing, and depth-traversal semantics. A sequence-decision is required before this RFC starts implementation: either (a) land RFC-002a's `RetrievalPolicy` first and have RFC-003 consume it as the policy carrier for depth routing, or (b) merge the two RFCs into one. Recommendation: option (a) — `RetrievalPolicy` is foundational and useful beyond depth routing.
- **RFC-009 (Enrichment Pipeline v2)** already shipped `VulnerabilityMeta` (see Prerequisite 2). RFC-002b consumers should use the shipped field names.
- **RFC-002b** is hard-blocked on this RFC. Do not start RFC-002b implementation work until Prerequisites 1, 3, 4, and 5 have landed and their acceptance criteria pass in CI.
- **In-flight 7B fine-tune** (separate project, see local memory `memory/project_finetune_7b.md`): not a dependency, but a sequencing input to Prerequisite 4. See that section's Future Model Option note.
- **v2.7.0 release** (target 2026-05-09 per ROADMAP): scope is frozen at issues #125, #73, #72. This RFC targets v2.7.1 or later.

## References

- RFC-002 (original cascading-synthesis spec, superseded 2026-04-20). The file was deleted from `docs/rfcs/` to resolve a number collision with the shipped `RFC-002-universal-llm-provider.md`. Supersession is preserved here and in `RFC-002b-cascading-synthesis.md`. Original content is recoverable from git history.
- RFC-002 review findings, 2026-04-20 (AI Engineer + Backend Architect).
- RFC-002a v2.6.2 audit, 2026-04-27 (Software Architect).
- RFC-009 (Enrichment Pipeline v2) — shipped `VulnerabilityMeta`.
- RFC-003 (Read-Path Depth Routing) — overlapping retrieval-pipeline surface; see Dependencies above.
- Existing code (verified v2.6.2): `blended_retriever.py:41-90`, `intent_classifier.py:183-233`, `memory_manager.py`, `synthesis_generator.py`, `llm_client.py`, `note_schema.py:47-59` (shipped VulnerabilityMeta).
- MITRE ATT&CK data already in `benchmarks/*-attack.json`.
