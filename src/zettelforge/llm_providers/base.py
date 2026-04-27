"""LLMProvider protocol — the contract every LLM backend implements.

Phase 1 of RFC-002. See docs/rfcs/RFC-002-universal-llm-provider.md.

Using ``typing.Protocol`` (PEP 544) rather than an abstract base class so
third-party providers only need duck-type compatibility — no forced
inheritance. ``runtime_checkable`` allows callers to opt into
``isinstance(obj, LLMProvider)`` validation when they want it; the
registry itself does not currently enforce the check at ``register()``
time.

Providers SHOULD raise :class:`LLMProviderConfigurationError` for
non-recoverable setup problems (missing API key, malformed config)
so the caller can surface the error instead of silently falling back.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMProviderConfigurationError(Exception):
    """Raised by a provider when it cannot operate due to configuration.

    Examples: missing API key, invalid URL, unavailable SDK at a version
    we actually need. The public ``generate()`` function propagates this
    rather than swallowing it into an empty string, because retrying
    with the same config will keep failing.
    """


@runtime_checkable
class LLMProvider(Protocol):
    """All LLM providers must implement this protocol.

    Attributes:
        name: Short provider identifier (e.g., ``"local"``, ``"ollama"``,
            ``"openai_compat"``, ``"anthropic"``, ``"mock"``). Used as the
            registry key.
    """

    name: str

    def generate(
        self,
        prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Generate text from a prompt.

        Providers MUST return an empty string on recoverable failure so
        callers can short-circuit cleanly. Configuration errors (missing
        SDK, missing API key, etc.) SHOULD raise so they surface during
        startup rather than failing silently per call.
        """
        ...
