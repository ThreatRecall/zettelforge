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
last_updated: "2026-04-09"
version: "2.0.0"
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

### typedb

```python
@dataclass
class TypeDBConfig:
    host: str = "localhost"
    port: int = 1729
    database: str = "zettelforge"
    username: str = "admin"
    password: str = "password"
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `typedb.host` | `str` | `localhost` | `TYPEDB_HOST` | TypeDB server hostname or IP. |
| `typedb.port` | `int` | `1729` | `TYPEDB_PORT` | TypeDB server port. |
| `typedb.database` | `str` | `zettelforge` | `TYPEDB_DATABASE` | TypeDB database name. |
| `typedb.username` | `str` | `admin` | `TYPEDB_USERNAME` | TypeDB authentication username. |
| `typedb.password` | `str` | `password` | `TYPEDB_PASSWORD` | TypeDB authentication password. |

---

### backend

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `backend` | `str` | `typedb` | `ZETTELFORGE_BACKEND` | Knowledge graph backend. Values: `typedb`, `jsonl`. If `typedb` and server unreachable, falls back to `jsonl` with warning. |

---

### embedding

```python
@dataclass
class EmbeddingConfig:
    provider: str = "fastembed"
    url: str = "http://127.0.0.1:11434"
    model: str = "nomic-embed-text-v1.5-Q"
    dimensions: int = 768
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `embedding.provider` | `str` | `fastembed` | `ZETTELFORGE_EMBEDDING_PROVIDER` | Embedding provider. Values: `fastembed` (in-process ONNX, default), `ollama` (requires Ollama running at `embedding.url`). |
| `embedding.url` | `str` | `http://127.0.0.1:11434` | `AMEM_EMBEDDING_URL` | Embedding server URL. Only used when `embedding.provider` is `ollama`. |
| `embedding.model` | `str` | `nomic-embed-text-v1.5-Q` | `AMEM_EMBEDDING_MODEL` | Embedding model name. Default for fastembed: `nomic-embed-text-v1.5-Q` (768-dim, ~130 MB, ~7ms/embed). |
| `embedding.dimensions` | `int` | `768` | `ZETTELFORGE_EMBEDDING_DIM` | Vector dimensionality. **Must match the model output.** If you change the embedding model, update this value and run `rebuild_index.py` to re-embed all notes. Common values: 768 (nomic), 1024 (mxbai), 1536 (OpenAI), 4096 (qwen3). |

---

### llm

```python
@dataclass
class LLMConfig:
    provider: str = "local"
    model: str = "Qwen2.5-3B-Instruct-Q4_K_M.gguf"
    url: str = "http://localhost:11434"
    temperature: float = 0.1
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `llm.provider` | `str` | `local` | `ZETTELFORGE_LLM_PROVIDER` | LLM provider. Values: `local` (in-process llama-cpp-python, default), `ollama` (requires Ollama running at `llm.url`). |
| `llm.model` | `str` | `Qwen2.5-3B-Instruct-Q4_K_M.gguf` | `ZETTELFORGE_LLM_MODEL` | LLM for fact extraction, intent classification, causal triple extraction, and synthesis. Default for local: Qwen2.5-3B-Instruct Q4_K_M GGUF (~2.0 GB, ~15.6 tok/s). For Ollama provider, use Ollama model tags (e.g., `qwen2.5:3b`). |
| `llm.url` | `str` | `http://localhost:11434` | `ZETTELFORGE_LLM_URL` | LLM server URL. Only used when `llm.provider` is `ollama`. |
| `llm.temperature` | `float` | `0.1` | -- | Sampling temperature. `0.0` = deterministic, `0.1` = near-deterministic (default), `0.7` = creative. |

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
```

| Key | Type | Default | Env Override | Description |
|:----|:-----|:--------|:-------------|:------------|
| `governance.enabled` | `bool` | `True` | -- | Enable governance validation on `remember()` operations. Set `False` for benchmarks. |
| `governance.min_content_length` | `int` | `1` | -- | Minimum character length for content passed to `remember()`. |

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
| `opencti.token` | `str` | `""` | `OPENCTI_TOKEN` | OpenCTI API token. **Always set via `OPENCTI_TOKEN` — never commit a token to `config.yaml`.** |
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

| Variable | Maps To | Example |
|:---------|:--------|:--------|
| `AMEM_DATA_DIR` | `storage.data_dir` | `/data/zettelforge` |
| `TYPEDB_HOST` | `typedb.host` | `db.internal` |
| `TYPEDB_PORT` | `typedb.port` | `1729` |
| `TYPEDB_DATABASE` | `typedb.database` | `zettelforge` |
| `TYPEDB_USERNAME` | `typedb.username` | `admin` |
| `TYPEDB_PASSWORD` | `typedb.password` | `s3cret` |
| `ZETTELFORGE_BACKEND` | `backend` | `jsonl` |
| `ZETTELFORGE_EMBEDDING_PROVIDER` | `embedding.provider` | `ollama` |
| `AMEM_EMBEDDING_URL` | `embedding.url` | `http://gpu-box:11434` |
| `AMEM_EMBEDDING_MODEL` | `embedding.model` | `nomic-embed-text-v1.5-Q` |
| `ZETTELFORGE_LLM_PROVIDER` | `llm.provider` | `ollama` |
| `ZETTELFORGE_LLM_MODEL` | `llm.model` | `qwen2.5:7b` |
| `ZETTELFORGE_LLM_URL` | `llm.url` | `http://gpu-box:11434` |
| `OPENCTI_URL` | `Enterprise only: opencti.url` | `https://opencti.corp.internal` |
| `OPENCTI_TOKEN` | `Enterprise only: opencti.token` | `abc123...` |
| `OPENCTI_SYNC_INTERVAL` | `Enterprise only: opencti.sync_interval` | `3600` |

**Note:** The `opencti` configuration section and `OPENCTI_*` environment-variable mapping are implemented in the Enterprise package. In Community builds, these values are ignored by `src/zettelforge/config.py`.
---

## Minimal config.yaml

```yaml
storage:
  data_dir: ~/.amem

backend: jsonl

embedding:
  provider: fastembed
  model: nomic-embed-text-v1.5-Q

llm:
  provider: local
  model: Qwen2.5-3B-Instruct-Q4_K_M.gguf
```

---

## LLM Quick Reference

ZettelForge configuration uses a layered resolution system: environment variables override config.yaml, which overrides config.default.yaml, which overrides hardcoded dataclass defaults. Access configuration via `get_config()` which returns a cached `ZettelForgeConfig` singleton. Call `reload_config()` to force a re-read.

**16 environment variables** are supported, covering storage (`AMEM_DATA_DIR`), TypeDB connection (`TYPEDB_HOST`, `TYPEDB_PORT`, `TYPEDB_DATABASE`, `TYPEDB_USERNAME`, `TYPEDB_PASSWORD`), backend selection (`ZETTELFORGE_BACKEND`), embedding provider (`ZETTELFORGE_EMBEDDING_PROVIDER`, `AMEM_EMBEDDING_URL`, `AMEM_EMBEDDING_MODEL`), LLM provider (`ZETTELFORGE_LLM_PROVIDER`, `ZETTELFORGE_LLM_MODEL`, `ZETTELFORGE_LLM_URL`), and OpenCTI integration (`OPENCTI_URL`, `OPENCTI_TOKEN`, `OPENCTI_SYNC_INTERVAL`).

**12 config sections** exist: `storage` (data directory), `typedb` (connection parameters), `backend` (typedb or jsonl), `embedding` (vector model and server), `llm` (language model for extraction/synthesis), `extraction` (two-phase pipeline settings), `retrieval` (vector search tuning), `synthesis` (RAG output control), `governance` (validation toggle), `cache` (TypeDB query cache), `logging` (verbosity control), and `opencti` (Enterprise only — OpenCTI platform URL, token, and sync interval).

**Key defaults:** Data stored in `~/.amem`. TypeDB on `localhost:1729`. Embedding via fastembed in-process with `nomic-embed-text-v1.5-Q` (768 dims, ONNX). LLM via llama-cpp-python in-process with `Qwen2.5-3B-Instruct-Q4_K_M.gguf` at temperature 0.1. Models download automatically on first use. Extraction produces up to 5 facts with importance >= 3. Retrieval returns 10 results with 0.25 similarity threshold and 2.5x entity boost. Synthesis uses `direct_answer` format with A+B tier notes and 3000 token context. Cache TTL is 300 seconds with 1024 max entries. Logging at INFO level.

**For air-gapped deployments:** Set `backend: jsonl` to avoid the TypeDB dependency entirely. With the default `fastembed` and `local` providers, the JSONL backend stores the knowledge graph as local files with no external services required at all. Pre-download models before going offline.
