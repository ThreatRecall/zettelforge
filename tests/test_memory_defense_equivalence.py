"""MemSAD vectorization must be numerically equivalent to the original math.

The gate ran leave-one-out calibration in pure Python (~1.1s per ingest at
50 references; 93% of remember() latency). The numpy rewrite must produce
identical scores, thresholds, and flag decisions. Oracle functions below are
verbatim copies of the pre-vectorization implementation.
"""

import math
import random
from collections import Counter
from types import SimpleNamespace

import pytest

from zettelforge.config import get_config, reload_config


# ── Oracle: verbatim pre-vectorization implementation ──────────────────────

def _oracle_cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _oracle_ngram_counts(text, ngram_size):
    normalized = " ".join(text.lower().split())
    if not normalized:
        return Counter()
    n = max(1, int(ngram_size))
    if len(normalized) <= n:
        return Counter([normalized])
    return Counter(normalized[i : i + n] for i in range(0, len(normalized) - n + 1))


def _oracle_jensen_shannon(left, right):
    if not left and not right:
        return 0.0
    if not left or not right:
        return 1.0
    left_total = sum(left.values())
    right_total = sum(right.values())
    keys = set(left) | set(right)
    divergence = 0.0
    for key in keys:
        p = left[key] / left_total
        q = right[key] / right_total
        m = 0.5 * (p + q)
        if p:
            divergence += 0.5 * p * math.log2(p / m)
        if q:
            divergence += 0.5 * q * math.log2(q / m)
    return min(1.0, max(0.0, divergence))


def _oracle_lexical_jsd(text, reference_texts, ngram_size):
    candidate = _oracle_ngram_counts(text, ngram_size)
    reference = Counter()
    for ref_text in reference_texts:
        reference.update(_oracle_ngram_counts(ref_text, ngram_size))
    return _oracle_jensen_shannon(candidate, reference)


def _oracle_memsad_score(candidate_vector, refs):
    similarities = [_oracle_cosine(candidate_vector, r) for r in refs]
    if not similarities:
        return 0.0, 0.0, 0.0
    max_similarity = max(similarities)
    mean_similarity = sum(similarities) / len(similarities)
    return 0.5 * max_similarity + 0.5 * mean_similarity, max_similarity, mean_similarity


def _oracle_calibration_scores(vectors, texts, cfg_lexical_weight, cfg_ngram_size):
    scores = []
    for i in range(len(vectors)):
        ref_vecs = vectors[:i] + vectors[i + 1 :]
        if not ref_vecs:
            continue
        memsad, _, _ = _oracle_memsad_score(vectors[i], ref_vecs)
        jsd = _oracle_lexical_jsd(texts[i], texts[:i] + texts[i + 1 :], cfg_ngram_size)
        scores.append(memsad + cfg_lexical_weight * jsd)
    return scores


# ── Fixtures ────────────────────────────────────────────────────────────────

def _make_note(i, dim=64, text=None, seed=None):
    rng = random.Random(seed if seed is not None else i)
    vec = [rng.uniform(-1, 1) for _ in range(dim)]
    body = text if text is not None else (
        f"Session {i}: " + " ".join(f"token{(i * 7 + j) % 23}" for j in range(120))
    )
    return SimpleNamespace(
        id=f"n{i}",
        content=SimpleNamespace(raw=body),
        embedding=SimpleNamespace(vector=vec),
        created_at=f"2026-06-09T{10 + i // 60:02d}:{i % 60:02d}:00",
    )


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    import zettelforge.memory_defense as md

    monkeypatch.setenv('ZETTELFORGE_ENRICHMENT_ENABLED', 'false')
    reload_config()
    md.reset_defense_caches_for_tests()
    yield
    md.reset_defense_caches_for_tests()
    reload_config()


def test_memsad_score_matches_oracle():
    import zettelforge.memory_defense as md

    notes = [_make_note(i) for i in range(12)]
    candidate = _make_note(99, seed=4242)
    got = md._memsad_score(candidate.embedding.vector, notes)
    want = _oracle_memsad_score(
        candidate.embedding.vector, [n.embedding.vector for n in notes]
    )
    assert got == pytest.approx(want, abs=1e-9)


def test_calibration_scores_match_oracle():
    import zettelforge.memory_defense as md

    cfg = get_config().governance.memory_defense
    notes = [_make_note(i) for i in range(12)]
    got = md._calibration_scores(notes, cfg)
    want = _oracle_calibration_scores(
        [n.embedding.vector for n in notes],
        [n.content.raw for n in notes],
        cfg.lexical_weight,
        cfg.ngram_size,
    )
    assert got == pytest.approx(want, abs=1e-9)


def test_calibration_handles_empty_text_note():
    import zettelforge.memory_defense as md

    cfg = get_config().governance.memory_defense
    notes = [_make_note(i) for i in range(6)]
    notes[2] = _make_note(2, text="   ")
    got = md._calibration_scores(notes, cfg)
    want = _oracle_calibration_scores(
        [n.embedding.vector for n in notes],
        [n.content.raw for n in notes],
        cfg.lexical_weight,
        cfg.ngram_size,
    )
    assert got == pytest.approx(want, abs=1e-9)


def test_lexical_jsd_matches_oracle():
    import zettelforge.memory_defense as md

    cfg = get_config().governance.memory_defense
    notes = [_make_note(i) for i in range(8)]
    candidate_text = "A brand new memory about painting classes in Toronto."
    got = md._lexical_jsd(candidate_text, [n.content.raw for n in notes], cfg.ngram_size)
    want = _oracle_lexical_jsd(candidate_text, [n.content.raw for n in notes], cfg.ngram_size)
    assert got == pytest.approx(want, abs=1e-9)


def test_evaluate_decision_matches_oracle_fields():
    import zettelforge.memory_defense as md

    notes = [_make_note(i) for i in range(60)]
    candidate = _make_note(99, seed=31337)
    gate = md.MemoryAnomalyGate()
    decision = gate.evaluate(candidate, notes, domain="cti")
    assert decision.score is not None, f"early-out decision: {decision.reason}"

    cfg = get_config().governance.memory_defense
    refs = md._select_reference_notes(candidate, notes, cfg.max_reference_notes)
    want_cal = _oracle_calibration_scores(
        [n.embedding.vector for n in refs],
        [n.content.raw for n in refs],
        cfg.lexical_weight,
        cfg.ngram_size,
    )
    want_memsad, want_max, want_mean = _oracle_memsad_score(
        candidate.embedding.vector, [n.embedding.vector for n in refs]
    )
    want_jsd = _oracle_lexical_jsd(
        candidate.content.raw, [n.content.raw for n in refs], cfg.ngram_size
    )
    want_score = want_memsad + cfg.lexical_weight * want_jsd
    want_mean_cal = sum(want_cal) / len(want_cal)
    want_std = math.sqrt(
        sum((v - want_mean_cal) ** 2 for v in want_cal) / (len(want_cal) - 1)
    )
    want_threshold = want_mean_cal + float(cfg.kappa) * want_std

    assert decision.score == pytest.approx(want_score, abs=1e-9)
    assert decision.threshold == pytest.approx(want_threshold, abs=1e-9)
    assert decision.memsad_score == pytest.approx(want_memsad, abs=1e-9)
    assert decision.lexical_jsd == pytest.approx(want_jsd, abs=1e-9)
    assert decision.max_similarity == pytest.approx(want_max, abs=1e-9)
    assert decision.flagged == (want_score > want_threshold)


def test_counter_cache_invalidates_on_content_change():
    import zettelforge.memory_defense as md

    cfg = get_config().governance.memory_defense
    note = _make_note(1, text="original text about hiking")
    first = md._lexical_jsd("query text", [note.content.raw], cfg.ngram_size)
    note.content.raw = "completely different content about databases"
    second = md._lexical_jsd("query text", [note.content.raw], cfg.ngram_size)
    want = _oracle_lexical_jsd(
        "query text", ["completely different content about databases"], cfg.ngram_size
    )
    assert second == pytest.approx(want, abs=1e-9)
    assert first != pytest.approx(second, abs=1e-9)
