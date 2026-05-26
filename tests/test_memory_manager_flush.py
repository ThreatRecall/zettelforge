"""Tests for MemoryManager enrichment queue draining."""

import threading
import time
from pathlib import Path

from zettelforge.memory_manager import MemoryManager, _EnrichmentJob


def test_flush_waits_for_in_flight_enrichment_job(tmp_path: Path, monkeypatch) -> None:
    mm = MemoryManager(
        jsonl_path=str(tmp_path / "notes.jsonl"),
        lance_path=str(tmp_path / "vec"),
    )
    started = threading.Event()
    release = threading.Event()
    done = threading.Event()

    def slow_enrichment(_job):
        started.set()
        release.wait(timeout=1)
        done.set()

    monkeypatch.setattr(mm, "_run_enrichment", slow_enrichment)

    mm._enrichment_queue.put_nowait(
        _EnrichmentJob(note_id="n1", domain="cti", content_len=500),
    )
    assert started.wait(timeout=1)
    assert mm._enrichment_queue.empty()
    assert not done.is_set()

    release.set()
    assert mm.flush(timeout=1) is True
    assert done.is_set()


def test_flush_returns_false_on_timeout_for_in_flight_job(tmp_path: Path, monkeypatch) -> None:
    mm = MemoryManager(
        jsonl_path=str(tmp_path / "notes.jsonl"),
        lance_path=str(tmp_path / "vec"),
    )
    started = threading.Event()
    release = threading.Event()

    def slow_enrichment(_job):
        started.set()
        release.wait(timeout=1)

    monkeypatch.setattr(mm, "_run_enrichment", slow_enrichment)

    mm._enrichment_queue.put_nowait(
        _EnrichmentJob(note_id="n1", domain="cti", content_len=500),
    )
    assert started.wait(timeout=1)

    assert mm.flush(timeout=0.01) is False
    release.set()
    for _ in range(100):
        if mm.flush(timeout=0.01):
            break
        time.sleep(0.01)
    assert mm.flush(timeout=1) is True
