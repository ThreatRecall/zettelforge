"""Tests for MemoryUpdater - Phase 2 of Mem0-style pipeline."""
import pytest
import tempfile
from unittest.mock import patch, MagicMock
from datetime import datetime

from zettelforge.memory_updater import MemoryUpdater, UpdateOperation
from zettelforge.memory_manager import MemoryManager
from zettelforge.note_schema import MemoryNote, Content, Semantic, Embedding, Metadata

NOW = datetime.now().isoformat()


def _make_note(note_id: str, raw: str, importance: int = 5) -> MemoryNote:
    return MemoryNote(
        id=note_id,
        created_at=NOW,
        updated_at=NOW,
        content=Content(raw=raw, source_type="test", source_ref=""),
        semantic=Semantic(context=raw[:50], keywords=[], tags=[], entities=[]),
        embedding=Embedding(vector=[0.1] * 768),
        metadata=Metadata(importance=importance),
    )


class TestUpdateOperation:
    def test_values(self):
        assert UpdateOperation.ADD.value == "ADD"
        assert UpdateOperation.UPDATE.value == "UPDATE"
        assert UpdateOperation.DELETE.value == "DELETE"
        assert UpdateOperation.NOOP.value == "NOOP"


class TestMemoryUpdaterParsing:
    def test_parse_add(self):
        updater = MemoryUpdater.__new__(MemoryUpdater)
        op = updater._parse_operation_response('{"operation": "ADD", "reason": "new fact"}')
        assert op == UpdateOperation.ADD

    def test_parse_update(self):
        updater = MemoryUpdater.__new__(MemoryUpdater)
        op = updater._parse_operation_response('{"operation": "UPDATE", "reason": "refines existing"}')
        assert op == UpdateOperation.UPDATE

    def test_parse_delete(self):
        updater = MemoryUpdater.__new__(MemoryUpdater)
        op = updater._parse_operation_response('{"operation": "DELETE", "reason": "contradicts"}')
        assert op == UpdateOperation.DELETE

    def test_parse_noop(self):
        updater = MemoryUpdater.__new__(MemoryUpdater)
        op = updater._parse_operation_response('{"operation": "NOOP", "reason": "already stored"}')
        assert op == UpdateOperation.NOOP

    def test_parse_garbage_defaults_to_add(self):
        updater = MemoryUpdater.__new__(MemoryUpdater)
        op = updater._parse_operation_response("not json")
        assert op == UpdateOperation.ADD

    def test_parse_markdown_wrapped(self):
        updater = MemoryUpdater.__new__(MemoryUpdater)
        op = updater._parse_operation_response('```json\n{"operation": "DELETE", "reason": "old"}\n```')
        assert op == UpdateOperation.DELETE


class TestMemoryUpdaterDecision:
    def test_add_when_no_similar_notes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(
                jsonl_path=f"{tmpdir}/notes.jsonl",
                lance_path=f"{tmpdir}/vectordb",
            )
            updater = MemoryUpdater(mm)
            op = updater.decide("APT28 shifted to edge devices", similar_notes=[])
            assert op == UpdateOperation.ADD

    @patch("zettelforge.llm_client.generate")
    def test_update_when_similar_exists(self, mock_generate):
        mock_generate.return_value = '{"operation": "UPDATE", "reason": "refines existing"}'
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(
                jsonl_path=f"{tmpdir}/notes.jsonl",
                lance_path=f"{tmpdir}/vectordb",
            )
            updater = MemoryUpdater(mm)
            existing = _make_note("old_001", "APT28 uses DROPBEAR malware")
            op = updater.decide("APT28 no longer uses DROPBEAR", similar_notes=[existing])
            assert op == UpdateOperation.UPDATE

    @patch("zettelforge.llm_client.generate")
    def test_delete_on_contradiction(self, mock_generate):
        mock_generate.return_value = '{"operation": "DELETE", "reason": "contradicts existing"}'
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(
                jsonl_path=f"{tmpdir}/notes.jsonl",
                lance_path=f"{tmpdir}/vectordb",
            )
            updater = MemoryUpdater(mm)
            existing = _make_note("old_002", "Server ALPHA is compromised")
            op = updater.decide("Server ALPHA has been fully remediated", similar_notes=[existing])
            assert op == UpdateOperation.DELETE


class TestMemoryUpdaterApply:
    def test_apply_add_creates_note(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(
                jsonl_path=f"{tmpdir}/notes.jsonl",
                lance_path=f"{tmpdir}/vectordb",
            )
            updater = MemoryUpdater(mm)
            note, status = updater.apply(
                UpdateOperation.ADD,
                fact_text="New fact about APT28",
                importance=8,
                source_ref="extraction:0",
                similar_notes=[],
            )
            assert status == "added"
            assert note is not None
            assert note.metadata.importance == 8
            assert mm.store.count_notes() == 1

    def test_apply_update_supersedes_old(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(
                jsonl_path=f"{tmpdir}/notes.jsonl",
                lance_path=f"{tmpdir}/vectordb",
            )
            old_note, _ = mm.remember("APT28 uses DROPBEAR", domain="cti")
            updater = MemoryUpdater(mm)
            new_note, status = updater.apply(
                UpdateOperation.UPDATE,
                fact_text="APT28 no longer uses DROPBEAR, shifted to edge exploitation",
                importance=9,
                source_ref="extraction:1",
                similar_notes=[old_note],
            )
            assert status == "updated"
            assert new_note is not None
            refreshed_old = mm.store.get_note_by_id(old_note.id)
            assert refreshed_old.links.superseded_by == new_note.id

    def test_apply_delete_marks_superseded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(
                jsonl_path=f"{tmpdir}/notes.jsonl",
                lance_path=f"{tmpdir}/vectordb",
            )
            old_note, _ = mm.remember("Server ALPHA is compromised", domain="incident")
            updater = MemoryUpdater(mm)
            new_note, status = updater.apply(
                UpdateOperation.DELETE,
                fact_text="Server ALPHA fully remediated",
                importance=7,
                source_ref="extraction:2",
                similar_notes=[old_note],
            )
            assert status == "corrected"
            refreshed_old = mm.store.get_note_by_id(old_note.id)
            assert refreshed_old.links.superseded_by is not None

    def test_apply_noop_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(
                jsonl_path=f"{tmpdir}/notes.jsonl",
                lance_path=f"{tmpdir}/vectordb",
            )
            updater = MemoryUpdater(mm)
            note, status = updater.apply(
                UpdateOperation.NOOP,
                fact_text="Already known",
                importance=5,
                source_ref="extraction:3",
                similar_notes=[],
            )
            assert status == "noop"
            assert note is None
            assert mm.store.count_notes() == 0
