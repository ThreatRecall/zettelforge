"""End-to-end tests for zettelforge.sigma.ingest.

Drives real ingest through a :class:`MemoryManager` pointed at a
tmpdir-backed SQLite store, then asserts the note landed and the
KG edges were persisted.

The environment (``CI=true``, ``ZETTELFORGE_LLM_PROVIDER=mock``,
``ZETTELFORGE_EMBEDDING_PROVIDER=fastembed``) is expected to be set
by the runner per the Stream A runbook — if a test runs outside that
envelope the causal explainer and LLM NER would try to fire, which
is fine for correctness but slower.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import zettelforge.knowledge_graph as knowledge_graph_module
from zettelforge import MemoryManager
from zettelforge.note_schema import Content, Embedding, MemoryNote, Metadata, Semantic

FIXTURES = Path(__file__).parent / "fixtures" / "sigma"


@pytest.fixture()
def mm() -> MemoryManager:
    """Isolated MemoryManager on a tmpdir. Mirrors test_causal_extraction."""
    old_data_dir = os.environ.get("AMEM_DATA_DIR")
    old_kg_instance = knowledge_graph_module._kg_instance
    tmpdir = tempfile.mkdtemp(prefix="sigma-ingest-test-")
    os.environ["AMEM_DATA_DIR"] = tmpdir
    knowledge_graph_module._kg_instance = None

    # Stub the LLM client so any stray causal/NER enrichment jobs don't
    # actually fire a network call under ``sync=True``. Returns empty
    # results, which the extractors treat as a no-op.
    patcher = patch("zettelforge.llm_client.generate", return_value="[]")
    patcher.start()

    manager = MemoryManager(
        jsonl_path=f"{tmpdir}/notes.jsonl",
        lance_path=f"{tmpdir}/vectordb",
    )
    try:
        yield manager
    finally:
        patcher.stop()
        knowledge_graph_module._kg_instance = old_kg_instance
        if old_data_dir is None:
            os.environ.pop("AMEM_DATA_DIR", None)
        else:
            os.environ["AMEM_DATA_DIR"] = old_data_dir


# ── ingest_rule ──────────────────────────────────────────────────────────────


def test_ingest_rule_single_file(mm: MemoryManager) -> None:
    from zettelforge.sigma.ingest import ingest_rule

    note, relations = ingest_rule(FIXTURES / "process_creation_example.yml", mm, domain="detection")
    # Note persisted → can be fetched back.
    assert note is not None
    fetched = mm.store.get_note_by_id(note.id)
    assert fetched is not None
    assert "Whoami Execution" in fetched.content.raw
    # Logsource edges made it into the KG.
    assert len(relations) >= 1


def test_ingest_rule_emits_kg_edges_for_logsource(mm: MemoryManager) -> None:
    """Verify edges land in the SQLite backend and are queryable by
    ``get_kg_neighbors`` — the detection-rule equivalent of the
    ``get_causal_edges`` pattern in test_causal_extraction.py."""
    from zettelforge.sigma.ingest import ingest_rule

    _note, _rels = ingest_rule(FIXTURES / "cloud_example.yml", mm)

    # cloud_example.yml → product=windows + service=security.
    neighbors = mm.store.get_kg_neighbors("SigmaRule", "929a690e-bef0-4204-a928-ef5e620d6fcb")
    targets = {(n["node"]["entity_type"], n["node"]["entity_value"]) for n in neighbors}
    assert ("LogSource", "product:windows") in targets
    assert ("LogSource", "service:security") in targets


def test_ingest_rule_emits_kg_edges_for_attack_and_cve_tags(mm: MemoryManager) -> None:
    """Tag-upgrade edges must land in the KG, not just the in-memory list."""
    from zettelforge.sigma.ingest import ingest_rule

    _note, _rels = ingest_rule(FIXTURES / "tagged_example.yml", mm)

    detects = mm.store.get_kg_neighbors(
        "SigmaRule", "7e3d88a2-bfaa-4f52-9e0b-2bbbdd0d4ea1", relationship="detects"
    )
    detects_values = {n["node"]["entity_value"] for n in detects}
    assert {"T1190", "T1059.001"} <= detects_values

    cves = mm.store.get_kg_neighbors(
        "SigmaRule",
        "7e3d88a2-bfaa-4f52-9e0b-2bbbdd0d4ea1",
        relationship="references_cve",
    )
    cve_values = {n["node"]["entity_value"] for n in cves}
    assert "CVE-2021-44228" in cve_values


def test_ingest_rule_accepts_yaml_string(mm: MemoryManager) -> None:
    """``ingest_rule`` should accept raw YAML text, not just a Path."""
    from zettelforge.sigma.ingest import ingest_rule

    yaml_text = (FIXTURES / "cloud_example.yml").read_text()
    note, relations = ingest_rule(yaml_text, mm)
    assert note is not None
    assert any(r["rel"] == "applies_to" for r in relations)


def test_ingest_rule_accepts_pre_parsed_dict(mm: MemoryManager) -> None:
    from zettelforge.sigma.ingest import ingest_rule
    from zettelforge.sigma.parser import parse_file

    rule = parse_file(FIXTURES / "cloud_example.yml")
    note, _rels = ingest_rule(rule, mm)
    assert note is not None


# ── ingest_rules_dir ─────────────────────────────────────────────────────────


def test_ingest_rules_dir_walks_tree(mm: MemoryManager) -> None:
    from zettelforge.sigma.ingest import ingest_rules_dir

    ingested, skipped = ingest_rules_dir(FIXTURES, mm)
    # Four fixtures: process_creation, cloud, correlation, tagged.
    assert ingested == 4
    assert skipped == 0


def test_ingest_rules_dir_bulk_defers_enrichment_and_flushes() -> None:
    from zettelforge.sigma.ingest import ingest_rules_dir

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

    ingested, skipped = ingest_rules_dir(FIXTURES, mm, bulk=True, flush_timeout=1.5)

    assert ingested == 4
    assert skipped == 0
    assert mm.calls
    assert all(call["sync"] is False for call in mm.calls)
    assert mm.flushed is True
    assert mm.flush_timeout == 1.5


def test_ingest_rules_dir_skips_invalid_file(tmp_path: Path, mm: MemoryManager) -> None:
    """Bad YAML / invalid schema must log-and-skip, not abort the walk."""
    from zettelforge.sigma.ingest import ingest_rules_dir

    # Copy one valid fixture plus add a broken one.
    good = tmp_path / "good.yml"
    good.write_text((FIXTURES / "cloud_example.yml").read_text())
    broken = tmp_path / "broken.yml"
    broken.write_text("title: missing required logsource + detection\n")

    ingested, skipped = ingest_rules_dir(tmp_path, mm)
    assert ingested == 1
    assert skipped == 1


def test_ingest_rule_raises_on_none_memory_manager() -> None:
    """CR-N2: passing ``mm=None`` must raise, not silently drop the rule."""
    from zettelforge.sigma.ingest import ingest_rule

    with pytest.raises(ValueError, match="MemoryManager"):
        ingest_rule(FIXTURES / "cloud_example.yml", None)  # type: ignore[arg-type]


def test_ingest_rule_source_ref_is_format_prefixed_content_scoped(
    mm: MemoryManager,
) -> None:
    """CR-W2: Sigma source_ref must follow ``sigma:<rule_id>:<hash12>``."""
    from zettelforge.sigma.ingest import ingest_rule

    note, _rels = ingest_rule(FIXTURES / "cloud_example.yml", mm)
    assert note is not None
    ref = note.content.source_ref
    assert ref.startswith("sigma:929a690e-bef0-4204-a928-ef5e620d6fcb:")
    # 12-char content-hash suffix → full ref ends with hex.
    assert len(ref.rsplit(":", 1)[-1]) == 12


def test_ingest_rule_is_idempotent_on_repeat_call(mm: MemoryManager) -> None:
    """CR-W2: re-ingesting an unchanged rule returns the same note, not a dup."""
    from zettelforge.sigma.ingest import ingest_rule

    first, _ = ingest_rule(FIXTURES / "cloud_example.yml", mm)
    second, _ = ingest_rule(FIXTURES / "cloud_example.yml", mm)
    assert first is not None and second is not None
    assert first.id == second.id


def test_ingest_rules_dir_skips_symlinks(tmp_path: Path, mm: MemoryManager) -> None:
    """SEC-3: a symlink in the rules dir must not be followed during ingest.

    Regression case: prior to SEC-3, a malicious rule tree could lure the
    walker into reading /etc/passwd via ``rules/evil.yml -> /etc/passwd``.
    """
    from zettelforge.sigma.ingest import ingest_rules_dir

    # One genuine rule file.
    real = tmp_path / "real.yml"
    real.write_text((FIXTURES / "cloud_example.yml").read_text())
    # A symlink pointing at a file outside the rules root.
    victim = tmp_path.parent / "victim.yml"
    victim.write_text((FIXTURES / "cloud_example.yml").read_text())
    link = tmp_path / "evil.yml"
    link.symlink_to(victim)

    ingested, skipped = ingest_rules_dir(tmp_path, mm)
    assert ingested == 1  # only the real file
    assert skipped == 1  # the symlink was refused
