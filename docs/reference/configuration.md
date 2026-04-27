---
title: "Configuration Reference"
description: "All configuration keys, types, defaults, and environment variable overrides for ZettelForge. Covers storage, TypeDB, embedding, LLM, extraction, retrieval, synthesis, governance, cache, and logging sections."
diataxis_type: "reference"
audience: "Senior CTI Practitioner"
tags:
  - configuration
  - environment-variables
  - settings
  - deployment
last_updated: "2026-04-25"
version: "2.6.0"
---

# Configuration Reference

Module: `zettelforge.config`

```python
from zettelforge.config import get_config, reload_config, ZettelForgeConfig
```

---

## Resolution Order

Configuration values are resolved with highest priority first:

| Priority | Source | Example |
|:---------|:-------|:--------|
| 1 (highest) | Environment variables | `TYPEDB_HOST=db.internal` |
| 2 | `config.yaml` in working directory | `./config.yaml` |
| 3 | `config.yaml` in project root | `<project>/config.yaml` |
| 4 | `config.default.yaml` in project root | `<project>/config.default.yaml` |
| 5 (lowest) | Hardcoded defaults in `config.py` | Dataclass field defaults |

---

## Config Access

```python
cfg = get_config()        # Load once, cached singleton
cfg = reload_config()     # Force reload from file + env

cfg.typedb.host           # "localhost"
cfg.retrieval.default_k   # 10
cfg.backend               # "typedb"
```

---

## All Configuration Keys

### storage

```python
@dataclass
class StorageConfig:
    data_dir: str = "~/.amem"
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `storage.data_dir` | `str` | `~/.amem` | `AMEM_DATA_DIR` | Root directory for LanceDB vectors, JSONL notes, entity indexes, and snapshots. |

---

### typedb (zettelforge-enterprise only)

```python
@dataclass
class TypeDBConfig:
    host: str = "localhost"
    port: int = 1729
    database: str = "zettelforge"
    username: str = ""
    password: str = ""
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `typedb.host` | `str` | `localhost` | `TYPEDB_HOST` | TypeDB server hostname or IP. |
| `typedb.port` | `int` | `1729` | `TYPEDB_PORT` | TypeDB server port. |
| `typedb.database` | `str` | `zettelforge` | `TYPEDB_DATABASE` | TypeDB database name. |
| `typedb.username` | `str` | `""` | `TYPEDB_USERNAME` | TypeDB authentication username. Supply via env var or `${TYPEDB_USERNAME}` in config.yaml. |
| `typedb.password` | `str` | `""` | `TYPEDB_PASSWORD` | TypeDB authentication password. Supply via env var or `${TYPEDB_PASSWORD}` in config.yaml. |

---

### backend

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `backend` | `str` | `sqlite` | `ZETTELFORGE_BACKEND` | Storage backend for notes, knowledge graph, and entity index. Community uses `sqlite`. TypeDB is extension-only. Legacy JSONL data should be migrated to SQLite. |

---

### embedding

```python
@dataclass
class EmbeddingConfig:
    provider: str = "fastembed"
    url: str = "http://127.0.0.1:11434"
    model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
    dimensions: int = 768
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `embedding.provider` | `str` | `fastembed` | `ZETTELFORGE_EMBEDDING_PROVIDER` | Embedding provider. Values: `fastembed` (in-process ONNX, default), `ollama` (requires Ollama running at `embedding.url`). |
| `embedding.url` | `str` | `http://127.0.0.1:11434` | `AMEM_EMBEDDING_URL` | Embedding server URL. Only used when `embedding.provider` is `ollama`. |
| `embedding.model` | `str` | `nomic-ai/nomic-embed-text-v1.5-Q` | `AMEM_EMBEDDING_MODEL` | Embedding model name. Must be a fastembed-supported identifier (full HF form such as `nomic-ai/nomic-embed-text-v1.5-Q` for fastembed; Ollama tags like `nomic-embed-text` when `provider=ollama`). Default is `nomic-ai/nomic-embed-text-v1.5-Q` (768-dim, ~130 MB, ~7 ms/embed). |
| `embedding.dimensions` | `int` | `768` | `ZETTELFORGE_EMBEDDING_DIM` | Vector dimensionality. **Must match the model output.** If you change the embedding model, update this value and run `rebuild_index.py` to re-embed all notes. Common values: 768 (nomic), 1024 (mxbai), 1536 (OpenAI), 4096 (qwen3). |

---

### llm

```python
@dataclass
class LLMConfig:
    provider: str = "ollama"
    model: str = "qwen3.5:9b"
    url: str = "http://localhost:11434"
    api_key: str = ""              # supports ${ENV_VAR} references
    temperature: float = 0.1
    timeout: float = 180.0    # v2.5.2 — reasoning-model headroom
    max_retries: int = 2
    fallback: str = ""             # "" preserves implicit local->ollama fallback
    local_backend: str = "llama-cpp-python"  # RFC-011
    extra: dict = field(default_factory=dict)
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `llm.provider` | `str` | `ollama` | `ZETTELFORGE_LLM_PROVIDER` | LLM provider name. Values shipped in core: `local` (in-process inference), `ollama` (HTTP), `litellm` (LiteLLM router to 100+ providers via `zettelforge[litellm]`), `mock` (tests only). Third-party providers register via the `zettelforge.llm_providers` entry point. |
| `llm.model` | `str` | `qwen3.5:9b` | `ZETTELFORGE_LLM_MODEL` | Model identifier. Meaning is provider-specific: Ollama tag (`qwen2.5:3b`), HuggingFace repo for local (`Qwen/Qwen2.5-3B-Instruct-GGUF`), LiteLLM model name (`gpt-4o`, `claude-sonnet-4-20250514`, `gemini/gemini-2.0-flash`), OpenAI-compatible model name, or Anthropic model ID. |
| `llm.url` | `str` | `http://localhost:11434` | `ZETTELFORGE_LLM_URL` | Base URL. Meaning is provider-specific -- Ollama endpoint for `ollama`, `/v1/chat/completions` base for `openai_compat`, ignored for `local` and `litellm`. |
| `llm.api_key` | `str` | `""` | `ZETTELFORGE_LLM_API_KEY` | API key for authenticated providers (`litellm`, `openai_compat`). Accepts `${ENV_VAR}` references -- never commit raw keys. Redacted from `repr(LLMConfig)`. For `litellm`, you may also rely on standard environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) instead of config. |
| `llm.temperature` | `float` | `0.1` | -- | Sampling temperature. `0.0` = deterministic, `0.1` = near-deterministic (default), `0.7` = creative. |
| `llm.timeout` | `float` | `180.0` | `ZETTELFORGE_LLM_TIMEOUT` | Request timeout in seconds. Applied by `ollama` (RFC-010) and `litellm` providers. **Bumped 60s → 180s in v2.5.2** because reasoning-model generations at the per-call-site `max_tokens` budgets routinely take 60–140s on a 9B-Q4_K_M model and the old default was firing `ReadTimeout` mid-generation. Lower this only on faster hardware where you've measured the 99th-percentile call duration. |
| `llm.max_retries` | `int` | `2` | `ZETTELFORGE_LLM_MAX_RETRIES` | Number of retries on transient failure. Applied by `litellm` (via `num_retries` kwarg). |
| `llm.fallback` | `str` | `""` | `ZETTELFORGE_LLM_FALLBACK` | Backup provider invoked when the primary fails with a non-configuration error. Empty string preserves the implicit `local -> ollama` fallback for backward compatibility; set explicitly to any other registered provider to route elsewhere. |
| `llm.local_backend` | `str` | `llama-cpp-python` | `ZETTELFORGE_LLM_LOCAL_BACKEND` | In-process inference engine when `provider: local`. Options: `llama-cpp-python` (GGUF, default, requires `zettelforge[local]`), `onnxruntime-genai` (ONNX, requires `zettelforge[local-onnx]`). Ignored for all other providers. |
| `llm.extra` | `dict` | `{}` | -- | Provider-specific kwargs forwarded to the constructor. String values inside `extra` also honour `${ENV_VAR}` resolution. Common uses: `{filename: qwen2.5-3b-instruct-q4_k_m.gguf, n_ctx: 4096}` for `local` provider; `{provider: rocm}` for `onnxruntime-genai` execution provider selection; `{drop_params: true}` for `litellm`. |

#### Provider quick-reference

| Provider | Install | Config Example | Model Format | Notes |
|:---------|:--------|:---------------|:-------------|:------|
| `local` | `pip install zettelforge[local]` | `provider: local` + `local_backend: llama-cpp-python` | HuggingFace GGUF repo ID | In-process, fully offline. See `local_backend` for engine selection. |
| `local` + onnx | `pip install zettelforge[local-onnx]` | `provider: local` + `local_backend: onnxruntime-genai` | HuggingFace ONNX repo ID | In-process, ROCm/DirectML/CoreML support. |
| `ollama` | core (no extra) | `provider: ollama` + `url: http://localhost:11434` | Ollama tag (`qwen3.5:9b`) | Requires `ollama serve` running. |
| `litellm` | `pip install zettelforge[litellm]` | `provider: litellm` + `model: gpt-4o` | LiteLLM model name | Routes to 100+ providers by model prefix. |
| `mock` | core (no extra) | `provider: mock` | N/A | Deterministic canned responses for testing. |

#### Per-call-site `max_tokens` budgets (v2.6.0: config-driven)

`llm.timeout` is config-driven. v2.6.0 moved `max_tokens` (Ollama `num_predict`) values to `LLMConfig`, making them config-overridable per call site. v2.5.2 raised these caps to give reasoning models (qwen3.5+, qwen3.6, nemotron-3) room to emit their hidden `<think>...</think>` tokens *and* a final answer; pre-2.5.2 caps were exhausted entirely by reasoning, leaving the JSON answer empty.

| Call site | File | Budget | Why |
|:----------|:-----|:-------|:----|
| Causal triple extraction (`note_constructor.extract_causal_triples`) | `note_constructor.py` | **8000** | Highest in the codebase. Asks the model to enumerate *every* causal relation in a passage; reasoning chain is longest. |
| Synthesis (`synthesis_generator._generate_synthesis`) | `synthesis_generator.py` | 2500 | Single-answer prompt; reasoning overhead is moderate. |
| Fact extraction (`fact_extractor.extract`) | `fact_extractor.py` | 2500 | Multi-fact JSON enumeration. |
| LLM NER (`entity_indexer._extract_via_llm`, retry path) | `entity_indexer.py` | 2500 | Conversational entity types only; regex covers CTI types separately. |
| Memory evolution (`memory_evolver.evolve_neighbors` and retry) | `memory_evolver.py` | 2500 | Two-note comparison + decision JSON. |

**Operational impact.** Causal extraction at 8000 tokens runs 60–140 s per call on a 9B-Q4_K_M reasoning model; `remember(sync=True)` therefore blocks 1–3 minutes per note. The default async path (background enrichment queue) is unaffected — these calls happen off the write hot path. If you're triggering `sync=True` or doing bulk ingestion you'll feel the latency; switch to async or scale up the model server.

If you're on faster hardware or smaller non-reasoning models you can monkey-patch lower values, but the 2.5.2 defaults trade latency for correctness on the reference qwen3.5:9b setup. v2.6.0 moves these to `LLMConfig` so you can override per call site without touching code — see [issue #125](https://github.com/rolandpg/zettelforge/issues/125).

#### LiteLLM model prefix examples

LiteLLM routes requests to the correct provider based on model name prefix. The `model` field determines the backend automatically -- no separate config needed.

| Model Name | Routes To | Required Env Var |
|:-----------|:----------|:-----------------|
| `gpt-4o`, `gpt-4o-mini` | OpenAI | `OPENAI_API_KEY` |
| `claude-sonnet-4-20250514` | Anthropic | `ANTHROPIC_API_KEY` |
| `gemini/gemini-2.0-flash` | Google Gemini | `GOOGLE_API_KEY` |
| `groq/llama-3.3-70b-versatile` | Groq | `GROQ_API_KEY` |
| `together_ai/meta-llama/Llama-3.3-70B` | Together AI | `TOGETHER_API_KEY` |
| `openrouter/anthropic/claude-3.5-sonnet` | OpenRouter | `OPENROUTER_API_KEY` |
| `bedrock/anthropic.claude-3-sonnet-v1` | AWS Bedrock | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` |
| `vertex_ai/claude-3-sonnet@20240229` | Google Vertex | `GOOGLE_APPLICATION_CREDENTIALS` |

---

### llm_ner

```python
@dataclass
class LLMNerConfig:
    enabled: bool = True
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `llm_ner.enabled` | `bool` | `True` | `ZETTELFORGE_LLM_NER_ENABLED` | Enable always-on LLM Named Entity Recognition. When `True`, every `remember()` call enqueues a background LLM NER job that augments the fast regex-based entity extraction with conversational entities (`person`, `location`, `organization`, `event`, `activity`, `temporal`). Fast-path writes still return in ~45 ms; LLM NER runs asynchronously via the enrichment queue and merges into the note's entity set when it completes. Set `False` for air-gapped or benchmark runs that need deterministic regex-only extraction. |

---

### extraction

```python
@dataclass
class ExtractionConfig:
    max_facts: int = 5
    min_importance: int = 3
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `extraction.max_facts` | `int` | `5` | -- | Maximum facts extracted per `remember_with_extraction()` call. |
| `extraction.min_importance` | `int` | `3` | -- | Facts scored below this threshold are discarded. Range: 1--10. |

---

### retrieval

```python
@dataclass
class RetrievalConfig:
    default_k: int = 10
    similarity_threshold: float = 0.25
    entity_boost: float = 2.5
    max_graph_depth: int = 2
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `retrieval.default_k` | `int` | `10` | -- | Default number of results for `recall()`. |
| `retrieval.similarity_threshold` | `float` | `0.25` | -- | Minimum cosine similarity to include a vector result (0.0--1.0). Note: VectorRetriever constructor overrides this to `0.15` at runtime. |
| `retrieval.entity_boost` | `float` | `2.5` | -- | Multiplicative boost per overlapping entity between query and note. |
| `retrieval.max_graph_depth` | `int` | `2` | -- | Maximum BFS hops in the knowledge graph. |

---

### synthesis

```python
@dataclass
class SynthesisConfig:
    max_context_tokens: int = 3000
    default_format: str = "direct_answer"
    tier_filter: List[str] = field(default_factory=lambda: ["A", "B"])
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `synthesis.max_context_tokens` | `int` | `3000` | -- | Maximum tokens in the synthesis context window. |
| `synthesis.default_format` | `str` | `direct_answer` | -- | Default synthesis output format. Values: `direct_answer`, `synthesized_brief`, `timeline_analysis`, `relationship_map`. |
| `synthesis.tier_filter` | `List[str]` | `["A", "B"]` | -- | Epistemic tiers to include. `A` = authoritative, `B` = operational, `C` = support. |

---

### governance

```python
@dataclass
class GovernanceConfig:
    enabled: bool = True
    min_content_length: int = 1
    pii: PIIConfig = field(default_factory=PIIConfig)
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `governance.enabled` | `bool` | `True` | -- | Enable governance validation on `remember()` operations. Set `False` for benchmarks. |
| `governance.min_content_length` | `int` | `1` | -- | Minimum character length for content passed to `remember()`. |

#### governance.pii (RFC-013, optional)

```python
@dataclass
class PIIConfig:
    enabled: bool = False
    action: str = "log"
    redact_placeholder: str = "[REDACTED]"
    entities: list[str] = field(default_factory=list)
    language: str = "en"
    nlp_model: str = "en_core_web_sm"
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `governance.pii.enabled` | `bool` | `False` | `ZETTELFORGE_PII_ENABLED` | Enable Microsoft Presidio PII detection during `remember()`. Soft dependency -- requires `pip install zettelforge[pii]` to activate. With `enabled=true` but the SDK missing, `GovernanceValidator` logs `pii_validator_unavailable` at WARNING and continues with `_pii=None` (every PII codepath becomes a no-op pass-through). |
| `governance.pii.action` | `str` | `log` | `ZETTELFORGE_PII_ACTION` | Policy when PII is detected: `log` (warn-only, content passes through unchanged), `redact` (replace each finding with `redact_placeholder` before storage), or `block` (raise `PIIBlockedError` and refuse the write). |
| `governance.pii.redact_placeholder` | `str` | `[REDACTED]` | -- | String substituted for each PII span when `action=redact`. |
| `governance.pii.entities` | `list[str]` | `[]` (= all) | -- | Entity types to detect. Empty list = detect every Presidio-supported type. CTI allowlist (`IP_ADDRESS`, `URL`, `DOMAIN_NAME`) is always filtered out automatically since these are legitimate threat-intel indicators, not personal data. |
| `governance.pii.language` | `str` | `en` | -- | Two-letter language code passed to Presidio's analyzer. |
| `governance.pii.nlp_model` | `str` | `en_core_web_sm` | -- | spaCy NLP model name. Larger models (`en_core_web_lg`) catch more entities at the cost of memory and warm-up time. |

See [Configure PII Detection](../how-to/configure-pii.md) for the full Presidio setup guide.

#### governance.limits (RFC-014)

```python
@dataclass
class LimitsConfig:
    max_content_length: int = 52428800
    recall_timeout_seconds: float = 30.0
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `governance.limits.max_content_length` | `int` | `52428800` | `ZETTELFORGE_LIMITS_MAX_CONTENT_LENGTH` | Maximum content length in bytes for `remember()`. 0 = unlimited. 50 MB default. |
| `governance.limits.recall_timeout_seconds` | `float` | `30.0` | `ZETTELFORGE_LIMITS_RECALL_TIMEOUT` | Maximum seconds for a recall() query. 0 = unlimited. |

---

### web (RFC-015)

### lance (RFC-009 Phase 1.5)

```python
@dataclass
class LanceConfig:
    cleanup_interval_minutes: int = 60
    cleanup_older_than_seconds: int = 3600
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `lance.cleanup_interval_minutes` | `int` | `60` | -- | How often the LanceDB version-prune daemon wakes per shard. **Set `0` to disable the daemon entirely** -- use only for diagnostics or when an external compaction process owns the data dir. |
| `lance.cleanup_older_than_seconds` | `int` | `3600` | -- | Minimum age of a LanceDB version before it becomes prune-eligible. Lower values reclaim disk faster but increase the chance of pruning a version a concurrent reader is still using. The 3600 s (1 h) default is the conservative value validated against the 2026-04-24 Vigil incident; **do not lower below 600 s** without measuring concurrent-reader behaviour first. |

**Operational impact.** Without this daemon, every `remember()` write appends an immutable version row to LanceDB. Over weeks of writes the version chain grows to multi-gigabyte overhead that quintuples `remember()` p95 latency (Vigil 2026-04-24: 5.66 GB version-chain -> `remember()` p95 = 49.8 s; one-shot `cleanup_old_versions` shrank to 29 MB -> p95 = 250 ms). The daemon ships enabled by default -- you only need to touch this section if you've moved compaction to an out-of-process job.

---

### web (RFC-015)

```python
@dataclass
class WebConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8088
    ui_dir: str = ""
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `web.enabled` | `bool` | `True` | `ZETTELFORGE_WEB_ENABLED` | Enable the web management interface. Set `False` for library-only deployments. |
| `web.host` | `str` | `0.0.0.0` | -- | Bind address for the FastAPI server. |
| `web.port` | `int` | `8088` | `ZETTELFORGE_WEB_PORT` | Port for the FastAPI server. |
| `web.ui_dir` | `str` | `""` | `ZETTELFORGE_WEB_UI_DIR` | Custom path to the SPA UI directory. Empty = `web/ui/` relative to project root. |

See [Use the Web Management Interface](../how-to/use-web-interface.md) for setup steps and [Web API Reference](web-api.md) for endpoint documentation.

---

### cache

```python
@dataclass
class CacheConfig:
    ttl_seconds: int = 300
    max_entries: int = 1024
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `cache.ttl_seconds` | `int` | `300` | -- | Cache entry time-to-live in seconds. Set `0` to disable caching. |
| `cache.max_entries` | `int` | `1024` | -- | Maximum cache entries. Set `0` to disable caching. |

---

### logging

```python
@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_intents: bool = True
    log_causal: bool = True
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `logging.level` | `str` | `INFO` | -- | Minimum log level. Values: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `logging.log_intents` | `bool` | `True` | -- | Log intent classification results during `recall()`. |
| `logging.log_causal` | `bool` | `True` | -- | Log causal triple extraction results during `remember()`. |

---

### opencti

> [!NOTE]
> This section is only active in **ZettelForge Enterprise**. It has no effect in the Community edition.

```python
@dataclass
class OpenCTIConfig:
    url: str = "http://localhost:8080"
    token: str = ""
    sync_interval: int = 0
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `opencti.url` | `str` | `http://localhost:8080` | `OPENCTI_URL` | Base URL of the OpenCTI platform. Use `https://` for cloud deployments. |
| `opencti.token` | `str` | `""` | `OPENCTI_TOKEN` | OpenCTI API token. **Always set via `OPENCTI_TOKEN` -- never commit a token to `config.yaml`.** |
| `opencti.sync_interval` | `int` | `0` | `OPENCTI_SYNC_INTERVAL` | Seconds between automatic pulls from OpenCTI. Set `0` to disable auto-sync and pull manually. |

**Minimal opencti config.yaml block:**

```yaml
opencti:
  url: http://localhost:8080
  token: ""            # Set via OPENCTI_TOKEN env var
  sync_interval: 3600  # Pull every hour; 0 = manual only
```

**Supported entity types for pull/push:**

| Entity Type | Pull | Push | Structured Fields |
|:------------|:----:|:----:|:------------------|
| `attack_pattern` | yes | -- | MITRE ATT&CK ID, tactic |
| `intrusion_set` | yes | -- | Aliases, motivation, resource level |
| `threat_actor` | yes | -- | Aliases, sophistication |
| `malware` | yes | -- | Types, implementation languages, is_family |
| `indicator` | yes | -- | STIX pattern, valid_from, valid_until |
| `vulnerability` | yes | -- | CVSS v3 score/vector, EPSS score/percentile, CISA KEV |
| `report` | yes | yes | Publication date, confidence, object_refs |

All entities preserve `tlp` (TLP marking label: `WHITE`, `GREEN`, `AMBER`, or `RED`) and `stix_confidence` (STIX integer 0–100; `-1` when unset in OpenCTI).

See [Configure OpenCTI Integration](../how-to/configure-opencti.md) for setup steps, pull/push examples, and troubleshooting.

---

## Environment Variables Summary

### General configuration

| Variable | Maps To | Example |
|:---------|:--------|:--------|
| `AMEM_DATA_DIR` | `storage.data_dir` | `/data/zettelforge` |
| `TYPEDB_HOST` | `typedb.host` | `db.internal` |
| `TYPEDB_PORT` | `typedb.port` | `1729` |
| `TYPEDB_DATABASE` | `typedb.database` | `zettelforge` |
| `TYPEDB_USERNAME` | `typedb.username` | `admin` |
| `TYPEDB_PASSWORD` | `typedb.password` | `s3cret` |
| `ZETTELFORGE_BACKEND` | `backend` | `sqlite` |
| `ZETTELFORGE_EMBEDDING_PROVIDER` | `embedding.provider` | `ollama` |
| `AMEM_EMBEDDING_URL` | `embedding.url` | `http://gpu-box:11434` |
| `AMEM_EMBEDDING_MODEL` | `embedding.model` | `nomic-embed-text-v1.5-Q` |
| `ZETTELFORGE_LLM_NER_ENABLED` | `llm_ner.enabled` | `true` |

### LLM configuration

| Variable | Maps To | Example |
|:---------|:--------|:--------|
| `ZETTELFORGE_LLM_PROVIDER` | `llm.provider` | `litellm` |
| `ZETTELFORGE_LLM_MODEL` | `llm.model` | `gpt-4o` |
| `ZETTELFORGE_LLM_URL` | `llm.url` | `http://gpu-box:11434` |
| `ZETTELFORGE_LLM_API_KEY` | `llm.api_key` | `sk-...` |
| `ZETTELFORGE_LLM_TIMEOUT` | `llm.timeout` | `180` |
| `ZETTELFORGE_LLM_MAX_RETRIES` | `llm.max_retries` | `2` |
| `ZETTELFORGE_LLM_FALLBACK` | `llm.fallback` | `ollama` |
| `ZETTELFORGE_LLM_LOCAL_BACKEND` | `llm.local_backend` | `onnxruntime-genai` |

### Web UI configuration (RFC-015)

| Variable | Maps To | Example |
|:---------|:--------|:--------|
| `ZETTELFORGE_WEB_ENABLED` | `web.enabled` | `true` |
| `ZETTELFORGE_WEB_PORT` | `web.port` | `8088` |
| `ZETTELFORGE_WEB_UI_DIR` | `web.ui_dir` | `/opt/zettelforge/ui` |

### Enterprise-only (OpenCTI)

| Variable | Maps To | Example |
|:---------|:--------|:--------|
| `OPENCTI_URL` | `opencti.url` | `https://opencti.corp.internal` |
| `OPENCTI_TOKEN` | `opencti.token` | `abc123...` |
| `OPENCTI_SYNC_INTERVAL` | `opencti.sync_interval` | `3600` |

**Note:** The `opencti` configuration section and `OPENCTI_*` environment-variable mapping are implemented in the Enterprise package. In Community builds, these values are ignored by `src/zettelforge/config.py`.

---

## Minimal config.yaml

```yaml
storage:
  data_dir: ~/.amem

backend: sqlite

embedding:
  provider: fastembed
  model: nomic-embed-text-v1.5-Q

llm:
  provider: local
  model: Qwen2.5-3B-Instruct-Q4_K_M.gguf
```

---

## Example Configurations by Use Case

### Local in-process (fully offline, default)

```yaml
llm:
  provider: local
  model: Qwen/Qwen2.5-3B-Instruct-GGUF
  extra:
    filename: qwen2.5-3b-instruct-q4_k_m.gguf
    n_ctx: 4096
```

### Local in-process with ONNX (AMD GPU)

```yaml
llm:
  provider: local
  local_backend: onnxruntime-genai
  model: microsoft/Phi-3-mini-4k-instruct-onnx
  extra:
    filename: phi3-mini-4k-instruct-q4.onnx
    provider: rocm
```

### Ollama (default config)

```yaml
llm:
  provider: ollama
  model: qwen3.5:9b
  url: http://localhost:11434
```

### LiteLLM -- OpenAI

```yaml
llm:
  provider: litellm
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}
```

### LiteLLM -- Anthropic

```yaml
llm:
  provider: litellm
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
```

### LiteLLM -- multiple providers via environment variables

```yaml
llm:
  provider: litellm
  model: gpt-4o            # Switch model to change provider
  # API keys read from env: OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.
```

### LiteLLM -- Groq (fast inference)

```yaml
llm:
  provider: litellm
  model: groq/llama-3.3-70b-versatile
  api_key: ${GROQ_API_KEY}
```

---

## LLM Quick Reference

ZettelForge configuration uses a layered resolution system: environment variables override config.yaml, which overrides config.default.yaml, which overrides hardcoded dataclass defaults. Access configuration via `get_config()` which returns a cached `ZettelForgeConfig` singleton. Call `reload_config()` to force a re-read.

**21 environment variables** are supported, covering storage (`AMEM_DATA_DIR`), TypeDB connection (`TYPEDB_HOST`, `TYPEDB_PORT`, `TYPEDB_DATABASE`, `TYPEDB_USERNAME`, `TYPEDB_PASSWORD`), backend selection (`ZETTELFORGE_BACKEND`), embedding provider (`ZETTELFORGE_EMBEDDING_PROVIDER`, `AMEM_EMBEDDING_URL`, `AMEM_EMBEDDING_MODEL`), LLM provider (`ZETTELFORGE_LLM_PROVIDER`, `ZETTELFORGE_LLM_MODEL`, `ZETTELFORGE_LLM_URL`, `ZETTELFORGE_LLM_API_KEY`, `ZETTELFORGE_LLM_TIMEOUT`, `ZETTELFORGE_LLM_MAX_RETRIES`, `ZETTELFORGE_LLM_FALLBACK`, `ZETTELFORGE_LLM_LOCAL_BACKEND`), web UI (`ZETTELFORGE_WEB_ENABLED`, `ZETTELFORGE_WEB_PORT`, `ZETTELFORGE_WEB_UI_DIR`), and OpenCTI integration (`OPENCTI_URL`, `OPENCTI_TOKEN`, `OPENCTI_SYNC_INTERVAL`).

**14 config sections** exist: `storage` (data directory), `typedb` (Enterprise TypeDB connection parameters), `backend` (community default: sqlite), `embedding` (vector model and server), `llm` (language model for extraction/synthesis with provider, model, API key, timeout, retry, fallback, local_backend, and extra), `extraction` (two-phase pipeline settings), `retrieval` (vector search tuning), `synthesis` (RAG output control), `governance` (validation toggle with pii and limits subsections), `cache` (query cache), `logging` (verbosity control), `lance` (LanceDB maintenance), `web` (web management interface host/port/ui_dir), and `opencti` (Enterprise only -- OpenCTI platform URL, token, and sync interval).

**Key defaults:** Data stored in `~/.amem`. Backend is SQLite (TypeDB available via zettelforge-enterprise extension). Embedding via fastembed in-process with `nomic-embed-text-v1.5-Q` (768 dims, ONNX). LLM via Ollama at `http://localhost:11434` with `qwen3.5:9b` at temperature 0.1. The `local` provider uses `llama-cpp-python` in-process with `Qwen2.5-3B-Instruct-Q4_K_M.gguf`. Models download automatically on first use. The `litellm` provider (optional, `pip install zettelforge[litellm]`) routes to 100+ providers by model name prefix. Extraction produces up to 5 facts with importance >= 3. Retrieval returns 10 results with 0.25 similarity threshold and 2.5x entity boost. Synthesis uses `direct_answer` format with A+B tier notes and 3000 token context. Cache TTL is 300 seconds with 1024 max entries. Logging at INFO level.

**For air-gapped deployments:** Keep `backend: sqlite` and use `provider: local` with `llama-cpp-python` or `onnxruntime-genai`. Pre-download embedding and LLM models before going offline. Legacy JSONL files are migration input, not the community default backend.

**For cloud-connected deployments:** Use `provider: litellm` with `pip install zettelforge[litellm]` to access OpenAI, Anthropic, Google, Groq, Together AI, AWS Bedrock, and 100+ other providers through a single interface. Set `api_key` in config or rely on standard environment variables.
