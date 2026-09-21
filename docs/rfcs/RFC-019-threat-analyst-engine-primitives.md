# RFC-019: Threat Analyst Agent Engine Primitives

## Status (2026-07-07)

**Draft — proposed.** No implementation has landed.

Source: this RFC extracts the **ZF-scoped items** from the Spec Kit expansion
package *Spec 011 Threat Analyst Agent* (ThreatEngram, 2026-07-07, rev 1.2).
That package spans both products; everything tagged `TR` (tenant policy, API
auth, UI rendering, feed scheduling, SIRP adapters, RBAC, export operations)
is **out of scope here** and is listed in §14 so the boundary is explicit.
Requirement IDs (`E-FR-NNN`) are preserved verbatim from the package for
traceability during reconciliation.

Working rule inherited from the package: **the engine computes, the SaaS
decides.** Scoring math, traversal, normalization, provenance enforcement,
staging, and validation live in ZettelForge. Thresholds, tenant overrides,
export destinations, and rendering live above it.

## 1. Motivation

ZettelForge already extracts CTI entities, builds a STIX-flavoured knowledge
graph, and serves recall/synthesis over a dual store. What it does not yet
provide is the primitive set a *threat analyst LLM agent* needs to operate
safely on that memory:

1. **Contextual enrichment** of raw IoCs with per-assertion confidence and
   provenance — where "the store knows nothing" is a first-class, structured
   answer, never improvised context.
2. **Bounded, deterministic graph exploration** — a subgraph payload an agent
   can cite and a UI can render without the two ever diverging.
3. **Indicator scoring and decay** — a closed-form, explainable score built
   from source confidence, per-type temporal decay, and disposition-weighted
   sightings, so downstream export gates fire on live intelligence instead of
   dead infrastructure.
4. **Curated ingestion primitives** — staging, batch revert, span-anchored
   free-text extraction, dedup, warning lists, and correlation candidates, so
   external data becomes memory only through a controlled, reversible path.

The primary consumer is an LLM agent (persona P1 in the package). The two
failure modes that dominate that consumer are **fabrication** (context that
sounds right but has no stored source) and **ambiguity between "nothing
known" and "query failed."** Both are promoted from quality notes to
contract-level requirements in this RFC.

## 2. Product boundary and plane separation

Every requirement below carries its package boundary tag. This RFC implements:

| Tag | Treatment here |
|---|---|
| `ZF` | Fully in scope. |
| `SHARED` | The **mechanism** half is in scope (math, storage, validation, audit hooks). The policy half (thresholds, tenant overrides, approval rules) is exposed as injectable parameters and callbacks, never hardcoded. |
| `TR` | Out of scope (§14). |

**Plane separation** (E-FR-031, `SHARED`; E-FR-027, `ZF`): the engine has
exactly two planes. The **query plane** (enrichment, traversal, scoring,
export evaluation) never makes an external network call and operates only on
the committed corpus — this preserves ZettelForge's existing offline-first
posture and matches the OSINT layer's fail-closed philosophy (RFC-016). The
**ingestion plane** (feed content handed in by the caller, uploads, free-text
import) is the only place external data enters, and everything it touches is
staged, gated, and audited before commit. A capability is on exactly one
plane; nothing straddles.

Note on tenancy: ZettelForge is a single-corpus engine. "Tenant isolation is
a hard pre-filter" (E-FR-026, `TR`) is satisfied at this layer by the
existing pattern of one `MemoryManager`/store per tenant (as `web/auth.py`'s
`get_mm_for_request` already does); no tenant logic enters engine primitives.

## 3. Design principles

- **Explicit absence over synthesis** (package constitution gate 7,
  E-FR-048): every agent-facing read tool returns a structured
  `known: false` shape for unknown entities, distinct from any error. No tool
  emits an object, relationship, or attribute absent from the store.
- **Provenance is mandatory per assertion** (E-FR-004): an assertion that
  cannot carry provenance is dropped from the response, never emitted bare.
- **Determinism** (E-FR-013): identical query + identical corpus snapshot =
  byte-identical payload, so agents can cite results and humans can verify
  them.
- **One normalization implementation, two call sites** (E-FR-034): the
  import path and the query path call the same canonicalization function, or
  lookups silently miss as they drift apart.
- **Staged and reversible ingestion** (E-FR-032): external data commits in
  batches; a poisoned source reverts as one audited operation.
- **Conflict preservation** (E-FR-005): contradictory attributions are
  returned in full with per-link confidence. The engine never tie-breaks.

## 4. IoC normalization and refanging (E-FR-001, `ZF`)

Extends `EntityExtractor` (`src/zettelforge/entity_indexer.py`) with a
shared canonicalization module:

- **Type inference** for `ipv4`, `ipv6`, `domain`, `url`, `md5`, `sha1`,
  `sha256`, `email`. (`ipv6` extraction is currently missing — issue #47 —
  and becomes a prerequisite of this RFC rather than a standalone
  nice-to-have.)
- **Refanging** of standard defang patterns: `hxxp://` → `http://`,
  `evil[.]example[.]com` → `evil.example.com`, `192.168.1[.]1` → dotted
  quad, `(at)`/`[at]` → `@`.
- **Canonical form recorded alongside raw input** in every response, so the
  caller can always see what was matched.

```python
# zettelforge/normalization.py (new module)
def canonicalize(raw: str) -> CanonicalIoC:
    """Refang, type-infer, and normalize. One implementation, imported by
    both the enrichment tool (query plane) and the staging pipeline
    (ingestion plane). Property-tested over a defang-variant corpus."""
```

## 5. Contextual enrichment (US1: E-FR-002 – E-FR-008)

A new engine call (and MCP tool, §11) that takes one or more raw IoCs and
returns the versioned enrichment response:

| ID | Requirement | Boundary |
|---|---|---|
| E-FR-002 | Single versioned JSON schema: normalized indicator, matched objects with STIX relationship types, ATT&CK annotations (technique ID, tactic, pinned version), per-assertion confidence, per-assertion provenance (source refs, `first_seen`, `last_seen`, report/note refs), retrieval-explanation block. | ZF core |
| E-FR-003 | Explicit absence: unknown indicator returns `{known: false, assertions: []}` — not an error, no synthesized context. | ZF |
| E-FR-004 | Provenance mandatory per assertion; unprovable assertions are dropped. | ZF |
| E-FR-005 | Conflicting attributions returned in full; no engine-side tie-breaking. | ZF |
| E-FR-006 | Depth-1 (direct relationships) mandatory. Transitive enrichment (depth ≥ 2) is gated on open question §13.1 and carries kill criterion KC-1. | ZF |
| E-FR-007 | Batch enrichment (default ceiling 100/call) with per-item isolation: one malformed item never fails the batch. | ZF |
| E-FR-008 | Retracted objects excluded by default; `include_retracted: true` returns them labeled with the retraction audit reference. (Whether the flag needs a caller-side permission is a TR question.) | SHARED |

Response schema sketch:

```json
{
  "schema_version": "1.0",
  "corpus_snapshot": "<snapshot-id>",
  "input_raw": "evil[.]example[.]com",
  "indicator": { "canonical": "evil.example.com", "type": "domain" },
  "known": true,
  "assertions": [
    {
      "object_ref": "intrusion-set--...",
      "object_type": "intrusion-set",
      "relationship": "attributed-to",
      "path_depth": 1,
      "confidence": 72,
      "provenance": {
        "source_refs": ["report--...", "note--..."],
        "first_seen": "2026-03-02T00:00:00Z",
        "last_seen": "2026-06-18T00:00:00Z"
      }
    }
  ],
  "attack_annotations": [
    { "technique_id": "T1071.001", "tactic": "command-and-control",
      "attack_version": "<pinned>" }
  ]
}
```

Implementation ground: assertions come from the existing `kg_nodes` /
`kg_edges` model (`KnowledgeGraph.add_node/add_edge`, `get_kg_neighbors`)
plus note back-references from the entity index; confidence and provenance
ride the existing edge `properties` dict, promoted to required fields for
edges emitted by this pipeline.

## 6. Relationship graph exploration (US2: E-FR-009 – E-FR-014)

| ID | Requirement | Boundary |
|---|---|---|
| E-FR-009 | Pivot query contract: entity ref, depth, direction, optional relationship-type filter → nodes and typed edges, every edge carrying STIX relationship type, confidence, provenance. | ZF |
| E-FR-010 | Bounds: `max_depth`, `max_nodes`, `max_edges` configurable with hard engine ceilings (proposed defaults: depth 3, 500 nodes, 2000 edges). Exceeding any bound sets `truncated: true` and returns a continuation cursor. Nothing is dropped silently. | ZF |
| E-FR-011 | Cycle safety via visited-set semantics; a cycle appears in the payload exactly once. | ZF |
| E-FR-012 | ATT&CK overlay: attack-pattern nodes annotated with technique ID, tactic, pinned ATT&CK version; unmapped entities flagged `unmapped`, never guessed. | ZF |
| E-FR-013 | Determinism: identical query against an identical corpus snapshot yields a byte-identical payload carrying the snapshot identifier. | ZF |
| E-FR-014 | Subgraph export as a valid STIX 2.1 bundle containing exactly the payload's objects and relationships. | ZF |

Deterministic ordering rule (normative): nodes sorted by
`(stix_type, id)`; edges by `(relationship, src, dst)`. Truncation removes
highest-index entries under that ordering, never a random subset.

```json
{
  "schema_version": "1.0",
  "corpus_snapshot": "<snapshot-id>",
  "pivot": "malware--...",
  "depth": 2,
  "truncated": false,
  "cursor": null,
  "nodes": [ { "id": "...", "stix_type": "intrusion-set", "attack": null } ],
  "edges": [
    { "src": "...", "dst": "...", "relationship": "uses", "confidence": 80,
      "provenance": { "source_refs": ["report--..."] } }
  ]
}
```

E-FR-015 (render fidelity) is the TR half of this contract: the payload *is*
the interface; any UI renders it read-only with no client-side inference.

## 7. Indicator scoring, decay, and sightings (US3: E-FR-016 – E-FR-024)

### 7.1 Score model (E-FR-016, `ZF`)

```
decay(dt, type) = exp(-ln(2) * dt / half_life[type])
score(t) = clamp_0_100( base_confidence * decay(t - anchor, type)
           + sum_i( w(disposition_i) * s_i * decay(t - t_i, type) ) )
w(true_positive) > 0, w(false_positive) < 0, w(unknown) = 0
anchor = max(created, latest true_positive sighting timestamp)
```

Deterministic closed form: identical inputs reproduce identical scores. A
MISP-compatible polynomial kernel
(`score = base * (1 - (elapsed/lifetime)^(1/decay_speed))`) is an open
alternative (§13.3); the kernel is selectable, not forked.

### 7.2 Per-type decay defaults (E-FR-017, `SHARED` — engine defaults, caller overrides)

| Type | Proposed half-life | Rationale |
|---|---|---|
| ipv4 / ipv6 | 21 days | C2 infrastructure churns fastest. |
| url | 30 days | Slightly stickier than raw IPs. |
| domain | 90 days | Registration/sinkholing cycles are slower. |
| file hash | 365 days | The artifact stays malicious; detection *relevance* decays. |
| email | 60 days | Between URL and domain persistence. |

### 7.3 Sightings (E-FR-018 – E-FR-020)

A new `Sighting` record with STIX 2.1 Sighting SRO semantics: sighted object
ref, source system, timestamp, count, disposition
(`true_positive` | `false_positive` | `unknown`). Storage is ZF (a table in
`sqlite_backend.py` mirroring the existing `kg_edges` pattern); the ingest
API/transport is the caller's concern. A true-positive sighting boosts the
score and re-anchors the decay clock (E-FR-019); false-positive sightings
apply the model penalty (E-FR-020) — how many consecutive FPs drop an
indicator below an export threshold is caller policy over engine math.

### 7.4 Explanation and retraction dominance (E-FR-021 – E-FR-024)

- **Score explanation payload** (E-FR-023, `ZF`): base confidence, decay
  factor with parameters and anchor, per-sighting contributions with
  disposition and weight, model version, resulting score. **Recomputing from
  the payload alone reproduces the score exactly.**
- **Export-gate evaluator** (E-FR-021 is TR policy over ZF score): the
  engine ships the evaluator as a library function with a *fixed* evaluation
  order — caller filter, retraction, marking/license, expiry, threshold —
  short-circuiting on first exclusion and reporting which check excluded and
  why. The ordering makes retraction structurally incapable of being outvoted
  by sightings, and marking violations incapable of being outvoted by score.
- **Recompute cadence** (E-FR-022, `SHARED`): event-driven recompute on
  sighting ingest rides the existing enrichment-queue machinery in
  `memory_manager.py`; the scheduled refresh cycle is the caller's job.
- **Retraction** (E-FR-024): forces exclusion from default enrichment and
  from export evaluation within one refresh cycle regardless of score,
  with an audit entry. Generalizes the existing supersession/audit patterns.

## 8. Ingestion and curation primitives (US4, engine half)

| ID | Requirement | Boundary |
|---|---|---|
| E-FR-032 | **Staging and batch model**: all external input lands in staging keyed by an import batch ID. Commit is an explicit, audited transition after normalization, dedup, and quality gates. Every committed object carries batch provenance; a whole batch is revertible — revert removes or tombstones exactly that batch's objects and derived correlation candidates. Committed objects are immutable; corrections flow through retraction or supersession, never in-place edits. | ZF storage |
| E-FR-034 | **Normalization unification**: the import path calls the same §4 implementation as the query path. STIX 2.1 field mapping, UTC timestamps, confidence mapped to one scale, TLP 2.0 markings preserved. | ZF |
| E-FR-035 | **Free-text import**: extract candidate observables/entities from unstructured text. Every proposal is span-anchored (source doc ref, character offsets, verbatim span). A validator rejects any proposal whose span does not exact-match the document slice or whose canonical form does not derive from the span via §4. LLM-assisted extraction is permitted **only behind this validator**: the extractor proposes, the validator disposes. | ZF |
| E-FR-036 | Staged proposals require approval before commit (approval *policy* is the caller's; the staging/approval state machine is the engine's). Committed objects carry document-plus-span provenance. | SHARED |
| E-FR-037 | **Dedup at commit**: exact canonical-form and STIX ID matches merge automatically with a merge audit entry preserving both provenance chains. Similarity-based near-duplicates are flagged as merge candidates and never auto-merged. | ZF |
| E-FR-038/039 | **Warning-list subsystem**: versioned lists (bundled, caller-custom, FP-derived); lookups at commit gates and on demand. Every exclusion or flag is audited with the matching list, entry, and list version. Nothing is silently dropped. | SHARED / ZF data |
| E-FR-040 | **Feed evaluation scorecard** computed from staging without commit: overlap vs corpus, warning-list hit rate, FP-list hit rate, net-new contribution, staleness distribution, format error rate. | SHARED |
| E-FR-041 | **Ingest-time correlation via both hemispheres**: semantic (typed paths through the ontology — shared observables, shared techniques, actor links) and associative (vector similarity over content). Output is a correlation-candidate record carrying method tag, score, and evidence refs. | ZF |
| E-FR-042 | **Candidates are hypotheses**: no correlation candidate creates a STIX relationship automatically. Promotion writes the promoting actor and candidate evidence into the relationship's provenance; dismissals are recorded, not deleted. | ZF mechanism |
| E-FR-045 | **Sector and origin faceting**: victim Identity objects carry the STIX industry-sector vocabulary; origin via Location objects (ISO 3166-1 alpha-2). Enrichment and graph interfaces accept sector/country facet filters. | ZF |
| E-FR-047 | **Marking propagation**: TLP 2.0 markings and license terms propagate to derived objects; the export-gate evaluator (§7.4) honours them. Blocking *policy* is the caller's. | SHARED |

Span-anchored proposal schema (free-text import):

```json
{
  "proposal_id": "...",
  "source_doc_ref": "note--... or artifact ref",
  "char_start": 1042,
  "char_end": 1063,
  "verbatim_span": "evil[.]example[.]com",
  "canonical": "evil.example.com",
  "proposed_type": "domain",
  "extraction_method": "regex | llm_assisted",
  "status": "staged | approved | rejected_span_mismatch | rejected_policy"
}
```

Validator rules: the document slice `[char_start, char_end)` must equal
`verbatim_span` byte-for-byte, and `canonical` must equal
`canonicalize(verbatim_span)`. This is what makes LLM-assisted extraction
safe to enable — the model can suggest, but nothing ungrounded can commit.
It composes directly with the existing prompt-injection guard: extracted
text is data, never instructions.

Correlation candidate record:

```json
{
  "candidate_id": "...",
  "subject_ref": "report--...",
  "object_ref": "intrusion-set--...",
  "method": "semantic_path | associative_similarity",
  "score": 0.87,
  "evidence": ["relationship--... (path)", "vector neighbor ref"],
  "status": "candidate | promoted | dismissed",
  "promoted_by": null,
  "batch_ref": "import-batch--..."
}
```

Commit pipeline order per batch (normative): normalize (E-FR-034) → dedup
(E-FR-037) → warning-list and FP-list gates (E-FR-038) → marking propagation
(E-FR-047) → commit with batch provenance stamped on every object.

## 9. Cross-cutting engine contracts

| ID | Requirement |
|---|---|
| E-FR-025 | All new capabilities are exposed as MCP tools with published, versioned JSON schemas. **Any PR that adds, removes, or renames an MCP tool updates the tool documentation in the same PR** — the permanent control for tool-count drift. |
| E-FR-027 / E-FR-031 | No external network calls on any query-plane path. External fetch exists only on the ingestion plane, and even there the engine consumes bytes handed to it — actual feed pulling/scheduling is the caller's. |
| E-FR-028 | Every agent-facing response carries `schema_version` and the **corpus snapshot identifier**. New primitive: a monotonic write-generation counter maintained by the storage backend (bumped on every committed write/merge/retraction), sufficient for "unchanged corpus" determinism checks without content hashing. |
| E-FR-030 | Latency budgets: p95 targets per operation fixed at planning time; proposed single-IoC enrichment target < 2s on the reference corpus. |
| E-FR-048 | **Uniform explicit-absence contract**: `known: false` shapes for unknown entities on *every* read tool — enrichment, graph pivot, score explanation, warning-list lookup. CI-enforced (SC-2). |

## 10. New entities

`Indicator` (scored view over existing IOC entities), `Sighting`,
`DecayModelConfig`, `EnrichmentResponse`, `SubgraphPayload`,
`ScoreExplanation`, `ImportBatch`, `StagedProposal`, `WarningList`,
`CorrelationCandidate`, `FeedScorecard`. All are human-readable typed
records — no latent representations — consistent with ZettelForge's explicit
memory model. Storage follows the RFC-016 precedent: rows in the existing
`kg_nodes`/`kg_edges` + new dedicated tables in `sqlite_backend.py`, with
ontology-level validation rather than per-type table proliferation.

## 11. MCP tool additions

Proposed tool surface (final names at implementation; registry doc updated
in the same PR per E-FR-025):

| Tool | Purpose |
|---|---|
| `zettelforge_enrich` | Single/batch IoC enrichment (§5). |
| `zettelforge_pivot` | Bounded subgraph exploration (§6); supersedes the current minimal `zettelforge_graph` payload for analyst use. |
| `zettelforge_score_explain` | Score + explanation payload for an indicator (§7.4). |
| `zettelforge_sighting_add` | Ingest a sighting record (§7.3). |
| `zettelforge_warninglist_check` | On-demand warning-list lookup (§8). |
| `zettelforge_import_freetext` | Span-anchored extraction into staging (§8). |
| `zettelforge_batch` | Staging batch operations: status, commit, revert (§8). |

## 12. Success criteria and kill criteria (engine-testable subset)

| ID | Criterion |
|---|---|
| SC-1 | Zero fabrication: an automated provenance audit over the enrichment eval set resolves 100% of emitted assertions to stored objects. Any miss fails the build. |
| SC-2 | Explicit absence: 100% of unknown-entity eval cases across all read tools return the structured `known: false` shape with zero synthesized content. |
| SC-3 | Determinism: ≥10 repeated identical graph queries against a fixed corpus snapshot produce byte-identical payloads in CI. |
| SC-4 | Decay correctness: computed scores match the closed form within 1e-6 across the type-parameter fixture matrix; expiry leaves the export evaluation within one refresh cycle. |
| SC-8 | Span grounding: 100% of committed free-text-derived objects carry spans that exact-match their source documents. Zero unanchored commits. |
| SC-9 | Item conservation: for the seeded import fixture, input count equals committed count plus audited exclusions and flags. Zero silent drops; every exclusion names its gate. |
| SC-10 | Batch reversibility: reverting the seeded batch restores the pre-import corpus diff-clean, and the revert is audited. |
| SC-11 | Normalization unity: import-path and query-path canonicalization produce byte-equal output across the shared property-test corpus. |
| SC-12 | Correlation discipline: 100% of correlation candidates carry method tag, score, and evidence refs; zero relationships created by associative similarity without a recorded promotion. |
| KC-1 | If transitive inference (depth ≥ 2 enrichment) is not backed by a real inference layer, E-FR-006 beyond depth 1 is cut and re-scoped as its own feature — not emulated with ad hoc application-side joins. |

## 13. Open questions

1. **Inference layer status** — is transitive enrichment (E-FR-006) backed
   by anything real today? Blocks depth ≥ 2 work; KC-1 applies.
2. **Open-core placement** — which of the §11 tools ship in ZettelForge OSS
   vs the SaaS layer. Blocks public-repo code for the affected FRs.
3. **Decay kernel** — exponential default vs MISP-compatible polynomial vs
   both selectable; and whether the kernel is shared with outcome-prior time
   decay elsewhere.
4. **Half-life defaults** (§7.2 values are proposals).
5. **Confidence scale** — STIX 2.1 integer 0–100 everywhere, or admiralty
   coding surfaced with 0–100 underneath. One scale in the data model.
6. **ATT&CK version pin and upgrade policy**, including deprecated and
   remapped technique IDs.
7. **Graph bound defaults** (proposed: depth 3, 500 nodes, 2000 edges) and
   batch ceiling (proposed: 100).
8. **Free-text import policy** — regex-only baseline vs LLM-assisted behind
   the span validator; which staged classes may auto-commit.
9. **Correlation promotion policy** — thresholds, whether an agent may
   auto-promote, per-caller overrides.
10. **Snapshot identifier mechanics** — write-generation counter (proposed)
    vs content hash; interaction with the JSONL backend.

## 14. Out of scope (TR-tagged in the source package)

- Tenant policy, RBAC, API auth, rate limits, and tenant-scoped audit
  configuration (E-FR-026, E-FR-029 policy half).
- Feed registry, connector framework, and scheduled feed pulling (E-FR-033):
  the engine consumes staged bytes; it does not fetch or schedule.
- SIRP adapters, outbound context push, inbound disposition mapping
  (E-FR-043, E-FR-044) — these terminate in `zettelforge_sighting_add`.
- Tenant sector profiles and relevance flags (E-FR-046).
- UI rendering of subgraph payloads (E-FR-015) beyond the payload contract.
- Export destinations and formats other than the STIX 2.1 bundle (E-FR-014).
- Query-time external enrichment (VirusTotal/Shodan lookups) — violates the
  query-plane rule, permanently.
- Retrieval-ranking changes — the decay kernel governs indicator lifecycle
  and export eligibility, not result ordering.

## 15. Phases and file changes

| Phase | Scope | Files |
|---|---|---|
| 1 | Normalization module + ipv6 (#47) + defang corpus; enrichment tool with explicit-absence and provenance enforcement; fabrication/absence CI harness (SC-1, SC-2). | `normalization.py` (new), `entity_indexer.py`, `enrichment.py` (new), `mcp/server.py`, tests |
| 2 | Subgraph payload: bounds, deterministic ordering, cursor, cycle safety, ATT&CK overlay, STIX bundle export; snapshot identifier in backends (SC-3). | `graph_payload.py` (new), `knowledge_graph.py`, `sqlite_backend.py`, `memory_store.py`, tests |
| 3 | Sighting store, decay engine, score explanation, export-gate evaluator with fixed ordering (SC-4). | `scoring.py` (new), `sqlite_backend.py`, `mcp/server.py`, tests |
| 4 | Staging/batch store with revert; free-text importer + span validator; dedup; warning lists; correlation candidates (SC-8 – SC-12). | `staging.py` (new), `freetext_import.py` (new), `warninglists.py` (new), `sqlite_backend.py`, `mcp/server.py`, tests |

Phases 1–3 (the read side) ship value standalone against a manually loaded
corpus; phase 4 follows without rework because the §4 normalization and §7.3
sighting contracts are fixed here first.

## 16. Backward compatibility

- No changes to existing note, KG, or MCP tool schemas; all additions are
  new tools, new tables, and new payloads.
- The existing `zettelforge_graph` tool remains; `zettelforge_pivot` is
  additive until a deprecation decision is made separately.
- All new subsystems are independently disableable (constitution gate 5
  analogue): decay falls back to raw base confidence with expiry only;
  transitive enrichment disables to depth 1; correlation candidates and
  warning lists are optional stages in the commit pipeline.
