"""
Tiered Decay — Hot/Warm/Cold/Frozen Memory Tiers

RFC-008 Phase 5: Tiered decay manages storage cost and keeps hot memory fast.
HOT notes get full retrieval weight; FROZEN notes are archived and excluded.

Tier definitions:
  HOT    — 3+ confirmations AND accessed < 7d → 100% weight
  WARM   — accessed < 30d → 50% weight
  COLD   — accessed 30-90d → 10% weight, archived
  FROZEN — accessed > 90d OR salience < 0.1 → excluded

Reference: rfc/rfc-008-memory-salience-spacing-FULL-SPEC.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from zettelforge.note_schema import MemoryNote, Tier


# ── Tier enum ────────────────────────────────────────────────────────────────


class MemoryTier(str, Enum):
    HOT = Tier.HOT      # "hot"
    WARM = Tier.WARM    # "warm"
    COLD = Tier.COLD    # "cold"
    FROZEN = Tier.FROZEN  # "frozen"


# ── Tier multipliers for retrieval (applied to RRF scores) ───────────────────


TIER_MULTIPLIERS = {
    MemoryTier.HOT: 1.0,
    MemoryTier.WARM: 0.5,
    MemoryTier.COLD: 0.1,
    MemoryTier.FROZEN: 0.0,  # Excluded from retrieval
}


# ── Config ───────────────────────────────────────────────────────────────────


@dataclass
class DecayConfig:
    """Configuration for tiered decay."""

    enabled: bool = True
    hot_threshold: int = 3          # Min confirmations for HOT
    hot_max_age_days: int = 7       # HOT → WARM after 7 days regardless
    warm_threshold_days: int = 30   # WARM → COLD after 30 days
    frozen_threshold_days: int = 90  # COLD → FROZEN after 90 days
    relevance_freeze_threshold: float = 0.1
    tier_update_batch_size: int = 500
    tier_update_schedule: str = "0 3 * * *"  # Daily 3am cron


# ── Tier computation ─────────────────────────────────────────────────────────


def compute_tier(note: MemoryNote, config: DecayConfig) -> MemoryTier:
    """
    Derive the current memory tier for a note.

    Priority order: FROZEN > HOT > WARM > COLD
    A note is FROZEN if it exceeds age threshold OR has low relevance.
    A note is HOT if it has enough confirmations AND is recent.
    """
    if not config.enabled:
        return MemoryTier.WARM  # Everything warm when disabled

    age_days = _note_age_days(note)
    counter = note.metadata.reinforcement_counter
    salience = note.metadata.salience_score

    # Frozen check: age OR relevance
    if age_days > config.frozen_threshold_days:
        return MemoryTier.FROZEN
    if salience < config.relevance_freeze_threshold:
        return MemoryTier.FROZEN

    # HOT: enough confirmations AND still recent
    if (
        counter >= config.hot_threshold
        and age_days < config.hot_max_age_days
    ):
        return MemoryTier.HOT

    # WARM: accessed recently
    if age_days < config.warm_threshold_days:
        return MemoryTier.WARM

    # Default: COLD
    return MemoryTier.COLD


def tier_multiplier(tier: MemoryTier, config: DecayConfig | None = None) -> float:
    """Return the retrieval weight multiplier for a tier."""
    if config is not None and not config.enabled:
        return 1.0
    return TIER_MULTIPLIERS.get(tier, 0.0)


def is_excluded(tier: MemoryTier) -> bool:
    """True if this tier is excluded from retrieval results."""
    return tier == MemoryTier.FROZEN


# ── Batch tier recomputation ──────────────────────────────────────────────────


def recompute_all_tiers(notes: list[MemoryNote], config: DecayConfig) -> list[MemoryNote]:
    """
    Recompute tier for every note. Used by daily maintenance cron job.

    Returns notes sorted: HOT first, then WARM, COLD, FROZEN.
    """
    tiered = []
    for note in notes:
        new_tier = compute_tier(note, config)
        note.metadata.memory_tier = new_tier.value
        tiered.append(note)

    # Sort by tier priority (HOT > WARM > COLD > FROZEN) then by salience
    tier_order = {MemoryTier.HOT: 0, MemoryTier.WARM: 1, MemoryTier.COLD: 2, MemoryTier.FROZEN: 3}
    tiered.sort(key=lambda n: (tier_order.get(MemoryTier(n.metadata.memory_tier), 3), -n.metadata.salience_score))
    return tiered


# ── Tier distribution stats ──────────────────────────────────────────────────


def tier_distribution(notes: list[MemoryNote]) -> dict[str, int]:
    """Return count of notes per tier. For monitoring and UI."""
    dist: dict[str, int] = {"hot": 0, "warm": 0, "cold": 0, "frozen": 0}
    for note in notes:
        tier = note.metadata.memory_tier or Tier.WARM
        if tier in dist:
            dist[tier] += 1
    return dist


# ── Helpers ───────────────────────────────────────────────────────────────────


def _note_age_days(note: MemoryNote) -> float:
    """Compute note age in days from last_accessed or created_at."""
    anchor = note.metadata.last_accessed or note.created_at
    try:
        dt = datetime.fromisoformat(anchor)
        age = datetime.utcnow() - dt
        return age.total_seconds() / 86400.0
    except (ValueError, TypeError):
        return 0.0
