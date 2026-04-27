# RFC-012: LiteLLM Unified Provider for LLM Routing

## Metadata

- **Author**: Patrick Roland
- **Status**: Draft
- **Created**: 2026-04-25
- **Last Updated**: 2026-04-25
- **Reviewers**: TBD
- **Related Tickets**: ZF-012
- **Related RFCs**: RFC-002 (Universal LLM Provider Interface), RFC-011 (Local LLM Backend Selection)

## Summary

Add `litellm` as a first-class LLM provider in the ZettelForge provider registry. A single `provider: litellm` config replaces the current pattern where users must configure separate providers for each model host (OpenAI, Anthropic, Groq, Together AI, etc.). LiteLLM's `completion()` function routes requests to the correct backend based on model name pattern matching, so users only set a model name and API key.

## Motivation

ZettelForge currently requires a separate provider registration in the registry for each LLM backend. RFC-002 defines `openai_compat` (Phase 2, not yet shipped) and `anthropic` (Phase 3, not yet shipped). Adding each provider requires:

- A new provider file implementing the `LLMProvider` protocol
- Registering it in `__init__.py`
- Testing against each provider's SDK
- Maintaining retry/error/streaming logic per-provider
- Updating config docs for each new option

This does not scale. ZettelForge users on AWS Bedrock, Google Vertex, Azure OpenAI, Together AI, Groq, Fireworks, Perplexity, or any of 100+ supported providers cannot use ZettelForge with those backends until a dedicated provider is shipped.

LiteLLM solves this in ~100 lines of provider code: its `litellm.completion()` function handles authentication, request formatting, retry, and response parsing for every supported provider, using the same OpenAI-compatible parameter surface.

### Who benefits

- **Any user of a non-Ollama, non-local LLM backend** — they configure one provider name (`litellm`) and set model name + API key
- **Users who switch providers frequently** — model name change is a one-field config edit
- **Power users of Azure OpenAI, Bedrock, Vertex** — these have complex auth that LiteLLM handles automatically
- **The project** — eliminates the need to ship and maintain `openai_compat`, `anthropic`, `azure_openai`, `bedrock`, `vertex` provider files

## Proposed Design

### Architecture

LiteLLM is a **new top-level provider** registered as `"litellm"` in the provider registry, sitting alongside `local`, `ollama`, and `mock`:

```
llm:
  provider: litellm                     # selects LiteLLM routing
  model: gpt-4o                         # any model name LiteLLM supports
  api_key: ${OPENAI_API_KEY}            # set per-model or globally

# LiteLLM uses model-name prefix routing:
#   gpt-4o, gpt-4o-mini    → OpenAI
#   claude-sonnet-4        → Anthropic
#   gemini/gemini-2.0-flash → Google Gemini
#   groq/llama-3.3-70b     → Groq
#   bedrock/...            → AWS Bedrock
#   vertex_ai/...          → Google Vertex
#   openai/fireworks-ai/... → custom base_url routing
```

No changes to `generate()`, the registry, or any of the seven callers. LiteLLM satisfies the same `LLMProvider` protocol.

### LiteLLMProvider Design

```python
# src/zettelforge/llm_providers/litellm_provider.py

import time
from typing import Any, Optional

from zettelforge.log import get_logger

_DEFAULT_MODEL = "gpt-4o-mini"
_PREVIEW_CHARS = 240
_logger = get_logger("zettelforge.llm.litellm")


class LiteLLMProvider:
    """LiteLLM routing provider.

    Delegates generation to ``litellm.completion()``, which routes to the
    correct provider SDK based on model name prefix matching. Supports
    100+ LLM providers (OpenAI, Anthropic, Google, AWS Bedrock, Groq,
    Together AI, Fireworks, Azure OpenAI, and more).

    Args:
        model: Model name (e.g. ``"gpt-4o"``, ``"claude-sonnet-4-20250514"``,
            ``"gemini/gemini-2.0-flash"``, ``"groq/llama-3.3-70b"``).
            LiteLLM routes to the correct provider based on the model prefix.
        api_key: API key for the provider. Supports ``${ENV_VAR}`` references
            resolved by the config loader before reaching this constructor.
            Many providers can also use environment variables directly
            (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, etc.).
        timeout: Request timeout in seconds.
        max_retries: Number of retries on transient failure.
        **_: Accept and ignore extra kwargs for registry compatibility.
    """

    name = "litellm"

    def __init__(
        self,
        model: str = "",
        api_key: str = "",
        timeout: float = 60.0,
        max_retries: int = 2,
        **_: Any,
    ) -> None:
        self._model = model or _DEFAULT_MODEL
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries

    def generate(
        self,
        prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
        system: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        try:
            import litellm
        except ImportError as exc:
            raise ImportError(
                "LiteLLM provider requires the litellm package. "
                "Install with: pip install zettelforge[litellm]"
            ) from exc

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": self._timeout,
            "num_retries": self._max_retries,
        }

        # Set api_key if explicitly configured (otherwise LiteLLM falls
        # back to standard env vars like OPENAI_API_KEY automatically).
        if self._api_key:
            kwargs["api_key"] = self._api_key

        # LiteLLM supports response_format via the OpenAI-compat path:
        #   response_format={"type": "json_object"}
        # This works for OpenAI, Azure OpenAI, and most OpenAI-compat endpoints.
        # Anthropic and others use the drop_params mechanism to ignore it.
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        prompt_chars = len(prompt)
        system_chars = len(system) if system else 0
        start = time.perf_counter()

        try:
            response = litellm.completion(**kwargs)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            _logger.warning(
                "llm_call_exception",
                provider="litellm",
                model=self._model,
                duration_ms=round(duration_ms, 1),
                error=type(exc).__name__,
                error_msg=str(exc)[:_PREVIEW_CHARS],
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        raw_response = str(response["choices"][0]["message"]["content"])
        stripped = raw_response.strip()
        is_empty = not stripped

        log_level = _logger.warning if is_empty else _logger.debug
        log_event = "llm_call_empty_response" if is_empty else "llm_call_complete"
        log_kwargs: dict[str, Any] = {
            "provider": "litellm",
            "model": self._model,
            "duration_ms": round(duration_ms, 1),
            "prompt_chars": prompt_chars,
            "system_chars": system_chars,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "json_mode": json_mode,
        }
        if is_empty:
            log_kwargs["response_preview"] = raw_response[:_PREVIEW_CHARS]
            log_kwargs["prompt_preview"] = prompt[:_PREVIEW_CHARS]
        log_level(log_event, **log_kwargs)

        return stripped
```

**Design notes:**

- Uses `litellm.completion()` which has the same signature as OpenAI's chat completions API but routes to any provider based on model prefix.
- `json_mode` uses `response_format={"type": "json_object"}` which works for OpenAI, Azure OpenAI, and most OpenAI-compat endpoints. For providers that don't support it, LiteLLM's `drop_params` mechanism silently ignores unknown parameters.
- Retry is handled by LiteLLM via `num_retries` parameter — no manual retry loop needed.
- API key can be set either via config (`api_key: ${OPENAI_API_KEY}`) or via standard environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) — LiteLLM checks both.
- Timeout is passed as a kwarg — LiteLLM applies it to the underlying HTTP client.

### API Key Strategy

LiteLLM supports multiple API key approaches:

1. **Config-level key** — `api_key: ${OPENAI_API_KEY}` in `config.yaml`. The config loader resolves `${ENV_VAR}` references. This key is passed to `litellm.completion(api_key=...)`.

2. **Environment-level key** — Set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_API_KEY`, etc. directly in the environment. LiteLLM reads these automatically. No config change needed.

3. **Per-model keys** — For users who use LiteLLM with multiple providers (e.g., OpenAI for chat, Anthropic for synthesis). Config: `model: gpt-4o` with `OPENAI_API_KEY` in env, and when generating with a different model name via a future per-call override, the corresponding env var is picked up automatically.

Strategy 1 is preferred for single-provider setups. Strategy 2 is preferred for multi-provider setups or users who already have the standard env vars set.

### Config Schema

```yaml
# LiteLLM — unified routing to 100+ LLM providers
llm:
  provider: litellm
  model: gpt-4o                       # LiteLLM routes to correct provider
  api_key: ${OPENAI_API_KEY}          # optional — env vars also work
  temperature: 0.1
  timeout: 60.0
  max_retries: 2
  fallback: ""                        # no implicit fallback for litellm
```

Example configs:

```yaml
# OpenAI (simple)
llm:
  provider: litellm
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}

# Anthropic (model prefix routing)
llm:
  provider: litellm
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}

# Groq (fast inference, prefix = "groq/")
llm:
  provider: litellm
  model: groq/llama-3.3-70b-versatile
  api_key: ${GROQ_API_KEY}

# Together AI (prefix = "together_ai/")
llm:
  provider: litellm
  model: together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo
  api_key: ${TOGETHER_API_KEY}

# Google Gemini (prefix = "gemini/")
llm:
  provider: litellm
  model: gemini/gemini-2.0-flash
  # GOOGLE_API_KEY in env, or api_key: ${GOOGLE_API_KEY}

# AWS Bedrock (prefix = "bedrock/")
llm:
  provider: litellm
  model: bedrock/anthropic.claude-3-sonnet-20240229-v1:0
  # AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY in env

# Google Vertex AI (prefix = "vertex_ai/")
llm:
  provider: litellm
  model: vertex_ai/claude-3-sonnet@20240229
  # GOOGLE_APPLICATION_CREDENTIALS in env

# OpenRouter (prefix = "openrouter/")
llm:
  provider: litellm
  model: openrouter/anthropic/claude-3.5-sonnet
  api_key: ${OPENROUTER_API_KEY}
```

### Config Dataclass Changes

No changes to `LLMConfig`. The existing fields (`provider`, `model`, `api_key`, `temperature`, `timeout`, `max_retries`, `fallback`, `extra`) are sufficient. LiteLLM accepts its model name as the `model` field and API key as `api_key`.

### Package Extras

```toml
# pyproject.toml addition

[project.optional-dependencies]
# LiteLLM — unified routing to 100+ LLM providers
litellm = [
    "litellm>=1.60.0",
]
```

### File Changes

| File | Change |
|------|--------|
| `src/zettelforge/llm_providers/litellm_provider.py` | **Create** — new `LiteLLMProvider` class |
| `src/zettelforge/llm_providers/__init__.py` | Register `"litellm"` provider in `_register_builtins()` |
| `pyproject.toml` | Add `litellm` optional dependency extra |
| `config.default.yaml` | Document `provider: litellm` with examples |
| `tests/test_llm_providers.py` | Add unit tests for `LiteLLMProvider` |

No changes to `config.py` (existing `LLMConfig` fields cover all needs), `llm_client.py` (no special per-provider logic needed for litellm), or `local_provider.py`.

### Migration

**New users:** Configure `provider: litellm` in `config.yaml` with desired model and API key. `pip install zettelforge[litellm]`.

**Existing users of any cloud LLM:** Switch from any future dedicated provider to LiteLLM by changing `provider` and model name. Example: if `openai_compat` shipped, users can switch to LiteLLM by changing `provider: litellm` and keeping the same model name.

**Users of local/ollama:** No change required. LiteLLM is an additional provider, not a replacement.

## Alternatives Considered

**Alternative 1: Ship openai_compat + anthropic + bedrock + vertex as separate providers.** Rejected because: (a) requires maintaining 4+ provider files with separate test suites; (b) each provider has different auth patterns that LiteLLM handles for free; (c) users of any of 90+ other providers (Groq, Together, Perplexity, Fireworks, DeepSeek, Mistral API, etc.) are still unsupported; (d) LiteLLM gets provider updates from its community, not from ZettelForge's maintenance burden.

**Alternative 2: Use LiteLLM as a core dependency (no optional extra).** Rejected because: (a) LiteLLM pulls in ~20 transitive dependencies (openai, anthropic, boto3, google-cloud-aiplatform, httpx, etc.); (b) many users never use cloud providers — forcing LiteLLM on them violates the optional-dependency principle established in RFC-002; (c) matches the pattern of `local` (optional), `local-onnx` (optional), `anthropic` (optional per RFC-002).

**Alternative 3: Replace both `openai_compat` and `anthropic` providers with LiteLLM.** Rejected because: (a) backward compatibility — if RFC-002 Phase 2/3 shipped, existing users would need to change config; (b) LiteLLM adds a ~30MB dependency for users who only want OpenAI; (c) `openai_compat` uses `httpx` (already a core dep) and `anthropic` uses the Anthropic SDK, both lighter than LiteLLM.

**Alternative 4: Per-provider `extra` fields instead of model name routing.** E.g., `provider: litellm` with `extra: { custom_llm_provider: "groq" }`. Rejected because: (a) LiteLLM's model-name prefix routing is the standard way to use it; (b) adds unnecessary config complexity; (c) users who want a specific provider can use a dedicated LiteLLM extra (future scope).

## Implementation Plan

### Phase 1: LiteLLMProvider + Registration (v2.5.0)

1. Create `src/zettelforge/llm_providers/litellm_provider.py` with `LiteLLMProvider` class.
2. Register `"litellm"` provider in `__init__.py` via conditional `try/except ImportError`.
3. Add `litellm` optional dependency to `pyproject.toml`.
4. Update `config.default.yaml` with full documentation.
5. Write unit tests with mocked `litellm.completion()`.

**Validation:** All existing tests pass. `provider: litellm` with mocked SDK produces expected output. No changes to config.py, llm_client.py, or local_provider.py.

### Phase 2: Per-call model override support (future)

When Phase 5 of RFC-002 ships (`generate()` with `provider=` override), LiteLLM users can set different models per call by passing `model` in `extra`. Deferred.

## Rollout Strategy

**Phase 1** (v2.5.0): `pip install zettelforge[litellm]`, set `provider: litellm` in config. Fully opt-in. No existing config breaks.

**Rollback:** Set `provider: ollama` or `provider: local` in config, `pip uninstall litellm`.

**Observability:** Standardized structured logging — `llm_call_complete` / `llm_call_exception` events with the same fields as the existing Ollama provider (provider, model, duration_ms, prompt_chars, response_chars, etc.).

## Open Questions

1. **Should LiteLLM have an implicit fallback?** LiteLLM sits alongside local/ollama as a first-class provider. It should not have an implicit fallback — if LiteLLM fails, the user should know. Explicit `fallback: ollama` can be configured if desired.

2. **Should we expose `drop_params` / `temperature` / other LiteLLM-specific kwargs via `extra`?** LiteLLM accepts additional kwargs like `drop_params=True`, `user="...", `mock_response=...`. These can already be set via `extra: { drop_params: true }`. No dedicated config field needed.

3. **What about embedding support?** LiteLLM also supports embeddings via `litellm.embedding()`. This RFC is scoped to LLM generation only. Embedding via LiteLLM can be a follow-up if users express interest.

4. **Should we add LiteLLM to the `local -> ollama` implicit fallback chain?** No — LiteLLM is an external API provider, not a local inference backend. If local fails, falling back to a paid API is surprising behavior.

## Decision

**Decision**: [Pending review]
**Date**: [Pending]
**Decision Maker**: [Pending]
**Rationale**: [Pending]
