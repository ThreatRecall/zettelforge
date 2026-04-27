"""LiteLLM routing provider (``litellm``).

RFC-012: delegates generation to ``litellm.completion()``, which routes to
the correct provider SDK based on model name prefix matching. Supports
100+ LLM providers through a single interface.

Designed to be registered as provider name ``"litellm"`` in the
:mod:`zettelforge.llm_providers` registry.

Usage::

    provider = LiteLLMProvider(model="gpt-4o", api_key="...")
    result = provider.generate("What is APT28?")
"""

from __future__ import annotations

import time
from typing import Any

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
            ``"gemini/gemini-2.0-flash"``). LiteLLM routes to the correct
            provider based on the model prefix.
        api_key: API key for the provider. Supports ``${ENV_VAR}``
            references resolved by the config loader. Leave empty to
            rely on standard environment variables (``OPENAI_API_KEY``,
            ``ANTHROPIC_API_KEY``, etc.).
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
        system: str | None = None,
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

        if self._api_key:
            kwargs["api_key"] = self._api_key

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
