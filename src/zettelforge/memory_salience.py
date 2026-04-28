"""
Memory Salience Scoring — Von Restorff Effect

RFC-008 Phase 2: Salience boosts distinctive, high-signal memories in retrieval.

Key insight: distinctiveness (low avg similarity) × signal weight (threat_actor=1.0)
× isolation (singleton clusters) = memorable notes that surface first.

Reference: rfc/rfc-008-memory-salience-spacing-FULL-SPEC.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# CTI entity type priority — threat actors and malware always score high
ENTITY_TYPE_PRIORITY = {
    "threat_actor": 1.0,
    "malware": 0.9,
    "vulnerability": 0.85,
    "attack_pattern": 0.8,
    "infrastructure": 0.75,
    "tool": 0.7,
    "campaign": 0.65,
    "industry": 0.5,
    "geopolitical": 0.5,
    "generic": 0.3,
}


@dataclass
class SalienceConfig:
    """Configuration for Von Restorff salience scoring."""

    enabled: bool = True
    distinctiveness_weight: float = 0.4
    signal_weight: float = 0.4
    isolation_weight: float = 0.2
    recompute_interval_days: int = 7
    recompute_batch_size: int = 500


@dataclass
class SalienceScore:
    """Result of salience computation."""

    score: float  # 0.0–1.0
    distinctiveness: float  # raw component
    signal_weight: float  # raw component
    isolation: float  # raw component
    computed_at: str  # ISO 8601


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_distinctiveness(
    note_embedding: list[float], all_embeddings: list[list[float]]
) -> float:
    """
    How unique this note is relative to all others.

    Uses cosine similarity: low average similarity = high distinctiveness.
    Novel notes (rare IOCs, unique observations) score near 1.0.
    Common boilerplate notes score near 0.
    """
    if not all_embeddings or not note_embedding:
        return 0.5

    similarities = [
        cosine_similarity(note_embedding, emb)
        for emb in all_embeddings
        if emb is not None and len(emb) == len(note_embedding)
    ]

    if not similarities:
        return 0.5

    avg_similarity = sum(similarities) / len(similarities)
    # Low average similarity = highly distinctive
    return 1.0 - avg_similarity


def compute_signal_weight(
    entity_type: str,
    confidence: float = 0.5,
    analyst_flagged: bool = False,
) -> float:
    """
    Entity type priority × confidence × analyst flag.

    Threat actors and malware always score high. Analyst-flagged notes get +0.2.
    """
    base_priority = ENTITY_TYPE_PRIORITY.get(entity_type, 0.3)
    analyst_bonus = 1.2 if analyst_flagged else 1.0

    score = base_priority * confidence * analyst_bonus
    return min(1.0, score)


def compute_isolation(cluster_id: Optional[str], total_notes: int, cluster_size: int) -> float:
    """
    Cluster isolation: how unique this note's cluster is.

    Singleton clusters (cluster_size=1) score 1.0 (fully isolated).
    Large clusters score low (note is typical of many others).
    Notes with no cluster score 1.0 (unclustered = maximally distinctive).
    """
    if not cluster_id:
        return 1.0  # No cluster = fully isolated

    if total_notes <= 1:
        return 1.0

    # What fraction of other notes share this cluster?
    other_notes_in_cluster = cluster_size - 1  # exclude self
    other_notes_total = total_notes - 1

    isolation_ratio = 1.0 - (other_notes_in_cluster / max(1, other_notes_total))
    return max(0.0, min(1.0, isolation_ratio))


def compute_salience_score(
    note_embedding: list[float],
    all_embeddings: list[list[float]],
    entity_type: str,
    confidence: float = 0.5,
    analyst_flagged: bool = False,
    cluster_id: Optional[str] = None,
    cluster_size: int = 1,
    total_notes: int = 0,
    config: SalienceConfig | None = None,
) -> SalienceScore:
    """
    Compute Von Restorff salience score for a note.

    Combines three orthogonal signals:
      1. Distinctiveness: how semantically unique this note is across the corpus
      2. Signal weight: entity type priority (APT groups and malware score highest)
      3. Isolation: how isolated this note's cluster is from others

    Formula: score = (dw × distinctiveness) + (sw × signal_weight) + (iw × isolation)
    Weights default to 0.4/0.4/0.2 per Cognitive Science Purist preset.

    Args:
        note_embedding: 768-dim embedding vector
        all_embeddings: list of all note embeddings in corpus
        entity_type: CTI entity type (threat_actor, malware, etc.)
        confidence: evidence confidence 0–1
        analyst_flagged: manually flagged by analyst (+0.2 bonus)
        cluster_id: entity cluster ID (None if unclustered)
        cluster_size: how many notes in the same cluster
        total_notes: total notes in corpus (for isolation denominator)
        config: SalienceConfig with weight overrides

    Returns:
        SalienceScore with all components for debugging
    """
    if config is None:
        config = SalienceConfig()

    if not config.enabled:
        return SalienceScore(
            score=0.5,
            distinctiveness=0.5,
            signal_weight=0.5,
            isolation=0.5,
            computed_at=datetime.utcnow().isoformat(),
        )

    distinctiveness = compute_distinctiveness(note_embedding, all_embeddings)
    signal_weight = compute_signal_weight(entity_type, confidence, analyst_flagged)
    isolation = compute_isolation(cluster_id, total_notes, cluster_size)

    raw = (
        config.distinctiveness_weight * distinctiveness
        + config.signal_weight * signal_weight
        + config.isolation_weight * isolation
    )
    score = min(1.0, max(0.0, raw))

    return SalienceScore(
        score=score,
        distinctiveness=distinctiveness,
        signal_weight=signal_weight,
        isolation=isolation,
        computed_at=datetime.utcnow().isoformat(),
    )
