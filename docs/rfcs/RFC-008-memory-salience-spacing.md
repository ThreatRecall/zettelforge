# RFC-008: Memory Salience & Spacing Effects
## Von Restorff + Spacing Effect — Full Technical Specification

**RFC:** RFC-008 | **Author:** Nexus | **Date:** 2026-04-28
**Status:** IMPLEMENTED | **Research:** 45/45 missions complete
**Preset:** Cognitive Science Purist (default: all features ON)

---

## Executive Summary

Add two cognitive science principles as configurable memory design in ZettelForge:

1. **Von Restorff Effect (Salience):** Distinctive, high-signal memories are remembered better and protected from decay
2. **Spacing Effect (Reinforcement):** Memories strengthen with each confirmed retrieval — distributed reinforcement over time beats massed review

Sorted by product improvement impact: salience scoring (Phase 2) → reinforcement (Phase 4) → tiered decay (Phase 5) → retrieval integration (Phase 3) → UI (Phase 6) → data model (Phase 1)

---

## Decision Record (Locked)

| # | Decision | Value |
|---|----------|-------|
| 1 | Reinforcement signal | BOTH implicit (no-edit 24h post-retrieval) AND explicit (👍 button) |
| 2 | Implementation | Fully in ZettelForge core — not zf-visibility, not threatrecall-api |
| 3 | Default preset | Cognitive Science Purist — all features ON |
| 4 | Cold storage | Archive, not delete — frozen memories preserved indefinitely |
| 5 | Cross-agent reinforcement | YES — all fleet agents share confirmation signals |
| 6 | Forget curve for CTI | Severity-weighted — critical IOCs decay slower than stale intel |

---

## Phase Order: Sorted by Product Improvement Impact

---

### ⭐ PHASE 2 (Highest Impact): Salience Scoring — Von Restorff Effect

**Why first:** Salience is the fastest win — boosts high-signal CTI entities immediately without waiting for reinforcement cycles. Directly addresses M-045's "intent-grounded retrieval" gap.

#### Data Model Additions (note_schema.py)

```python
# In Metadata:
salience_score: float = 0.5        # 0.0–1.0, computed on write/update
salience_breakdown: dict = {}       # {distinctiveness, signal_weight, isolation}
last_salience_update: str = None   # ISO 8601, recomputed on entity update + weekly batch
reinforcement_counter: int = 0     # Times analyst confirmed retrieval was useful
memory_tier: str = Tier.WARM       # hot | warm | cold | frozen
```

#### Salience Scoring Algorithm

```
score = (0.4 × distinctiveness) + (0.4 × signal_weight) + (0.2 × isolation)
```

**Distinctiveness:** Cosine similarity of note embedding vs all corpus embeddings. Novel notes (rare IOCs, unique observations) score near 1.0. Common boilerplate scores near 0.

**Signal Weight:** Entity type priority × confidence × analyst flag. Threat actors and malware always score high:

| Entity Type | Priority |
|------------|----------|
| threat_actor | 1.0 |
| malware | 0.9 |
| vulnerability | 0.85 |
| attack_pattern | 0.8 |
| infrastructure | 0.75 |
| tool | 0.7 |
| campaign | 0.65 |
| generic | 0.3 |

**Isolation:** Notes in small clusters score higher. Singleton clusters (no cluster membership) score 1.0. Unclustered notes = maximally distinctive.

---

### ⭐ PHASE 4 (High Impact): Reinforcement / Spacing Effect

**Why second:** Spacing effect takes longer to show value — requires multiple retrieval cycles over days/weeks. But it's the core of "distinctive memories survive" and directly maps to M-045's "retrieval-driven mutation."

#### Reinforcement Formula

```
strength = base × e^(-decay_rate × age_days) × (1 + 0.1 × √counter)
```

With half_life=30 days:
- counter=0: strength = 54.9% (no confirmations)
- counter=4: strength = 65.9% (+4 confirmations)
- counter=16: strength = 76.8% (+16 confirmations)

Diminishing returns via √counter prevents over-weighting frequently-accessed notes.

#### Spacing Interval

```
interval_days = half_life / (1 + counter)
```

- counter=0: interval = 30 days (first reminder after 30 days)
- counter=3: interval = 7.5 days (next reminder after 7.5 days)
- counter=9: interval = 3 days (next reminder after 3 days)

Interval shrinks with counter (frequently accessed notes get reminded sooner) but never below 1 day.

---

### ⭐ PHASE 5 (High Impact): Tiered Decay

**Why third:** Tiered decay manages storage cost and keeps hot memory fast. Depends on reinforcement (Phase 4) but can be spec'd in parallel with retrieval integration.

| Tier | Entry Condition | Retrieval Weight | Storage |
|------|---------------|-----------------|---------|
| **HOT** | reinforcement_counter >= 3 AND last_accessed < 7d | 100% | RAM/fast index |
| **WARM** | last_accessed < 30d | 50% | Fast disk |
| **COLD** | last_accessed 30–90d | 10% | Archive storage |
| **FROZEN** | last_accessed > 90d OR salience_score < 0.1 | 0% (excluded) | Cold archive |

Frozen notes are **preserved, not deleted** — for compliance and audit.

---

### PHASE 3: Retrieval Integration

**Retrieval weight formula:**

```
retrieval_weight = rrf_score × (1 + salience_boost) × tier_multiplier × spacing_strength

salience_boost = (salience_score - 0.5) × salience_weight_config
tier_multiplier: hot=1.0, warm=0.5, cold=0.1, frozen=0.0
```

FROZEN notes return 0 from `tier_multiplier` and are excluded from results.

---

### PHASE 6 (High Visibility): UI Settings Panel

All three features configurable from Settings page with three presets:

| Preset | Salience | Spacing | Decay |
|--------|---------|---------|-------|
| **Cognitive Science Purist** | ON (0.4/0.4/0.2) | ON (30d, 0.1, 3×) | ON (3/7/30/90) |
| **Conservative** | ON (0.2/0.6/0.2) | ON (60d, 0.05, 5×) | ON (5/14/60/180) |
| **Minimal** | OFF | ON (30d, 0.1, 3×) | OFF |
| **Off** | OFF | OFF | OFF |

UI shows: Memory Health stats (HOT/WARM/COLD/FROZEN counts), per-feature toggle + sliders.

---

## Modules

| File | Purpose |
|------|---------|
| `note_schema.py` | New fields: salience_score, salience_breakdown, reinforcement_counter, memory_tier, last_salience_update |
| `config.py` | New dataclasses: SalienceConfig, SpacingConfig, DecayConfig, RetrievalWeightsConfig |
| `memory_salience.py` | Von Restorff scoring: compute_salience_score(), compute_distinctiveness(), compute_signal_weight(), compute_isolation() |
| `memory_spacing.py` | Reinforcement + decay curves: reinforce(), memory_strength(), should_reinforce(), spacing_interval_days() |
| `tiered_decay.py` | Tier computation + batch recompute: compute_tier(), recompute_all_tiers(), tier_distribution() |

---

## All Config Defaults (Cognitive Science Purist)

```yaml
salience:
  enabled: true
  distinctiveness_weight: 0.4
  signal_weight: 0.4
  isolation_weight: 0.2
  recompute_interval_days: 7

spacing:
  enabled: true
  half_life_days: 30
  reinforcement_factor: 0.1
  decay_rate: 0.02
  implicit_confirm_window_hours: 24
  reinforcement_threshold: 3

decay:
  enabled: true
  hot_threshold: 3
  hot_max_age_days: 7
  warm_threshold_days: 30
  frozen_threshold_days: 90
  relevance_freeze_threshold: 0.1

retrieval_weights:
  salience_weight: 0.5
  tier_hot_multiplier: 1.0
  tier_warm_multiplier: 0.5
  tier_cold_multiplier: 0.1
  tier_frozen_multiplier: 0.0
```

---

## Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1: Data Model | ✅ IMPLEMENTED | note_schema.py fields added |
| Phase 2: Salience | ✅ IMPLEMENTED | memory_salience.py complete |
| Phase 3: Retrieval Integration | ⚠️ PARTIAL | Tier multiplier math spec'd; blended_retriever integration pending |
| Phase 4: Reinforcement/Spacing | ✅ IMPLEMENTED | memory_spacing.py complete |
| Phase 5: Tiered Decay | ✅ IMPLEMENTED | tiered_decay.py complete |
| Phase 6: UI Settings | ⚠️ PENDING | Wireframe spec'd; UI not yet built |
| Phase 7: Testing | ⚠️ PENDING | Unit tests pending |
| Phase 8: Iteration Loop | ✅ SPEC COMPLETE | Standing process |

**Research dependency: NONE.** All phases unblocked.

---

_Last updated: 2026-04-28 | Author: Nexus | Based on 45-paper research corpus_
_Reference: rfc/rfc-008-memory-salience-spacing-FULL-SPEC.md (precursor)_