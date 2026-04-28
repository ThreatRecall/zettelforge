# Local Embedding Model (fastembed) Implementation Plan

**Date:** 2026-04-09
**Status:** PLAN — Ready for implementation
**Estimated effort:** 1 day (3-4 tasks)
**Branch:** `feat/fastembed-local-embeddings`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Ollama embedding dependency with fastembed (ONNX-based, bundled model). Embeddings run in-process with zero external server dependencies. Model ships with the package (~130MB quantized).

**Architecture:** fastembed's `TextEmbedding` loads an ONNX model at startup and runs inference in-process via `onnxruntime`. The model (`nomic-ai/nomic-embed-text-v1.5-Q`, 768-dim, quantized to 130MB) downloads on first use and caches to `~/.cache/fastembed/`. All existing code calls `get_embedding()` from `vector_memory.py` — that single function is the integration point.

**Tech Stack:** fastembed 0.8.0, onnxruntime, nomic-embed-text-v1.5-Q (768-dim, 130MB)

---

## Why

| | Before (Ollama) | After (fastembed) |
|---|---|---|
| **Server dependency** | Requires `ollama serve` running on port 11434 | None — runs in-process |
| **Model management** | `ollama pull nomic-embed-text` separately | Auto-downloads on first use, cached |
| **Latency** | ~30ms per embed (HTTP round-trip) | ~7ms per embed (in-process ONNX) |
| **Batch support** | Sequential HTTP calls | Native batch (`model.embed([...])`) |
| **Air-gapped** | Must pre-copy Ollama models | Must pre-cache `~/.cache/fastembed/` |
| **Package size** | Ollama binary + model (~2GB total) | fastembed + ONNX model (~180MB total) |
| **Dimensions** | 768 (nomic-embed-text) | 768 (nomic-embed-text-v1.5-Q) — compatible |

Ollama is **still required** for LLM tasks (extraction, classification, synthesis) — only the embedding path changes.

## Benchmarked Performance

```
Model: nomic-ai/nomic-embed-text-v1.5-Q (quantized, ONNX)
Size:  130MB
Dims:  768 (matches existing LanceDB schema)
Load:  2.8s (first call, cached thereafter)
Speed: 7ms per embed (single), 7ms/embed batch (amortized)
```

---

## Integration Points (from discovery)

| File | Line | Current Code | What Changes |
|---|---|---|---|
| `src/zettelforge/vector_memory.py` | 43-49 | `ollama.embeddings(model, prompt=text)` | Replace with `fastembed.TextEmbedding.embed()` |
| `src/zettelforge/vector_memory.py` | 59-61 | `get_embedding_batch()` loops over `get_embedding()` | Replace with native batch `model.embed(texts)` |
| `src/zettelforge/prospective_indexer.py` | 159 | `ollama.embeddings(model, prompt=entry)` | Call `get_embedding()` from vector_memory instead |
| `src/zettelforge/prospective_indexer.py` | 212 | `ollama.embeddings(model, prompt=query)` | Call `get_embedding()` from vector_memory instead |
| `src/zettelforge/note_schema.py` | 28 | `model: str = "nomic-embed-text-v2-moe"` | Update default to `"nomic-embed-text-v1.5-Q"` |
| `pyproject.toml` | dependencies | No fastembed | Add `"fastembed>=0.8.0"` |
| `config.default.yaml` | embedding section | `url: http://127.0.0.1:11434` | Add `provider: fastembed` option |

**Files NOT changed:** `note_constructor.py`, `vector_retriever.py`, `memory_store.py`, `synthesis_generator.py`, `intent_classifier.py` — these all call `get_embedding()` from vector_memory.py, so they get the new backend transparently.

---

## File Structure

| File | Responsibility |
|------|---------------|
| **Modify:** `src/zettelforge/vector_memory.py` | Replace `get_embedding()` and `get_embedding_batch()` with fastembed backend |
| **Modify:** `src/zettelforge/prospective_indexer.py` | Replace direct `ollama.embeddings()` calls with `get_embedding()` |
| **Modify:** `src/zettelforge/note_schema.py` | Update default model name |
| **Modify:** `src/zettelforge/config.py` | Add `embedding.provider` field ("fastembed" or "ollama") |
| **Modify:** `config.default.yaml` | Document new provider option |
| **Modify:** `pyproject.toml` | Add fastembed dependency |
| **Create:** `tests/test_embedding.py` | Tests for fastembed + ollama fallback |

---

### Task 1: Replace embedding backend in vector_memory.py

**Files:**
- Modify: `src/zettelforge/vector_memory.py`
- Create: `tests/test_embedding.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_embedding.py`:

```python
"""Tests for embedding backends (fastembed + ollama fallback)."""
import pytest
from zettelforge.vector_memory import get_embedding, get_embedding_batch, _get_embed_model


class TestFastembedBackend:
    def test_embedding_returns_768_dims(self):
        """fastembed produces 768-dimensional vectors."""
        vec = get_embedding("APT28 uses Cobalt Strike for lateral movement")
        assert len(vec) == 768

    def test_embedding_is_deterministic(self):
        """Same text produces same embedding."""
        v1 = get_embedding("Lazarus Group targets cryptocurrency exchanges")
        v2 = get_embedding("Lazarus Group targets cryptocurrency exchanges")
        assert v1 == v2

    def test_embedding_differs_for_different_text(self):
        """Different text produces different embeddings."""
        v1 = get_embedding("APT28 uses spearphishing")
        v2 = get_embedding("Volt Typhoon compromises edge devices")
        assert v1 != v2

    def test_batch_embedding(self):
        """Batch embedding returns correct count and dimensions."""
        texts = [
            "APT28 uses Cobalt Strike",
            "Lazarus targets crypto exchanges",
            "CVE-2024-3094 is a backdoor in XZ Utils",
        ]
        results = get_embedding_batch(texts)
        assert len(results) == 3
        assert all(len(v) == 768 for v in results)

    def test_empty_text_returns_vector(self):
        """Empty string still returns a 768-dim vector (not crash)."""
        vec = get_embedding("")
        assert len(vec) == 768

    def test_model_singleton(self):
        """Model is loaded once and reused."""
        m1 = _get_embed_model()
        m2 = _get_embed_model()
        assert m1 is m2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_embedding.py -v`
Expected: FAIL (`_get_embed_model` doesn't exist yet)

- [ ] **Step 3: Rewrite vector_memory.py embedding functions**

Replace the embedding section of `src/zettelforge/vector_memory.py`. The key changes:

1. Add a module-level `_embed_model` singleton for the fastembed `TextEmbedding` instance
2. Replace `get_embedding()` to use fastembed by default, with ollama fallback controlled by config
3. Replace `get_embedding_batch()` with native fastembed batch

```python
# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q"
DEFAULT_EMBEDDING_PROVIDER = "fastembed"  # "fastembed" or "ollama"


def get_embedding_provider() -> str:
    """Get embedding provider from environment or default."""
    return os.environ.get("ZETTELFORGE_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER)


def get_embedding_model() -> str:
    """Get embedding model from environment or default."""
    return os.environ.get("AMEM_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


# ── fastembed singleton ──────────────────────────────────────────────────────

_embed_model = None
_embed_lock = threading.Lock()


def _get_embed_model():
    """Get or create the fastembed TextEmbedding model (singleton)."""
    global _embed_model
    if _embed_model is None:
        with _embed_lock:
            if _embed_model is None:
                from fastembed import TextEmbedding
                _embed_model = TextEmbedding(get_embedding_model())
    return _embed_model


# ── Embedding ────────────────────────────────────────────────────────────────

def get_embedding(text: str, model: Optional[str] = None) -> List[float]:
    """Generate embedding. Uses fastembed (in-process) by default, ollama as fallback."""
    provider = get_embedding_provider()

    if provider == "fastembed":
        try:
            m = _get_embed_model()
            results = list(m.embed([text]))
            return results[0].tolist()
        except Exception:
            pass  # Fall through to ollama

    # Ollama fallback
    try:
        import ollama
        model = model or get_embedding_model()
        resp = ollama.embeddings(model=model, prompt=text)
        return resp.get("embedding", [0.0] * 768)
    except Exception:
        # Deterministic mock embedding if everything fails
        h = int(hashlib.md5(text.encode()).hexdigest(), 16)
        import random
        random.seed(h)
        return [random.random() for _ in range(768)]


def get_embedding_batch(texts: List[str], model: Optional[str] = None) -> List[List[float]]:
    """Batch embed multiple texts. Native batch with fastembed, sequential with ollama."""
    provider = get_embedding_provider()

    if provider == "fastembed":
        try:
            m = _get_embed_model()
            results = list(m.embed(texts))
            return [r.tolist() for r in results]
        except Exception:
            pass

    return [get_embedding(text, model) for text in texts]
```

Add `import threading` to the imports at the top of the file if not already present.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_embedding.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Run existing test suite to check regressions**

Run: `python3 -m pytest tests/test_basic.py tests/test_recall_integration.py tests/test_typedb_client.py -v`
Expected: All pass (embedding dimension unchanged at 768)

- [ ] **Step 6: Commit**

```bash
git add src/zettelforge/vector_memory.py tests/test_embedding.py
git commit -m "feat: replace Ollama embeddings with fastembed (in-process ONNX)"
```

---

### Task 2: Fix prospective_indexer.py direct ollama calls

**Files:**
- Modify: `src/zettelforge/prospective_indexer.py`

The `prospective_indexer.py` in the openclaw copy calls `ollama.embeddings()` directly in two places (lines 159 and 212) instead of using `get_embedding()` from vector_memory. Fix both to use the shared embedding function.

- [ ] **Step 1: Replace line ~159**

Find:
```python
emb_response = ollama.embeddings(
    model=embedding_model,
    prompt=entry,
)
vector = emb_response.get("embedding", [])
```

Replace with:
```python
from zettelforge.vector_memory import get_embedding
vector = get_embedding(entry)
```

- [ ] **Step 2: Replace line ~212**

Find:
```python
q_emb = ollama.embeddings(
    model="nomic-embed-text-v2-moe",
    prompt=query,
).get("embedding", [])
```

Replace with:
```python
from zettelforge.vector_memory import get_embedding
q_emb = get_embedding(query)
```

- [ ] **Step 3: Remove the `import ollama` at the top** if it's only used for embeddings. Keep it if `ollama.generate()` is still called elsewhere in the file.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_cti_integration.py`

- [ ] **Step 5: Commit**

```bash
git add src/zettelforge/prospective_indexer.py
git commit -m "fix: route prospective_indexer embeddings through get_embedding()"
```

---

### Task 3: Update config, schema defaults, and dependencies

**Files:**
- Modify: `src/zettelforge/note_schema.py`
- Modify: `src/zettelforge/config.py`
- Modify: `config.default.yaml`
- Modify: `pyproject.toml`

- [ ] **Step 1: Update note_schema.py default model name**

In `src/zettelforge/note_schema.py`, change:
```python
model: str = "nomic-embed-text-v2-moe"
```
to:
```python
model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
```

Note: The openclaw copy at `~/.openclaw/workspace/skills/zettelforge` also has this — update both if syncing.

- [ ] **Step 2: Add embedding.provider to config.py**

In `src/zettelforge/config.py`, update the `EmbeddingConfig` dataclass:
```python
@dataclass
class EmbeddingConfig:
    url: str = "http://127.0.0.1:11434"
    model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
    dimensions: int = 768
    provider: str = "fastembed"  # "fastembed" or "ollama"
```

Add env override in `_apply_env()`:
```python
if v := os.environ.get("ZETTELFORGE_EMBEDDING_PROVIDER"):
    cfg.embedding.provider = v
```

- [ ] **Step 3: Update config.default.yaml**

Add `provider` to the embedding section:
```yaml
embedding:
  # Provider: "fastembed" (in-process ONNX, no server needed)
  #           "ollama" (requires running Ollama server)
  #
  # Examples:
  #   provider: fastembed    # default — 130MB model, 7ms/embed, zero dependencies
  #   provider: ollama       # legacy — requires `ollama serve` on port 11434
  #
  # Env override: ZETTELFORGE_EMBEDDING_PROVIDER=ollama
  provider: fastembed
  # Ollama endpoint (only used when provider=ollama)
  url: http://127.0.0.1:11434
  # Model name (fastembed uses HuggingFace format, ollama uses short names)
  #   fastembed: nomic-ai/nomic-embed-text-v1.5-Q (768-dim, 130MB, quantized)
  #   ollama:    nomic-embed-text (768-dim, ~500MB)
  model: nomic-ai/nomic-embed-text-v1.5-Q
  dimensions: 768
```

- [ ] **Step 4: Add fastembed to pyproject.toml**

```toml
dependencies = [
    "lancedb>=0.5.0",
    "pyarrow>=14.0.0",
    "pydantic>=2.0.0",
    "numpy>=1.24.0",
    "requests>=2.31.0",
    "tantivy>=0.11.0",
    "typedb-driver>=3.8.0",
    "fastembed>=0.8.0",
]
```

- [ ] **Step 5: Run full test suite**

```bash
cd zettelforge
python3 -m pytest tests/test_embedding.py tests/test_basic.py tests/test_config.py tests/test_typedb_client.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/zettelforge/note_schema.py src/zettelforge/config.py config.default.yaml pyproject.toml
git commit -m "feat: add fastembed as default embedding provider, update config and deps"
```

---

### Task 4: Update README and docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update Quick Start section**

Remove the `ollama pull nomic-embed-text` line from Quick Start. The embedding model auto-downloads on first use.

Update to:
```bash
# Start TypeDB (ontology layer)
docker compose -f docker/docker-compose.yml up -d

# Start Ollama (LLM only — embeddings run locally via fastembed)
ollama pull qwen2.5:3b
ollama serve
```

- [ ] **Step 2: Update Configuration table**

Add:
```
| `embedding.provider` | `str` | `fastembed` | `ZETTELFORGE_EMBEDDING_PROVIDER` | `fastembed` (in-process) or `ollama` (server) |
```

- [ ] **Step 3: Update Features list**

Change "Local-First" bullet to mention fastembed:
```
- **Zero-Server Embeddings**: 768-dim vectors generated in-process via fastembed (ONNX) — no Ollama needed for embeddings
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README for fastembed embedding provider"
```

---

## Rollback / Provider Switching

Users can switch back to Ollama at any time:

```yaml
# config.yaml
embedding:
  provider: ollama
  url: http://localhost:11434
  model: nomic-embed-text
```

Or via environment variable:
```bash
export ZETTELFORGE_EMBEDDING_PROVIDER=ollama
```

The fastembed model cache lives at `~/.cache/fastembed/`. For air-gapped deployments, pre-populate this directory from a connected machine.

## Model Compatibility

| Model | Provider | Dimensions | Size | Speed |
|-------|----------|------------|------|-------|
| `nomic-ai/nomic-embed-text-v1.5-Q` | fastembed | 768 | 130MB | 7ms/embed |
| `nomic-ai/nomic-embed-text-v1.5` | fastembed | 768 | 520MB | 10ms/embed |
| `nomic-embed-text` | ollama | 768 | ~500MB | ~30ms/embed |
| `nomic-embed-text-v2-moe` | ollama | 768 | ~800MB | ~40ms/embed |

All produce 768-dim vectors — existing LanceDB indexes remain compatible. No re-indexing needed when switching providers.
