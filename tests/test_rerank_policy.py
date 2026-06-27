"""Cross-encoder rerank policy: bounded candidates, bounded doc length, kill switch.

The reranker is the dominant read-path cost (ONNX cross-encoder on CPU).
These knobs bound its work without changing the blended order of the
unreranked tail.
"""

import pytest

from zettelforge.config import get_config, reload_config


@pytest.fixture(autouse=True)
def _no_enrichment(monkeypatch):
    monkeypatch.setenv('ZETTELFORGE_ENRICHMENT_ENABLED', 'false')
    reload_config()
    yield
    reload_config()


class _FakeReranker:
    def __init__(self):
        self.calls = []

    def rerank(self, query, docs):
        self.calls.append((query, list(docs)))
        # Reverse order: last doc gets the highest score
        return [float(i) for i in range(len(docs))]


def _corpus_manager(tmp_path):
    from zettelforge.memory_manager import MemoryManager

    mm = MemoryManager(
        jsonl_path=str(tmp_path / 'notes.jsonl'),
        lance_path=str(tmp_path / 'vec'),
    )
    for i in range(8):
        mm.remember(
            f'Report {i}: threat actor activity involving infrastructure item {i}. ' * 8,
            source_type='threat_report',
            source_ref=f'r{i}',
            domain='cti',
        )
    return mm


def test_rerank_receives_bounded_candidates_and_doc_chars(tmp_path, monkeypatch):
    import zettelforge.memory_manager as mmod

    fake = _FakeReranker()
    monkeypatch.setattr(mmod, '_get_reranker', lambda: fake)
    cfg = get_config()
    monkeypatch.setattr(cfg.retrieval, 'rerank_max_candidates', 3)
    monkeypatch.setattr(cfg.retrieval, 'rerank_doc_chars', 100)

    mm = _corpus_manager(tmp_path)
    mm.recall('threat actor infrastructure', k=8, exclude_superseded=False)

    assert fake.calls, 'reranker should have been invoked'
    _, docs = fake.calls[-1]
    assert len(docs) <= 3
    assert all(len(d) <= 100 for d in docs)


def test_rerank_disabled_skips_reranker(tmp_path, monkeypatch):
    import zettelforge.memory_manager as mmod

    fake = _FakeReranker()
    monkeypatch.setattr(mmod, '_get_reranker', lambda: fake)
    monkeypatch.setattr(get_config().retrieval, 'rerank_enabled', False)

    mm = _corpus_manager(tmp_path)
    results = mm.recall('threat actor infrastructure', k=8, exclude_superseded=False)

    assert fake.calls == []
    assert results, 'recall still returns blended results'


def test_rerank_tail_preserves_blended_order(tmp_path, monkeypatch):
    import zettelforge.memory_manager as mmod

    fake = _FakeReranker()
    monkeypatch.setattr(mmod, '_get_reranker', lambda: fake)
    cfg = get_config()
    monkeypatch.setattr(cfg.retrieval, 'rerank_max_candidates', 2)

    mm = _corpus_manager(tmp_path)
    results = mm.recall('threat actor infrastructure', k=8, exclude_superseded=False)

    assert len(results) >= 3
    # Head (first 2) was reranked: fake scores reverse their relative order.
    # Tail (3rd onward) must match the no-rerank ordering for the same query.
    monkeypatch.setattr(cfg.retrieval, 'rerank_enabled', False)
    unreranked = mm.recall('threat actor infrastructure', k=8, exclude_superseded=False)
    assert [n.id for n in results[:2]] == [n.id for n in reversed(unreranked[:2])]
    assert [n.id for n in results[2:]] == [n.id for n in unreranked[2:]]


def test_env_kill_switch(monkeypatch):
    monkeypatch.setenv('ZETTELFORGE_RERANK_ENABLED', 'false')
    cfg = reload_config()
    assert cfg.retrieval.rerank_enabled is False
