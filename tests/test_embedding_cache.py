"""Query-embedding LRU cache: repeated texts hit the model once.

Embedding is the second-largest read-path cost; agents re-ask the same
queries, so a (model, text)-keyed cache pays for itself immediately.
"""

import pytest

from zettelforge.config import reload_config


@pytest.fixture(autouse=True)
def _fresh_cache():
    import zettelforge.vector_memory as vm

    vm.reset_embedding_cache_for_tests()
    yield
    vm.reset_embedding_cache_for_tests()
    reload_config()


def test_repeated_text_computes_once(monkeypatch):
    import zettelforge.vector_memory as vm

    calls = {'n': 0}
    orig = vm._compute_embedding

    def counting(text, model=None):
        calls['n'] += 1
        return orig(text, model)

    monkeypatch.setattr(vm, '_compute_embedding', counting)

    e1 = vm.get_embedding('What tools does APT28 use?')
    e2 = vm.get_embedding('What tools does APT28 use?')
    assert calls['n'] == 1
    assert e1 == e2


def test_distinct_texts_compute_separately(monkeypatch):
    import zettelforge.vector_memory as vm

    calls = {'n': 0}
    orig = vm._compute_embedding

    def counting(text, model=None):
        calls['n'] += 1
        return orig(text, model)

    monkeypatch.setattr(vm, '_compute_embedding', counting)

    vm.get_embedding('first query')
    vm.get_embedding('second query')
    assert calls['n'] == 2


def test_cache_keyed_by_model(monkeypatch):
    import zettelforge.vector_memory as vm

    calls = {'n': 0}
    orig = vm._compute_embedding

    def counting(text, model=None):
        calls['n'] += 1
        return orig(text, model)

    monkeypatch.setattr(vm, '_compute_embedding', counting)

    vm.get_embedding('same text', model='model-a')
    vm.get_embedding('same text', model='model-b')
    assert calls['n'] == 2
