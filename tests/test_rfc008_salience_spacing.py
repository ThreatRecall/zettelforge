"""  
Tests for RFC-008: Memory Salience & Spacing Effects.

Covers: memory_salience, memory_spacing, tiered_decay, config YAML apply.

Run: pytest tests/test_rfc008_salience_spacing.py -v
"""

import math
import pytest
from datetime import datetime, timedelta, timezone

from zettelforge.config import ZettelForgeConfig, _apply_yaml
from zettelforge.memory_salience import (
    ENTITY_TYPE_PRIORITY,
    SalienceConfig,
    SalienceScore,
    cosine_similarity,
    compute_distinctiveness,
    compute_signal_weight,
    compute_isolation,
    compute_salience_score,
)
from zettelforge.memory_spacing import (
    SpacingConfig,
    reinforce,
    memory_strength,
    should_reinforce,
    spacing_interval_days,
    decay_strength,
)
from zettelforge.tiered_decay import (
    MemoryTier,
    DecayConfig,
    compute_tier,
    tier_multiplier,
    is_excluded,
    recompute_all_tiers,
    tier_distribution,
    TIER_MULTIPLIERS,
)
from zettelforge.note_schema import MemoryNote, Tier


# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_note(
    created_at: str | None = None,
    last_accessed: str | None = None,
    reinforcement_counter: int = 0,
    salience_score: float = 0.5,
    memory_tier: str = "warm",
) -> MemoryNote:
    """Build a minimal MemoryNote for testing.

    All RFC-008 fields (reinforcement_counter, salience_score, memory_tier)
    live inside Metadata.  The top-level content.source_type, content.source_ref,
    and embedding fields are required by the schema.
    """
    # Use naive UTC to match zettelforge.tiered_decay._note_age_days which uses datetime.utcnow()
    now = datetime.utcnow().isoformat()
    created = created_at or now

    return MemoryNote(
        id="test-note-1",
        created_at=created,
        updated_at=now,
        content={
            "raw": "APT29 campaign targeting government agencies.",
            "source_type": "observation",
            "source_ref": "test:note-1",
        },
        metadata={
            "domain": "cti",
            "confidence": 0.85,
            "reinforcement_counter": reinforcement_counter,
            "salience_score": salience_score,
            "memory_tier": memory_tier,
            "last_accessed": last_accessed,
        },
        semantic={
            "entities": ["APT29"],
            "context": "nation-state espionage",
            "keywords": ["APT29", "espionage"],
            "tags": ["nation-state"],
        },
        embedding={
            "vector": [0.1] * 768,
            "dimensions": 768,
        },
    )


# =============================================================================
# memory_salience - cosine_similarity
# =============================================================================

class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal_vectors(self):
        sim = cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(sim) < 1e-9

    def test_opposite_vectors(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0

    def test_empty_vectors(self):
        assert cosine_similarity([], []) == 0.0

    def test_mismatched_length(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.5]) == 0.0

    def test_normalized_result(self):
        sim = cosine_similarity([0.6, 0.8], [0.6, 0.8])
        assert 0.999 < sim < 1.001


# =============================================================================
# memory_salience - compute_distinctiveness
# =============================================================================

class TestComputeDistinctiveness:
    def _emb(self, v: float) -> list[float]:
        return [v]

    def test_single_identical_embedding_is_not_distinctive(self):
        """One corpus note that is identical to this one → avg_sim=1.0 → distinctiveness=0.0."""
        assert compute_distinctiveness([0.5], [[0.5]]) == 0.0

    def test_empty_corpus_returns_05(self):
        """No corpus embeddings → no comparison possible → neutral 0.5."""
        assert compute_distinctiveness([0.5], []) == 0.5

    def test_identical_embeddings_low_distinctiveness(self):
        """High avg similarity → low distinctiveness."""
        emb = [1.0, 0.0]
        corpus = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]
        d = compute_distinctiveness(emb, corpus)
        assert d < 0.1  # near-identical

    def test_dissimilar_embeddings_high_distinctiveness(self):
        """Low avg similarity → high distinctiveness."""
        emb = [1.0, 0.0]
        # All orthogonal to emb
        corpus = [[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
        d = compute_distinctiveness(emb, corpus)
        assert d > 0.9  # highly distinctive

    def test_partial_similarity(self):
        """One identical, one orthogonal → avg_sim=0.5 → distinctiveness=0.5."""
        d1 = compute_distinctiveness([1.0, 0.0], [[1.0, 0.0], [0.0, 1.0]])
        # Both orthogonal to note → avg_sim=0.0 → distinctiveness=1.0
        d2 = compute_distinctiveness([1.0, 0.0], [[0.0, 1.0], [0.0, 1.0]])
        assert d1 == 0.5
        assert d2 == 1.0


# =============================================================================
# memory_salience - compute_signal_weight
# =============================================================================

class TestComputeSignalWeight:
    def test_threat_actor_highest_priority(self):
        s = compute_signal_weight("threat_actor", confidence=0.9)
        assert s == pytest.approx(0.9)  # 1.0 × 0.9 × 1.0

    def test_malware_high_priority(self):
        s = compute_signal_weight("malware", confidence=0.9)
        assert s == pytest.approx(0.81)  # 0.9 × 0.9 × 1.0

    def test_generic_low_priority(self):
        s = compute_signal_weight("generic", confidence=0.5)
        assert s == pytest.approx(0.15)  # 0.3 × 0.5 × 1.0

    def test_analyst_flagged_bonus(self):
        unflagged = compute_signal_weight("generic", confidence=0.5)
        flagged = compute_signal_weight("generic", confidence=0.5, analyst_flagged=True)
        assert flagged > unflagged
        assert flagged == pytest.approx(0.18)  # 0.3 × 0.5 × 1.2

    def test_confidence_scaling(self):
        low = compute_signal_weight("threat_actor", confidence=0.5)
        high = compute_signal_weight("threat_actor", confidence=1.0)
        assert high > low
        assert high == pytest.approx(1.0)  # capped at 1.0
        assert low == pytest.approx(0.5)

    def test_unknown_entity_type_defaults_to_generic(self):
        s = compute_signal_weight("totally_unknown_type", confidence=1.0)
        assert s == pytest.approx(0.3)


# =============================================================================
# memory_salience - compute_isolation
# =============================================================================

class TestComputeIsolation:
    def test_no_cluster_is_isolated(self):
        assert compute_isolation(None, 100, 1) == 1.0

    def test_singleton_cluster_is_isolated(self):
        assert compute_isolation("cluster-1", 100, 1) == 1.0

    def test_large_cluster_is_not_isolated(self):
        """If 99 of 99 other notes share cluster, it's not isolated."""
        d = compute_isolation("big-cluster", 100, 100)
        assert d == pytest.approx(0.0)

    def test_small_cluster_is_somewhat_isolated(self):
        """Cluster of 2 in corpus of 10: 1/9 other notes share it."""
        d = compute_isolation("small-cluster", 10, 2)
        assert 0 < d < 1.0

    def test_total_notes_of_one(self):
        assert compute_isolation("only-note", 1, 1) == 1.0


# =============================================================================
# memory_salience - compute_salience_score
# =============================================================================

class TestComputeSalienceScore:
    def _cfg(self, **kw) -> SalienceConfig:
        return SalienceConfig(**kw)

    def test_disabled_returns_05(self):
        note_emb = [1.0, 0.0]
        score = compute_salience_score(
            note_emb, [[0.0, 1.0]],
            "threat_actor", confidence=0.9,
            config=self._cfg(enabled=False),
        )
        assert score.score == 0.5

    def test_weights_sum_to_normalized_score(self):
        """With equal-weight config, score should be in [0,1]."""
        score = compute_salience_score(
            note_embedding=[1.0, 0.0],
            all_embeddings=[[0.0, 1.0]],
            entity_type="generic",
            confidence=1.0,
            config=self._cfg(distinctiveness_weight=0.4, signal_weight=0.4, isolation_weight=0.2),
        )
        assert 0.0 <= score.score <= 1.0

    def test_threat_actor_high_signal(self):
        s = compute_salience_score(
            [1.0, 0.0], [[0.5, 0.5]],
            "threat_actor", confidence=0.9,
        )
        assert s.signal_weight > 0.8  # threat_actor × 0.9 × 1.0

    def test_analyst_flagged_higher_than_unflagged(self):
        base_emb = [1.0, 0.0]
        base_embs = [[0.0, 1.0], [0.0, 1.0]]
        unflagged = compute_salience_score(base_emb, base_embs, "generic", confidence=0.5)
        flagged = compute_salience_score(base_emb, base_embs, "generic", confidence=0.5, analyst_flagged=True)
        assert flagged.score > unflagged.score

    def test_returns_all_components(self):
        score = compute_salience_score(
            [1.0, 0.0], [[0.5, 0.5]],
            "malware", confidence=0.8,
        )
        assert hasattr(score, "score")
        assert hasattr(score, "distinctiveness")
        assert hasattr(score, "signal_weight")
        assert hasattr(score, "isolation")
        assert hasattr(score, "computed_at")

    def test_score_bounded_0_to_1(self):
        """Score should never exceed [0, 1] regardless of inputs."""
        for _ in range(50):
            s = compute_salience_score(
                [0.1 * i for i in range(10)],
                [[0.1 * i for i in range(10)] for _ in range(20)],
                "threat_actor",
                confidence=0.99,
                analyst_flagged=True,
            )
            assert 0.0 <= s.score <= 1.0


# =============================================================================
# memory_spacing - memory_strength
# =============================================================================

class TestMemoryStrength:
    def _cfg(self, **kw) -> SpacingConfig:
        return SpacingConfig(**kw)

    def test_disabled_returns_max(self):
        note = make_note()
        note.metadata.reinforcement_counter = 10
        assert memory_strength(note, self._cfg(enabled=False)) == 1.0

    def test_decay_over_time(self):
        """Strength decreases as note ages."""
        note_old = make_note(
            created_at=(datetime.utcnow() - timedelta(days=30)).isoformat(),
        )
        note_new = make_note(
            created_at=datetime.utcnow().isoformat(),
        )
        old_str = memory_strength(note_old, self._cfg(half_life_days=30, decay_rate=0.02))
        new_str = memory_strength(note_new, self._cfg(half_life_days=30, decay_rate=0.02))
        assert new_str > old_str

    def test_reinforcement_boosts_strength(self):
        """Higher counter → higher strength (with diminishing returns)."""
        cfg = self._cfg(half_life_days=30, decay_rate=0.02, reinforcement_factor=0.1)
        note = make_note(created_at=(datetime.utcnow() - timedelta(days=10)).isoformat())

        note.metadata.reinforcement_counter = 0
        s0 = memory_strength(note, cfg)
        note.metadata.reinforcement_counter = 4
        s4 = memory_strength(note, cfg)
        note.metadata.reinforcement_counter = 16
        s16 = memory_strength(note, cfg)

        assert s4 > s0
        assert s16 > s4
        # Diminishing returns: 4→16 (12 step) adds less than 0→4 (4 step)
        assert (s4 - s0) > (s16 - s4)

    def test_never_exceeds_max_strength(self):
        note = make_note()
        note.metadata.reinforcement_counter = 1000
        s = memory_strength(note, self._cfg(max_strength=1.0))
        assert s <= 1.0

    def test_decay_rate_formula(self):
        """Verify e^(-decay_rate × days) formula at known points."""
        # decay_rate=0.02, 30 days: e^(-0.6) ≈ 0.5488
        result = decay_strength(1.0, 30.0, 0.02)
        assert result == pytest.approx(math.exp(-0.6), rel=1e-3)


# =============================================================================
# memory_spacing - should_reinforce
# =============================================================================

class TestShouldReinforce:
    def _cfg(self, **kw) -> SpacingConfig:
        return SpacingConfig(half_life_days=30, reinforcement_threshold=3, **kw)

    def test_disabled_never_reinforces(self):
        note = make_note()
        assert should_reinforce(note, self._cfg(enabled=False)) is False

    def test_first_access_should_reinforce(self):
        """Never accessed → should reinforce."""
        note = make_note(last_accessed=None)
        assert should_reinforce(note, self._cfg()) is True

    def test_recent_access_should_not_reinforce(self):
        """Accessed 1 day ago with counter=0: interval = 30 days → no reinforce."""
        note = make_note(
            last_accessed=(datetime.utcnow() - timedelta(days=1)).isoformat(),
            reinforcement_counter=0,
        )
        assert should_reinforce(note, self._cfg()) is False

    def test_counter_shrinks_interval(self):
        """Higher counter → shorter interval →reinforce fires sooner."""
        note_new = make_note(
            last_accessed=(datetime.utcnow() - timedelta(days=5)).isoformat(),
            reinforcement_counter=0,
        )
        note_old = make_note(
            last_accessed=(datetime.utcnow() - timedelta(days=5)).isoformat(),
            reinforcement_counter=9,
        )
        # counter=0, interval=30d → 5d not enough
        # counter=9, interval=30/10=3d → 5d is enough
        assert should_reinforce(note_new, self._cfg()) is False
        assert should_reinforce(note_old, self._cfg()) is True

    def test_interval_floors_at_1_day(self):
        """Very high counter → interval floors at 1 day."""
        note = make_note(
            last_accessed=(datetime.utcnow() - timedelta(hours=12)).isoformat(),
            reinforcement_counter=1000,
        )
        # interval = 30/(1+1000) ≈ 0.03 → floored to 1 day; 12h < 1d → False
        assert should_reinforce(note, self._cfg()) is False


# =============================================================================
# memory_spacing - spacing_interval_days
# =============================================================================

class TestSpacingIntervalDays:
    def _cfg(self, **kw) -> SpacingConfig:
        return SpacingConfig(half_life_days=30, **kw)

    def test_counter_zero_returns_half_life(self):
        note = make_note(reinforcement_counter=0)
        assert spacing_interval_days(note, self._cfg()) == 30.0

    def test_counter_decreases_interval(self):
        note0 = make_note(reinforcement_counter=0)
        note3 = make_note(reinforcement_counter=3)
        note9 = make_note(reinforcement_counter=9)
        assert spacing_interval_days(note0, self._cfg()) > spacing_interval_days(note3, self._cfg())
        assert spacing_interval_days(note3, self._cfg()) > spacing_interval_days(note9, self._cfg())

    def test_interval_floors_at_1(self):
        note = make_note(reinforcement_counter=999)
        assert spacing_interval_days(note, self._cfg()) == 1.0


# =============================================================================
# memory_spacing - reinforce
# =============================================================================

class TestReinforce:
    def test_increments_counter(self):
        note = make_note(reinforcement_counter=2)
        reinforce(note)
        assert note.metadata.reinforcement_counter == 3

    def test_updates_last_accessed(self):
        note = make_note(last_accessed=None)
        before = datetime.utcnow()
        reinforce(note)
        after = datetime.utcnow()
        assert note.metadata.last_accessed is not None
        accessed = datetime.fromisoformat(note.metadata.last_accessed)
        assert before <= accessed <= after


# =============================================================================
# tiered_decay - compute_tier
# =============================================================================

class TestComputeTier:
    def _cfg(self, **kw) -> DecayConfig:
        return DecayConfig(
            hot_threshold=3,
            hot_max_age_days=7,
            warm_threshold_days=30,
            frozen_threshold_days=90,
            relevance_freeze_threshold=0.1,
            **kw,
        )

    def test_disabled_returns_warm(self):
        note = make_note(reinforcement_counter=0)
        assert compute_tier(note, self._cfg(enabled=False)) == MemoryTier.WARM

    def test_hot_requires_confirmations_and_recency(self):
        note = make_note(
            reinforcement_counter=3,
            salience_score=0.5,
            last_accessed=(datetime.utcnow() - timedelta(days=2)).isoformat(),
            created_at=(datetime.utcnow() - timedelta(days=2)).isoformat(),
        )
        assert compute_tier(note, self._cfg()) == MemoryTier.HOT

    def test_hot_requires_both_conditions(self):
        """Sufficient confirmations but too old → not HOT."""
        note = make_note(
            reinforcement_counter=3,
            salience_score=0.5,
            last_accessed=(datetime.utcnow() - timedelta(days=14)).isoformat(),
            created_at=(datetime.utcnow() - timedelta(days=14)).isoformat(),
        )
        # 14d > hot_max_age_days(7) → too old for HOT
        assert compute_tier(note, self._cfg()) != MemoryTier.HOT

    def test_warm_tier(self):
        note = make_note(
            reinforcement_counter=1,
            salience_score=0.5,
            last_accessed=(datetime.utcnow() - timedelta(days=5)).isoformat(),
            created_at=(datetime.utcnow() - timedelta(days=5)).isoformat(),
        )
        assert compute_tier(note, self._cfg()) == MemoryTier.WARM

    def test_cold_tier(self):
        note = make_note(
            reinforcement_counter=0,
            salience_score=0.5,
            last_accessed=(datetime.utcnow() - timedelta(days=60)).isoformat(),
            created_at=(datetime.utcnow() - timedelta(days=60)).isoformat(),
        )
        assert compute_tier(note, self._cfg()) == MemoryTier.COLD

    def test_frozen_by_age(self):
        note = make_note(
            reinforcement_counter=0,
            salience_score=0.5,
            last_accessed=(datetime.utcnow() - timedelta(days=120)).isoformat(),
            created_at=(datetime.utcnow() - timedelta(days=120)).isoformat(),
        )
        assert compute_tier(note, self._cfg()) == MemoryTier.FROZEN

    def test_frozen_by_low_salience(self):
        """High-age but adequate salience → still frozen by relevance."""
        note = make_note(
            reinforcement_counter=0,
            salience_score=0.05,  # below 0.1 threshold
            last_accessed=(datetime.utcnow() - timedelta(days=120)).isoformat(),
            created_at=(datetime.utcnow() - timedelta(days=120)).isoformat(),
        )
        # Would be WARM by age (120d < 90d? no, 120 > 90) → FROZEN by age
        # But also frozen by relevance
        assert compute_tier(note, self._cfg()) == MemoryTier.FROZEN

    def test_low_salience_without_age_still_frozen(self):
        """Recent note but below relevance threshold → frozen."""
        note = make_note(
            reinforcement_counter=0,
            salience_score=0.05,
            last_accessed=datetime.utcnow().isoformat(),
            created_at=datetime.utcnow().isoformat(),
        )
        assert compute_tier(note, self._cfg()) == MemoryTier.FROZEN

    def test_boundary_warm_vs_cold_gives_clear_answer(self):
        """Age just inside vs just outside warm_threshold_days should differ in tier.

        warm_threshold_days=30:
          30.001d → COLD (no longer < 30)
          29.999d → WARM (< 30)
        """
        cfg = self._cfg()

        warm_note = make_note(
            reinforcement_counter=0,
            salience_score=0.5,
            # ~29.9 days — clearly inside WARM
            last_accessed=(datetime.utcnow() - timedelta(days=29, hours=22)).isoformat(),
            created_at=(datetime.utcnow() - timedelta(days=29, hours=22)).isoformat(),
        )
        cold_note = make_note(
            reinforcement_counter=0,
            salience_score=0.5,
            # ~30.1 days — just outside WARM → COLD
            last_accessed=(datetime.utcnow() - timedelta(days=30, hours=2)).isoformat(),
            created_at=(datetime.utcnow() - timedelta(days=30, hours=2)).isoformat(),
        )

        assert compute_tier(warm_note, cfg) == MemoryTier.WARM
        assert compute_tier(cold_note, cfg) == MemoryTier.COLD


# =============================================================================
# tiered_decay - tier_multiplier
# =============================================================================

class TestTierMultiplier:
    def _cfg(self, **kw) -> DecayConfig:
        return DecayConfig(**kw)

    def test_hot_multiplier_is_1(self):
        assert tier_multiplier(MemoryTier.HOT) == 1.0

    def test_warm_multiplier_is_05(self):
        assert tier_multiplier(MemoryTier.WARM) == 0.5

    def test_cold_multiplier_is_01(self):
        assert tier_multiplier(MemoryTier.COLD) == 0.1

    def test_frozen_multiplier_is_zero(self):
        assert tier_multiplier(MemoryTier.FROZEN) == 0.0

    def test_disabled_config_returns_1(self):
        assert tier_multiplier(MemoryTier.FROZEN, self._cfg(enabled=False)) == 1.0


# =============================================================================
# tiered_decay - is_excluded
# =============================================================================

class TestIsExcluded:
    def test_frozen_is_excluded(self):
        assert is_excluded(MemoryTier.FROZEN) is True

    def test_warm_not_excluded(self):
        assert is_excluded(MemoryTier.WARM) is False

    def test_hot_not_excluded(self):
        assert is_excluded(MemoryTier.HOT) is False

    def test_cold_not_excluded(self):
        assert is_excluded(MemoryTier.COLD) is False


# =============================================================================
# tiered_decay - recompute_all_tiers
# =============================================================================

class TestRecomputeAllTiers:
    def _cfg(self, **kw) -> DecayConfig:
        return DecayConfig(
            hot_threshold=3,
            hot_max_age_days=7,
            warm_threshold_days=30,
            frozen_threshold_days=90,
            relevance_freeze_threshold=0.1,
            **kw,
        )

    def _note(self, counter: int, days_ago: int, salience: float = 0.5) -> MemoryNote:
        return make_note(
            reinforcement_counter=counter,
            salience_score=salience,
            last_accessed=(datetime.utcnow() - timedelta(days=days_ago)).isoformat(),
            created_at=(datetime.utcnow() - timedelta(days=days_ago)).isoformat(),
        )

    def test_hot_notes_sorted_first(self):
        hot = self._note(counter=5, days_ago=1)
        warm = self._note(counter=1, days_ago=5)
        cold = self._note(counter=0, days_ago=60)
        frozen = self._note(counter=0, days_ago=120)

        result = recompute_all_tiers([frozen, cold, warm, hot], self._cfg())
        tiers = [MemoryTier(n.metadata.memory_tier) for n in result]
        assert tiers[0] == MemoryTier.HOT

    def test_same_tier_sorted_by_salience(self):
        """HOT notes with higher salience rank first within tier."""
        n1 = self._note(counter=5, days_ago=1, salience=0.3)
        n2 = self._note(counter=5, days_ago=1, salience=0.9)
        result = recompute_all_tiers([n1, n2], self._cfg())
        tiers = [MemoryTier(n.metadata.memory_tier) for n in result]
        # Both HOT; n2 (0.9) should come before n1 (0.3)
        saliences = [n.metadata.salience_score for n in result]
        assert saliences == [0.9, 0.3]

    def test_all_tiers_represented(self):
        notes = [
            self._note(counter=5, days_ago=1),   # HOT
            self._note(counter=1, days_ago=5),   # WARM
            self._note(counter=0, days_ago=60), # COLD
            self._note(counter=0, days_ago=120), # FROZEN
        ]
        result = recompute_all_tiers(notes, self._cfg())
        tiers = {MemoryTier(n.metadata.memory_tier) for n in result}
        assert tiers == {MemoryTier.HOT, MemoryTier.WARM, MemoryTier.COLD, MemoryTier.FROZEN}


# =============================================================================
# tiered_decay - tier_distribution
# =============================================================================

class TestTierDistribution:
    def _note(self, tier: str) -> MemoryNote:
        return make_note(memory_tier=tier)

    def test_counts_all_tiers(self):
        notes = [
            self._note("hot"),
            self._note("hot"),
            self._note("warm"),
            self._note("cold"),
            self._note("cold"),
            self._note("cold"),
            self._note("frozen"),
        ]
        dist = tier_distribution(notes)
        assert dist["hot"] == 2
        assert dist["warm"] == 1
        assert dist["cold"] == 3
        assert dist["frozen"] == 1

    def test_empty_returns_zeros(self):
        dist = tier_distribution([])
        assert all(v == 0 for v in dist.values())


# =============================================================================
# config - RFC-008 sections in _apply_yaml
# =============================================================================

class TestConfigRFC008Apply:
    def test_salience_section_applied(self):
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {
            "salience": {
                "enabled": False,
                "distinctiveness_weight": 0.2,
            }
        })
        assert cfg.salience.enabled is False
        assert cfg.salience.distinctiveness_weight == 0.2
        # Unchanged fields stay at defaults
        assert cfg.salience.signal_weight == 0.4

    def test_spacing_section_applied(self):
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {
            "spacing": {
                "enabled": True,
                "half_life_days": 60,
                "reinforcement_factor": 0.08,
            }
        })
        assert cfg.spacing.enabled is True
        assert cfg.spacing.half_life_days == 60
        assert cfg.spacing.reinforcement_factor == 0.08

    def test_decay_section_applied(self):
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {
            "decay": {
                "enabled": True,
                "hot_threshold": 5,
                "hot_max_age_days": 14,
                "warm_threshold_days": 60,
                "frozen_threshold_days": 180,
            }
        })
        assert cfg.decay.enabled is True
        assert cfg.decay.hot_threshold == 5
        assert cfg.decay.hot_max_age_days == 14
        assert cfg.decay.warm_threshold_days == 60
        assert cfg.decay.frozen_threshold_days == 180

    def test_retrieval_weights_section_applied(self):
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {
            "retrieval_weights": {
                "salience_weight": 0.8,
                "tier_hot_multiplier": 1.5,
                "tier_warm_multiplier": 0.6,
                "tier_cold_multiplier": 0.2,
                "tier_frozen_multiplier": 0.0,
            }
        })
        assert cfg.retrieval_weights.salience_weight == 0.8
        assert cfg.retrieval_weights.tier_hot_multiplier == 1.5
        assert cfg.retrieval_weights.tier_warm_multiplier == 0.6

    def test_all_rfc008_sections_applied_together(self):
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {
            "salience": {"enabled": True, "distinctiveness_weight": 0.3},
            "spacing": {"enabled": True, "half_life_days": 45},
            "decay": {"enabled": True, "hot_threshold": 4},
            "retrieval_weights": {"salience_weight": 1.0},
        })
        assert cfg.salience.enabled is True
        assert cfg.spacing.half_life_days == 45
        assert cfg.decay.hot_threshold == 4
        assert cfg.retrieval_weights.salience_weight == 1.0

    def test_unknown_keys_ignored(self):
        """No AttributeError on unknown keys - they're silently ignored."""
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {
            "salience": {"totally_fake_field": 999},
            "spacing": {"another_fake": "ignored"},
        })
        # Should not raise - unknown fields ignored
        assert cfg.salience.enabled is True  # default unchanged


class TestConfigRFC008Defaults:
    def test_salience_default_enabled(self):
        cfg = ZettelForgeConfig()
        assert cfg.salience.enabled is True
        assert cfg.salience.distinctiveness_weight == 0.4
        assert cfg.salience.signal_weight == 0.4
        assert cfg.salience.isolation_weight == 0.2

    def test_spacing_default_enabled(self):
        cfg = ZettelForgeConfig()
        assert cfg.spacing.enabled is True
        assert cfg.spacing.half_life_days == 30
        assert cfg.spacing.reinforcement_factor == 0.1
        assert cfg.spacing.decay_rate == 0.02
        assert cfg.spacing.reinforcement_threshold == 3

    def test_decay_default_enabled(self):
        cfg = ZettelForgeConfig()
        assert cfg.decay.enabled is True
        assert cfg.decay.hot_threshold == 3
        assert cfg.decay.hot_max_age_days == 7
        assert cfg.decay.warm_threshold_days == 30
        assert cfg.decay.frozen_threshold_days == 90
        assert cfg.decay.relevance_freeze_threshold == 0.1

    def test_retrieval_weights_defaults(self):
        cfg = ZettelForgeConfig()
        assert cfg.retrieval_weights.salience_weight == 0.5
        assert cfg.retrieval_weights.tier_hot_multiplier == 1.0
        assert cfg.retrieval_weights.tier_warm_multiplier == 0.5
        assert cfg.retrieval_weights.tier_cold_multiplier == 0.1
        assert cfg.retrieval_weights.tier_frozen_multiplier == 0.0


class TestTierConstants:
    def test_frozen_multiplier_is_zero(self):
        """FROZEN notes must be excluded from retrieval (multiplier = 0)."""
        assert TIER_MULTIPLIERS[MemoryTier.FROZEN] == 0.0

    def test_hot_is_highest_multiplier(self):
        """HOT should have the highest retrieval weight."""
        assert TIER_MULTIPLIERS[MemoryTier.HOT] == 1.0

    def test_tier_order(self):
        """HOT > WARM > COLD > FROZEN in multiplier value."""
        multipliers = {
            MemoryTier.HOT: TIER_MULTIPLIERS[MemoryTier.HOT],
            MemoryTier.WARM: TIER_MULTIPLIERS[MemoryTier.WARM],
            MemoryTier.COLD: TIER_MULTIPLIERS[MemoryTier.COLD],
            MemoryTier.FROZEN: TIER_MULTIPLIERS[MemoryTier.FROZEN],
        }
        assert multipliers[MemoryTier.HOT] > multipliers[MemoryTier.WARM]
        assert multipliers[MemoryTier.WARM] > multipliers[MemoryTier.COLD]
        assert multipliers[MemoryTier.COLD] > multipliers[MemoryTier.FROZEN]
