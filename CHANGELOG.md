# Changelog

All notable changes to ZettelForge are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/).
Versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **CrewAI integration** (issue #40). New optional extra
  `pip install zettelforge[crewai]` exposes `ZettelForgeRecallTool`,
  `ZettelForgeRememberTool`, and `ZettelForgeSynthesizeTool` as CrewAI
  `BaseTool` subclasses. CTI-focused crews can now use ZettelForge as a
  drop-in alternative to CrewAI's existing Mem0 memory tools, with
  per-tool description copy aimed at routing the LLM to the right tool
  (recall for lookups, remember for findings, synthesize for final answers).
  See `examples/crewai_cti_crew.py` for a runnable two-agent demo.
  Tests gated on `pytest.importorskip("crewai")`; 11 pass against
  crewai 1.14.x.

## [2.6.2] - 2026-04-27

UI/UX release. Fixes the `/config` page so the Apply button actually works
and surfaces enum-style settings as dropdowns instead of free-text inputs.
No data migration. No config changes. No API contract changes.

### Fixed

- **`/config` "Save Changes" button is no longer dead.** The Quick Settings
  panel called `saveConfigForm()` and `reloadConfig()` — neither function
  was defined anywhere, so the button silently no-op'd and the panel
  rendered "Loading schema..." forever. Replaced with a real form-based
  editor whose Apply button PUTs a nested payload to `/api/config` and
  reloads from server on success.

### Added

- **Form-based config editor with dropdowns.** `/config` now renders a
  grouped settings form alongside the YAML editor. Known enum fields
  (`backend`, `embedding.provider`, `llm.provider`, `llm.local_backend`,
  `logging.level`, `synthesis.default_format`, `governance.pii.action`)
  render as `<select>` controls instead of free-text inputs. Restart-
  required leaves get a "restart required" badge sourced from the same
  set the server uses, so the UI warning is never out of sync with the
  server's classification.
- **Pending-changes counter and Revert button.** The form tracks dirty
  fields by dotted path, builds a single nested payload on Apply, and
  shows `N pending change(s) (M need restart)` next to the buttons.
- **YAML editor accepts both YAML and JSON** (was JSON-only despite the
  label) and skips redacted `***` secrets so they aren't PUT back as
  literal strings.

### Tests

- 4 new tests in `tests/test_web_api.py`: dropdown enum round-trip for
  `logging.level` (restart-required) and `synthesis.default_format` (live);
  multi-section nested payload from a single Apply; and a regression guard
  on the `/config` HTML structure (form tab, dropdown enum declarations,
  restart-leaf flags, and proof the dead `saveConfigForm`/`reloadConfig`
  handlers are gone). 28 passed, 2 skipped (was 24 + 2).

## [2.6.1] - 2026-04-25

Hotfix release. Resolves three blockers found in code review of the
RFC-015 web GUI shipped in v2.6.0. No data migration. No config changes.

### Fixed

- **`/config` HTML page now renders.** `_to_dict` was defined as a closure
  inside `get_config_endpoint`, so every render of `/config` raised
  `NameError`, was silently swallowed by a bare `except`, and left the
  YAML body blank on initial server-side render. Promoted to a module-level
  `_config_to_dict` helper used by both routes. (PR #131)
- **`PUT /api/config` correctly reports nested restart-required fields.**
  The check compared top-level payload keys against a set of dotted-path
  fields, so payloads like `{"embedding": {"provider": "x"}}` were
  reported as `applied: ["embedding"]`, `pending_restart: []`, telling
  operators a restart-required change had taken effect when it had not.
  Added `_flatten_keys` to walk nested payloads to dotted leaf paths;
  `applied` and `pending_restart` now contain accurate dotted paths.
  (PR #131)
- **`/config` HTML route is now auth-gated.** `/api/config` was protected,
  but the HTML shell (and once the `_to_dict` bug was fixed, its
  server-rendered YAML body) was reachable without an API key. Added
  `Depends(require_api_guard)` and made the YAML body redact secrets
  before serialization. (PR #131)

### Tests

- Added four regression tests in `tests/test_web_api.py` covering all
  three fixes. 24 passed, 2 skipped (was 20 + 2).

## [2.6.0] - 2026-04-25

Feature release. Adds configurable content-size limits for DoS mitigation
(RFC-014) and moves per-call-site LLM token budgets out of hardcoded
literals into `LLMConfig`, making them overridable at deploy time.

### Added

- **Configurable content size limits** (`GovernanceConfig.limits.max_content_length`,
  default 50 MB). `remember()` calls with content exceeding the limit are
  rejected with a clear error message. Set to `0` to disable the check.
  Environment override: `ZETTELFORGE_LIMITS_MAX_CONTENT_LENGTH`.
  (RFC-014, PR #123)
- **Per-call-site `max_tokens` budgets configurable via `LLMConfig`**.
  Five new fields: `max_tokens_causal` (8000), `max_tokens_synthesis` (2500),
  `max_tokens_fact` (2500), `max_tokens_ner` (2500), `max_tokens_evolution` (2500).
  Defaults match v2.5.2 values. No behavioral change for existing configs.
  (PR #126, issue #125)

### Changed

- **Docs: config reconciliation for v2.5.2** — `config.default.yaml` gained
  the `lance:` section (RFC-009 Phase 1.5), `docs/reference/configuration.md`
  now covers all v2.5.2 knobs (`lance`, `pii`, per-call-site budgets), and
  `docs/explanation/llm-budgets-and-timeouts.md` explains the reasoning-model
  token-budget tradeoffs. (PR #126)
- **`_apply_yaml()` now handles `lance:` section** — previously the
  `lance.cleanup_interval_minutes` and `lance.cleanup_older_than_seconds` YAML
  knobs were silently ignored (regression from RFC-009 Phase 1.5 landing in
  v2.4.x without the `_apply_yaml` branch). (PR #126, code review finding)

### Internal

- **Removed `docs/superpowers/` from version control**. The directory holds
  workspace scratch — internal research and notes with unredacted incident
  detail. 18 files (7319 lines) untracked. No published content lost.
  (PR #128)

## [2.5.2] - 2026-04-25

Hotfix release. Restores end-to-end functionality of synthesis, causal
triple extraction, fact extraction, LLM NER, and neighbor evolution
under any reasoning-style LLM (qwen3.5+, qwen3.6, nemotron-3, etc.).

### Fixed

- **Reasoning-model token starvation across every LLM call site**.
  Reasoning models emit hidden `<think>...</think>` tokens that count
  against `num_predict` but never appear in the final `response` field
  Ollama returns. Pre-2.5.2 token caps (`max_tokens=300`/`400`/`800`/
  `1024`) were exhausted entirely by the thinking phase on these
  models, leaving the JSON answer empty. Symptoms: synthesis fell back
  to `"No specific answer found for: …"` on every query; causal triple
  extraction persisted **0 edges** despite rich CTI text; LLM NER
  silently no-opped; neighbor evolution `parse_failed{schema=...,
  raw=""}` warnings flooded the log.

  Bumped every `generate(..., max_tokens=...)` call site to give
  reasoning models room to think *and* emit a final answer. Affected
  files:

  | File | Old cap | New cap |
  |---|---|---|
  | `note_constructor.py` (causal triples) | 300 | **8000** |
  | `synthesis_generator.py` | 800 | 2500 |
  | `fact_extractor.py` | 400 | 2500 |
  | `entity_indexer.py` (NER) | 300 | 2500 |
  | `memory_evolver.py` (2 sites) | 1024 | 2500 |

  Causal extraction needs the largest budget because the prompt asks
  the model to enumerate *every* causal relation in a passage; this
  triggers the longest reasoning chains anywhere in the system.
  Empirical against `qwen3.5:9b`: at 4000 tokens the call was
  *stochastically* sufficient (eval_count varied 2.8k–4k+, ~70%
  success), so 8000 is the conservative cap that keeps the success
  rate above 95% on the same model. Other call sites converge with
  less reasoning overhead so 2500 suffices.

- **LLM client timeout bumped 60s → 180s**. `LLMConfig.timeout` and
  `OllamaProvider` constructor default were both 60 seconds — well
  below the 60–120s wall-clock time of a 4000–8000 token reasoning
  generation on a 9B-Q4_K_M model. `ReadTimeout` was firing during
  causal extraction even when the model would have returned valid
  JSON given another 30 seconds. Bumped both defaults plus
  `config.default.yaml` to 180s.

  Verified end-to-end on `qwen3.5:9b`:
  - Synthesis: query "What CVE does DROPBEAR exploit?" returns
    `"CVE-2024-3094"` with 1 source citation (was returning
    `"No specific answer found for: …"` on every call pre-2.5.2).
  - Causal extraction: corpus seeded with APT28/DROPBEAR/CVE-2024-3094
    text yields a 4-triple JSON array in 137s wall time:
    `APT28 → targets → manufacturing sector`,
    `APT28 → uses → DROPBEAR`,
    `DROPBEAR → exploits → CVE-2024-3094`,
    `APT28 → attributed_to → Russian GRU Unit 26165`.

### Operational note

Slow models. With 8000 tokens of reasoning budget, single causal
extraction calls now take 60–140s on a 9B model. `remember(sync=True)`
in this configuration will block 1–3 minutes per note. The default
async path (background enrichment queue) is the preferred mode.
Operators on faster hardware or smaller models can lower the caps via
config/env if needed, but the v2.5.2 defaults trade latency for
end-to-end correctness on the reference model.

### Notes

This explains the `evolution_parse_failed` and `causal_triples
parse_failed` cascades documented in the v2.4.x Vigil incident. The
v2.4.2 PR #95 Tier 1/2 LLM observability surfaced the empty responses
but the root-cause attribution to token-cap-vs-thinking-budget waited
until the v2.5.1 perf-bench run made the failure reproducible end-to-end.

## [2.5.1] - 2026-04-25

Hotfix release. Surfaced during the v2.5.0 perf benchmark run.

### Fixed

- **`KnowledgeGraph._cache_edge` crashed on legacy-schema edges**.
  Long-running deployments accumulated `kg_edges.jsonl` entries written
  by a now-removed pre-v2.5.x writer that used
  `{source_id, target_id, relation_type}` instead of the canonical
  `{from_node_id, to_node_id, relationship}` keys. The loader hard-failed
  with `KeyError: 'from_node_id'` on the first such row, taking down
  every `recall()` and `synthesize()` that touches the KG. Affects any
  workspace with mixed-schema edge history; observed locally with 189k
  edges where ~80k were the legacy shape.
  `_normalize_edge_schema()` now remaps legacy keys to canonical on load
  and silently drops entries that are still un-normalizable, with a
  count logged at WARNING so operators can see the skip volume.
  Six new regression tests in `tests/test_kg_edge_schema.py` cover
  pass-through, remap, missing-fields, non-dict, mixed-batch, and
  corrupt-JSON cases. The previously-broken environment-dependent
  `test_basic.py::test_ingest_relationship` now passes deterministically.

## [2.5.0] - 2026-04-25

Compliance-driven minor release. Closes every CRITICAL and HIGH audit
finding except H-3 (mypy strict) and the ANN slice of H-1, both of
which need per-module ratchet plans. Also adds two new optional LLM
backends, a Presidio PII detector, and supply-chain hardening.

### Added

- **RFC-011 — Local LLM backend selection** (#104). New `local_backend`
  config knob picks between `llama-cpp-python` (GGUF) and
  `onnxruntime-genai` (ONNX) at runtime. Both ship as optional extras
  (`pip install zettelforge[local]` or `[local-onnx]`).
- **RFC-012 — LiteLLM unified provider** (#108). Routes to 100+
  upstream LLM providers via the LiteLLM SDK. Optional extra
  (`pip install zettelforge[litellm]`); the base package never imports
  it unless the SDK is present.
- **RFC-013 — Microsoft Presidio PII detection** (#118). Optional PII
  validator with three policies (`log` / `redact` / `block`),
  configurable via `governance.pii.*`. CTI allowlist excludes
  `IP_ADDRESS` / `URL` / `DOMAIN_NAME` from detection so legitimate
  threat-intel indicators flow through unmodified. Soft dependency —
  `pip install zettelforge[pii]` to activate; the base package never
  imports `presidio_analyzer` unless the SDK is present.
- **GOV-009 Snyk SCA + SAST declared in `controls.yaml`** (#114). The
  spec-drift validator now walks every `.github/workflows/*.yml` so
  controls whose CI step lives outside `ci.yml` (Snyk's separate
  workflow) can be honestly declared.
- **GOV-006 solo-maintainer compensating controls** (#117). New
  `controls.yaml` entry pins the existing CI gates (lint, tests,
  governance spec-drift) as compensating controls for the GOV-006
  two-person review rule that cannot be physically satisfied with one
  human maintainer. CODEOWNERS updated with explanatory comment.
- **`SECURITY.md` + CODEOWNERS** added to the repo root for vulnerability
  disclosure and review attribution.

### Changed

- **All GitHub Actions are now SHA-pinned** (audit H-5 hardening). Every
  `uses: org/repo@vX` reference replaced with `uses: org/repo@<full-sha> # vX.Y.Z`
  to prevent supply-chain attacks via tag rewrites.
- **Ruff rule set ratcheted to GOV-003 §"Tooling and Automation" minus
  ANN** (#106 + #107 + #109 + #111 + #113). Active `select` list:
  `{E, F, I, W, N, T20, B, UP, SIM, RUF, S}`. Per-line `# noqa: SXXX`
  annotations document each accepted exception (best-effort fallbacks,
  non-crypto RNG, `?`-bound SQL with constant column lists).
  `RUF002`/`RUF003` ignored globally for stylistic en-dash and ×.
- **CI install-step shell precedence fixed** (#112). The
  `pip install -e ".[dev]" || pip install -e "." && pip install pytest...`
  chain parsed as `(A || B) && C`, so the pytest install ran on
  every success path including when `[dev]` already provided pytest.
  Wrapped the fallback in parentheses.
- **CONTRIBUTING.md accuracy** (#115). Documents `ruff format`
  (project hasn't used black for a while) and lists what CI actually
  enforces so new contributors have a green-build target.

### Compliance audit closure (`tasks/compliance-audit-2026-04-25.md`)

| Severity | Finding | Status |
|---|---|---|
| CRITICAL | C-1 branch protection | CLOSED (with required status checks) |
| CRITICAL | C-2 fabricated `no_hardcoded_secrets` claim | CLOSED (#100) |
| HIGH | H-1 ruff full select per GOV-003 | CLOSED for {E,F,I,W,N,T20,B,UP,SIM,RUF,S}; ANN ratcheting per-module |
| HIGH | H-2 coverage threshold not enforced | CLOSED (#100) |
| HIGH | H-4 GOV-006 / CODEOWNERS solo-maintainer | CLOSED on the zettelforge side (#117); GOV-006 doc amendment in `rolandpg/governance` repo is separate scope |
| HIGH | H-5 SCA gate + SHA-pinned actions | CLOSED (#102 + #114 + SHA-pin commit) |
| MEDIUM | M-1 bare `except:` in production | CLOSED (#100) |
| MEDIUM | M-3 OCSF `timezone_offset` field | CLOSED (#100) |
| LOW | L-4 CI install-step shell precedence | CLOSED (#112) |

Outstanding: H-3 (mypy --strict in CI; needs per-module ratchet plan
for 393 errors across 38 files), M-2 (rewrite GOV-016 to match the
YAML-frontmatter practice already in use), M-4 (lock file), H-1 ANN
ratchet (121 findings across 38 files).

## [2.4.3] - 2026-04-25

Patch release. Three small but consequential fixes that landed during the post-v2.4.2 Vigil live-test session, plus the standalone `compact_lance` maintenance script and Nexus's Tier 0/1/2 LLM observability instrumentation.

### Added

- **OCSF `metadata.product.version` self-correct** (#96). `ocsf.py:_resolve_product_version()` now prefers the source `pyproject.toml` reachable from `__file__` and falls back to `importlib.metadata.version("zettelforge")`. Editable installs — where `git checkout vX.Y.Z` updates the source tree but not the installed-metadata record — no longer emit stale version strings. Observed live on Vigil 2026-04-24: v2.4.2 source was emitting `product.version=2.4.1` events because the editable-install metadata hadn't been refreshed.
- **`ZETTELFORGE_LOG_LEVEL` env var honored** (#96). `log.py:get_logger()` now resolves the log level via env var → `config.yaml log.level` → INFO default. Operators can flip DEBUG without editing code or restarting agent boot order. Resolves the "config.yaml `log.level=DEBUG` was dead code" trap hit on Vigil 2026-04-24, where the auto-configure hardcoded INFO and locked `_configured=True` before any caller could read config.
- **Fastembed preload** (#96). New `vector_memory.preload_embedding_model()` invoked from `MemoryManager.__init__`. Moves the ~800 ms fastembed model-load cost off the first `remember()` and onto agent startup. Best-effort, no-op when `provider != fastembed`. Phase 0.5 measurement: cold `construct=799ms` vs warm `construct=37ms`.
- **`compact_lance` maintenance script** (#94). New `python -m zettelforge.scripts.compact_lance` for offline LanceDB shard maintenance. Discovers all `<name>.lance/` tables under `<data-dir>/vectordb/`, supports `--dry-run` / `--table` / `--all` / `--mode {compact,optimize}` / `--force`, emits a per-table JSON report with before/after fragment count, on-disk bytes, row count, and elapsed seconds. Operationalized the Phase 0.5 cleanup intervention (see "Vigil incident response" below).
- **Tier 0/1/2 LLM observability** (#95, Nexus). `ollama_provider.py` now logs every LLM call (model, prompt_chars, response_chars, response_preview, prompt_preview, duration_ms, eval_count, prompt_eval_count, done_reason). `memory_evolver.py` retries log prompt and raw response previews instead of just `neighbor_id`. `fact_extractor.py` empty completions now emit `parse_failed{schema="fact_extraction", reason="empty_completion"}` (`fact_extractor.py:69-71`) instead of silently returning `[]`. `entity_indexer.py` LLM extractions log prompt previews. `structlog.contextvars`-based `trace_id` propagates through `remember()` so every event in a single note's pipeline shares one correlation key.

### Operational notes

The 2026-04-24/25 Vigil live-test session — driven by the v2.4.2 Phase 0.5 instrumentation — found and fixed a 5.66 GB LanceDB version-history bloat on Vigil's `notes_cti` shard. `cleanup_old_versions()` shrank it 5.69 GB → 29 MB and collapsed `remember()` p95 from 49.8 s → ~250 ms. Full evidence in `docs/superpowers/research/2026-04-25-phase-0.5-attribution.md`. The periodic-cleanup feature itself ships in v2.5.0 as RFC-009 Phase 1.5; the v2.4.3 `compact_lance` script supports the one-shot operator workflow until then.

## [2.4.2] - 2026-04-24

Patch release bundling the RFC-010 enrichment-pipeline hotfix with the
RFC-009 Phase 0.5 latency-attribution instrumentation. Response to the
2026-04-24 Vigil telemetry audit.

### Fixed

- **RFC-010 hotfix — `OllamaProvider` timeout plumbing** (#88). The
  constructor's `**_: Any` absorbed the configured `timeout` kwarg, so
  `ollama.Client(host=...)` was built with no timeout and `remember()`
  could hang up to 66.5s on a slow backend. `timeout` is now a
  first-class parameter (default 60.0s) threaded through to the client.
- **RFC-010 hotfix — consolidation shutdown race** (#88). A third
  `iterate_notes()` site at `consolidation.py:224` was not covered by
  PR #84's two-site guard. Added a two-layer defense: fast-path
  `_accepting` pre-check plus a narrow `BackendClosedError` catch on
  the iterator itself. Clean skip instead of `consolidation_failed`
  log noise during `atexit`.

### Added

- **RFC-009 Phase 0.5 — per-phase timers in `remember()`** (#90).
  `memory_manager.remember()` now wraps each direct-store phase
  (`construct`, `write_note`, `lance_index`, `entity_index`,
  `consolidation_observe`, `supersession`, `kg_update`,
  `enrichment_dispatch`) in `time.perf_counter()` and emits the
  breakdown inside the existing `ocsf_api_activity` event as
  `phase_timings_ms`. Pure observability. Enables Vigil-side latency
  attribution without host-side profilers, which do not apply to a
  library-per-turn deployment. `enrichment_dispatch` is intentionally
  skipped in `sync=True` runs so inline LLM work cannot corrupt the
  dispatch bucket.
- **Phase 0.5 preliminary attribution artifact** (#91) —
  `docs/superpowers/research/2026-04-24-phase-0.5-attribution-prelim.md`.
  Analyses 961 real `remember()` calls from Vigil's v2.4.1 OCSF log
  and finds **98.4% of `remember()` wall-clock is one LanceDB `Update`
  on the `notes_cti` shard**, which has 7,356 uncompacted fragments
  versus 458 on the healthy `notes_general` shard. Reshapes RFC-009's
  Phase 1–6 priority ordering: those phases target the LLM / queue /
  consolidation paths, which are not what drives the 5.7s average.
  To be refined or falsified with `phase_timings_ms` data from this
  release.

### Does NOT address

- The ~2,329 enrichment-job drops/day are still present. Those are
  caused by HTTP 200 + empty Ollama responses (Ollama returns
  successfully but with no parseable body), not by hangs — RFC-010's
  timeout fix does not touch them. The durable outbox + circuit
  breaker in RFC-009 Phases 1–3 (v2.5.0) is the real fix.
- LanceDB fragment accumulation on `notes_cti` is identified here but
  not fixed here. RFC-009 is being revised to add periodic compaction
  to Phase 1 scope.

## [2.4.1] - 2026-04-24

Operational telemetry (RFC-007), TypeDB authentication hardening, and a
tranche of SQLite backend correctness fixes surfaced by the sqlite
review in issue #83.

### Added

- **Operational telemetry** (RFC-007, #85) — per-query recall /
  synthesis metrics captured to `~/.amem/telemetry/telemetry_YYYY-MM-DD.jsonl`
  when `ZETTELFORGE_LOG_LEVEL=DEBUG`. Five shipped components:
  - `TelemetryCollector` class (`start_query` / `log_recall` /
    `log_synthesis` / `log_feedback` / `auto_feedback_from_synthesis`)
    with INFO/DEBUG-gated field sets, 1-hour TTL on in-memory query
    context, and thread-safe JSONL append.
  - `MemoryManager` integration — `recall()` and `synthesize()` gain a
    non-breaking `actor=` kwarg; OCSF events extended via the
    sanctioned `unmapped` object with a `zf_` prefix (class_uid 6002
    compliant). `recall()` wraps `retriever.retrieve()` and
    `graph_retriever.retrieve_note_ids()` with narrow-scope
    `perf_counter` deltas for `vector_latency_ms` / `graph_latency_ms`.
  - Daily aggregator (`python -m zettelforge.scripts.telemetry_aggregator`)
    emitting a `DailyMetrics` JSON report (latency averages, tier
    distribution, unused-notes count, top-utility notes).
  - Human-evaluation workflow — 6-question rubric (`docs/human-evaluation-rubric.md`),
    sampler script (`python -m zettelforge.scripts.human_eval_sampler`)
    that selects 20 random briefings as a fill-in Markdown template,
    and a `--write-events` path to append `event_type: "human_eval"`
    entries back to telemetry.
  - Optional Streamlit dashboard (`streamlit run
    src/zettelforge/scripts/telemetry_dashboard.py`) — query volume,
    latency p50/p95/max, tier distribution, utility trend,
    unused-notes warning.
  - Privacy contract: raw note content never persisted (IDs / tiers /
    source_types / domains only); query text truncated at 200 chars
    INFO / 500 chars DEBUG; local-only, no network calls.

### Fixed

- **SQLite shutdown NPE** (#84, issue #83 H3) — `close()` and
  `initialize()` are now lock-protected and idempotent. Readers and
  writers raise a clean `BackendClosedError` (new, in
  `storage_backend`) instead of the opaque `AttributeError: 'NoneType'
  object has no attribute 'execute'` seen 170× in production logs on
  2026-04-23 during atexit. `memory_manager._enrichment_loop` and
  `_drain_enrichment_queue` catch `BackendClosedError` and exit
  cleanly.
- **SQLite torn snapshot** (#84, issue #83 C1) — `export_snapshot()`
  now uses `sqlite3.Connection.backup()` for a page-consistent copy.
  The previous `shutil.copy2` path could produce a corrupt backup
  missing `-wal` / `-shm` sidecars, unsafe for DR restore.
- **SQLite reindex race** (#84, issue #83 C2) — `reindex_vector()` now
  uses a single-lock targeted `UPDATE` on the `embedding_vector`
  column. The previous `get_note_by_id → rewrite_note` path spanned
  two lock acquisitions and could clobber concurrent
  `mark_access_dirty` / `evolve` / supersede edits via
  `INSERT OR REPLACE`.

### Security

- **TypeDB authentication hardening** (#82) — removed known-insecure
  `admin` / `password` defaults from `TypeDBConfig` and
  `config.default.yaml`. `TypeDBConfig.__repr__` now redacts
  non-empty passwords as `***`. The config loader resolves
  `${TYPEDB_USERNAME}` / `${TYPEDB_PASSWORD}` env-var references in
  YAML (same pattern already used for `llm.api_key`), so secrets can
  stay in env / container secret stores rather than on disk.
  Migration: set `TYPEDB_USERNAME` / `TYPEDB_PASSWORD` in your
  environment or use the `${VAR}` references in a local
  `config.yaml`. Direct env overrides (`TYPEDB_USERNAME=…`) already
  worked and are unaffected.

### Docs

- **Architecture Deep Dive + Module Inventory for v2.4.0** (#80) —
  reference-level architecture documentation.
- **RFC-007 Operational Telemetry** (#85) — full design doc including
  the four subagent-resolved frictions (caller-opt-in query_id
  correlation, narrow-scope latency instrumentation, OCSF unmapped
  extension, hybrid `__new__`-bypass integration tests).
- **Human Evaluation Rubric** (#85) — 6-question monthly review
  rubric with scoring summary table.
- **Troubleshoot guide** (#85) — "Operational telemetry" subsection
  covering the three CLI entry points and the privacy contract.

## [2.4.0] - 2026-04-19

Detection-rules-as-memory, MCP Registry publication, SQLite concurrency
hardening, and a full test-suite hygiene pass.

### Added

- **Detection rules as first-class memory** (#70) — Sigma and YARA rules
  are now ingested, indexed, and retrieved alongside CTI entities, with
  an LLM rule explainer that surfaces what each rule detects and the
  actors/techniques it's associated with. See the "Detection Rules as
  Memory" section in the README (#74) for usage.
- **MCP Registry publication** (#75) — `server.json` and the `mcp-name`
  tag required to publish ZettelForge to the canonical MCP Registry
  (registry.modelcontextprotocol.io), which feeds mcp.so and the
  modelcontextprotocol.io community-servers list.
- **Brand & docs polish** (#61) — neural-chain architecture diagram with
  light/dark parity, updated GitHub social preview, canonical security
  channels + RFC 9116 `security.txt`, real Code of Conduct contacts,
  and a complete brand documentation set.

### Fixed

- **SQLite backend concurrency** (#69) — 16 reader methods in
  `SQLiteBackend` (`get_note_by_id`, `get_note_by_source_ref`,
  `iterate_notes`, `get_notes_by_domain`, `get_recent_notes`,
  `count_notes`, `get_kg_node`, `get_kg_node_by_id`,
  `get_kg_neighbors`, `traverse_kg`, `get_entity_timeline`,
  `get_changes_since`, `get_causal_edges`, `get_incoming_causal`,
  `get_note_ids_for_entity`, `search_entities`) were executing
  `SELECT` statements without holding `_write_lock`, while writers
  acquired it. Under concurrent background enrichment, readers could
  observe a partially-written row and raise `pydantic.ValidationError`
  on NULL columns. Each reader now wraps its SQL execute+fetch block
  in `with self._write_lock:` (RLock, reentrant-safe). Closes #68.
  Eliminates the `test_apply_delete_marks_superseded` flake and
  prevents the same race from surfacing in production
  `recall()`-during-write paths.
- **CI regressions** (#67) — stabilized three tests exposed by the
  test-suite audit sprint.

### Changed

- **Test suite hygiene** (#62, #63, #64, #65) — post-v2.3.0 audit (see
  `docs/superpowers/research/2026-04-17-test-suite-audit.md`)
  converted 10 CI-skipped LLM tests to the mock provider (RFC-002
  Phase 1), resolved both remaining `xfail` tests via prompt-routed
  mocks, eliminated two long-standing flakes
  (`test_recall_cve_returns_notes`, `test_apply_delete_marks_superseded`),
  prepped `langchain_retriever` for Pydantic V3 by migrating to
  `ConfigDict`, and reinstated meaningful causal-edge validation via
  mock-seeded triples + `SQLiteBackend.get_causal_edges` query. Net
  test-suite delta: 280 passed / 17 skipped / 2 xfailed → 305 passed
  / 10 skipped / 0 xfailed on test-3.12.

## [2.3.0] - 2026-04-17

Pluggable LLM provider infrastructure (RFC-002 Phase 1), MCP server
as a first-class Python module, PyPI discoverability refresh, SEO
foundations across the docs site, and a full docs-vs-code
reconciliation. All additions are backward-compatible; no existing
API changes. Supersedes the never-tagged 2.2.1 metadata patch —
its PyPI classifier / keyword / image-URL changes are folded in
below.

### Added

- **Pluggable LLM provider infrastructure (RFC-002 Phase 1)** — new
  `zettelforge.llm_providers` package with a `@runtime_checkable`
  `LLMProvider` protocol, a thread-safe registry, and built-in
  providers for `local` (llama-cpp-python), `ollama`, and `mock`.
  The public `generate()` signature is unchanged; all 7 existing call
  sites (`fact_extractor`, `memory_updater`, `synthesis_generator`,
  `intent_classifier`, `note_constructor`, `entity_indexer`,
  `memory_evolver`) keep working without modification. Third-party
  providers can register via the `zettelforge.llm_providers`
  entry-point group. `openai_compat` and `anthropic` providers land
  in Phase 2 and Phase 3.
- **`LLMConfig` expanded** — new `api_key`, `timeout`, `max_retries`,
  `fallback`, and `extra` fields. `api_key` supports `${ENV_VAR}`
  references and is redacted from `repr()`. Sensitive keys inside
  `extra` (matching `key|token|secret|password|credential|auth`) are
  redacted as well. New env overrides: `ZETTELFORGE_LLM_API_KEY`,
  `ZETTELFORGE_LLM_TIMEOUT`, `ZETTELFORGE_LLM_MAX_RETRIES`,
  `ZETTELFORGE_LLM_FALLBACK`.
- **`LLMProviderConfigurationError`** — new exception surfaced for
  non-recoverable provider setup problems (bad API key, missing
  optional SDK) so `generate()` can distinguish "try the fallback"
  from "stop and report".
- **`llm_client.reload()` helper** — clears the provider registry
  and config cache so test suites and long-lived processes can
  reconfigure the LLM backend without a process restart.
- **Hardened .gitignore** per GOV-023 — added `.env.*`, `*.key`,
  `*.pem`.
- **MCP server as a first-class module** — `python -m zettelforge.mcp`
  now works out of a `pip install zettelforge` with no git clone
  required. New package `zettelforge.mcp` (with `server.py`,
  `__main__.py`, and a console-script entry `zettelforge-mcp`).
  The previous entry point at `web/mcp_server.py` is retained as a
  thin backward-compat shim.
- **Console scripts** — `zettelforge` and `zettelforge-mcp` entry
  points added to `pyproject.toml`.
- **How-to guides** — migration (`migrate-jsonl-to-sqlite.md`),
  benchmark reproduction (`reproduce-benchmarks.md`), troubleshooting
  (`troubleshoot.md`), and upgrade (`upgrade.md`). Linked from the
  MkDocs nav.
- **Design and About sections in the docs nav** — RFC-001, RFC-002,
  RFC-003 and the origin-story narrative are now discoverable from
  `docs.threatrecall.ai`.
- **RFC-003 design proposal (docs only)** — read-path depth routing
  with a deterministic Quality Gate plus System 1 / System 2 recall
  paths. Ships with an adversarial-review artifact (4 blockers, 13
  warnings). No runtime changes yet — implementation deferred.
- **Archive directory** — `docs/archive/` holds retired v1.0.0-alpha
  snapshots (`SKILL.md`, `PACKAGE_SUMMARY.md`) with a README explaining
  their provenance.
- **`llm_ner` configuration reference** — `docs/reference/configuration.md`
  now documents `llm_ner.enabled` and the `ZETTELFORGE_LLM_NER_ENABLED`
  environment override.
- **Docs SEO foundation** — per-page canonical URLs, OpenGraph and
  Twitter-card metadata, and a `SoftwareApplication` JSON-LD block on
  the home page via a `docs/overrides/main.html` theme override. The
  `softwareVersion` value is sourced from `config.extra.version` in
  `mkdocs.yml` so it stays in sync with releases.
- **PyPI classifier refresh** — added `Topic :: Security` (primary
  filter security engineers use to browse PyPI) and
  `Topic :: Software Development :: Libraries :: Python Modules`.
  Existing `Topic :: Scientific/Engineering :: Artificial Intelligence`
  retained. Development Status stays at `4 - Beta`.
- **PyPI keyword refresh** — swapped `agent-memory` → `agentic-memory`
  (emerging category keyword) and `zettelkasten` → `llm-memory`
  (direct intent match for Mem0/Graphiti discovery traffic). Still
  10 keywords total; within the PyPI display limit.

### Changed

- **SECURITY.md** — contact updated to `contact@threatrecall.ai`,
  supported-versions table refreshed to mark `2.3.x` as current and
  `2.2.x` as the prior minor release; storage section refreshed to
  reflect SQLite-by-default.
- **`docs/llms.txt`** — rewritten to match current reality (SQLite
  default, 19 runtime entity types, correct GOV-003/007/011/012
  descriptions, MCP invocation).
- **BENCHMARK_REPORT.md** — CTIBench ATE row updated (F1 = 0.146);
  architecture summary reframed as SQLite + LanceDB default with
  TypeDB as an extension; `ctibench_results.json` date bumped.
- **README** — above-fold rewritten (CTA row, keyword density,
  PyPI-safe absolute-URL images). Pipeline step 1 entity count
  corrected from "10 types" to the 19 types `EntityExtractor`
  actually recognises.
- **README image paths** — `docs/assets/demo.gif` and
  `docs/assets/zettelforge_architecture.svg` rewritten to absolute
  `raw.githubusercontent.com` URLs so the PyPI long description
  renders correctly (relative paths 404 on the PyPI CDN). Pinned to
  the `master` ref; can be re-pinned to the `v2.3.0` tag in the
  next release PR if PyPI-side stability matters.
- **`docs/superpowers/plans/` renamed to `docs/superpowers/research/`**
  with a README making clear these are aspirational synthesis, not
  roadmap commitments. The stray untracked `docs/plans/` directory
  was removed.
- **Tutorials and governance-controls reference** — `last_updated`
  and `version` metadata refreshed.
- **`zettelforge.ontology` exports** — `TypedEntityStore`,
  `OntologyValidator`, `get_ontology_store`, `get_ontology_validator`
  removed from the top-level `__all__` (still importable from
  `zettelforge.ontology`). They are a parallel store not wired into
  `MemoryManager`.
- **`observability.py` and `cache.py` headers** — annotated as
  currently unwired; kept for future integration.
- **OCSF `_PRODUCT_VERSION`** — sourced from
  `importlib.metadata.version("zettelforge")` instead of a hard-coded
  string, so emitted OCSF events stop drifting when `__version__`
  bumps.
- **OpenGraph `og:type`** — `website` on the home page, `article`
  elsewhere (was unconditionally `article`).

### Fixed

- **OllamaProvider host routing** — now instantiates
  `ollama.Client(host=self._url)` so the configured URL actually
  takes effect (previously the module-level `ollama.generate()` call
  ignored per-instance host).
- **Provider registry race** — `register()` now checks and mutates
  under the registry lock, closing a TOCTOU window on concurrent
  provider registration.
- **MCP server lazy instantiation** — `MemoryManager` is now created
  on first tool call rather than at server import time, so `--help`
  and protocol-handshake tests don't pay the model-load cost.

### Removed

- Six superseded branches that had already been squash-merged into
  master — `feat/causal-chain-fix-and-demo-gif`,
  `feat/entity-vocabulary-expansion`,
  `feature/RFC-001-conversational-entity-extractor`,
  `fix/intent-classifier-graph-weight`,
  `fix/p0-production-blockers`, `feat/remember-evolve`.

## [2.2.0] - 2026-04-16

SQLite default backend, causal chain retrieval, memory evolution, STIX taxonomy alignment, and community-first package cleanup.

### Added

- **SQLite default backend** — SQLite (WAL mode) replaces JSONL as the default storage for notes, knowledge graph, and entity index. Zero-config, ACID guarantees. LanceDB stays for vector search. `StorageBackend` ABC (33 methods), `SQLiteBackend` (700+ lines), backend factory with auto-detection.
- **JSONL to SQLite migration script** — `scripts/migrate_jsonl_to_sqlite.py` with backup, verification, and idempotent re-runs.
- **Causal chain retrieval** — Fixed `edge_type="causal"` bug that made all LLM-extracted causal edges invisible. Added reverse traversal (`get_incoming_causal`) for "why did X happen?" queries. Bidirectional `provenance_chain()` with direction parameter.
- **Memory Evolution wired** — `MemoryEvolver` (A-Mem inspired, 255 lines) now auto-triggers after `remember()` when 3+ notes exist. Background enrichment queue dispatches evolution jobs alongside causal extraction. Public `evolve_note()` API.
- **Spec-driven governance** — `governance/controls.yaml` manifest as single source of truth. Spec-drift detection tests catch phantom controls in CI.
- **Demo GIF** — Playwright-based terminal animation in README hero.
- **LangChain retriever** — `ZettelForgeRetriever` integration for LangChain pipelines.
- **SQLite integration tests** — 5 end-to-end tests with real SQLiteBackend.
- **CODE_OF_CONDUCT.md** — Contributor Covenant v2.1.

### Changed

- **STIX 2.1 entity taxonomy** — APT/UNC/TA/FIN groups now stored as `intrusion_set` (not `actor`). `recall_actor()` searches `actor`, `threat_actor`, and `intrusion_set` for backward compatibility.
- **Web app hardened** — API key authentication required for exposed endpoints, localhost-only default, XSS fix, rate limiting, request bounds.
- **Backend defaults aligned** — `config.py`, `config.default.yaml`, `knowledge_graph.py`, tutorials, and docs all default to SQLite.
- **CI simplified** — Extension-only tests gated with `pytest.importorskip()`, no more `--ignore` flags. Backend matrix dropped fake JSONL entry.
- **Coverage threshold** — Governance doc updated from 80% to 67% to match actual enforcement.
- **CTIBench ATE** — F1 improved from 0.0 to 0.146 (fixed broken ingestion pipeline, removed ICS matrix noise).

### Fixed

- **Causal edges invisible to retrieval** — `store_causal_edges()` was not setting `edge_type="causal"` in properties, defaulting all causal edges to `"heuristic"`. `get_causal_edges()` filter found nothing.
- **Alias resolution on causal triples** — Subjects and objects now resolved before storage, preventing duplicate graph nodes.
- **Graph traversal blackout on relational queries** — FACTUAL intent was dominating CTI relational queries. Graph weight raised, RELATIONAL keywords expanded.
- **LangChain test fixture** — `persist_directory` kwarg corrected to `jsonl_path`.
- **Phantom governance controls removed** — GOV-006 (CODEOWNERS) and undocumented print() scan were in CI without spec backing.

### Removed

- One-off demo recording scripts (`record-demo-playwright.js`, `frames-to-gif.py`) — SafeSkill flagged filesystem operations.

## [2.1.1] - 2026-04-15

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
- **Extension detection** — detects optional `zettelforge-enterprise`
  package presence and enables extension features when available;
  `/api/edition` endpoint reports installed extensions
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
- Dependencies split: core vs `pip install zettelforge[extensions]`
- Extension features: TypeDB STIX ontology, OpenCTI integration,
  Sigma generation, multi-tenant auth
- Core includes full memory pipeline: blended retrieval, two-phase
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
- ZettelForge web UI (FastAPI)
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
