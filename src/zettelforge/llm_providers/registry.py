"""Thread-safe registry of LLM providers keyed by name.

Providers register a class; the registry creates singleton instances on
first access. Callers resolve via :func:`get`. See RFC-002.
"""

from __future__ import annotations

import threading

from zettelforge.llm_providers.base import LLMProvider
from zettelforge.log import get_logger

_logger = get_logger("zettelforge.llm_providers.registry")

_registry: dict[str, type[LLMProvider]] = {}
_instances: dict[str, LLMProvider] = {}
_lock = threading.Lock()


def register(name: str, provider_class: type[LLMProvider]) -> None:
    """Register a provider class by name.

    Raises:
        ValueError: if ``name`` is already registered.
    """
    with _lock:
        if name in _registry:
            raise ValueError(f"LLM provider '{name}' is already registered")
        _registry[name] = provider_class
        _logger.debug("provider_registered", provider=name)


def get(name: str, **kwargs: object) -> LLMProvider:
    """Get or create a provider instance by name.

    Instances are singletons per provider name (thread-safe). ``kwargs``
    are passed to the provider constructor on first creation and ignored
    on subsequent calls (the cached instance is returned).

    Raises:
        ValueError: if ``name`` is not registered.
    """
    if name not in _instances:
        with _lock:
            if name not in _instances:
                if name not in _registry:
                    raise ValueError(
                        f"Unknown LLM provider '{name}'. "
                        f"Available: {', '.join(sorted(_registry.keys())) or '<none>'}"
                    )
                _instances[name] = _registry[name](**kwargs)
                _logger.info("provider_initialized", provider=name)
    return _instances[name]


def available() -> list[str]:
    """Return the sorted list of registered provider names."""
    return sorted(_registry.keys())


def reset() -> None:
    """Clear cached instances. Registrations are preserved.

    Intended for test isolation — production code should not call this.
    """
    with _lock:
        _instances.clear()


def reset_registrations() -> None:
    """Clear both instances and registrations. Tests only."""
    with _lock:
        _instances.clear()
        _registry.clear()
