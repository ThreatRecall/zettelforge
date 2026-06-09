"""Enrichment off-switch: ZETTELFORGE_ENRICHMENT_ENABLED gates all background jobs.

Benchmarks and offline ingestion need deterministic writes with no LLM
enrichment dispatch (causal extraction, LLM NER, neighbor evolution).
"""

import pytest

from zettelforge.config import get_config, reload_config


@pytest.fixture(autouse=True)
def _restore_config():
    yield
    reload_config()


def test_enrichment_config_default_enabled(monkeypatch):
    monkeypatch.delenv('ZETTELFORGE_ENRICHMENT_ENABLED', raising=False)
    cfg = reload_config()
    assert cfg.enrichment.enabled is True


def test_enrichment_env_override(monkeypatch):
    monkeypatch.setenv('ZETTELFORGE_ENRICHMENT_ENABLED', 'false')
    cfg = reload_config()
    assert cfg.enrichment.enabled is False


def test_remember_dispatches_nothing_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv('ZETTELFORGE_ENRICHMENT_ENABLED', 'false')
    reload_config()
    from zettelforge.memory_manager import MemoryManager

    mm = MemoryManager(
        jsonl_path=str(tmp_path / 'notes.jsonl'),
        lance_path=str(tmp_path / 'vec'),
    )
    for i in range(4):
        mm.remember(
            f'APT28 used DROPBEAR in campaign {i}.',
            source_type='threat_report',
            source_ref=f'r{i}',
            domain='cti',
        )
    assert mm._enrichment_queue.qsize() == 0
    assert len(mm._pending_enrichment) == 0


def test_remember_dispatches_jobs_when_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv('ZETTELFORGE_ENRICHMENT_ENABLED', raising=False)
    reload_config()
    assert get_config().enrichment.enabled is True
    from zettelforge.memory_manager import MemoryManager

    mm = MemoryManager(
        jsonl_path=str(tmp_path / 'notes.jsonl'),
        lance_path=str(tmp_path / 'vec'),
    )
    # Count dispatches without letting the background worker consume them
    # (avoids racing the worker and avoids real LLM calls).
    dispatched = []
    monkeypatch.setattr(mm._enrichment_queue, 'put_nowait', dispatched.append)
    mm.remember(
        'APT28 used DROPBEAR in a campaign.',
        source_type='threat_report',
        source_ref='r0',
        domain='cti',
    )
    assert len(dispatched) > 0
