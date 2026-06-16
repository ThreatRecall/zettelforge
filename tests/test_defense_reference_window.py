"""Bounded reference fetch for the memory defense gate.

The gate only keeps the most recent max_reference_notes; fetching the
whole domain per ingest was O(n) rows + Pydantic parses.
"""

from types import SimpleNamespace

import pytest

from zettelforge.config import reload_config


@pytest.fixture(autouse=True)
def _no_enrichment(monkeypatch):
    monkeypatch.setenv("ZETTELFORGE_ENRICHMENT_ENABLED", "false")
    reload_config()
    yield
    reload_config()


def test_recent_notes_by_domain_orders_and_limits(tmp_path):
    from zettelforge.memory_manager import MemoryManager

    mm = MemoryManager(jsonl_path=str(tmp_path / "n.jsonl"), lance_path=str(tmp_path / "v"))
    for i in range(5):
        mm.remember(f"cti note {i}", source_type="threat_report", source_ref=f"c{i}", domain="cti")
    for i in range(3):
        mm.remember(
            f"general note {i}", source_type="conversation", source_ref=f"g{i}", domain="general"
        )

    recent = mm.store.get_recent_notes_by_domain("cti", 3)
    assert len(recent) == 3
    assert all(n.metadata.domain == "cti" for n in recent)
    timestamps = [n.created_at for n in recent]
    assert timestamps == sorted(timestamps, reverse=True)


def test_defense_gate_receives_bounded_reference_set(tmp_path, monkeypatch):
    from zettelforge.memory_manager import MemoryManager

    mm = MemoryManager(jsonl_path=str(tmp_path / "n.jsonl"), lance_path=str(tmp_path / "v"))
    seen = {"sizes": []}
    orig = mm.memory_defense.enforce

    def recording(note, reference_notes, **kwargs):
        seen["sizes"].append(len(reference_notes))
        return orig(note, reference_notes, **kwargs)

    monkeypatch.setattr(mm.memory_defense, "enforce", recording)
    for i in range(6):
        mm.remember(f"note {i}", source_type="conversation", source_ref=f"s{i}", domain="general")

    # Window is max(200, 4 * max_reference_notes); with 6 notes the gate
    # sees at most the existing store, never more than the window.
    assert seen["sizes"] == [min(i, 200) for i in range(6)]


def test_defense_reference_window_expands_when_recent_vectors_are_invalid(tmp_path, monkeypatch):
    from zettelforge.memory_manager import MemoryManager

    mm = MemoryManager(jsonl_path=str(tmp_path / "n.jsonl"), lance_path=str(tmp_path / "v"))
    limits = []
    invalid_notes = [
        SimpleNamespace(id=f"i{i}", embedding=SimpleNamespace(vector=[])) for i in range(200)
    ]
    valid_notes = [
        SimpleNamespace(id=f"v{i}", embedding=SimpleNamespace(vector=[0.1, 0.2])) for i in range(50)
    ]

    def recent(_domain, limit):
        limits.append(limit)
        if limit == 200:
            return invalid_notes
        return [*invalid_notes, *valid_notes]

    monkeypatch.setattr(mm.store, "get_recent_notes_by_domain", recent)

    refs = mm._memory_defense_reference_notes(
        "cti",
        max_reference_notes=50,
        min_calibration_notes=20,
    )

    assert limits == [200, 400]
    assert refs == [*invalid_notes, *valid_notes]
