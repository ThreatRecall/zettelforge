"""
Tests for RFC-001: Conversational Entity Extractor

Validates hybrid regex+LLM entity extraction, knowledge graph edge inference,
and supersession for conversational entity types.
"""

import os

import pytest

from zettelforge.entity_indexer import EntityExtractor, EntityIndexer
from zettelforge.note_constructor import NoteConstructor


class TestRegexExtraction:
    """CTI regex extraction — deterministic, no LLM needed."""

    def test_cve_extraction_returns_matching_id(self):
        ext = EntityExtractor()
        result = ext.extract_regex("Vulnerability CVE-2024-1234 was exploited")
        assert "cve-2024-1234" in result["cve"]

    def test_actor_extraction_returns_apt_group(self):
        ext = EntityExtractor()
        result = ext.extract_regex("APT28 conducted the attack")
        assert "apt28" in result["actor"]

    def test_tool_extraction_returns_malware_name(self):
        ext = EntityExtractor()
        result = ext.extract_regex("They used Cobalt Strike for C2")
        assert "cobalt-strike" in result["tool"]

    def test_campaign_extraction_returns_operation_name(self):
        ext = EntityExtractor()
        result = ext.extract_regex("Operation Aurora targeted Google")
        assert "operation-aurora" in result["campaign"]

    def test_regex_no_match_returns_empty(self):
        ext = EntityExtractor()
        result = ext.extract_regex("Alice went to Paris yesterday")
        for etype in ["cve", "actor", "tool", "campaign"]:
            assert result.get(etype, []) == []


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="LLM tests crash in CI due to llama-cpp native library segfault",
)
class TestLLMExtraction:
    """LLM NER extraction for conversational types."""

    def test_llm_extraction_returns_person(self):
        ext = EntityExtractor()
        result = ext.extract_llm("Alice went to the store with Bob")
        # LLM should find at least one person
        assert len(result.get("person", [])) >= 1

    def test_llm_extraction_returns_location(self):
        ext = EntityExtractor()
        result = ext.extract_llm("Sarah visited Paris last summer")
        assert len(result.get("location", [])) >= 1

    def test_llm_extraction_short_text_returns_empty(self):
        ext = EntityExtractor()
        result = ext.extract_llm("Hi")
        for etype in ["person", "location", "organization"]:
            assert result.get(etype, []) == []


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="LLM tests crash in CI due to llama-cpp native library segfault",
)
class TestHybridExtraction:
    """Combined regex + LLM extraction via extract_all."""

    def test_extract_all_regex_only_returns_cti(self):
        ext = EntityExtractor()
        result = ext.extract_all("APT28 used CVE-2024-1234", use_llm=False)
        assert "apt28" in result["actor"]
        assert "cve-2024-1234" in result["cve"]
        # Conversational types present but empty
        for etype in ["person", "location", "organization", "event", "activity", "temporal"]:
            assert etype in result

    def test_extract_all_includes_conversational_types(self):
        ext = EntityExtractor()
        result = ext.extract_all("Alice met Bob at Google headquarters", use_llm=True)
        # Should have CTI types (empty) + conversational types (possibly populated)
        assert "person" in result
        assert "location" in result
        assert "organization" in result


class TestNERParsing:
    """Test NER output parsing robustness."""

    def test_parse_valid_json_returns_entities(self):
        ext = EntityExtractor()
        output = '{"person": ["Alice"], "location": ["Paris"], "organization": [], "event": [], "activity": [], "temporal": []}'
        result = ext._parse_ner_output(
            output, ["person", "location", "organization", "event", "activity", "temporal"]
        )
        assert "alice" in result["person"]
        assert "paris" in result["location"]

    def test_parse_markdown_fenced_json_returns_entities(self):
        ext = EntityExtractor()
        output = '```json\n{"person": ["Bob"], "location": [], "organization": [], "event": [], "activity": [], "temporal": []}\n```'
        result = ext._parse_ner_output(
            output, ["person", "location", "organization", "event", "activity", "temporal"]
        )
        assert "bob" in result["person"]

    def test_parse_empty_output_returns_empty(self):
        ext = EntityExtractor()
        result = ext._parse_ner_output("", ["person", "location"])
        assert result == {"person": [], "location": []}


class TestNoteConstructorDelegation:
    """Verify NoteConstructor delegates to EntityExtractor."""

    def test_constructor_uses_extractor(self):
        nc = NoteConstructor()
        assert hasattr(nc, "_extractor")
        assert isinstance(nc._extractor, EntityExtractor)

    def test_constructor_extract_entities_delegates(self):
        nc = NoteConstructor()
        result = nc.extract_entities("APT28 uses Cobalt Strike")
        assert "actor" in result
        assert "tool" in result


class TestInferEntityType:
    """Test _infer_entity_type with conversational type hints."""

    def test_cve_pattern_returns_cve(self):
        nc = NoteConstructor()
        assert nc._infer_entity_type("CVE-2024-1234") == "cve"

    def test_actor_pattern_returns_actor(self):
        nc = NoteConstructor()
        assert nc._infer_entity_type("APT28") == "actor"

    def test_tool_pattern_returns_tool(self):
        nc = NoteConstructor()
        assert nc._infer_entity_type("Cobalt Strike") == "tool"

    def test_conversational_type_hint_trusted(self):
        nc = NoteConstructor()
        assert nc._infer_entity_type("Alice", entity_type_hint="person") == "person"
        assert nc._infer_entity_type("Paris", entity_type_hint="location") == "location"
        assert nc._infer_entity_type("Google", entity_type_hint="organization") == "organization"
        assert nc._infer_entity_type("birthday", entity_type_hint="event") == "event"

    def test_unknown_entity_returns_entity(self):
        nc = NoteConstructor()
        assert nc._infer_entity_type("something_random") == "entity"


class TestEntityIndexerConversational:
    """Test EntityIndexer with conversational entity types."""

    def test_index_has_all_entity_types(self):
        idx = EntityIndexer()
        for etype in EntityExtractor.ENTITY_TYPES:
            assert etype in idx.index

    def test_add_note_with_person_entity(self):
        idx = EntityIndexer()
        idx.add_note("note-1", {"person": ["alice"], "location": ["paris"]})
        assert "note-1" in idx.get_note_ids("person", "alice")
        assert "note-1" in idx.get_note_ids("location", "paris")

    def test_search_entities_finds_across_types(self):
        idx = EntityIndexer()
        idx.add_note("note-1", {"person": ["alice"], "location": ["paris"]})
        idx.add_note("note-2", {"organization": ["paris-university"]})
        results = idx.search_entities("paris")
        assert "location" in results
        assert "organization" in results
