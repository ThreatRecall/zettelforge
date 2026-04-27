"""Deterministic mock provider for tests.

Records every call and returns canned responses in order. See
:class:`MockProvider` for usage patterns.
"""

from __future__ import annotations

from typing import Any


class MockProvider:
    """Returns canned responses in order, cycling when exhausted.

    Every call is recorded in :attr:`calls` so tests can assert what was
    requested. Thread-unsafe by design — tests should exercise one
    instance per test.

    Args:
        responses: Responses to cycle through. Defaults to
            ``["mock response"]``.
    """

    name = "mock"

    def __init__(self, responses: list[str] | None = None, **_: Any) -> None:
        self._responses: list[str] = list(responses) if responses else ["mock response"]
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "json_mode": json_mode,
            }
        )
        response = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        return response
