"""Ollama HTTP provider.

Extracted from the previous ``llm_client._generate_ollama`` for RFC-002
Phase 1. Reads the model tag and URL from constructor args so the
registry can build instances from :class:`~zettelforge.config.LLMConfig`.
"""

from __future__ import annotations

import time
from typing import Any

from zettelforge.log import get_logger

_DEFAULT_MODEL = "qwen2.5:3b"
_DEFAULT_URL = "http://localhost:11434"
_PREVIEW_CHARS = 240

_logger = get_logger("zettelforge.llm.ollama")


class OllamaProvider:
    """Ollama HTTP API provider.

    Args:
        model: Ollama model tag (e.g. ``"qwen2.5:3b"``).
        url: Base URL of the Ollama server.
        timeout: HTTP timeout in seconds (applied to ``ollama.Client``). Before
            RFC-010 this kwarg was silently dropped — requests inherited the
            ollama-python client's effectively-unbounded default. Production
            audit 2026-04-24 attributed `remember()` p95 of ~66s to hung
            Ollama calls; fixing this caps the hang class.
        **_: Ignored — registry may pass other providers' kwargs.
    """

    name = "ollama"

    def __init__(
        self,
        model: str = "",
        url: str = "",
        timeout: float = 180.0,  # see config.LLMConfig.timeout for rationale
        **_: Any,
    ) -> None:
        self._model = model or _DEFAULT_MODEL
        self._url = url or _DEFAULT_URL
        self._timeout = timeout

    def generate(
        self,
        prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        import ollama

        kwargs: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            kwargs["system"] = system
        if json_mode:
            kwargs["format"] = "json"

        # Route through a per-instance Client so ``self._url`` actually affects
        # where the call goes. The module-level ``ollama.generate`` always
        # targets the default localhost:11434, ignoring this provider's config.
        # ``timeout`` is now threaded through per RFC-010.
        client = ollama.Client(host=self._url, timeout=self._timeout)

        prompt_chars = len(prompt)
        system_chars = len(system) if system else 0
        start = time.perf_counter()
        try:
            response = client.generate(**kwargs)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            _logger.warning(
                "llm_call_exception",
                provider="ollama",
                model=self._model,
                duration_ms=round(duration_ms, 1),
                prompt_chars=prompt_chars,
                system_chars=system_chars,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
                error=type(exc).__name__,
                error_msg=str(exc)[:200],
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        raw_response = str(response.get("response", ""))
        stripped = raw_response.strip()
        response_chars = len(raw_response)
        eval_count = response.get("eval_count")
        prompt_eval_count = response.get("prompt_eval_count")
        done_reason = response.get("done_reason")

        # Empty completion is a distinct failure class — surface it loudly.
        # Without this, callers like fact_extractor silently no-op on "" and
        # the failure vanishes from the audit trail entirely.
        is_empty = not stripped
        log_event = "llm_call_empty_response" if is_empty else "llm_call_complete"
        log_level = _logger.warning if is_empty else _logger.debug
        log_kwargs: dict[str, Any] = {
            "provider": "ollama",
            "model": self._model,
            "duration_ms": round(duration_ms, 1),
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
            "system_chars": system_chars,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "json_mode": json_mode,
            "eval_count": eval_count,
            "prompt_eval_count": prompt_eval_count,
            "done_reason": done_reason,
        }
        if is_empty:
            log_kwargs["response_preview"] = raw_response[:_PREVIEW_CHARS]
            log_kwargs["prompt_preview"] = prompt[:_PREVIEW_CHARS]
        log_level(log_event, **log_kwargs)
        return stripped
