"""Tests for LLM client (local llama-cpp-python + ollama fallback)."""

import os
from unittest.mock import patch

import pytest

from zettelforge.llm_client import _get_local_llm, generate

_RUN_LLM_INTEGRATION = os.environ.get("ZETTELFORGE_RUN_LLM_INTEGRATION") == "1"
_SKIP_INTEGRATION = pytest.mark.skipif(
    not _RUN_LLM_INTEGRATION,
    reason=(
        "LLM integration tests require an explicitly configured local model "
        "or Ollama; set ZETTELFORGE_RUN_LLM_INTEGRATION=1 to run them"
    ),
)


@_SKIP_INTEGRATION
class TestLocalLLMIntegration:
    """Full-stack integration tests requiring a real llama-cpp or Ollama backend.

    These exercise output quality (instruction-following, JSON-ish content), not
    just API shape, so they need a real model. Stay skipped in CI — the mock
    provider cannot meaningfully verify quality. See ``TestGenerateContract``
    below for CI-safe coverage of the ``generate()`` API contract.
    """

    def test_generate_returns_string(self):
        result = generate("Say hello in one word.", max_tokens=10)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_follows_instruction(self):
        result = generate(
            "Classify this as factual, temporal, or relational: What CVE was used?",
            max_tokens=20,
            temperature=0.1,
        )
        assert any(
            word in result.lower()
            for word in ["factual", "temporal", "relational", "exploratory", "causal"]
        )

    def test_generate_json_extraction(self):

        result = generate(
            'Extract facts as JSON array: [{"fact": "text", "importance": 1-10}]\n'
            "Text: APT28 uses Cobalt Strike.",
            max_tokens=200,
            temperature=0.1,
        )
        # Should contain JSON-like content
        assert "{" in result

    def test_model_singleton(self):
        m1 = _get_local_llm()
        m2 = _get_local_llm()
        assert m1 is m2

    def test_system_prompt(self):
        result = generate(
            "What tools does APT28 use?",
            max_tokens=50,
            system="Reply in exactly one sentence.",
        )
        assert isinstance(result, str)
        assert len(result) > 0


class TestGenerateContract:
    """Verify the public ``generate()`` API contract via the mock provider.

    Covers the same surface area as the skipped integration tests (string
    return type, ``max_tokens`` / ``system`` / ``json_mode`` kwargs flowing
    through to the provider) but asserts contract — return types and that
    arguments reach the provider — rather than model output quality. Runs
    in CI because it has no external dependency.
    """

    @pytest.fixture(autouse=True)
    def _mock_provider(self, monkeypatch):
        from zettelforge import llm_client
        from zettelforge.llm_providers import MockProvider, registry

        monkeypatch.setenv("ZETTELFORGE_LLM_PROVIDER", "mock")

        # Capture the instance constructed by the registry so tests can
        # inspect ``calls``. A fresh instance per test keeps ``calls`` clean.
        captured: dict = {}

        class CapturingMockProvider(MockProvider):
            def __init__(self, **_kwargs):
                super().__init__(responses=['{"ok": true}'])
                captured["instance"] = self

        original_cls = registry._registry.get("mock")
        registry._registry["mock"] = CapturingMockProvider
        llm_client.reload()
        try:
            yield captured
        finally:
            if original_cls is not None:
                registry._registry["mock"] = original_cls
            llm_client.reload()

    def test_generate_returns_string(self, _mock_provider):
        result = generate("hello", max_tokens=10)
        assert isinstance(result, str)
        assert result == '{"ok": true}'

    def test_max_tokens_flows_to_provider(self, _mock_provider):
        generate("hello", max_tokens=42)
        assert _mock_provider["instance"].calls[-1]["max_tokens"] == 42

    def test_system_prompt_flows_to_provider(self, _mock_provider):
        generate("hello", system="Be concise.")
        assert _mock_provider["instance"].calls[-1]["system"] == "Be concise."

    def test_json_mode_flows_to_provider(self, _mock_provider):
        generate("hello", json_mode=True)
        assert _mock_provider["instance"].calls[-1]["json_mode"] is True


class TestGenerateJsonMode:
    """Verify generate() propagates json_mode and system args to the provider.

    Post RFC-002 (Phase 1) these flags flow through the provider registry,
    so the tests intercept :func:`zettelforge.llm_providers.registry.get`
    and return a :class:`MockProvider` whose recorded calls we inspect.
    """

    def _with_mock_provider(self, provider_name: str):
        """Context manager returning (MockProvider, patch) for ``provider_name``."""
        from zettelforge.llm_providers import MockProvider

        mock = MockProvider(responses=['{"test": true}'])
        return (
            mock,
            patch(
                "zettelforge.llm_providers.registry.get",
                return_value=mock,
            ),
            patch(
                "zettelforge.llm_client.get_llm_provider",
                return_value=provider_name,
            ),
        )

    def test_json_mode_passed_to_provider(self):
        mock, registry_patch, provider_patch = self._with_mock_provider("ollama")
        with registry_patch, provider_patch:
            generate("test prompt", json_mode=True)
        assert mock.calls[-1]["json_mode"] is True
        assert mock.calls[-1]["prompt"] == "test prompt"

    def test_system_prompt_passed_to_provider(self):
        mock, registry_patch, provider_patch = self._with_mock_provider("ollama")
        with registry_patch, provider_patch:
            generate("test", system="Be a JSON robot")
        assert mock.calls[-1]["system"] == "Be a JSON robot"
