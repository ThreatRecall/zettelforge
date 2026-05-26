"""Tests for shared JSON parsing utility."""

import pytest
from zettelforge.json_parse import (
    extract_json,
    get_parse_stats,
    reset_parse_stats,
    strip_thinking_tags,
)


class TestExtractJson:
    def setup_method(self):
        reset_parse_stats()

    def test_simple_object(self):
        assert extract_json('{"key": "value"}') == {"key": "value"}

    def test_simple_array(self):
        assert extract_json("[1, 2, 3]", expect="array") == [1, 2, 3]

    def test_code_fence_json(self):
        raw = '```json\n{"key": "value"}\n```'
        assert extract_json(raw) == {"key": "value"}

    def test_code_fence_no_lang(self):
        raw = '```\n{"key": "value"}\n```'
        assert extract_json(raw) == {"key": "value"}

    def test_surrounding_prose(self):
        raw = 'Here is the result: {"key": "value"} and some more text.'
        assert extract_json(raw) == {"key": "value"}

    def test_nested_object(self):
        raw = '{"outer": {"inner": "value"}}'
        result = extract_json(raw)
        assert result == {"outer": {"inner": "value"}}

    def test_array_of_objects(self):
        raw = '[{"fact": "APT28 uses Cobalt Strike", "importance": 8}]'
        result = extract_json(raw, expect="array")
        assert len(result) == 1
        assert result[0]["fact"] == "APT28 uses Cobalt Strike"

    def test_none_input(self):
        assert extract_json(None) is None

    def test_empty_string(self):
        assert extract_json("") is None

    def test_garbage_input(self):
        assert extract_json("this is not json at all") is None

    def test_wrong_type_object_when_array_expected(self):
        assert extract_json('{"key": "value"}', expect="array") is None

    def test_wrong_type_array_when_object_expected(self):
        assert extract_json("[1, 2, 3]", expect="object") is None

    def test_stats_increment_on_success(self):
        extract_json('{"key": "value"}')
        stats = get_parse_stats()
        assert stats["success"] == 1
        assert stats["failure"] == 0

    def test_stats_increment_on_failure(self):
        extract_json("garbage")
        stats = get_parse_stats()
        assert stats["success"] == 0
        assert stats["failure"] == 1

    def test_markdown_with_prose_before_and_after(self):
        raw = 'Here is the JSON:\n```json\n[{"a": 1}]\n```\nDone.'
        result = extract_json(raw, expect="array")
        assert result == [{"a": 1}]

    def test_think_tags_are_removed_before_object_parse(self):
        raw = '<think>private chain of thought {"not": "json"}</think>\n{"ok": true}'
        assert extract_json(raw) == {"ok": True}

    def test_thinking_tags_are_removed_before_array_parse(self):
        raw = '<thinking>reasoning [0]</thinking>\n[{"ok": true}]'
        assert extract_json(raw, expect="array") == [{"ok": True}]

    def test_strip_thinking_tags_preserves_markdown_bold(self):
        raw = '**thinking** is just markdown {"ok": true}'
        assert strip_thinking_tags(raw) == raw
