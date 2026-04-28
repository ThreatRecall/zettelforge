"""Tests for embedding backends (fastembed + fallback)."""
import pytest
from zettelforge.vector_memory import get_embedding, get_embedding_batch, _get_embed_model


class TestFastembedBackend:
    def test_embedding_returns_768_dims(self):
        vec = get_embedding("APT28 uses Cobalt Strike for lateral movement")
        assert len(vec) == 768

    def test_embedding_is_deterministic(self):
        v1 = get_embedding("Lazarus Group targets cryptocurrency exchanges")
        v2 = get_embedding("Lazarus Group targets cryptocurrency exchanges")
        assert v1 == v2

    def test_embedding_differs_for_different_text(self):
        v1 = get_embedding("APT28 uses spearphishing")
        v2 = get_embedding("Volt Typhoon compromises edge devices")
        assert v1 != v2

    def test_batch_embedding(self):
        texts = [
            "APT28 uses Cobalt Strike",
            "Lazarus targets crypto exchanges",
            "CVE-2024-3094 is a backdoor in XZ Utils",
        ]
        results = get_embedding_batch(texts)
        assert len(results) == 3
        assert all(len(v) == 768 for v in results)

    def test_empty_text_returns_vector(self):
        vec = get_embedding("")
        assert len(vec) == 768

    def test_model_singleton(self):
        m1 = _get_embed_model()
        m2 = _get_embed_model()
        assert m1 is m2

    def test_returns_python_list_not_numpy(self):
        vec = get_embedding("test")
        assert isinstance(vec, list)
        assert isinstance(vec[0], float)
