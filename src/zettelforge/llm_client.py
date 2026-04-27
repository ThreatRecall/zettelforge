"""Unified LLM interface.

Delegates to a registered :class:`~zettelforge.llm_providers.base.LLMProvider`
chosen by ``llm.provider`` config. The public ``generate()`` signature
is stable — RFC-002 Phase 1 refactored the internals without changing
the call contract, so existing call sites (``fact_extractor``,
``memory_updater``, ``synthesis_generator``, ``intent_classifier``,
``note_constructor``, ``entity_indexer``, ``memory_evolver``) do not
need to change.

Example::

    from zettelforge.llm_client import generate

    text = generate("Extract facts from: APT28 uses Cobalt Strike")
"""

from __future__ import annotations

import os
from typing import Any

from zettelforge.llm_providers import LLMProviderConfigurationError, registry
from zettelforge.log import get_logger

_logger = get_logger("zettelforge.llm_client")


# ── Environment-variable helpers (preserved for backward compat) ──────────────

DEFAULT_LLM_PROVIDER = "local"
DEFAULT_LLM_MODEL = "Qwen/Qwen2.5-3B-Instruct-GGUF"
DEFAULT_LLM_FILENAME = "qwen2.5-3b-instruct-q4_k_m.gguf"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# RFC-011: ONNX GenAI backend defaults
_DEFAULT_ONNX_MODEL = "microsoft/Phi-3-mini-4k-instruct-onnx"
_DEFAULT_ONNX_FILENAME = "phi3-mini-4k-instruct-q4.onnx"


def get_llm_provider() -> str:
    """Return the configured provider name, honouring env var and config."""
    if value := os.environ.get("ZETTELFORGE_LLM_PROVIDER"):
        return value
    try:
        from zettelforge.config import get_config

        return get_config().llm.provider or DEFAULT_LLM_PROVIDER
    except Exception:
        return DEFAULT_LLM_PROVIDER


def get_llm_model() -> str:
    """Return the configured LLM model identifier (env > config > default)."""
    if value := os.environ.get("ZETTELFORGE_LLM_MODEL"):
        return value
    try:
        from zettelforge.config import get_config

        return get_config().llm.model or DEFAULT_LLM_MODEL
    except Exception:
        return DEFAULT_LLM_MODEL


def get_ollama_url() -> str:
    """Return the configured LLM server URL for the ollama provider."""
    if value := os.environ.get("ZETTELFORGE_LLM_URL"):
        return value
    try:
        from zettelforge.config import get_config

        return get_config().llm.url or DEFAULT_OLLAMA_URL
    except Exception:
        return DEFAULT_OLLAMA_URL


# ── Provider kwargs ──────────────────────────────────────────────────────────


def _provider_kwargs(provider_name: str) -> dict[str, Any]:
    """Build constructor kwargs for a provider from current config + env.

    The registry caches instances keyed by name, so these kwargs are only
    consumed on first creation. Call :func:`reload` (below) to pick up
    config changes at runtime — it clears both the cached config and the
    cached provider instances.
    """
    kwargs: dict[str, Any] = {}

    try:
        from zettelforge.config import get_config

        llm_cfg = get_config().llm
    except Exception:
        llm_cfg = None

    if llm_cfg is not None:
        kwargs["model"] = llm_cfg.model
        kwargs["url"] = llm_cfg.url
        kwargs["api_key"] = getattr(llm_cfg, "api_key", "")
        kwargs["timeout"] = getattr(llm_cfg, "timeout", 60.0)
        kwargs["max_retries"] = getattr(llm_cfg, "max_retries", 2)
        # Guard against the simple-YAML fallback (no PyYAML installed) which
        # can leave ``extra`` as the literal string ``"{}"``. Only merge dicts.
        extra = getattr(llm_cfg, "extra", None)
        if isinstance(extra, dict):
            kwargs.update(extra)

    # Env overrides preserved from pre-RFC-002 behaviour.
    if provider_name == "local":
        # The shared config's ``llm.model`` may be an Ollama tag like
        # ``qwen3.5:9b``. llama-cpp-python interprets that as a HuggingFace
        # repo id and fails. If the configured value looks like an Ollama tag
        # (colon, no slash) we ignore it and fall back to a backend-appropriate
        # default unless the user explicitly set ``ZETTELFORGE_LLM_MODEL``.
        cfg_model = kwargs.get("model") or ""
        looks_like_ollama_tag = ":" in cfg_model and "/" not in cfg_model

        # RFC-011: determine local backend to select correct defaults
        local_backend = "llama-cpp-python"
        if llm_cfg is not None:
            lb = getattr(llm_cfg, "local_backend", None)
            if lb:
                local_backend = lb
                kwargs["backend"] = lb

        if local_backend == "onnxruntime-genai":
            kwargs["model"] = os.environ.get(
                "ZETTELFORGE_LLM_MODEL",
                ("" if looks_like_ollama_tag else (cfg_model or _DEFAULT_ONNX_MODEL)),
            )
            kwargs["filename"] = os.environ.get(
                "ZETTELFORGE_LLM_FILENAME",
                kwargs.get("filename") or _DEFAULT_ONNX_FILENAME,
            )
        else:
            kwargs["model"] = os.environ.get(
                "ZETTELFORGE_LLM_MODEL",
                ("" if looks_like_ollama_tag else cfg_model) or DEFAULT_LLM_MODEL,
            )
            kwargs["filename"] = os.environ.get(
                "ZETTELFORGE_LLM_FILENAME",
                kwargs.get("filename") or DEFAULT_LLM_FILENAME,
            )
    elif provider_name == "ollama":
        # ``ZETTELFORGE_OLLAMA_MODEL`` is deprecated in favour of
        # ``ZETTELFORGE_LLM_MODEL`` but still honoured through v2.x.
        kwargs["model"] = os.environ.get(
            "ZETTELFORGE_LLM_MODEL",
            os.environ.get("ZETTELFORGE_OLLAMA_MODEL", kwargs.get("model") or DEFAULT_OLLAMA_MODEL),
        )
        kwargs["url"] = os.environ.get(
            "ZETTELFORGE_LLM_URL", kwargs.get("url") or DEFAULT_OLLAMA_URL
        )

    return {k: v for k, v in kwargs.items() if v != ""}


def _fallback_provider(primary: str) -> str | None:
    """Return the fallback provider name for ``primary`` (or ``None``)."""
    try:
        from zettelforge.config import get_config

        fallback = getattr(get_config().llm, "fallback", "") or ""
    except Exception:
        fallback = ""

    if fallback:
        return fallback if fallback != primary else None

    # Historical implicit fallback: local → ollama. Preserved so existing
    # installs keep working if the GGUF model fails to load.
    if primary == "local":
        return "ollama"
    return None


# ── Public API ───────────────────────────────────────────────────────────────


def generate(
    prompt: str,
    max_tokens: int = 400,
    temperature: float = 0.1,
    system: str | None = None,
    json_mode: bool = False,
) -> str:
    """Generate text from a prompt via the configured LLM provider.

    Args:
        prompt: The user prompt.
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature (``0.0`` = deterministic).
        system: Optional system prompt.
        json_mode: Instruct the backend to emit JSON where supported.

    Returns:
        Generated text, or ``""`` when both primary and fallback providers
        fail recoverably. Configuration errors are propagated.
    """
    primary = get_llm_provider()

    try:
        provider = registry.get(primary, **_provider_kwargs(primary))
    except (ImportError, LLMProviderConfigurationError, ValueError):
        # Configuration errors (missing SDK / bad config / unknown
        # provider name) are non-recoverable. Surface them rather than
        # silently falling back to a different provider, which would hide
        # the real problem until the user debugs the wrong component.
        _logger.error("llm_provider_config_error", provider=primary, exc_info=True)
        raise

    try:
        return provider.generate(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            json_mode=json_mode,
        )
    except (ImportError, LLMProviderConfigurationError):
        # Same rule as above — config errors raised from ``generate()``
        # are non-recoverable and must not be masked by the fallback.
        raise
    except Exception:
        _logger.debug("primary_provider_failed", provider=primary, exc_info=True)

    fallback_name = _fallback_provider(primary)
    if fallback_name is None:
        _logger.error("all_llm_backends_failed", provider=primary)
        return ""

    try:
        fallback = registry.get(fallback_name, **_provider_kwargs(fallback_name))
        return fallback.generate(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            json_mode=json_mode,
        )
    except (ImportError, LLMProviderConfigurationError, ValueError):
        # Misconfigured fallback is still a config error — don't eat it.
        raise
    except Exception:
        _logger.error(
            "all_llm_backends_failed", primary=primary, fallback=fallback_name, exc_info=True
        )
        return ""


def reload() -> None:
    """Reload LLM config and clear cached provider instances.

    Provider instances are cached in the registry keyed by name, so
    config changes made after the first ``generate()`` call do not reach
    already-initialised providers. Call this when you mutate env vars or
    ``config.yaml`` and want the next ``generate()`` to re-read both the
    config and the provider constructor kwargs.

    Registrations (which providers exist) are preserved; only instance
    caches are cleared.
    """
    from zettelforge.config import reload_config

    reload_config()
    registry.reset()


# ── Backward-compat shims ────────────────────────────────────────────────────
# The old private helpers are kept so ``from zettelforge.llm_client import
# _get_local_llm`` and similar internal patches in existing tests continue
# to work. They now thread through the provider registry.


def _get_local_llm() -> Any:
    """Return the underlying llama-cpp ``Llama`` instance (test/debug only)."""
    provider = registry.get("local", **_provider_kwargs("local"))
    if hasattr(provider, "_get_llm"):
        return provider._get_llm()
    raise RuntimeError("local provider has no _get_llm() hook")


def _generate_local(
    prompt: str,
    max_tokens: int,
    temperature: float,
    system: str | None,
    json_mode: bool = False,
) -> str:
    """Deprecated compat shim — prefer :func:`generate`."""
    provider = registry.get("local", **_provider_kwargs("local"))
    return provider.generate(
        prompt, max_tokens=max_tokens, temperature=temperature, system=system, json_mode=json_mode
    )


def _generate_ollama(
    prompt: str,
    max_tokens: int,
    temperature: float,
    system: str | None = None,
    json_mode: bool = False,
) -> str:
    """Deprecated compat shim — prefer :func:`generate`."""
    provider = registry.get("ollama", **_provider_kwargs("ollama"))
    return provider.generate(
        prompt, max_tokens=max_tokens, temperature=temperature, system=system, json_mode=json_mode
    )
