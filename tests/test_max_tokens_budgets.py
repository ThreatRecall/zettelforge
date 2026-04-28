"""Regression tests for per-call-site max_tokens budgets (RFC-125).

Snapshots the literal max_tokens values passed to generate() at each
call site so operators can verify they meet the documented thresholds.
"""

import pytest

from zettelforge.json_parse import extract_json, strip_thinking_tags
from zettelforge.config import get_config


class TestMaxTokensBudgets:
    """Each call site that calls generate() must pass max_tokens >= a
    known minimum threshold.  These tests import the module, trigger
    the config path (but not an actual LLM call), and assert the
    configured value."""

    def test_note_constructor_causal_budget(self):
        """note_constructor.extract_causal_triples: max_tokens >= 8000."""
        cfg = get_config()
        assert cfg.llm.max_tokens_causal >= 8000, (
            f"Expected max_tokens_causal >= 8000, got {cfg.llm.max_tokens_causal}"
        )

    def test_synthesis_generator_budget(self):
        """synthesis_generator._generate_synthesis: max_tokens >= 2500."""
        cfg = get_config()
        assert cfg.llm.max_tokens_synthesis >= 2500, (
            f"Expected max_tokens_synthesis >= 2500, got {cfg.llm.max_tokens_synthesis}"
        )

    def test_fact_extractor_budget(self):
        """fact_extractor.extract: max_tokens >= 2500."""
        cfg = get_config()
        assert cfg.llm.max_tokens_extraction >= 2500, (
            f"Expected max_tokens_extraction >= 2500, got {cfg.llm.max_tokens_extraction}"
        )

    def test_entity_indexer_ner_budget(self):
        """entity_indexer.extract_llm: max_tokens >= 2500."""
        cfg = get_config()
        assert cfg.llm.max_tokens_ner >= 2500, (
            f"Expected max_tokens_ner >= 2500, got {cfg.llm.max_tokens_ner}"
        )

    def test_memory_evolver_budget(self):
        """memory_evolver.evaluate_evolution: max_tokens >= 2500."""
        cfg = get_config()
        assert cfg.llm.max_tokens_evolve >= 2500, (
            f"Expected max_tokens_evolve >= 2500, got {cfg.llm.max_tokens_evolve}"
        )


class TestBudgetsReadFromConfig:
    """Verify env var overrides work for each budget field."""

    def _override_and_reload(self, env_key: str, value: str, attr: str):
        import os
        os.environ[env_key] = value
        try:
            from zettelforge.config import reload_config
            cfg = reload_config()
            assert getattr(cfg.llm, attr) == int(value)
        finally:
            del os.environ[env_key]
            from zettelforge.config import reload_config
            reload_config()

    def test_causal_override_from_env(self):
        self._override_and_reload("ZETTELFORGE_LLM_MAX_TOKENS_CAUSAL", "9999", "max_tokens_causal")

    def test_synthesis_override_from_env(self):
        self._override_and_reload("ZETTELFORGE_LLM_MAX_TOKENS_SYNTHESIS", "5000", "max_tokens_synthesis")

    def test_extraction_override_from_env(self):
        self._override_and_reload("ZETTELFORGE_LLM_MAX_TOKENS_EXTRACTION", "5000", "max_tokens_extraction")

    def test_ner_override_from_env(self):
        self._override_and_reload("ZETTELFORGE_LLM_MAX_TOKENS_NER", "5000", "max_tokens_ner")

    def test_evolve_override_from_env(self):
        self._override_and_reload("ZETTELFORGE_LLM_MAX_TOKENS_EVOLVE", "5000", "max_tokens_evolve")


class TestReasoningModelScaling:
    """When reasoning_model=True, budgets and timeout should auto-scale."""

    def test_reasoning_model_auto_scales_timeout_and_budgets(self):
        """reasoning_model=True bumps timeout to >= 180s and doubles budgets."""
        import os
        os.environ["ZETTELFORGE_LLM_REASONING_MODEL"] = "true"
        os.environ["ZETTELFORGE_LLM_TIMEOUT"] = "30"
        try:
            from zettelforge.config import reload_config
            cfg = reload_config()
            assert cfg.llm.timeout >= 180.0
            assert cfg.llm.max_tokens_causal >= 8000 * 2
            assert cfg.llm.max_tokens_synthesis >= 2500 * 2
            assert cfg.llm.max_tokens_extraction >= 2500 * 2
            assert cfg.llm.max_tokens_ner >= 2500 * 2
            assert cfg.llm.max_tokens_evolve >= 2500 * 2
            assert cfg.llm.reasoning_model is True
        finally:
            del os.environ["ZETTELFORGE_LLM_REASONING_MODEL"]
            del os.environ["ZETTELFORGE_LLM_TIMEOUT"]
            from zettelforge.config import reload_config
            reload_config()

    def test_reasoning_model_respects_existing_high_timeout(self):
        """If timeout is already >= 180s, reasoning_model leaves it alone."""
        import os
        os.environ["ZETTELFORGE_LLM_REASONING_MODEL"] = "true"
        os.environ["ZETTELFORGE_LLM_TIMEOUT"] = "300"
        try:
            from zettelforge.config import reload_config
            cfg = reload_config()
            assert cfg.llm.timeout == 300.0
        finally:
            del os.environ["ZETTELFORGE_LLM_REASONING_MODEL"]
            del os.environ["ZETTELFORGE_LLM_TIMEOUT"]
            from zettelforge.config import reload_config
            reload_config()

    def test_reasoning_model_false_does_not_scale(self):
        """reasoning_model=False keeps default budgets."""
        cfg = get_config()
        assert cfg.llm.reasoning_model is False
        # Defaults should stay at their configured values
        assert cfg.llm.max_tokens_causal >= 8000
        assert cfg.llm.max_tokens_synthesis >= 2500


class TestStripThinkingTags:
    """Tests for strip_thinking_tags in json_parse.py."""

    def test_strips_thinking_tags_simple(self):
        """<thinking>...</thinking> block is removed."""
        raw = "<thinking>Let me analyze</thinking>result{\"key\": \"value\"}"
        cleaned = strip_thinking_tags(raw)
        assert "thinking" not in cleaned
        assert "Let me analyze" not in cleaned
        assert cleaned == "result{\"key\": \"value\"}"

    def test_strips_think_tags_no_ing(self):
        """<think>...</think> (without 'ing') block is also removed."""
        raw = "<think>Processing</think>result{\"key\": \"value\"}"
        cleaned = strip_thinking_tags(raw)
        assert "think" not in cleaned
        assert cleaned == "result{\"key\": \"value\"}"

    def test_strips_thinking_tags_multiline(self):
        """Multi-line thinking blocks are removed."""
        raw = "<thinking>\nStep 1\nStep 2\n</thinking>\n{\"key\": \"value\"}"
        cleaned = strip_thinking_tags(raw)
        assert "Step 1" not in cleaned
        assert "{" in cleaned

    def test_no_thinking_tags(self):
        """Text without thinking tags is unchanged."""
        raw = "{\"key\": \"value\"}"
        cleaned = strip_thinking_tags(raw)
        assert cleaned == raw

    def test_empty_input(self):
        """Empty string produces empty string."""
        assert strip_thinking_tags("") == ""

    def test_extract_json_with_thinking_tags(self):
        """extract_json handles input with thinking tags and code fences."""
        raw = "<thinking>Let me process</thinking>response```json\n{\"key\": \"value\"}\n```"
        result = extract_json(raw)
        assert result == {"key": "value"}

    def test_extract_json_with_thinking_tags_no_fence(self):
        """extract_json handles thinking tags without code fences."""
        raw = "<thinking>Analyzing</thinking>{\"key\": \"value\"}"
        result = extract_json(raw)
        assert result == {"key": "value"}

    def test_extract_json_with_think_short_tag(self):
        """extract_json handles <think> (no 'ing') tags."""
        raw = "<think>Processing</think>```json\n{\"key\": \"value\"}\n```"
        result = extract_json(raw)
        assert result == {"key": "value"}

    def test_extract_json_preserves_prose_after_thinking(self):
        """Text after thinking but before JSON is preserved for extraction."""
        raw = "<thinking>Analyze</thinking>The answer is: {\"key\": \"value\"}"
        result = extract_json(raw)
        assert result == {"key": "value"}

    def test_parse_stats_are_accessible(self):
        """get_parse_stats() and reset_parse_stats() work."""
        from zettelforge.json_parse import get_parse_stats, reset_parse_stats
        reset_parse_stats()
        stats = get_parse_stats()
        assert "success" in stats
        assert "failure" in stats
