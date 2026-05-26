"""Tests for SEC-011 write-time memory anomaly defenses."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from zettelforge.config import MemoryDefenseConfig
from zettelforge.memory_defense import MemoryAnomalyError, MemoryAnomalyGate


def _note(note_id: str, vector: list[float], raw: str = "benign cti note"):
    return SimpleNamespace(
        id=note_id,
        created_at=f"2026-05-25T00:00:{note_id[-1]}Z",
        content=SimpleNamespace(raw=raw),
        embedding=SimpleNamespace(vector=vector),
    )


def test_insufficient_calibration_allows_write():
    cfg = MemoryDefenseConfig(enabled=True, min_calibration_notes=3)
    gate = MemoryAnomalyGate(config=cfg)
    candidate = _note("candidate", [1.0, 0.0])
    refs = [_note("ref1", [1.0, 0.0]), _note("ref2", [0.0, 1.0])]

    decision = gate.evaluate(candidate, refs, domain="cti", request_id="req")

    assert decision.reason == "calibration_insufficient"
    assert decision.reference_count == 2
    assert decision.flagged is False
    assert decision.should_stop_write is False


def test_high_similarity_candidate_flags_in_audit_mode():
    cfg = MemoryDefenseConfig(
        enabled=True,
        mode="audit",
        min_calibration_notes=4,
        max_reference_notes=4,
        lexical_weight=0.0,
    )
    gate = MemoryAnomalyGate(config=cfg)
    refs = [
        _note("ref1", [1.0, 0.0, 0.0], "alpha benign"),
        _note("ref2", [0.0, 1.0, 0.0], "bravo benign"),
        _note("ref3", [0.0, 0.0, 1.0], "charlie benign"),
        _note("ref4", [-1.0, 0.0, 0.0], "delta benign"),
    ]
    candidate = _note("candidate", [1.0, 0.0, 0.0], "triggered write payload")

    decision = gate.evaluate(candidate, refs, domain="cti", request_id="req")

    assert decision.flagged is True
    assert decision.action == "audit"
    assert decision.score is not None
    assert decision.threshold is not None
    assert decision.score > decision.threshold
    assert decision.should_stop_write is False


def test_quarantine_mode_writes_forensic_record_and_blocks(tmp_path):
    quarantine_path = tmp_path / "quarantine.jsonl"
    cfg = MemoryDefenseConfig(
        enabled=True,
        mode="quarantine",
        min_calibration_notes=4,
        max_reference_notes=4,
        lexical_weight=0.0,
        quarantine_path=str(quarantine_path),
    )
    gate = MemoryAnomalyGate(config=cfg)
    refs = [
        _note("ref1", [1.0, 0.0, 0.0], "alpha benign"),
        _note("ref2", [0.0, 1.0, 0.0], "bravo benign"),
        _note("ref3", [0.0, 0.0, 1.0], "charlie benign"),
        _note("ref4", [-1.0, 0.0, 0.0], "delta benign"),
    ]
    candidate = _note("candidate", [1.0, 0.0, 0.0], "poison payload")

    with pytest.raises(MemoryAnomalyError) as exc_info:
        gate.enforce(candidate, refs, domain="cti", source_type="test", request_id="req")

    assert exc_info.value.decision.action == "quarantine"
    records = [json.loads(line) for line in quarantine_path.read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["raw_content"] == "poison payload"
    assert records[0]["decision"]["flagged"] is True
