# RFC-011: Local LLM Backend Selection via Config (llama-cpp-python + onnxruntime-genai)

## Metadata

- **Author**: Patrick Roland
- **Status**: Draft
- **Created**: 2026-04-24
- **Last Updated**: 2026-04-24
- **Reviewers**: TBD
- **Related Tickets**: ZF-011
- **Related RFCs**: RFC-002 (Universal LLM Provider Interface), RFC-010 (Enrichment Hotfix)

## Summary

Introduce a config-managed `backend` field under the LLM provider for local inference, allowing users to select between `llama-cpp-python` (the current default for `provider: local`) and `onnxruntime-genai` as the local runtime engine. The `llm.provider: local` key remains the user-facing selector; a new `llm.local_backend` field in `config.yaml` switches between the two in-process engines without changing calling code or config topology.

## Motivation

ZettelForge's `local` LLM provider currently hardwires `llama-cpp-python` as its inference backend. This is a deliberate, working default, but two observations motivate adding a second local backend:

**1. Hardware diversity.** `llama-cpp-python` is heavily optimized for CPU (AVX2, NEON, BLAS backends) and NVIDIA GPU via cuBLAS. `onnxruntime-genai` provides native support for DirectML (Windows AMD/NVIDIA/Intel), ROCm (AMD), OpenVINO (Intel), and Apple CoreML — hardware that llama-cpp-python supports poorly or not at all. Users on AMD GPUs, Intel Arc, Apple Silicon, or non-NVIDIA Windows machines get degraded performance or need container workarounds.

**2. Deployment surface reduction.** `llama-cpp-python` compiles native extensions from source on install (`pip install` triggers CMake + a C++ compiler toolchain). This adds 3-5 minutes per install, requires build-essential / MSVC, and fails in minimal containers (Alpine, distroless, Azure Functions). `onnxruntime-genai` ships pre-compiled wheels for all major platforms, reducing install to a pure download-and-link step. For CI/CD pipelines, ephemeral containers, and serverless deployments, this difference matters.

**3. Model format ubiquity.** GGUF (llama-cpp-python) and ONNX (onnxruntime-genai) both have large, growing model ecosystems. Supporting both lets users pull models from HuggingFace in the format their hardware prefers without running conversion scripts.

The existing `EmbeddingConfig.provider` field already uses this pattern — `fastembed` (in-process ONNX) vs `ollama` (HTTP server). This RFC applies the same approach to the local LLM provider.

### Who benefits

- **AMD GPU users** running ZettelForge on ROCm hardware (DGX Spark is NVIDIA so less relevant here, but the project serves a broader community)
- **Windows analysts** who find `llama-cpp-python` install failure rate high due to MSVC toolchain requirements
- **Container / serverless deployments** where build-time compilation of llama-cpp-python adds unacceptable cold-start latency
- **Intel Arc and Apple Silicon users** who get ONNX-optimized kernels without workarounds

## Proposed Design

### Architecture

The `local` provider becomes a thin dispatcher that lazily imports and instantiates the selected backend:

```
llm:
  provider: local                  # selects the local provider (unchanged)
  local_backend: llama-cpp-python  # NEW: "llama-cpp-python" or "onnxruntime-genai"

llm_client.generate()
  -> registry.get("local")
    -> LocalProvider
      -> _Backend: LocalBackend protocol
        +-> LlamaCppBackend       # uses llama_cpp.Llama (existing code)
        +-> OnnxGenAIBackend      # uses onnxruntime_genai (new code)
```

The `LLMProvider` protocol (RFC-002) is already satisfied by `LocalProvider`. Backend selection is an internal detail of that provider — no change to `generate()`, no change to the registry, no change to the seven callers.

### Backend Protocol

Each backend implements a thin protocol internal to `local_provider.py`:

```python
# Inside src/zettelforge/llm_providers/local_provider.py

from typing import Protocol, Optional


class LocalBackend(Protocol):
    """Internal protocol for local inference backends."""

    def generate(
        self,
        prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
        system: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        ...


class LlamaCppBackend:
    """llama-cpp-python GGUF backend (existing code, extracted)."""

    def __init__(self, model: str, filename: str, n_ctx: int, **kwargs):
        ...

    def generate(self, prompt, max_tokens, temperature, system, json_mode):
        ...


class OnnxGenAIBackend:
    """ONNX Runtime GenAI backend (new)."""

    def __init__(self, model: str, filename: str, n_ctx: int, **kwargs):
        ...

    def generate(self, prompt, max_tokens, temperature, system, json_mode):
        ...
```

The `LocalProvider` constructor gains a `backend` parameter:

```python
class LocalProvider:
    name = "local"

    def __init__(
        self,
        model: str = "",
        filename: str = "",
        n_ctx: int = _DEFAULT_N_CTX,
        backend: str = "llama-cpp-python",  # NEW
        **kwargs,
    ):
        self._model_id = model or _DEFAULT_MODEL
        self._filename = filename or _DEFAULT_FILENAME
        self._n_ctx = n_ctx
        self._backend_name = backend
        self._impl: LocalBackend | None = None
        self._lock = threading.Lock()

    def _get_impl(self) -> LocalBackend:
        if self._impl is None:
            with self._lock:
                if self._impl is None:
                    if self._backend_name == "onnxruntime-genai":
                        self._impl = OnnxGenAIBackend(
                            model=self._model_id,
                            filename=self._filename,
                            n_ctx=self._n_ctx,
                        )
                    else:
                        self._impl = LlamaCppBackend(
                            model=self._model_id,
                            filename=self._filename,
                            n_ctx=self._n_ctx,
                        )
        return self._impl
```

### Config Schema

New `local_backend` field under `llm:` in `config.yaml`:

```yaml
llm:
  provider: local
  local_backend: llama-cpp-python    # "llama-cpp-python" or "onnxruntime-genai"
  model: Qwen/Qwen2.5-3B-Instruct-GGUF
  extra:
    filename: qwen2.5-3b-instruct-q4_k_m.gguf
    n_ctx: 4096
```

Example configs:

```yaml
# ONNX Runtime GenAI on AMD GPU
llm:
  provider: local
  local_backend: onnxruntime-genai
  model: microsoft/Phi-3-mini-4k-instruct-onnx
  extra:
    filename: phi3-mini-4k-instruct-q4.onnx
    provider: rocm          # dml, rocm, cuda, cpu, openvino, coreml

# llama-cpp-python on NVIDIA GPU
llm:
  provider: local
  local_backend: llama-cpp-python
  model: Qwen/Qwen2.5-7B-Instruct-GGUF
  extra:
    filename: qwen2.5-7b-instruct-q4_k_m.gguf
    n_ctx: 8192
    n_gpu_layers: -1         # offload all layers to GPU
```

### Config Dataclass Changes

```python
# src/zettelforge/config.py — LLMConfig updated

@dataclass
class LLMConfig:
    provider: str = "ollama"
    model: str = "qwen3.5:9b"
    url: str = "http://localhost:11434"
    api_key: str = ""
    temperature: float = 0.1
    timeout: float = 60.0
    max_retries: int = 2
    fallback: str = ""
    local_backend: str = "llama-cpp-python"  # NEW — only meaningful when provider=local
    extra: Dict[str, Any] = field(default_factory=dict)
```

The `_apply_yaml` function already handles `llm.extra` generically, so `local_backend` just needs a simple setattr line:

```python
if "llm" in data and isinstance(data["llm"], dict):
    for k, v in data["llm"].items():
        if not hasattr(cfg.llm, k):
            continue
        if k == "api_key" and isinstance(v, str):
            v = _resolve_env_refs(v)
        elif k == "extra" and isinstance(v, dict):
            v = {ek: _resolve_env_refs(ev) if isinstance(ev, str) else ev for ek, ev in v.items()}
        setattr(cfg.llm, k, v)
```

And env override:

```python
# In _apply_env()
if v := os.environ.get("ZETTELFORGE_LLM_LOCAL_BACKEND"):
    cfg.llm.local_backend = v
```

### OnnxGenAIBackend Design

```python
class OnnxGenAIBackend:
    """ONNX Runtime GenAI backend.

    Args:
        model: HuggingFace repo id (e.g. ``"microsoft/Phi-3-mini-4k-instruct-onnx"``).
        filename: Specific ONNX model file within the repo (e.g. ``"phi3-mini-4k-instruct-q4.onnx"``).
        n_ctx: Context window size in tokens.
        provider: Execution provider (``"cpu"``, ``"cuda"``, ``"rocm"``,
            ``"dml"``, ``"openvino"``, ``"coreml"``). Default: ``"cpu"``.
    """

    name = "onnxruntime-genai"

    def __init__(
        self,
        model: str = "",
        filename: str = "",
        n_ctx: int = 4096,
        provider: str = "cpu",
        **kwargs,
    ):
        self._model_id = model or _DEFAULT_ONNX_MODEL
        self._filename = filename or _DEFAULT_ONNX_FILENAME
        self._n_ctx = n_ctx
        self._provider = provider
        self._model_obj = None
        self._tokenizer = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model_obj is not None:
            return
        with self._lock:
            if self._model_obj is not None:
                return
            try:
                import onnxruntime_genai as og
            except ImportError:
                raise ImportError(
                    "ONNX GenAI backend requires onnxruntime-genai. "
                    "Install with: pip install zettelforge[local-onnx]"
                ) from None

            # Download model from HuggingFace if not cached
            # onnxruntime-genai has its own model download: og.Model.from_pretrained()
            self._model_obj = og.Model.from_pretrained(
                self._model_id,
                filename=self._filename,
                provider=self._provider,
            )
            self._tokenizer = og.Tokenizer(self._model_obj)

    def generate(self, prompt, max_tokens=400, temperature=0.1,
                 system=None, json_mode=False):
        self._load()

        # Build full prompt (ONNX GenAI uses raw tokenization, not chat template API)
        full_prompt = prompt
        if system:
            full_prompt = f"{system}\n\n{full_prompt}"

        tokenizer = self._tokenizer
        input_tokens = tokenizer.encode(full_prompt)

        params = og.GeneratorParams(self._model_obj)
        params.set_search_options(
            max_length=len(input_tokens) + max_tokens,
            temperature=temperature,
        )
        params.input_ids = input_tokens

        generator = og.Generator(self._model_obj, params)
        try:
            generator.append_tokens(input_tokens) if hasattr(generator, 'append_tokens') else None
            output_tokens = []
            for _ in range(max_tokens):
                token = generator.generate_next_token()
                if token == tokenizer.eos_token_id:
                    break
                output_tokens.append(token)
            return tokenizer.decode(output_tokens).strip()
        finally:
            del generator
```

**Design notes on `onnxruntime-genai`:**

- Model download follows the same `from_pretrained` pattern as `Llama.from_pretrained()` used by llama-cpp-python, keeping the UX consistent.
- Execution provider is passed through `extra: { provider: rocm }` in config, keeping it out of the top-level schema.
- The SDK is scoped to `pip install zettelforge[local-onnx]` — it is never a core dependency.
- `json_mode` is handled via system prompt hint (same pattern as llama-cpp-python), since ONNX GenAI has no `response_format` parameter.
- No chat template API exists in `onnxruntime-genai` at the SDK level — the backend constructs prompts directly. This is identical to the current `llama-cpp-python` approach.

### Package Extras

```toml
# pyproject.toml additions

[project.optional-dependencies]
# Existing
local = ["llama-cpp-python>=0.3.0"]

# New — ONNX GenAI backend
local-onnx = ["onnxruntime-genai>=0.4.0"]

# Combines both (convenience for local development)
local-all = [
    "zettelforge[local]",
    "zettelforge[local-onnx]",
]
```

### File Changes

| File | Change |
|------|--------|
| `src/zettelforge/llm_providers/local_provider.py` | Extract `LlamaCppBackend` class; add `OnnxGenAIBackend` class; refactor `LocalProvider` to dispatch on `backend` parameter |
| `src/zettelforge/config.py` | Add `local_backend` field to `LLMConfig`; add env override `ZETTELFORGE_LLM_LOCAL_BACKEND` |
| `config.default.yaml` | Document `local_backend` field and both engine options |
| `pyproject.toml` | Add `local-onnx` and `local-all` optional extras |
| `tests/test_llm_providers.py` | Add unit tests for `OnnxGenAIBackend` (mock SDK) |

### Migration

**Existing users with `provider: local` (current default):**

Zero config changes. `local_backend` defaults to `llama-cpp-python`, which is what the current code runs. Behavior is identical.

**Users switching to ONNX GenAI:**

Change `config.yaml`:
```yaml
llm:
  provider: local
  local_backend: onnxruntime-genai
  model: microsoft/Phi-3-mini-4k-instruct-onnx
  extra:
    filename: phi3-mini-4k-instruct-q4.onnx
    provider: cpu
```
Then `pip install zettelforge[local-onnx]`.

**Callers of generate():**

Zero changes. The 7 call sites are unaffected.

## Alternatives Considered

**Alternative 1: Separate providers (`local-llama`, `local-onnx`).** Replace `local_backend` with separate provider names like `local-llama` and `local-onnx` that each get their own registration in the registry. Rejected because: (a) multiplies provider names in the registry for what is a single API contract; (b) makes the implicit `local -> ollama` fallback ambiguous (should it apply to both?); (c) users must remember two provider names for local inference; (d) configuration docs and UI dropdowns need two entries for the same category.

**Alternative 2: Generic `local` provider with all params in `extra`.** Do not add `local_backend` at all — infer the backend from the model file extension (`.gguf` vs `.onnx`). Rejected because: (a) fragile — model repos may contain both formats; (b) the execution provider selection (CUDA vs ROCm vs CPU) has no natural file-extension inference; (c) explicit config is more maintainable and searchable.

**Alternative 3: Provider-specific sub-configs (`local.llama_cpp:`, `local.onnx:`).** Add nested config blocks. Rejected because: (a) over-engineered for two backends; (b) inconsistent with the rest of the YAML config structure which uses flat key-value under sections; (c) `extra` already captures provider-specific knobs.

**Alternative 4: Only support onnxruntime-genai, deprecate llama-cpp-python.** Rejected because: (a) breaks all existing users; (b) llama-cpp-python has superior CPU kernel support (AVX-512, Q4_0_4_4, Q6_K) and a larger GGUF ecosystem; (c) ONNX GenAI is newer and less battle-tested — keeping both gives users a safety net.

## Implementation Plan

### Phase 1: Refactor + OnnxGenAIBackend (v2.5.0)

1. Extract existing `LocalProvider.generate()` code into `LlamaCppBackend` class inside `local_provider.py`.
2. Add `OnnxGenAIBackend` class implementing the same internal interface.
3. Update `LocalProvider.__init__()` to accept and store `backend` parameter.
4. Update `LocalProvider._get_llm()` → `_get_impl()` to dispatch on backend name.
5. Add `local_backend` field to `LLMConfig` in `config.py`.
6. Add `ZETTELFORGE_LLM_LOCAL_BACKEND` env override.
7. Add `local-onnx` and `local-all` extras to `pyproject.toml`.
8. Update `config.default.yaml` with documentation.
9. Write unit tests: `LlamaCppBackend` (verify existing behavior preserved), `OnnxGenAIBackend` (mock SDK, verify generate flow), `LocalProvider` dispatch (verify backend parameter routing), config loading (verify `local_backend` field parses correctly).

**Validation:** All existing tests pass. `provider: local` with no `local_backend` set produces identical results to pre-Phase 1.

### Phase 2: Provider Extra Override Support (shipped with Phase 1)

`onnxruntime-genai` needs `provider` (execution provider) passed via `extra`. Verify that `_provider_kwargs()` in `llm_client.py` correctly forwards `extra` key-values. This already works for the existing `local` provider (which reads `filename` and `n_ctx` from `extra`); Phase 2 is a no-op beyond testing that the plumbing works for `provider: rocm` style keys.

## Rollout Strategy

**Phase 1** (v2.5.0): Feature-gated behind `local_backend: onnxruntime-genai` in config. Defaults to `llama-cpp-python` — existing users see zero change. `pip install zettelforge[local-onnx]` required for the new backend.

**Rollback:** Set `local_backend: llama-cpp-python` (or remove the key) in `config.yaml`. No data migration required — both backends consume and produce the same text.

**Observability:** A structured log event `local_llm_backend_selected` is emitted at INFO level on first `generate()` call, recording the backend name. If the selected backend fails to import, an ERROR log event with the `pip install` hint is emitted before the error propagates.

## Open Questions

1. **Should `local_backend` have a corresponding `local_provider` field for execution provider selection (CPU, CUDA, ROCm, DirectML)?** The `extra` dict already handles this (e.g. `extra: { provider: rocm }`). A dedicated field would make discovery easier but adds surface area. Proposal: keep it in `extra` for v1, promote to a named field if users find it hard to discover.

2. **Should the ONNX GenAI backend support chat templates?** The current `llama-cpp-python` backend does not use Jinja chat templates either — it constructs messages directly. The `onnxruntime-genai` Python SDK also lacks a chat template API at the 0.4.x release level. Proposal: defer to v2 if/when the SDK adds this.

3. **Should both backends share a model cache?** `llama-cpp-python` caches in `~/.cache/huggingface/hub/`. `onnxruntime-genai` uses an internal model downloader. Proposal: keep them separate — they download different file formats anyway. A future RFC may introduce a unified cache path.

4. **What about `vllm` as a local backend?** vLLM is a server process, not an in-process library — it belongs as a separate provider (`provider: openai_compat` pointing at a vLLM server). Out of scope for this RFC.

## Decision

**Decision**: Accepted -- shipped concurrently with RFC (owner override for rapid iteration)
**Date**: 2026-04-24
**Decision Maker**: Patrick Roland
**Rationale**: Implementation shipped alongside the RFC document to minimize time-to-value. The design was reviewed as part of the PR process. RFC-002 provider infrastructure provides the necessary extension points; the changes are isolated to `local_provider.py` and `config.py` with zero caller impact.

## Implementation Status

| Component | Scope | Status | Shipped in |
|-----------|-------|--------|------------|
| Phase 1 | `LlamaCppBackend` extraction from `LocalProvider` | **Shipped** | 2026-04-24 (PR #104) |
| Phase 1 | `OnnxGenAIBackend` class with `onnxruntime-genai` SDK integration | **Shipped** | 2026-04-24 (PR #104) |
| Phase 1 | `LocalProvider` backend dispatching via `backend` parameter | **Shipped** | 2026-04-24 (PR #104) |
| Phase 1 | `local_backend` field in `LLMConfig` dataclass + `__repr__` inclusion | **Shipped** | 2026-04-24 (PR #104) |
| Phase 1 | `ZETTELFORGE_LLM_LOCAL_BACKEND` env override | **Shipped** | 2026-04-24 (PR #104) |
| Phase 1 | `local-onnx` and `local-all` package extras in `pyproject.toml` | **Shipped** | 2026-04-24 (PR #104) |
| Phase 1 | `config.default.yaml` documentation updates | **Shipped** | 2026-04-24 (PR #104) |
| Phase 1 | Unit tests: 15 new tests covering backend dispatching, all backends, and fallback scenarios | **Shipped** | 2026-04-24 (PR #104) |
| Phase 2 | Execution provider override testing (`extra: { provider: rocm }` plumbing) | Deferred | -- |
