"""Pluggable LLM providers for ZettelForge (RFC-002 Phase 1).

Public surface:

- :class:`~zettelforge.llm_providers.base.LLMProvider` — the duck-typed
  protocol every provider implements.
- :mod:`~zettelforge.llm_providers.registry` — register, get, reset.
- Built-in providers: ``local``, ``ollama``, ``mock``.

Callers should continue to use :func:`zettelforge.llm_client.generate`;
the public ``generate()`` API delegates to the registered provider.
Third-party packages can register additional providers via the
``zettelforge.llm_providers`` entry-point group.
"""

from __future__ import annotations

import contextlib

from zettelforge.llm_providers.base import LLMProvider, LLMProviderConfigurationError
from zettelforge.llm_providers.local_provider import LocalProvider
from zettelforge.llm_providers.mock_provider import MockProvider
from zettelforge.llm_providers.ollama_provider import OllamaProvider
from zettelforge.llm_providers.registry import available, get, register, reset
from zettelforge.log import get_logger

_logger = get_logger("zettelforge.llm_providers")

__all__ = [
    "LLMProvider",
    "LLMProviderConfigurationError",
    "LocalProvider",
    "MockProvider",
    "OllamaProvider",
    "available",
    "get",
    "register",
    "reset",
]


def _register_builtins() -> None:
    """Register the providers that ship with the core package."""
    for name, cls in (
        ("local", LocalProvider),
        ("ollama", OllamaProvider),
        ("mock", MockProvider),
    ):
        # Already registered (re-import / test runtime); silently skip.
        with contextlib.suppress(ValueError):
            register(name, cls)

    # RFC-012: LiteLLM is an optional provider — installed via
    # pip install zettelforge[litellm]. Registration is conditional
    # on the SDK being importable so the core package never hard-requires it.
    try:
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        register("litellm", LiteLLMProvider)
        _logger.debug("litellm_provider_registered")
    except ImportError:
        _logger.debug("litellm_provider_unavailable")


def _discover_entry_points() -> None:
    """Load third-party providers exposed via entry points.

    Entry-point group: ``zettelforge.llm_providers``. Load failures are
    logged at DEBUG so a broken plugin never stops core startup.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover — Python < 3.8 not supported
        return

    try:
        eps = entry_points(group="zettelforge.llm_providers")
    except Exception:  # pragma: no cover — metadata backend issues
        _logger.debug("entry_point_discovery_failed", exc_info=True)
        return

    for ep in eps:
        try:
            provider_class = ep.load()
            register(ep.name, provider_class)
        except Exception:
            _logger.debug(
                "third_party_provider_load_failed",
                entry_point=ep.name,
                exc_info=True,
            )


_register_builtins()
_discover_entry_points()
