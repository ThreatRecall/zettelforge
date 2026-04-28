# PRD: GOV-012 Logging & Observability Compliance

## Introduction

ZettelForge's current logging implementation uses 16 bare `print()` calls across 7 source files, has 30 silent `except Exception` blocks that swallow errors, and does not emit structured or OCSF-formatted log events. The `Observability` class exists but is only wired into `retry.py` — none of the core memory operations (`remember`, `recall`, `synthesize`) use it.

This deviates from GOV-012 (Observability and Logging Standards), GOV-003 (Python Coding Standards), and the FedRAMP Moderate control families AU-2, AU-3, AU-6, AU-8, and AU-12 as mapped in GOV-019. The silent exception swallowing pattern was the direct root cause of issue #26 (LanceDB single-row bug), where indexing failures went undetected for weeks.

This PRD scopes the work to bring ZettelForge into full GOV-012 compliance for logging and audit trails. Metrics (Prometheus) and distributed tracing (OpenTelemetry) are out of scope but noted for a follow-on effort.

## Goals

- Eliminate all `print()` usage in production code, replacing with `structlog` structured JSON logging per GOV-003 and GOV-012
- Emit OCSF-schema events for all auditable operations across all GOV-012 event classes
- Replace all silent `except Exception: print/pass` blocks with proper error propagation and structured error logging
- Write structured logs to local files with rotation, formatted for future SIEM ingestion (Sentinel, OpenSearch)
- Satisfy FedRAMP AU-2 (auditable events defined), AU-3 (required fields present), AU-8 (UTC timestamps), and AU-12 (audit generation in all components)

## User Stories

### US-001: Replace logging infrastructure with structlog

**Description:** As a developer, I need a shared structured logging configuration so that all components emit consistent JSON log output per GOV-003 and GOV-012.

**Acceptance Criteria:**
- [ ] `structlog` added to project dependencies (`pyproject.toml`)
- [ ] New module `src/zettelforge/log.py` provides `configure_logging()` and `get_logger(name)` functions
- [ ] `configure_logging()` sets up structlog with processors: `merge_contextvars`, `add_log_level`, `TimeStamper(fmt="iso", utc=True, key="time")`, `StackInfoRenderer`, `format_exc_info`, `JSONRenderer`
- [ ] Log output goes to both stdout (for container environments) and a rotating file at `{data_dir}/logs/zettelforge.log`
- [ ] File rotation: 10 MB max size, 9 backup files (approx 90 days at typical volume)
- [ ] `LoggingConfig` in `config.py` gains `log_file` (path, default `{data_dir}/logs/zettelforge.log`) and `log_to_stdout` (bool, default `True`) fields
- [ ] Existing `logging.basicConfig` call in `observability.py` is removed
- [ ] All tests pass, typecheck passes

### US-002: Define OCSF event emitters for all GOV-012 event classes

**Description:** As a compliance auditor, I need all security-relevant events emitted in OCSF v1.3 schema so that log entries satisfy AU-3 (content of audit records) and are ingestible by any SIEM.

**Acceptance Criteria:**
- [ ] New module `src/zettelforge/ocsf.py` provides typed helper functions for each OCSF event class
- [ ] **API Activity (class_uid: 6002):** `log_api_activity(actor, operation, resource, status, duration_ms, **details)` — covers `remember`, `recall`, `synthesize`, `remember_report`, `remember_with_extraction`
- [ ] **Authentication (class_uid: 3001):** `log_authentication(actor, auth_protocol, status, src_endpoint)` — covers MCP server auth, API key validation
- [ ] **Authorization (class_uid: 3003):** `log_authorization(actor, privileges, resource, status, policy)` — covers governance validation decisions
- [ ] **Configuration Change (class_uid: 5002):** `log_config_change(actor, resource, prev_value, new_value, status)` — covers config.yaml changes, governance enable/disable
- [ ] **File Activity (class_uid: 1001):** `log_file_activity(actor, file_path, activity, status)` — covers JSONL writes, LanceDB table operations, index rebuilds
- [ ] **Process Activity (class_uid: 1007):** `log_process_activity(process_name, activity, status)` — covers service start/stop, rebuild script execution
- [ ] **Account Change (class_uid: 3005):** `log_account_change(actor, user, activity, prev_value, new_value)` — stub for future multi-tenant use
- [ ] Every emitter includes required OCSF base fields: `class_uid`, `class_name`, `category_uid`, `category_name`, `severity_id`, `severity`, `activity_id`, `activity_name`, `status_id`, `status`, `time` (UTC ISO 8601), `metadata.version` ("1.3.0"), `metadata.product.name` ("zettelforge"), `metadata.product.version` (from package)
- [ ] All tests pass, typecheck passes

### US-003: Instrument core memory operations

**Description:** As a developer debugging a recall failure, I need every `remember`, `recall`, and `synthesize` call to emit a structured log entry with timing, success/failure, and operation details so that I can trace what happened.

**Acceptance Criteria:**
- [ ] `MemoryManager.__init__` initializes a structlog logger via `get_logger("zettelforge.memory")`
- [ ] `remember()` emits OCSF API Activity event on entry (activity: "Create") and on completion/failure with `duration_ms`, `note_id`, `domain`, `status`
- [ ] `recall()` emits OCSF API Activity event with `query` (truncated to 200 chars), `domain`, `k`, `result_count`, `duration_ms`, `status`
- [ ] `synthesize()` emits OCSF API Activity event with `query`, `source_count`, `duration_ms`, `status`
- [ ] `remember_with_extraction()` and `remember_report()` emit their own events (not just delegating to `remember`)
- [ ] `recall_entity()`, `recall_cve()`, `recall_actor()`, `recall_tool()` emit events with the entity/identifier being searched
- [ ] All events include a `request_id` (UUID4, generated per call) for correlation
- [ ] Governance validation decisions (`GovernanceValidator.enforce()`) emit OCSF Authorization events (class 3003) with `status_id` 1 (allowed) or 2 (denied) and the specific rule that triggered
- [ ] All tests pass, typecheck passes

### US-004: Instrument LanceDB and vector operations

**Description:** As a developer, I need LanceDB indexing and vector retrieval operations to emit structured logs so that silent failures like issue #26 are immediately visible.

**Acceptance Criteria:**
- [ ] `_index_in_lance()` emits OCSF File Activity event (class 1001) with `table_name`, `note_id`, `activity` ("Create" or "Update"), `status`, `duration_ms`
- [ ] `_index_in_lance()` failure emits severity 4 (High) event, not silently swallowed
- [ ] `VectorRetriever._retrieve_via_lancedb()` emits event with `table_name`, `result_count`, `duration_ms`
- [ ] `VectorRetriever._retrieve_via_memory()` fallback emits severity 3 (Medium) event indicating LanceDB was bypassed
- [ ] `rebuild_index.py` emits Process Activity events (class 1007) for start, progress (every 500 notes), and completion with total counts
- [ ] All tests pass, typecheck passes

### US-005: Instrument entity extraction and knowledge graph operations

**Description:** As a developer, I need entity extraction, fact extraction, and knowledge graph operations logged so that pipeline failures are traceable.

**Acceptance Criteria:**
- [ ] `EntityExtractor.extract()` emits event with `note_id`, `entity_count`, `duration_ms`, `status`
- [ ] `FactExtractor.extract()` emits event with `note_id`, `triple_count`, `duration_ms`, `status`
- [ ] `NoteConstructor.construct()` emits event with `note_id`, `duration_ms`, `status`
- [ ] `KnowledgeGraph` operations (add_edge, query) emit events with `operation`, `entity_count`, `duration_ms`
- [ ] `IntentClassifier.classify()` emits event with `intent`, `confidence`, `duration_ms` (controlled by `logging.log_intents` config)
- [ ] Causal triple extraction emits event with `note_id`, `triple_count` (controlled by `logging.log_causal` config)
- [ ] All tests pass, typecheck passes

### US-006: Eliminate silent exception swallowing

**Description:** As a developer, I need all `except Exception: print/pass` blocks replaced with structured error logging and appropriate error propagation so that failures are never invisible.

**Acceptance Criteria:**
- [ ] All 30 `except Exception` blocks across 16 files are audited and categorized:
  - **Propagate:** Errors that should bubble up (e.g., `_index_in_lance`, `construct`, `extract`) — re-raise after logging
  - **Degrade gracefully:** Errors where fallback is correct (e.g., LanceDB unavailable, TypeDB fallback to JSONL) — log at severity 3 (Medium), continue with fallback
  - **Ignore safely:** Errors that are truly ignorable (e.g., optional cache warmup) — log at severity 2 (Low), continue
- [ ] Zero remaining `print()` calls in `src/zettelforge/` (all replaced with structlog)
- [ ] Every `except` block that catches `Exception` logs the full exception with `logger.exception()` or `logger.error(..., exc_info=True)`
- [ ] No bare `except Exception: pass` remains — each has at minimum a severity-appropriate log entry
- [ ] Files affected (30 blocks across 16 files):
  - `memory_store.py` (5 blocks)
  - `vector_retriever.py` (3 blocks)
  - `vector_memory.py` (3 blocks)
  - `note_constructor.py` (2 blocks)
  - `memory_manager.py` (3 blocks)
  - `entity_indexer.py` (2 blocks)
  - `llm_client.py` (2 blocks)
  - `fact_extractor.py` (1 block)
  - `intent_classifier.py` (1 block)
  - `config.py` (1 block)
  - `knowledge_graph.py` (1 block)
  - `alias_resolver.py` (2 blocks)
  - `memory_updater.py` (1 block)
  - `ontology.py` (1 block)
  - `retry.py` (1 block)
  - `observability.py` (1 block)
- [ ] All tests pass, typecheck passes

### US-007: Refactor Observability class

**Description:** As a developer, I need the existing `Observability` class updated to use structlog and OCSF emitters instead of its current ad-hoc implementation, so that the decorator and metrics tracking remain useful.

**Acceptance Criteria:**
- [ ] `Observability` class uses structlog logger from `log.py` instead of `logging.basicConfig`
- [ ] `log_operation()` delegates to appropriate OCSF emitter based on operation name
- [ ] `@timed_operation` decorator updated to emit OCSF events
- [ ] In-memory metrics counters retained for `/metrics` endpoint (future work)
- [ ] `retry.py` integration continues to work with updated `Observability`
- [ ] Remove the now-redundant `logging.basicConfig(level=logging.INFO)` global call
- [ ] All tests pass, typecheck passes

### US-008: Log file management and retention configuration

**Description:** As an operator, I need log files to rotate automatically and be configurable so that disk usage is bounded and logs are retained per compliance requirements.

**Acceptance Criteria:**
- [ ] Logs written to `{data_dir}/logs/zettelforge.log` by default
- [ ] `{data_dir}/logs/` directory created automatically on startup
- [ ] Rotation: `RotatingFileHandler` with 10 MB max, 9 backups
- [ ] Audit-critical events (OCSF classes 3001, 3003, 3005, 5002) additionally written to `{data_dir}/logs/audit.log` with separate rotation (10 MB, 52 backups for ~1 year retention per AU requirements)
- [ ] Config keys: `logging.log_file`, `logging.audit_log_file`, `logging.log_to_stdout`, `logging.max_bytes`, `logging.backup_count`
- [ ] All config keys documented in `config.default.yaml`
- [ ] All tests pass, typecheck passes

### US-009: Add logging compliance tests

**Description:** As a developer, I need automated tests that verify no `print()` usage exists in production code and that core operations emit required OCSF fields, so that compliance regressions are caught in CI.

**Acceptance Criteria:**
- [ ] Test: `test_no_print_in_production` — scans all `.py` files under `src/zettelforge/` and fails if any `print(` call is found (excluding `__main__` blocks and debug-only code)
- [ ] Test: `test_remember_emits_ocsf_event` — calls `remember()`, captures log output, verifies OCSF base fields present (`class_uid`, `time`, `status_id`, `metadata.product.name`)
- [ ] Test: `test_recall_emits_ocsf_event` — same for `recall()`
- [ ] Test: `test_synthesize_emits_ocsf_event` — same for `synthesize()`
- [ ] Test: `test_lance_failure_logged_not_swallowed` — forces a LanceDB error, verifies severity 4 log entry emitted (regression test for #26)
- [ ] Test: `test_governance_violation_emits_authorization_event` — triggers a governance violation, verifies OCSF class 3003 event with `status_id: 2`
- [ ] Test: `test_audit_log_separation` — verifies auth/authz/config-change events appear in audit log file
- [ ] All tests pass, typecheck passes

## Functional Requirements

- FR-1: All production Python code must use `structlog` for log output. Zero `print()` calls permitted in `src/zettelforge/`.
- FR-2: All log entries must be JSON-formatted with OCSF v1.3 base fields: `class_uid`, `class_name`, `category_uid`, `severity_id`, `time` (UTC ISO 8601), `status_id`, `metadata.product`.
- FR-3: The following OCSF event classes must be emitted:
  - 6002 (API Activity): all `remember`, `recall`, `synthesize` operations and their variants
  - 3001 (Authentication): MCP server connections, API key validation
  - 3003 (Authorization): governance validation allow/deny decisions
  - 5002 (Configuration Change): config.yaml changes, governance enable/disable
  - 1001 (File Activity): JSONL writes, LanceDB table create/add/drop, index rebuilds
  - 1007 (Process Activity): service start/stop, rebuild script execution
  - 3005 (Account Change): stub emitter for future multi-tenant support
- FR-4: Every `except Exception` block must log the exception at an appropriate OCSF severity level. No silent swallowing.
- FR-5: Errors in non-critical paths (LanceDB indexing, entity extraction fallbacks) must log at severity 3+ and continue. Errors in critical paths (JSONL write, governance enforcement) must log at severity 4+ and propagate.
- FR-6: Log output must go to a rotating local file (`zettelforge.log`, 10 MB x 10 files). Audit-critical events (classes 3001, 3003, 3005, 5002) must additionally go to `audit.log` (10 MB x 53 files, ~1 year).
- FR-7: Stdout logging must be enabled by default and disableable via config for headless/batch use.
- FR-8: A `request_id` (UUID4) must be generated per top-level operation and included in all log entries for that operation's lifecycle.
- FR-9: Log messages must use static templates with structured data in extra fields. No f-string interpolation in log messages per GOV-012.
- FR-10: Secrets, credentials, tokens, and PII must never appear in log output per GOV-012.

## Non-Goals (Out of Scope)

- **Prometheus metrics endpoint** — GOV-012 requires this, but it is deferred to a follow-on effort. The `Observability` class retains in-memory counters as a migration path. A separate PRD should address FR for `/metrics` endpoint, histogram instrumentation, and Grafana dashboard provisioning.
- **OpenTelemetry distributed tracing** — GOV-012 requires `request_id` propagation via `X-Request-ID` and `traceparent` headers for multi-service architectures. ZettelForge is currently single-process. The `request_id` field added here provides the correlation foundation; full OTel integration is deferred.
- **Log aggregation infrastructure** — Fluent Bit, OpenSearch, Sentinel integration. This PRD produces OCSF-formatted local files that are ready for ingestion; the collection pipeline is an infrastructure concern.
- **SIEM alert rules and dashboards** — Grafana/Sentinel alerting configuration. Deferred until log aggregation is in place.
- **Multi-tenant audit separation** — Account Change (3005) emitter is a stub. Full multi-tenant audit trails require the ThreatRecall SaaS auth layer (Clerk) to be in place.

## Technical Considerations

- **Dependency:** `structlog` must be added to `pyproject.toml` dependencies. It is a pure-Python package with no native extensions.
- **Backward compatibility:** The `Observability` class public API (`log_operation`, `get_metrics`, `record_cache_event`, `@timed_operation`) must remain stable. Internal implementation changes only.
- **Performance:** Structured logging adds ~0.1ms per log call. File I/O is buffered. No measurable impact on `remember`/`recall` latency (which are dominated by embedding computation at 50-200ms).
- **Testing:** Log capture in tests uses `structlog.testing.capture_logs()` context manager. No mocking of file I/O needed for unit tests.
- **Config migration:** New `logging.*` config keys are additive. Existing `logging.level`, `logging.log_intents`, `logging.log_causal` keys are preserved and honored.
- **Exception audit:** The 30 `except Exception` blocks must be individually reviewed. A blanket "log and re-raise" would break legitimate fallback patterns (e.g., TypeDB -> JSONL fallback in `knowledge_graph.py`). Each block needs case-by-case categorization.

## FedRAMP Control Satisfaction

| Control | Requirement | How This PRD Satisfies It |
|---------|-------------|---------------------------|
| AU-2 | Define auditable events | FR-3: Seven OCSF event classes defined |
| AU-3 | Required audit record fields | FR-2: OCSF base fields on every event |
| AU-6 | Audit review capability | FR-6: Searchable local log files (JSON, grep-friendly) |
| AU-8 | UTC timestamps | FR-2: `TimeStamper(fmt="iso", utc=True)` |
| AU-12 | Audit generation in all components | US-003 through US-005: all components instrumented |
| SI-4 | System monitoring | FR-4, FR-5: no silent failures, severity-based alerting readiness |

## Success Metrics

- Zero `print()` calls in `src/zettelforge/` (enforced by CI test)
- Zero bare `except Exception: pass` blocks (all log at minimum severity 2)
- 100% of `remember`, `recall`, `synthesize` calls emit OCSF API Activity events with required base fields
- All OCSF event classes in FR-3 have at least one emitter wired in
- Log files parseable by `jq` (valid JSON per line)
- Audit log retains 1 year of auth/authz/config events at typical volume
- Regression test for #26 pattern (silent LanceDB failure) passes

## Future Work (Noted for Follow-On PRDs)

- **PRD: GOV-012 Metrics Compliance** — Prometheus client instrumentation, `/metrics` endpoint, Grafana dashboard provisioning, SLO-derived alert thresholds
- **PRD: GOV-012 Tracing Compliance** — OpenTelemetry SDK integration, Jaeger backend, `traceparent` header propagation for MCP server calls
- **PRD: Log Aggregation Infrastructure** — Fluent Bit sidecar, OpenSearch cluster, Sentinel workspace connector, log pipeline from local files to SIEM

## Open Questions

1. Should `audit.log` use a separate structlog logger instance or a stdlib `logging.FileHandler` filter on OCSF class_uid?
2. Should the `request_id` be generated in `MemoryManager` or passed in from the MCP server layer (to correlate with MCP tool call IDs)?
3. What is the appropriate severity for LLM client failures (e.g., Ollama/llama-cpp timeout)? Severity 3 (needs attention) or 4 (prompt response)?
4. Should `config.py` load failures (currently `except Exception: pass`) be fatal or log-and-use-defaults? Current behavior silently falls back.
