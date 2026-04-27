# ZettelForge Threat Model

> **Document ID:** THREAT-001
> **Classification:** Internal (Tier 2)
> **Last Updated:** 2026-04-25
> **Framework:** STRIDE (GOV-011 SSDL Requirement)
> **Scope:** Community Edition v2.5.x (MIT-licensed codebase)
> **Compliance Mapping:** FedRAMP SA-3, SA-8, SA-11, SA-15; NIST 800-171 3.11, 3.13, 3.14

## 1. System Overview

### 1.1 High-Level Architecture

ZettelForge is an agentic memory system for cyber threat intelligence (CTI). It ingests unstructured text (threat reports, analyst notes, agent observations) through `remember()`, stores it in a hybrid SQLite + LanceDB backend, and retrieves it via `recall()` and `synthesize()` with intent-classified, policy-weighted blended retrieval.

```
                      ┌─────────────────────────────┐
                      │     External Actors          │
                      │  (Analyst / AI Agent / MCP)  │
                      └─────────────┬───────────────┘
                                    │
                      ┌─────────────▼───────────────┐
                      │   MemoryManager              │
                      │   remember() / recall()      │
                      │   synthesize()               │
                      └─────┬───────────────┬───────┘
                            │               │
               ┌────────────▼───┐    ┌──────▼────────────┐
               │  Governance    │    │  LLM Providers    │
               │  Validator     │    │  (local/ollama/   │
               │  (PII, rules)  │    │   litellm/mock)  │
               └────────┬───────┘    └──────┬────────────┘
                        │                   │
               ┌────────▼───────┐    ┌──────▼────────────┐
               │  SQLite +      │    │  Enrichment Queue │
               │  LanceDB       │    │  (causal / LLM   │
               │  (notes, vec)  │    │   NER extraction)│
               └────────────────┘    └───────────────────┘
```

### 1.2 Trust Boundaries

| Boundary # | Description | Type |
|------------|-------------|------|
| TB-1 | External → API surface (MCP, REST, direct Python API) | External network / process |
| TB-2 | Python API → MemoryManager | Internal process |
| TB-3 | MemoryManager → SQLite / LanceDB filesystem | Local filesystem |
| TB-4 | LLM Provider → External API (litellm, ollama) | Outbound network |
| TB-5 | Enrichment worker → LLM (fact extraction, NER) | Internal process |
| TB-6 | Configuration loader → env vars / YAML files | Local filesystem |

### 1.3 Data Flow Diagram

```
[C2] Analyst/AI Agent
  │
  │  remember(content) / recall(query)
  ▼
TB-1 ──────────────────────────────────────────────────┐
  │                                                      │
  ▼                                                      │
[P1] MemoryManager._remember_inner()                     │
  │                                                      │
  │  content                                             │
  ▼                                                      │
[P2] GovernanceValidator.validate_remember()             │
  │  ┌──────────────────┐                               │
  │  │ (Optional) PII    │  TB-5 (lazy)                 │
  │  │ Validator         │──→ presidio-analyzer         │
  │  │ (log/redact/block)│    (in-process spaCy)        │
  │  └──────────────────┘                               │
  │                                                      │
  │  redacted content (or original)                     │
  ▼                                                      │
[P3] NoteConstructor → construct MetadataNote           │
  │                                                      │
  ├──→ [DS1] EntityIndexer → extract entities           │
  ├──→ [DS2] AliasResolver → resolve APT28/Fancy Bear   │
  ├──→ [DS3] SQLite DB (notes, KG, entity index)       │
  ├──→ [DS4] LanceDB (vector index, IVF_PQ 768-dim)     │
  │                                                      │
  └──→ Enrichment Queue (async)                         │
       ├──→ [P4] LLM Causal Triple Extraction            │
       └──→ [P5] LLM NER (background)                    │
                                                         │
[S1] LLM Provider Dispatch                               │
  ├──→ local (in-process llama-cpp-python / onnx)      │
  ├──→ ollama (HTTP to localhost:11434) TB-4           │
  └──→ litellm (HTTP to cloud APIs)    TB-4            │
                                                         │
[C1] Configuration Loader                                │
  ├── config.yaml / config.default.yaml  TB-6          │
  ├── Environment variables (ZETTELFORGE_*)             │
  └── ${ENV_VAR} resolution for secrets                 │
```

---

## 2. STRIDE Threat Analysis

### 2.1 Spoofing

| ID | Threat | Component | Risk | Mitigation |
|----|--------|-----------|------|------------|
| S-01 | Attacker spoofs a valid MCP client to call `remember()` / `recall()` with malicious content | MCP Server / REST API (TB-1) | **High** — unauthorized memory access | MCP server relies on transport-level auth (stdio transport for local agents; TLS client certs or API tokens for remote). No built-in authentication in Community edition. Enterprise edition adds JWT/OAuth. |
| S-02 | Attacker spoofs an LLM provider endpoint (e.g., fake Ollama server) to return malicious model output | LLM Provider (TB-4, ollama/litellm) | **Medium** — model output is treated as data, not executable; but could inject false threat intelligence | No TLS verification for localhost endpoints (default ollama). litellm uses HTTPS for cloud APIs. Local deployments are responsible for network isolation. |
| S-03 | Attacker spoofs configuration file to inject malicious settings | Config Loader (TB-6) | **High** — could set `provider: litellm` with attacker-controlled API key or disable governance | Config files are local filesystem; `config.yaml` is in `.gitignore` to prevent accidental commits. No integrity verification on config files. |

### 2.2 Tampering

| ID | Threat | Component | Risk | Mitigation |
|----|--------|-----------|------|------------|
| T-01 | Attacker modifies SQLite database or LanceDB index files on disk | Storage (TB-3) | **Critical** — persistent memory corruption | SQLite WAL mode with no built-in integrity check on reads. No HMAC or signature on stored notes. Mitigation relies on OS-level filesystem permissions. Encrypt filesystem at OS level for sensitive deployments (noted in SECURITY.md). |
| T-02 | Attacker modifies config.yaml in-place to change LLM provider, disable PII validation, or alter governance settings | Config Loader (TB-6) | **High** — silent security downgrade | Config files are local. `config.default.yaml` is tracked in git. `config.yaml` is user-owned. No integrity verification. |
| T-03 | Attacker tampers with enrichment queue data in memory | Enrichment Queue (P4/P5) | **Low** — in-process queue, not network-accessible | The queue is an in-memory Python `queue.Queue` with `maxsize=500`. No external access path. |
| T-04 | Attacker modifies a note's embedding to bias recall results | LanceDB (DS4) | **Medium** — retrieval poisoning | LanceDB stores vectors as parquet files. OS-level file permissions are the only protection. |

### 2.3 Repudiation

| ID | Threat | Component | Risk | Mitigation |
|----|--------|-----------|------|------------|
| R-01 | Attacker performs operations (remember, recall, synthesize) without audit trail | MemoryManager | **High** — compliance failure for FedRAMP AU-2/AU-3 | All operations emit OCSF structured events via `log_api_activity()` / `log_authorization()`. OCSF class 1001 (API Activity) and 3001/3003 (Authorization) are emitted for every operation. Events include `request_id`, `actor`, `resource`, `status_id`. |
| R-02 | Governance violation occurs without attribution | GovernanceValidator | **Medium** — violation logged but no actor identity | `log_authorization()` records `actor="system"` for automatic calls. MCP and REST API paths should include authenticated actor. Currently Community edition uses hardcoded `"system"` actor. |
| R-03 | PII detection events without traceability | PIIValidator (RFC-013) | **Medium** — compliance requirement for data protection | `pii_detected` structured log event includes count, action, entity types, and scores. No raw PII text is logged (fixed in commit 5ac162c). |

### 2.4 Information Disclosure

| ID | Threat | Component | Risk | Mitigation |
|----|--------|-----------|------|------------|
| I-01 | Stored threat intelligence (notes, entities, IOCs) leaked via filesystem access | SQLite / LanceDB (DS3/DS4) | **Critical** — all CTI data exposed | No encryption at rest in Community edition. SQLite WAL files and LanceDB parquet files contain plaintext. **Mitigation:** encrypt filesystem at OS level. Enterprise edition adds optional SQLite encryption. |
| I-02 | PII stored in notes leaks through recall/synthesize responses | Storage → Retrieval | **High** — PII compliance | RFC-013 PIIValidator with `action=redact` strips PII before storage. `action=block` prevents storage entirely. Disabled by default — user must opt in. |
| I-03 | API keys logged in structured logs | LLM Provider / Config Loader | **Critical** — credential exposure | `LLMConfig.__repr__` redacts `api_key` as `'***'`. `extra` dict fields matching sensitive key patterns (`key`, `token`, `secret`, `password`, `credential`, `auth`) are also redacted. Config resolution uses `${ENV_VAR}` references so raw keys never appear in YAML. |
| I-04 | Error messages leak internal paths, configuration, or stack traces | All components | **Medium** — information gathering | No global exception handler catches and sanitizes errors. structlog can redact PII from log messages if configured. |
| I-05 | Raw PII text previously logged in structured events | PIIValidator (fixed) | **Medium** — historical exposure | Fixed in 5ac162c: PII text removed from log entities. Only entity type and score are logged. Users on prior commits should rotate logs containing PII. |

### 2.5 Denial of Service

| ID | Threat | Component | Risk | Mitigation |
|----|--------|-----------|------|------------|
| D-01 | Large content in `remember()` exhausts memory or blocks the enrichment queue | MemoryManager (P1) | **Low** — gracefully rejected | `governance.limits.max_content_length` (RFC-014, default 50 MB) blocks oversized content with a clear error. `remember_report()` chunks long documents. Enrichment queue has `maxsize=500` backpressure. |
| D-02 | LLM provider (ollama, litellm) hangs and blocks `remember()` | LLM Provider (TB-4) | **High** — operation blocks | OllamaProvider has timeout (RFC-010, default 60s). LitellmProvider has timeout + num_retries. `generate()` returns empty string on recoverable failure. Fallback provider (e.g., local -> ollama) gives alternative path. |
| D-03 | Malicious query triggers deep graph traversal exhausting time/resources | BlendedRetriever | **Medium** — bounded, but timeout may still block | `governance.limits.recall_timeout_seconds` (RFC-014, default 30s) applies a wall-clock timeout to the recall pipeline, but the current `ThreadPoolExecutor`-based approach must not be treated as guaranteeing prompt return on timeout. `max_graph_depth` (default 2) limits BFS hops. `default_k` (default 10) limits results. Reclassify to **Low** only after the timeout path is verified to return promptly and log `recall_timed_out` without waiting for the running task to finish. |
| D-04 | spaCy model download blocks first `remember()` when PII is enabled | PIIValidator (lazy load) | **Low** — delayed first call (~2-3 seconds) | One-time download cost. Matching fastembed pattern. Can be pre-downloaded for air-gapped deployments. |

### 2.6 Elevation of Privilege

| ID | Threat | Component | Risk | Mitigation |
|----|--------|-----------|------|------------|
| E-01 | MCP client accesses notes from a different domain/tenant than authorized | MemoryManager / MCP Server | **High** — cross-tenant data access | No domain-level access control in Community edition. Enterprise edition adds multi_tenant config. Domain is a metadata field on notes, not an access control boundary. |
| E-02 | Attacker bypasses governance validation (PII, rules) by calling storage backend directly | Direct filesystem / SQLite access | **Critical** — all governance controls bypassed | Governance runs in-memory in `_remember_inner()`. Direct SQLite or LanceDB access bypasses it entirely. Mitigation: OS-level filesystem permissions. |
| E-03 | Config change elevates provider from mocked/local to cloud API without user knowledge | Config Loader | **Medium** — unexpected outbound calls | No change of config is signed or validated. User is responsible for config integrity. |

---

## 3. Risk Summary

| Risk Level | Count | Key Concerns |
|------------|-------|--------------|
| **Critical** | 2 | T-01 (storage tampering), I-01 (unencrypted data at rest), E-02 (governance bypass via filesystem) |
| **High** | 7 | S-01 (spoofed MCP client), S-03 (config tampering), T-02 (config security downgrade), R-01 (repudiation without audit), I-02 (PII in stored notes), D-02 (LLM provider hang), E-01 (cross-tenant data access) |
| **Medium** | 7 | S-02 (fake LLM provider), T-04 (retrieval poisoning), R-02, R-03, I-04 (error message leakage), E-03 |
| **Low** | 3 | D-01, D-03, D-04 (PII model download delay) |

### Top 5 Mitigations (Priority Order)

1. **Encryption at rest** — Encrypt the data directory filesystem (OS-level LUKS, BitLocker, or eCryptfs). ZettelForge does not apply at-rest encryption itself.
2. **Filesystem permissions** — Restrict access to `~/.amem/` to the ZettelForge process user only. Prevents governance bypass (E-02) and storage tampering (T-01).
3. **Network isolation** — Run Ollama and ZettelForge on a dedicated VLAN or firewall zone. Prevent unauthorized MCP clients (S-01) and fake provider attacks (S-02).
4. **Enable PII redaction** — Set `governance.pii.enabled: true` and `action: redact` in production. Prevents PII persistence (I-02).
5. **Audit log retention** — Ensure OCSF logs are shipped to a SIEM (via structlog JSON output). Satisfies FedRAMP AU-2/AU-3 (R-01).

---

## 4. Mitigation Details

### 4.1 Existing Controls

| Control | Threat(s) | Mechanism | Verification |
|---------|-----------|-----------|--------------|
| OCSF audit logging | R-01, R-02 | `log_api_activity()`, `log_authorization()` emitted on every operation | CI test coverage, structlog configuration |
| API key redaction | I-03 | `LLMConfig.__repr__` redacts api_key and sensitive extra keys | Unit tests in `test_llm_providers.py` |
| PII detection + redaction | I-02 | PIIValidator (RFC-013): log/redact/block | Unit tests in `test_pii_validator.py` |
| LLM provider timeout | D-02 | `OllamaProvider` timeout=60s, `LiteLLMProvider` timeout + num_retries | Unit tests (RFC-010, RFC-012) |
| Content size limit | D-01 | `governance.limits.max_content_length` (RFC-014, default 50 MB) blocks oversized content | Unit tests in `test_governance.py` |
| Recall timeout | D-03 | `governance.limits.recall_timeout_seconds` (RFC-014, default 30s) wraps recall in ThreadPoolExecutor with wall-clock timeout | Unit tests in `test_governance.py` |
| Config env-var resolution | I-03 | `${ENV_VAR}` syntax prevents raw secrets in YAML | Unit tests |
| Configurable model provider | S-02, E-03 | `provider` key selects backend; no implicit unauthenticated outbound calls | Config validation |
| Enrichment queue backpressure | D-01 | `maxsize=500` bounded queue | Code review |

### 4.2 Recommended Additions (Not Yet Implemented)

| Recommendation | Threat(s) | Effort | Priority |
|---------------|-----------|--------|----------|
| Add global exception handler that sanitizes error output | I-04 | Medium | P2 |
| Add TLS verification option for self-hosted LLM endpoints | S-02 | Small | P2 |
| Add config file integrity check (SHA-256 of default vs. loaded) | T-02, S-03 | Medium | P3 |
| Add recall timeout (configurable, default 30s) | D-03 | Medium | P3 |
| Domain-level access control for multi-tenant | E-01 | Large | Enterprise |

---

## 5. Threat Model Maintenance

| Activity | Frequency | Owner | Evidence |
|----------|-----------|-------|----------|
| Threat model review | Per quarter or per significant feature | CTO/CIO | Updated THREAT_MODEL.md |
| STRIDE assessment for new components | Per RFC (GOV-016 requirement) | RFC Author | Threats section in RFC |
| SAST scan | Every PR (CI) | Automated | CI pipeline logs |
| SCA scan | Every PR + daily scheduled | Automated | pip-audit, Snyk reports |
| Secret scan | Every PR (CI) | Automated | GitGuardian |
| Dependency vulnerability review | Per advisory (GOV-009 timelines) | Maintainer | GitHub Dependabot, Snyk |

---

## 6. Data Classification Mapping

Per GOV-021, the following data types exist in the system:

| Data | Classification | Storage | Handling |
|------|---------------|---------|----------|
| Threat intelligence notes (actor TTPs, IOCs, campaigns) | Internal (Tier 2) | SQLite + LanceDB, no encryption at rest | OS-level filesystem encryption recommended |
| PII (names, emails, phones — if not redacted) | Confidential (Tier 3) | SQLite (if PII passes through without redaction) | **Must** enable PII redaction (RFC-013) |
| API keys / credentials | Confidential (Tier 3) | Never committed; env vars only | Redacted from logs, resolved at runtime |
| Audit logs (OCSF events) | Internal (Tier 2) | Structured logs (GOV-012) | Logs must not contain Tier 3/4 data values |
| Configuration files | Internal (Tier 2) | config.yaml, config.default.yaml | `.gitignore` excludes user config; no secrets in YAML |
| Embedding vectors | Internal (Tier 2) | LanceDB parquet files | Derived from notes; same classification as source |
| CUI (federal contract data) | CUI (Tier 4) | **Not handled** in Community edition | Enterprise edition only, after FedRAMP authorization |

---

## 7. Recent Changes Affecting Threat Model

| Change | RFC/PR | Date | Threat Model Impact |
|--------|--------|------|---------------------|
| Content size limits + recall timeout | RFC-014 | 2026-04-25 | Mitigation for D-01 (content size limit, default 50 MB); partial mitigation for D-03 (timeout) |
| PII detection and redaction | RFC-013 (PR #118) | 2026-04-25 | New control for I-02; new attack surface (D-04); PII text logging fixed |
| LiteLLM unified provider | RFC-012 (PR #108) | 2026-04-25 | New provider for I-03 (API keys); new outbound traffic pattern (TB-4) |
| Local LLM backend selection | RFC-011 (PR #104) | 2026-04-25 | No new threat surface — extends existing local provider |
| Ollama provider timeout | RFC-010 | 2026-04-24 | Mitigation for D-02 |
| LLM provider registry | RFC-002 | 2026-04-16 | Foundation for S-02, E-03 via provider selection |
| SQLite backend default | v2.2.0 | 2026-04-14 | Migration path changes attack surface of legacy JSONL |
| Injection defenses | v2.1.1 | 2026-04-10 | Fixed parameterized queries (was: P0 SQL injection — see CHANGELOG) |

---

## 8. Threat Model Review Log

| Date | Reviewer | Changes | Next Review |
|------|----------|---------|-------------|
| 2026-04-25 | Hermes Agent (automated) | Initial threat model creation per GOV-011 | 2026-07-25 |
