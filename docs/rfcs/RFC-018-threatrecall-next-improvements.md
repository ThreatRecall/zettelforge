# RFC-018: ThreatRecall Next Improvements After Recall Hardening

**Status:** Proposed  
**Date:** 2026-06-24  
**Target:** Build, release, and push the RFC-018 release train
**Related fixes:** Unreleased `MemoryManager.flush()` wait semantics, concurrent Plyara parsing serialization, CCCS YARA metadata validation hardening, and LLM generation budget controls.

## Summary

The latest ThreatRecall hardening work closed two classes of production risk:

1. **Deferred enrichment completion was ambiguous.** `MemoryManager.flush()` now waits for queued and in-flight enrichment work, and concurrent YARA parsing no longer races on the cached `Plyara` parser.
2. **Detection-rule ingestion accepted unsafe metadata shapes.** CCCS YARA metadata validation now detects multiline regex injection and overly permissive author values. The default YARA ingest tier still warns and accepts the rule for compatibility; strict mode rejects invalid required fields.

This RFC converts those fixes into the next improvement-and-release plan. The goal is to move from point fixes to a predictable ingestion-and-recall control plane and then ship it as a controlled release train: durable enrichment jobs, parser isolation, shared metadata policy, operator-visible health, regression gates that prove the fixed behavior stays fixed, and explicit build/push steps for new package, container, docs, and hosted ThreatRecall releases.

## Motivation

ThreatRecall's most important user promise is that remembered intelligence becomes safely retrievable. The recent fixes improved that promise, but they also exposed follow-up gaps:

- `flush()` can now wait correctly, but enrichment job state is still mostly implicit and process-local.
- Parser serialization prevents a known race, but parser safety is not expressed as a reusable contract for Sigma, YARA, OSINT, and future importers.
- CCCS YARA metadata is now measurable and strict-mode enforceable, but the default warn tier still accepts invalid metadata and policy is not yet centralized across detection-rule formats.
- Operators still need to infer ingestion health from tests or logs instead of a first-class dashboard/API contract.
- LLM budget floors and JSON parse stripping reduce runaway generation failures, but recall quality still needs budget-aware telemetry and release gates.

## Goals

1. Make deferred enrichment durable, observable, and replayable.
2. Turn parser and metadata hardening into shared ingestion contracts.
3. Expose ThreatRecall ingestion health in APIs, telemetry, and the web UI.
4. Add regression tests and benchmarks that specifically cover the recently fixed failures.
5. Preserve existing public APIs unless a new optional status endpoint is required.
6. Build and push signed release artifacts for each RFC-018 milestone.
7. Publish operator-facing release notes that explain migration, rollback, and health-check expectations.

## Non-goals

- No new hosted-only ThreatRecall dependency in the community package.
- No change to the default storage backend selection.
- No semantic change to `recall()` ranking in this RFC.
- No additional LLM provider work beyond using existing generation-budget controls.
- No forced hosted ThreatRecall rollout before community artifacts and rollback checks pass.

## Proposed work

### 1. Durable enrichment job ledger

Add a storage-backed ledger for deferred enrichment jobs. Each job records:

| Field | Description |
|---|---|
| `job_id` | Stable UUID generated when work is enqueued. |
| `note_id` | Memory note or detection rule identifier. |
| `job_type` | `llm_ner`, `fact_extraction`, `causal_extraction`, `neighbor_evolution`, `rule_entity_extraction`, or `index_repair`. |
| `state` | `queued`, `running`, `succeeded`, `failed`, `dead_lettered`, `cancelled`. |
| `attempt_count` | Retry count with bounded backoff. |
| `last_error_code` | Redacted machine-readable error category. |
| `created_at`, `started_at`, `finished_at` | Timestamps for latency and stuck-job detection. |

`MemoryManager.flush()` should become a ledger-aware barrier: it returns `True` only when all jobs known at barrier start have reached a terminal state and keeps returning `False` on timeout to preserve the current public contract. The ledger makes the barrier restart-aware only when paired with a startup/reaper contract that leases jobs or requeues stale `running` rows after a process crash.

### 2. Parser isolation contract

Introduce a small `ParserAdapter` contract for ingestion parsers:

```python
class ParserAdapter(Protocol):
    name: str
    thread_safe: bool

    def parse(self, payload: str) -> ParsedArtifact: ...
```

Adapters with `thread_safe=False` must be wrapped by a per-adapter lock or process-isolated worker before concurrent ingestion can call them. The cached `Plyara` serialization fix becomes the first implementation, not a one-off exception.

Acceptance criteria:

- Concurrent YARA bulk ingest remains deterministic under high thread counts.
- Parser locks are scoped by parser type, not global across all ingestion.
- Tests verify no parser adapter can be registered without an explicit thread-safety declaration.

### 3. Shared detection metadata policy

Create a reusable metadata-policy layer used by YARA, Sigma, and future detection-rule ingesters. Policy checks should include:

- Single-line constraints for fields rendered into prompts, dashboards, and generated explanations.
- Author/source allowlists or deny-patterns for high-risk metadata fields.
- Maximum length per metadata field.
- Normalized violation codes, for example `metadata.multiline`, `metadata.author.invalid`, and `metadata.too_long`.

CCCS YARA validation remains a specific profile in this layer. Sigma should initially run in audit mode so existing rule corpora are not blocked without measurement.

### 4. Enrichment and parser health API

Add a read-only health endpoint for local UI and operators:

```http
GET /api/enrichment/health
```

Response shape:

```json
{
  "queued": 0,
  "running": 0,
  "succeeded_24h": 128,
  "failed_24h": 2,
  "dead_lettered": 0,
  "oldest_running_age_seconds": 0,
  "parser_locks": {
    "yara.plyara": {"waiting": 0, "held": false}
  }
}
```

The endpoint must use the same authentication and rate-limit posture as existing local APIs. It must not expose raw exception strings or rule contents.

### 5. Budget-aware recall and enrichment telemetry

Extend telemetry events with bounded, non-sensitive fields:

- `generation_budget_name`
- `generation_budget_tokens`
- `json_repair_applied`
- `deferred_enrichment_pending_at_recall`
- `enrichment_barrier_wait_ms`
- `parser_wait_ms`

These fields let operators answer whether a recall miss happened because content was not enriched yet, a parser was serialized under load, or an LLM output was repaired/truncated.

### 6. Regression suite and release gates

Add tests that reproduce the fixed failure classes and prove the follow-up controls:

1. `flush()` waits for jobs that are already running before the call begins.
2. `flush(timeout=...)` preserves the current `False` timeout return while leaving unfinished work visible in the ledger.
3. Concurrent YARA ingestion produces stable entity counts across repeated runs.
4. CCCS metadata rejects multiline injection and invalid author values with stable violation codes.
5. Sigma metadata audit mode records violations but does not block ingestion.
6. `/api/enrichment/health` redacts exception text and reports ledger counts.
7. Telemetry correlates recall misses with pending enrichment counts.


### 7. Build and push release train

RFC-018 should ship as a sequence of small releases rather than one large drop. Each release must be buildable, taggable, and rollback-safe.

| Release | Scope | Required artifacts | Push target | Rollback trigger |
|---|---|---|---|---|
| `v2.8.0-alpha.1` | Ledger schema, no-op telemetry fields, parser registry skeleton. | Python wheel/sdist, docs preview, container image. | TestPyPI or internal package index, staging container registry, preview docs. | Migration failure, import regression, or ledger write overhead above threshold. |
| `v2.8.0-beta.1` | Ledger-backed `flush()`, stale-job recovery, parser isolation, YARA metadata-policy migration. | Wheel/sdist, staging image, benchmark report, SBOM. | Staging package registry and staging ThreatRecall deployment. | `flush()` timeout regressions, stale-running jobs after restart, parser contention p95 breach, or metadata false-positive spike. |
| `v2.8.0-rc.1` | Health API, telemetry fields, web UI panel, Sigma audit mode. | Release candidate wheel/sdist, Docker image, docs site, signed tag. | Public pre-release, staging docs, staging hosted release. | Health endpoint leakage, auth/rate-limit regression, or telemetry cardinality violation. |
| `v2.8.0` | General availability after soak. | Final wheel/sdist, Docker image, docs, changelog, signed provenance/SBOM. | PyPI, production container registry, production docs, hosted ThreatRecall rollout. | Any P0/P1 regression or failed smoke test during progressive rollout. |

Build commands should be codified in release automation instead of run manually. Minimum release pipeline steps:

1. Verify version and changelog are consistent.
2. Run unit, integration, governance, web API, and RFC-018 regression suites.
3. Run the deferred-enrichment stress benchmark and publish its report.
4. Build Python wheel and source distribution.
5. Build the Docker image by immutable commit SHA and record the image digest.
6. Generate SBOM and provenance metadata.
7. Push artifacts to staging first, run smoke tests, then promote the verified digest to public targets.
8. Create the signed release tag only after artifacts and docs are reproducible, or retag/promote the already-verified commit digest without rebuilding.
9. Roll out hosted ThreatRecall progressively by environment and tenant cohort.
10. Publish release notes with known risks, rollback instructions, and health-check commands.

## Rollout plan

### Phase 0: Specification and instrumentation

- Land this RFC.
- Add ledger schema and no-op telemetry fields behind defaults.
- Keep existing in-memory behavior as fallback for non-SQLite stores.
- Build and push `v2.8.0-alpha.1` to staging targets only. Do not publish alpha GitHub releases through the current PyPI workflow unless `publish.yml` is first guarded to exclude prerelease tags or route them to TestPyPI/internal indices.

### Phase 1: Durable ledger and barrier semantics

- Persist enrichment jobs.
- Make `flush()` ledger-aware.
- Add dead-letter handling, stale-running job recovery, and operator-facing error codes.
- Keep beta blocked until Phase 2 parser isolation and YARA policy migration are also complete.

### Phase 2: Parser and metadata policy consolidation

- Add `ParserAdapter` and parser registry.
- Move CCCS YARA rules into shared metadata policy.
- Add Sigma audit-mode metadata checks.
- Build and push `v2.8.0-beta.1` after ledger migrations, stale-job recovery, parser isolation, metadata-policy migration, and stress benchmarks pass.

### Phase 3: Operator visibility

- Ship `/api/enrichment/health`.
- Add web UI health panel and telemetry dashboard fields.
- Document troubleshooting workflows for stuck enrichment and parser contention.
- Build and push `v2.8.0-rc.1` after API redaction, auth, and UI smoke tests pass.

### Phase 4: Release gates

- Require the new regression suite in CI.
- Add a small stress benchmark for bulk YARA/Sigma ingestion with deferred enrichment enabled.
- Publish pass/fail thresholds in release notes.
- Build and push `v2.8.0` GA only after staging soak, artifact verification, and hosted ThreatRecall canary checks pass.

## Release readiness checklist

Before each RFC-018 release is pushed, release owners must verify:

- Version, changelog, and RFC status are aligned.
- `git tag -s` or equivalent signed-tag policy is available for the release candidate.
- Wheel, sdist, container image, SBOM, and docs are generated from the same commit.
- Staging install succeeds from pushed artifacts, not from the local checkout.
- `/api/enrichment/health` returns healthy counts after a sample deferred-enrichment ingest.
- Rollback has been tested against the previous stable release.
- Hosted ThreatRecall canary rollout has an owner, abort threshold, and communication plan.

## Compatibility

- Existing callers of `remember()`, `remember_report()`, `flush()`, and `recall()` keep working.
- `flush()` keeps returning `True` on completion and `False` on timeout. Any richer result object must use a new versioned API rather than changing this return contract.
- New API fields are additive.
- Pre-release builds must use semver-compatible identifiers so downstream deployments can pin or avoid them.
- Metadata policy starts with YARA enforcement where the fix already exists and Sigma audit mode for compatibility.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Ledger adds write overhead to high-volume ingestion. | Batch job-state updates and keep payloads out of the ledger. |
| Parser locks reduce throughput. | Lock only non-thread-safe adapters and expose wait metrics. |
| Metadata policy blocks legitimate legacy rules. | Enforce only known-fixed CCCS YARA profile first; run other profiles in audit mode. |
| Health API leaks sensitive data. | Return counts and redacted error codes only. |
| Telemetry cardinality grows too high. | Use bounded enums and booleans, never raw prompts or rule bodies. |
| Release artifacts diverge from the tested commit. | Generate artifacts, docs, SBOM, and tags from a single immutable commit. |
| Hosted rollout exposes tenants to unproven behavior. | Use alpha/beta/RC staging releases, canaries, and explicit rollback triggers before GA. |

## Open questions

1. Should the enrichment ledger live in the existing SQLite backend only first, or should JSONL get a minimal append-only implementation for parity?
2. Should `flush()` expose a new `FlushResult` immediately, or should that wait until a major version?
3. Which Sigma metadata fields should move from audit to enforce first?
4. Should parser isolation eventually support process pools for parsers with native-library global state?
5. Should RFC-018 publish alpha/beta/RC artifacts publicly or keep alpha builds on an internal index until ledger migrations stabilize?
6. Which release promotion gates should be mandatory branch-protection checks?

## Definition of done

- Operators can see whether deferred enrichment is queued, running, failed, or dead-lettered.
- A process restart does not lose knowledge of unfinished deferred enrichment jobs.
- Non-thread-safe parsers cannot be used concurrently without an explicit guard.
- CCCS YARA hardening is represented as reusable metadata policy.
- The regression suite covers the exact classes of issues fixed in the latest ThreatRecall hardening pass.
- Alpha, beta, release-candidate, and GA artifacts are built from immutable commits and pushed through staging before public or hosted promotion.
