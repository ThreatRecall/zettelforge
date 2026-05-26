"""Regression tests for configurable LLM max-token budgets."""

from __future__ import annotations

import pytest


_TOKEN_ENV_VARS = [
    "ZETTELFORGE_LLM_MAX_TOKENS",
    "ZETTELFORGE_LLM_MAX_TOKENS_CAUSAL",
    "ZETTELFORGE_LLM_MAX_TOKENS_SYNTHESIS",
    "ZETTELFORGE_LLM_MAX_TOKENS_EXTRACTION",
    "ZETTELFORGE_LLM_MAX_TOKENS_NER",
    "ZETTELFORGE_LLM_MAX_TOKENS_EVOLVE",
    "ZETTELFORGE_LLM_REASONING_MODEL",
]


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch):
    from zettelforge.config import reload_config

    for name in _TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    reload_config()
    yield
    reload_config()


def test_llm_config_defaults_include_reasoning_budget_floors():
    from zettelforge.config import LLMConfig

    cfg = LLMConfig()

    assert cfg.max_tokens == 400
    assert cfg.max_tokens_causal == 8000
    assert cfg.max_tokens_synthesis == 2500
    assert cfg.max_tokens_extraction == 2500
    assert cfg.max_tokens_ner == 2500
    assert cfg.max_tokens_evolve == 2500
    assert cfg.reasoning_model is False


def test_llm_budget_env_overrides_and_reasoning_scaling(monkeypatch):
    from zettelforge.config import reload_config

    monkeypatch.setenv("ZETTELFORGE_LLM_MAX_TOKENS", "123")
    monkeypatch.setenv("ZETTELFORGE_LLM_MAX_TOKENS_CAUSAL", "16000")
    monkeypatch.setenv("ZETTELFORGE_LLM_MAX_TOKENS_SYNTHESIS", "100")
    monkeypatch.setenv("ZETTELFORGE_LLM_TIMEOUT", "30")
    monkeypatch.setenv("ZETTELFORGE_LLM_REASONING_MODEL", "true")

    cfg = reload_config().llm

    assert cfg.max_tokens == 123
    assert cfg.max_tokens_causal == 16000
    assert cfg.max_tokens_synthesis == 2500
    assert cfg.timeout == 180.0
    assert cfg.reasoning_model is True


def test_generate_uses_config_default_when_max_tokens_omitted(monkeypatch):
    from zettelforge import llm_client
    from zettelforge.config import reload_config
    from zettelforge.llm_providers import MockProvider, registry

    monkeypatch.setenv("ZETTELFORGE_LLM_PROVIDER", "mock")
    monkeypatch.setenv("ZETTELFORGE_LLM_MAX_TOKENS", "321")
    reload_config()

    captured: dict[str, MockProvider] = {}

    class CapturingMockProvider(MockProvider):
        def __init__(self, **_kwargs):
            super().__init__(responses=['{"ok": true}'])
            captured["instance"] = self

    original_cls = registry._registry.get("mock")
    registry._registry["mock"] = CapturingMockProvider
    llm_client.reload()
    try:
        assert llm_client.generate("hello") == '{"ok": true}'
        assert captured["instance"].calls[-1]["max_tokens"] == 321
    finally:
        if original_cls is not None:
            registry._registry["mock"] = original_cls
        llm_client.reload()


def test_causal_extraction_uses_configured_budget(monkeypatch):
    from zettelforge.config import reload_config
    from zettelforge.note_constructor import NoteConstructor

    calls: list[dict] = []

    def fake_generate(prompt: str, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        return '[{"subject":"APT28","relation":"uses","object":"Cobalt Strike"}]'

    monkeypatch.setenv("ZETTELFORGE_LLM_MAX_TOKENS_CAUSAL", "9001")
    reload_config()
    monkeypatch.setattr("zettelforge.llm_client.generate", fake_generate)

    triples = NoteConstructor().extract_causal_triples("APT28 uses Cobalt Strike")

    assert triples
    assert calls[-1]["max_tokens"] == 9001


def test_synthesis_uses_configured_budget(monkeypatch):
    from zettelforge.config import reload_config
    from zettelforge.synthesis_generator import SynthesisGenerator

    calls: list[dict] = []

    def fake_generate(prompt: str, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        return '{"answer":"ok","confidence":0.9,"sources":[]}'

    monkeypatch.setenv("ZETTELFORGE_LLM_MAX_TOKENS_SYNTHESIS", "3333")
    reload_config()
    monkeypatch.setattr("zettelforge.llm_client.generate", fake_generate)

    result = SynthesisGenerator()._generate_synthesis("q", "context", "direct_answer")

    assert result["answer"] == "ok"
    assert calls[-1]["max_tokens"] == 3333


def test_fact_extraction_uses_configured_budget(monkeypatch):
    from zettelforge.config import reload_config
    from zettelforge.fact_extractor import FactExtractor

    calls: list[dict] = []

    def fake_generate(prompt: str, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        return '[{"fact":"APT28 uses Cobalt Strike","importance":8}]'

    monkeypatch.setenv("ZETTELFORGE_LLM_MAX_TOKENS_EXTRACTION", "3334")
    reload_config()
    monkeypatch.setattr("zettelforge.llm_client.generate", fake_generate)

    facts = FactExtractor().extract("APT28 uses Cobalt Strike")

    assert facts
    assert calls[-1]["max_tokens"] == 3334


def test_entity_ner_uses_configured_budget(monkeypatch):
    from zettelforge.config import reload_config
    from zettelforge.entity_indexer import EntityExtractor

    calls: list[dict] = []

    def fake_generate(prompt: str, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        return '{"person":[],"location":[],"organization":["ACME"],"event":[],"activity":[],"temporal":[]}'

    monkeypatch.setenv("ZETTELFORGE_LLM_MAX_TOKENS_NER", "3335")
    reload_config()
    monkeypatch.setattr("zettelforge.llm_client.generate", fake_generate)

    entities = EntityExtractor().extract_llm("ACME observed a campaign")

    assert entities["organization"] == ["acme"]
    assert calls[-1]["max_tokens"] == 3335


def test_memory_evolution_uses_configured_budget(monkeypatch):
    from zettelforge.config import reload_config
    from zettelforge.memory_evolver import MemoryEvolver
    from zettelforge.note_schema import Content, Embedding, MemoryNote, Metadata, Semantic

    calls: list[dict] = []

    def fake_generate(prompt: str, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        return '{"action":"keep","reason":"redundant","updated_content":""}'

    def note(note_id: str, raw: str) -> MemoryNote:
        return MemoryNote(
            id=note_id,
            created_at="2026-05-26T00:00:00",
            updated_at="2026-05-26T00:00:00",
            content=Content(raw=raw, source_type="test", source_ref=note_id),
            semantic=Semantic(context="", keywords=[], tags=[], entities=[]),
            embedding=Embedding(vector=[]),
            metadata=Metadata(),
        )

    monkeypatch.setenv("ZETTELFORGE_LLM_MAX_TOKENS_EVOLVE", "3336")
    reload_config()
    monkeypatch.setattr("zettelforge.memory_evolver.generate", fake_generate)

    result = MemoryEvolver(memory_manager=object()).evaluate_evolution(
        note("new", "APT28"),
        note("old", "APT29"),
    )

    assert result["action"] == "keep"
    assert calls[-1]["max_tokens"] == 3336
