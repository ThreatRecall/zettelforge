"""Tests for LLM client (local llama-cpp-python + ollama fallback)."""
import pytest
from zettelforge.llm_client import generate, _get_local_llm


class TestLocalLLM:
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
        assert any(word in result.lower() for word in ["factual", "temporal", "relational", "exploratory", "causal"])

    def test_generate_json_extraction(self):
        import json
        result = generate(
            'Extract facts as JSON array: [{"fact": "text", "importance": 1-10}]\n'
            'Text: APT28 uses Cobalt Strike.',
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
