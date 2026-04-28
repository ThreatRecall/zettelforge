"""
Memory Spacing & Reinforcement — Spacing Effect

RFC-008 Phase 4: Each confirmed retrieval strengthens memory via a diminishing-
returns curve. Reinforcement counter drives tier computation. Spacing interval
grows with each confirmation (longer intervals = stronger retention per Ebbinghaus).

Reference: rfc/rfc-008-memory-salience-spacing-FULL-SPEC.md
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from zettelforge.note_schema import MemoryNote, Tier


@dataclass
class SpacingConfig:
    """Configuration for Spacing Effect reinforcement."""

    enabled: bool = True
    half_life_days: int = 30
    reinforcement_factor: float = 0.1  # Diminishing returns via sqrt
    decay_rate: float = 0.02  # e^(-decay_rate × age_days)
    implicit_confirm_window_hours: int = 24
    reinforcement_threshold: int = 3
    max_strength: float = 1.0


def reinforce(note: MemoryNote) -> None:
    """
    Increment reinforcement counter and update last_accessed.

    Called on:
      - Explicit: analyst clicks 👍 on retrieval result
      - Implicit: 24h passes after retrieval with no edit

    Cross-agent: any fleet agent's confirmation counts (all share ZettelForge).
    """
    note.metadata.reinforcement_counter += 1
    note.metadata.last_accessed = datetime.utcnow().isoformat()
    # memory_tier will be recomputed by tiered_decay on next retrieval


def memory_strength(note: MemoryNote, config: SpacingConfig) -> float:
    """
    Ebbinghaus-inspired forgetting curve with reinforcement multiplier.

    Formula: strength = base × e^(-decay_rate × age_days) × (1 + RF × √counter)

    With counter=0, half_life=30:  strength = 1.0 × e^(-0.02×30) = ~54.9%
    With counter=4, half_life=30:  strength = 1.0 × e^(-0.02×30) × (1 + 0.1×2) = ~65.9%
    With counter=16, half_life=30: strength = 1.0 × e^(-0.02×30) × (1 + 0.1×4) = ~76.8%

    Diminishing returns: each confirmation adds less than the last.
    """
    if not config.enabled:
        return 1.0

    age_days = _note_age_days(note)
    counter = note.metadata.reinforcement_counter

    # Decay factor: e^(-decay_rate × age)
    decay = math.exp(-config.decay_rate * age_days)

    # Reinforcement bonus: diminishing via sqrt(counter), not linear
    reinforcement_bonus = 1.0 + config.reinforcement_factor * math.sqrt(counter)

    strength = config.max_strength * decay * reinforcement_bonus
    return min(config.max_strength, max(0.0, strength))


def should_reinforce(note: MemoryNote, config: SpacingConfig) -> bool:
    """
    Check if enough days have passed since last reinforcement.

    Spacing insight: longer intervals between reinforcements = better retention.
    But interval grows with counter (to avoid spamming the analyst).

    With counter=0, half_life=30: interval = 30/(1+0) = 30 days
    With counter=3, half_life=30: interval = 30/(1+3) = 7.5 days
    With counter=9, half_life=30: interval = 30/(1+9) = 3 days

    Interval shrinks with counter, but never goes below 1 day (at least once per day).
    """
    if not config.enabled:
        return False

    interval_days = config.half_life_days / (1 + note.metadata.reinforcement_counter)
    interval_days = max(1.0, interval_days)  # At least once per day

    if not note.metadata.last_accessed:
        return True

    try:
        last_access = datetime.fromisoformat(note.metadata.last_accessed)
        age_days = (datetime.utcnow() - last_access).days
        return age_days >= interval_days
    except (ValueError, TypeError):
        return True


def spacing_interval_days(note: MemoryNote, config: SpacingConfig) -> float:
    """Return current spacing interval in days for this note."""
    interval = config.half_life_days / (1 + note.metadata.reinforcement_counter)
    return max(1.0, interval)


def _note_age_days(note: MemoryNote) -> float:
    """Compute note age in days from created_at."""
    try:
        created = datetime.fromisoformat(note.created_at)
        age = datetime.utcnow() - created
        return age.total_seconds() / 86400.0
    except (ValueError, TypeError):
        return 0.0


def decay_strength(base_strength: float, age_days: float, decay_rate: float) -> float:
    """
    Standalone decay function for use in batch tier recomputation.

    Ebbinghaus curve: S(t) = S0 × e^(-λt)
    """
    return base_strength * math.exp(-decay_rate * age_days)
