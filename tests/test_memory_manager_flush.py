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


def test_enrichment_enqueue_records_ledger_and_worker_marks_terminal(tmp_path: Path, monkeypatch) -> None:
    mm = MemoryManager(
        jsonl_path=str(tmp_path / "notes.jsonl"),
        lance_path=str(tmp_path / "vec"),
    )
    release = threading.Event()

    def slow_enrichment(_job):
        release.wait(timeout=1)

    monkeypatch.setattr(mm, "_run_enrichment", slow_enrichment)
    job = _EnrichmentJob(note_id="n-ledger", domain="cti", content_len=500)

    assert mm._enqueue_enrichment_job(job, queue_full_event="test_queue_full") is True

    for _ in range(100):
        counts = mm.store.count_enrichment_jobs_by_state()
        if counts.get("running") == 1:
            break
        time.sleep(0.01)
    assert mm.store.count_enrichment_jobs_by_state().get("running") == 1

    [running] = mm.store.list_enrichment_jobs(state="running")
    assert running["job_id"] == job.job_id
    assert running["note_id"] == "n-ledger"
    assert running["job_type"] == "causal_extraction"
    assert running["attempt_count"] == 1

    release.set()
    assert mm.flush(timeout=1) is True
    assert mm.store.count_enrichment_jobs_by_state() == {"succeeded": 1}
