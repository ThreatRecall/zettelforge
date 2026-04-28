"""Tests for FactExtractor - Phase 1 of Mem0-style pipeline."""
import pytest
from unittest.mock import patch, MagicMock

from zettelforge.fact_extractor import FactExtractor, ExtractedFact


class TestExtractedFact:
    def test_creation(self):
        fact = ExtractedFact(text="APT28 shifted to edge devices", importance=8)
        assert fact.text == "APT28 shifted to edge devices"
        assert fact.importance == 8

    def test_defaults(self):
        fact = ExtractedFact(text="some fact")
        assert fact.importance == 5


class TestFactExtractorParsing:
    def test_parse_valid_json_array(self):
        extractor = FactExtractor()
        raw = '[{"fact": "APT28 uses edge devices", "importance": 8}, {"fact": "DROPBEAR deprecated", "importance": 6}]'
        facts = extractor._parse_extraction_response(raw)
        assert len(facts) == 2
        assert facts[0].text == "APT28 uses edge devices"
        assert facts[0].importance == 8

    def test_parse_markdown_wrapped(self):
        extractor = FactExtractor()
        raw = '```json\n[{"fact": "test fact", "importance": 7}]\n```'
        facts = extractor._parse_extraction_response(raw)
        assert len(facts) == 1
        assert facts[0].importance == 7

    def test_parse_empty_returns_empty(self):
        extractor = FactExtractor()
        facts = extractor._parse_extraction_response("")
        assert facts == []

    def test_parse_garbage_returns_empty(self):
        extractor = FactExtractor()
        facts = extractor._parse_extraction_response("not json at all")
        assert facts == []

    def test_facts_sorted_by_importance_descending(self):
        extractor = FactExtractor()
        raw = '[{"fact": "low", "importance": 2}, {"fact": "high", "importance": 9}, {"fact": "mid", "importance": 5}]'
        facts = extractor._parse_extraction_response(raw)
        assert facts[0].importance == 9
        assert facts[1].importance == 5
        assert facts[2].importance == 2

    def test_max_facts_limit(self):
        extractor = FactExtractor(max_facts=2)
        raw = '[{"fact": "a", "importance": 9}, {"fact": "b", "importance": 7}, {"fact": "c", "importance": 5}]'
        facts = extractor._parse_extraction_response(raw)
        assert len(facts) == 2


class TestFactExtractorWithMockedLLM:
    @patch("zettelforge.llm_client.generate")
    def test_extract_calls_llm(self, mock_generate):
        mock_generate.return_value = '[{"fact": "APT28 shifted tactics", "importance": 8}]'
        extractor = FactExtractor()
        facts = extractor.extract("APT28 has shifted tactics to edge devices")
        assert len(facts) == 1
        assert facts[0].text == "APT28 shifted tactics"
        mock_generate.assert_called_once()

    @patch("zettelforge.llm_client.generate")
    def test_extract_with_context(self, mock_generate):
        mock_generate.return_value = '[{"fact": "new tactic", "importance": 7}]'
        extractor = FactExtractor()
        facts = extractor.extract(
            "They now use compromised credentials",
            context="Previous: APT28 used DROPBEAR malware"
        )
        assert len(facts) == 1
        # Verify context was in the prompt
        call_args = mock_generate.call_args
        assert "Previous:" in call_args[0][0]  # first positional arg is the prompt

    @patch("zettelforge.llm_client.generate")
    def test_extract_handles_llm_error(self, mock_generate):
        mock_generate.side_effect = Exception("LLM down")
        extractor = FactExtractor()
        facts = extractor.extract("some content")
        assert len(facts) == 1
        assert "some content" in facts[0].text
        assert facts[0].importance == 5
