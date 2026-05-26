# RFC-017: MemSAD-Inspired Write-Time Memory Defenses

**Status:** Proposed  
**Date:** 2026-05-26  
**Related brief:** `/home/rolandpg/research/briefs/2026-05-25-SEC-011-memsad.md`  
**Scope:** Community repository `rolandpg/zettelforge`, local checkout, and GitHub repository controls

## Summary

SEC-011 identifies the highest-risk gap as absent write-time anomaly detection for
ZettelForge memory and entity ingestion. The current write path validates size and
optional PII, then constructs a note, writes it, indexes its vector, extracts
entities, and writes entity mappings. There is no calibrated anomaly gate before
the note becomes retrievable.

This RFC proposes a composite memory-write defense:

1. A MemSAD-style similarity anomaly scorer against a trusted calibration set.
2. A lexical drift scorer using character n-gram Jensen-Shannon divergence to
   reduce synonym/paraphrase evasion.
3. Source provenance and trust gates before high-impact CTI writes are indexed.
4. A quarantine path that preserves forensic evidence without exposing rejected
   content to recall, entity lookup, or graph traversal.
5. Repository and web hardening items that close the immediately visible control
   gaps found during the evaluation.

The first implementation should ship in dry-run/audit mode, then move to
enforced quarantine once a trusted calibration corpus is available.

## Evaluation Findings

### Local Project

- The direct `remember()` write path has no anomaly gate between governance
  validation and persistence. The note is constructed at
  `src/zettelforge/memory_manager.py:288`, written at
  `src/zettelforge/memory_manager.py:293`, added to the in-memory entity index
  at `src/zettelforge/memory_manager.py:314`, and persisted to the SQLite entity
  index at `src/zettelforge/memory_manager.py:319`.
- Entity extraction is deterministic regex plus optional LLM NER, but the
  extracted entity set is trusted once produced. `EntityExtractor.extract_all()`
  starts at `src/zettelforge/entity_indexer.py:340`; it normalizes strings but
  does not score entity-write risk.
- Existing governance covers structural validation, content length, and optional
  PII redaction/blocking, but not memory poisoning. The governance config
  currently has PII and limits only in `src/zettelforge/config.py:205`.
- Audit logging exists for authorization/API/file events, but there is no memory
  anomaly event class or quarantine audit record.
- The web API has an API-key guard and rate limiting in `web/app.py:156`, but
  several exception handlers return `str(e)` to clients. GitHub CodeQL reports
  11 open medium `py/stack-trace-exposure` alerts in `web/app.py`.
- MCP stdio is local-process scoped, but tool calls do not enforce the same
  input length, `k`, or synthesis format constraints as the web API.

### GitHub Repository

Observed via GitHub API on 2026-05-26:

- Repository is public, default branch is `master`, and the current user has
  admin permissions.
- Branch protection on `master` is enabled with strict required checks:
  `lint`, `test (3.12)`, `test (3.13)`, `governance`, and `build`.
- Admin enforcement, linear history, conversation resolution, no force pushes,
  and no deletions are enabled.
- Required approving review count is `1`, but code owner reviews and stale review
  dismissal are disabled.
- Dependabot alerts and secret-scanning alerts are currently empty.
- Code scanning default setup is configured, but open CodeQL alerts remain.
- Repository Actions allow all actions and `sha_pinning_required` is false.
  Most local workflows pin action SHAs, but `.github/workflows/stale.yml` uses
  `actions/stale@v9`, so the `SECURITY.md` claim that all third-party actions
  are SHA-pinned is not fully true.
- `pip-audit` and Snyk jobs exist, but branch protection does not require
  `pip-audit` or `Snyk Security`.
- Open PR #146 addresses unrelated P0 hardening for LLM budgets, bulk ingest,
  and CCCS regexes. There is no open MemSAD/anomaly-filter issue or PR.

## Threat Model

The cross-mission chain in SEC-011 is:

```text
Memory poisoning -> entity stored without write-time filtering ->
triggered CTI recall -> poisoned context steers tool/action selection ->
downstream exfiltration or false intelligence
```

The defense objective is to break the chain before the poison is indexed. A
rejected or quarantined write must not be present in:

- vector retrieval,
- entity index lookup,
- knowledge graph traversal,
- synthesis context,
- neighbor evolution or supersession decisions.

## Design

### 1. Memory Write Assessment

Add `src/zettelforge/memory_security.py` with these core types:

- `MemoryWriteAssessment`
  - `decision`: `allow`, `audit`, `quarantine`, or `reject`
  - `risk_score`
  - `memsad_score`
  - `lexical_drift_score`
  - `source_trust_score`
  - `reasons`
  - `calibration_version`
- `MemoryWriteFilter`
  - `assess(content, note, entities, domain, source_type, source_ref)`
  - `record_decision(assessment, note_id=None)`

The filter should be called after in-memory note construction and entity
extraction, but before `store.write_note()`, LanceDB indexing, entity indexing,
KG updates, supersession, and enrichment dispatch.

### 2. MemSAD-Style Similarity Score

For a candidate content embedding `E(c)` and trusted domain history `H`:

```text
s_comb(c; H) = 0.5 * max cos(E(c), E(q)) + 0.5 * mean cos(E(c), E(q))
```

Initial threshold:

```text
tau = mean(reference_scores) + kappa * stddev(reference_scores)
```

Default `kappa` should be `2.0` in audit mode. Enforcement should not be enabled
until at least 50 trusted calibration entries exist for the target domain.

### 3. Lexical Drift Scorer

Pure embedding defenses are weak against discrete synonym substitution. Add a
second feature family:

- character 3-gram and 4-gram distributions,
- Jensen-Shannon divergence against the nearest trusted neighbors,
- optional token-level Jaccard/containment features,
- suspicious instruction phrases such as "ignore previous", "system prompt",
  "tool call", "exfiltrate", and "secret".

This scorer should not be used as a standalone reject rule at first. It should
raise the composite score, add reasons, and help prioritize quarantine review.

### 4. Provenance Gates

Add source-aware policy before high-impact CTI writes:

- `source_type` must be present and normalized.
- `source_ref` is required for `domain="cti"` unless explicitly disabled.
- `evolve=True` writes should require provenance above a configurable trust
  floor before they supersede existing notes.
- Bulk ingest from YARA/Sigma/OpenCTI can be allowlisted by source type but
  should still be scored.

### 5. Quarantine Store

Add SQLite tables through the storage backend:

```sql
CREATE TABLE IF NOT EXISTS memory_write_assessments (
    assessment_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    note_id TEXT,
    domain TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT DEFAULT '',
    decision TEXT NOT NULL,
    risk_score REAL NOT NULL,
    memsad_score REAL,
    lexical_drift_score REAL,
    source_trust_score REAL,
    calibration_version TEXT DEFAULT '',
    reasons TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS memory_quarantine (
    quarantine_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    content_raw TEXT NOT NULL,
    domain TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT DEFAULT '',
    assessment_id TEXT NOT NULL
);
```

Quarantined content is evidence, not memory. It must not be written to the
`notes`, `entity_index`, `kg_nodes`, `kg_edges`, or LanceDB tables.

### 6. Configuration

Add a nested config section:

```yaml
security:
  memory_filter:
    enabled: true
    mode: audit        # off | audit | quarantine | reject
    min_calibration_entries: 50
    kappa: 2.0
    calibration_window: 500
    require_cti_source_ref: true
    quarantine_on_high_risk: true
    lexical_ngram_sizes: [3, 4]
    max_quarantine_content_length: 50000
```

Environment overrides should mirror existing config style:

- `ZETTELFORGE_MEMORY_FILTER_ENABLED`
- `ZETTELFORGE_MEMORY_FILTER_MODE`
- `ZETTELFORGE_MEMORY_FILTER_KAPPA`
- `ZETTELFORGE_MEMORY_FILTER_MIN_CALIBRATION`

### 7. Audit Logging

Add OCSF-compatible memory anomaly events. Minimum fields:

- `operation="memory_write_assessment"`
- `request_id`
- `note_id` when allowed
- `assessment_id`
- `decision`
- `risk_score`
- `reasons`
- `domain`
- `source_type`
- `source_ref_hash` instead of full source ref when sensitive

The web API should expose aggregate counts only by default. Raw quarantine
content should require an authenticated admin route or remain CLI-only in
Community edition.

## Implementation Plan

### Phase 0: Close Existing Control Gaps

1. Fix the 11 open CodeQL `py/stack-trace-exposure` findings in `web/app.py` by
   returning generic client errors and logging details server-side.
2. Add a FastAPI global exception handler so future routes do not reintroduce
   `{"error": str(e)}` responses.
3. Align `SECURITY.md` and `.github/SECURITY.md` into one current policy.
4. Pin `actions/stale` by SHA or restrict repository Actions to selected
   pinned actions.
5. Add branch-protection required checks for `pip-audit` and the Snyk workflow
   once the Snyk token is present.
6. Decide whether open PR #146 should merge first. It is not a dependency for
   MemSAD, but it touches ingestion behavior and may reduce merge conflicts.

Acceptance:

- Code scanning open alerts for `web/app.py` are zero.
- Branch protection includes all security gates that are expected to block.
- Security policy no longer claims controls that are not enforced.

### Phase 1: Dry-Run Memory Filter

1. Add config dataclasses and env overrides for `security.memory_filter`.
2. Add `MemoryWriteFilter` and pure scorer functions with deterministic unit
   tests.
3. Add storage methods for `memory_write_assessments`.
4. Wire assessment into `MemoryManager._remember_inner()` before persistence,
   but keep `mode=audit` as default.
5. Emit audit events for every write assessment.

Acceptance:

- `remember()` still stores notes in audit mode.
- Every direct write produces one assessment record and one audit event.
- Tests cover empty calibration, exactly 50 calibration entries, and
  over-threshold scoring.

### Phase 2: Quarantine Enforcement

1. Add `memory_quarantine` storage methods.
2. In `mode=quarantine`, prevent high-risk writes from reaching note/vector/
   entity/KG stores.
3. Return a structured status such as `("quarantined")` without leaking raw
   scorer internals to unauthenticated clients.
4. Update web and MCP handlers to surface quarantine safely.

Acceptance:

- Quarantined notes are absent from `recall()`, `recall_entity()`,
  `traverse_graph()`, and `synthesize()`.
- Quarantine writes preserve content and assessment metadata for review.
- Regression tests prove the enrichment worker is not dispatched for
  quarantined content.

### Phase 3: Entity and Evolution Hardening

1. Score both raw content and extracted entity set deltas.
2. Add entity-count, rare-entity, and suspicious-relationship heuristics.
3. Add provenance gates to `MemoryUpdater.apply()` so LLM-decided update/delete
   operations cannot supersede trusted notes from untrusted sources.
4. Add source trust metadata to notes or assessment records for downstream
   policy.

Acceptance:

- High-risk entities can be filtered before `add_entity_mapping()`.
- Untrusted evolved facts cannot supersede a trusted note without explicit
  policy.
- Tests cover poisoning attempts through direct remember, evolve, bulk ingest,
  and MCP.

### Phase 4: Calibration Management

1. Add CLI commands:
   - `zettelforge security calibrate --domain cti --trusted-source <selector>`
   - `zettelforge security status`
   - `zettelforge security quarantine list/show/release/reject`
2. Seed calibration from explicit trusted notes only, never from arbitrary first
   writes.
3. Add rolling calibration that only admits allowed, non-quarantined,
   provenance-sufficient notes.
4. Store `calibration_version` on assessments.

Acceptance:

- New deployments remain audit-only until calibration is sufficient.
- Recalibration is reproducible and logged.
- Releasing a quarantined note re-assesses it against the current calibration
  version before indexing.

### Phase 5: Operational Logging and Repo Controls

1. Add optional audit-log HMAC chaining or document external log shipping as the
   supported tamper-evidence path.
2. Add a SIEM/syslog export guide for `~/.amem/logs/audit.log`.
3. Require CodeQL, Snyk, pip-audit, tests, and governance gates in branch
   protection.
4. Enable code owner reviews for `.github/**`, `src/zettelforge/config.py`,
   `src/zettelforge/memory_manager.py`, `src/zettelforge/entity_indexer.py`,
   storage backends, and security modules.

Acceptance:

- Security-sensitive code paths require CODEOWNER review or documented
  solo-maintainer compensating control.
- Audit events can be shipped off-machine.
- The repository control docs match GitHub settings.

## Test Strategy

Add focused tests before broad end-to-end coverage:

- `tests/test_memory_write_filter.py`
  - cosine score math,
  - threshold calculation,
  - insufficient calibration fallback,
  - lexical n-gram JSD,
  - composite decision ordering.
- `tests/test_memory_quarantine.py`
  - quarantined content is not retrievable,
  - no entity mappings or KG edges are written,
  - assessment and quarantine records are present.
- `tests/test_memory_filter_integration.py`
  - direct `remember()`,
  - `remember(evolve=True)`,
  - MCP tool call,
  - web `/api/remember` and `/api/ingest`.
- `tests/test_web_api.py`
  - generic 500 responses,
  - no `str(e)` leakage,
  - quarantine status shape.
- Governance drift test update:
  - add new runtime controls for memory anomaly filtering and quarantine audit.

## Rollout

1. Default `mode=off` for one patch release if compatibility risk is high, or
   `mode=audit` if telemetry volume is acceptable.
2. Dogfood on the maintainer CTI corpus with `mode=audit`, `kappa=2.0`,
   `min_calibration_entries=50`.
3. Review false positives and tune lexical/composite weights.
4. Switch CTI deployments to `mode=quarantine`.
5. Keep `mode=reject` reserved for highly controlled sources after observed
   false-positive rates are acceptable.

## Non-Goals

- Proving a complete defense against all synonym/paraphrase attacks.
- Replacing OS-level filesystem protection or encryption at rest.
- Multi-tenant authorization in Community edition.
- Off-machine log infrastructure in the first code PR.

## Immediate Backlog

1. `fix(web): sanitize API error responses and close CodeQL alerts`
2. `chore(ci): require pip-audit/Snyk and pin stale action`
3. `feat(security): add memory write assessment dry-run mode`
4. `feat(security): add quarantine storage and enforcement`
5. `feat(security): add entity/evolution provenance gates`
6. `docs(security): document calibration, quarantine review, and log shipping`

