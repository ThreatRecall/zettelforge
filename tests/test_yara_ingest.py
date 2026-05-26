"""End-to-end ingest tests for zettelforge.yara.ingest."""

from pathlib import Path

import pytest

from zettelforge.memory_manager import MemoryManager
from zettelforge.note_schema import Content, Embedding, MemoryNote, Metadata, Semantic
from zettelforge.yara.ingest import ingest_rule, ingest_rules_dir

FIXTURES = Path(__file__).parent / "fixtures" / "yara"


@pytest.fixture
def mm(tmp_path: Path) -> MemoryManager:
    """Fresh MemoryManager backed by a scratch SQLite/JSONL pair."""
    return MemoryManager(
        jsonl_path=str(tmp_path / "notes.jsonl"),
        lance_path=str(tmp_path / "vec"),
    )


def test_ingest_rule_creates_note_and_relations(mm: MemoryManager) -> None:
    note, relations = ingest_rule(FIXTURES / "technique_loader.yar", mm, tier="warn")
    assert note is not None
    assert note.content.source_type == "yara"
    # Every CCCS technique rule in the fixtures maps to at least one
    # AttackPattern + technique YaraTag relation.
    rel_kinds = {r["rel"] for r in relations}
    assert "detects" in rel_kinds
    assert any(r["to_type"] == "YaraTag" for r in relations)


def test_ingest_rule_accepts_raw_text(mm: MemoryManager) -> None:
    src = (FIXTURES / "malware_hash.yar").read_text()
    note, _ = ingest_rule(src, mm, tier="non_cccs")
    assert note is not None


def test_ingest_rule_is_idempotent_on_content_sha256(mm: MemoryManager) -> None:
    """Second call for an unchanged rule returns the original note."""
    first, _ = ingest_rule(FIXTURES / "technique_loader.yar", mm, tier="warn")
    second, _ = ingest_rule(FIXTURES / "technique_loader.yar", mm, tier="warn")
    assert first is not None and second is not None
    assert first.id == second.id


def test_ingest_rules_dir_walks_tree(mm: MemoryManager) -> None:
    result = ingest_rules_dir(FIXTURES, mm, tier="warn")
    assert result["ingested"] >= 3
    assert result["errors"] == []


def test_ingest_rules_dir_bulk_defers_enrichment_and_flushes() -> None:
    class _Store:
        def get_note_by_source_ref(self, _source_ref):
            return None

        def add_kg_edge(self, **_kwargs):
            return None

    class _MM:
        def __init__(self):
            self.store = _Store()
            self.calls = []
            self.flushed = False

        def remember(self, *, content, source_type, source_ref, domain, sync):
            self.calls.append({"source_ref": source_ref, "sync": sync})
            note = MemoryNote(
                id=f"note-{len(self.calls)}",
                created_at="2026-05-26T00:00:00",
                updated_at="2026-05-26T00:00:00",
                content=Content(raw=content, source_type=source_type, source_ref=source_ref),
                semantic=Semantic(context="", keywords=[], tags=[], entities=[]),
                embedding=Embedding(vector=[]),
                metadata=Metadata(domain=domain),
            )
            return note, "created"

        def flush(self, timeout=None):
            self.flushed = True
            self.flush_timeout = timeout
            return True

    mm = _MM()

    result = ingest_rules_dir(FIXTURES, mm, tier="warn", bulk=True, flush_timeout=1.5)

    assert result["ingested"] >= 3
    assert result["errors"] == []
    assert mm.calls
    assert all(call["sync"] is False for call in mm.calls)
    assert mm.flushed is True
    assert mm.flush_timeout == 1.5


def test_ingest_rules_dir_second_run_skips_existing(mm: MemoryManager) -> None:
    """Re-ingesting the same tree bumps ``skipped`` via the idempotent path."""
    first = ingest_rules_dir(FIXTURES, mm, tier="warn")
    second = ingest_rules_dir(FIXTURES, mm, tier="warn")
    assert first["ingested"] >= 3
    assert second["ingested"] == 0
    assert second["skipped"] >= first["ingested"]


def test_ingest_rule_strict_rejects_plain_yara(mm: MemoryManager) -> None:
    """Plain YARA (no CCCS meta) is rejected under strict tier."""
    note, _ = ingest_rule(FIXTURES / "malware_hash.yar", mm, tier="strict")
    assert note is None


def test_ingest_rule_writes_note_findable_by_source_ref(mm: MemoryManager) -> None:
    note, _ = ingest_rule(FIXTURES / "technique_loader.yar", mm, tier="warn")
    assert note is not None
    # CR-W5: rule_id for a non-CCCS-id rule is now a content-hash fallback
    # (``yara_<16-hex>``) instead of the rule_name, so two rules named the
    # same in different files don't collide on the same source_ref.
    assert note.content.source_ref.startswith("yara:yara_")
    refetched = mm.store.get_note_by_source_ref(note.content.source_ref)
    assert refetched is not None
    assert refetched.id == note.id


def test_yara_rule_id_falls_back_to_content_hash_not_rule_name() -> None:
    """CR-W5: two distinct rules sharing a ``rule_name`` must not collide."""
    from zettelforge.yara.entities import rule_to_entities
    from zettelforge.yara.parser import parse_yara

    a_text = 'rule silent_banker { strings: $a = "A" condition: $a }'
    b_text = 'rule silent_banker { strings: $b = "B" condition: $b }'
    a_entity, _ = rule_to_entities(parse_yara(a_text)[0])
    b_entity, _ = rule_to_entities(parse_yara(b_text)[0])
    assert a_entity.rule_id != b_entity.rule_id
    assert a_entity.rule_id.startswith("yara_")
    assert b_entity.rule_id.startswith("yara_")


def test_ingest_rule_persists_kg_edges(mm: MemoryManager) -> None:
    """CR-B1: YARA ingest must write relations into the KG, not just return them.

    Pre-fix: relations were returned to the caller but never reached
    ``store.add_kg_edge``. This test exercises ``get_kg_neighbors`` to
    assert the edges actually landed in the backend.
    """
    note, relations = ingest_rule(FIXTURES / "technique_loader.yar", mm, tier="warn")
    assert note is not None
    assert relations, "expected at least one relation on a technique rule"

    # technique_loader.yar → MITRE T1218 + a 'loader:memorymodule' YaraTag.
    neighbors = mm.store.get_kg_neighbors("YaraRule", relations[0]["from_value"])
    targets = {(n["node"]["entity_type"], n["node"]["entity_value"]) for n in neighbors}
    assert ("AttackPattern", "T1218") in targets
    assert any(t[0] == "YaraTag" for t in targets)


def test_ingest_rules_dir_skips_symlinks(tmp_path: Path, mm: MemoryManager) -> None:
    """SEC-3: a symlink in the rules dir must not be followed during ingest."""
    # Real rule inside the walked root.
    real = tmp_path / "real.yar"
    real.write_text((FIXTURES / "malware_hash.yar").read_text())
    # Symlink whose target lives outside the walked root.
    victim = tmp_path.parent / "outside_victim.yar"
    victim.write_text((FIXTURES / "malware_hash.yar").read_text())
    link = tmp_path / "evil.yar"
    link.symlink_to(victim)

    result = ingest_rules_dir(tmp_path, mm, tier="non_cccs")
    # Exactly one rule makes it in; the symlink is refused.
    assert result["ingested"] == 1
    assert result["skipped"] >= 1
