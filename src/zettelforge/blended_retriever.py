"""
Blended Retriever - Combines vector and graph retrieval results.

Merges results from VectorRetriever and GraphRetriever using
intent-based policy weights, then applies salience + tier boosts
per RFC-008 Phase 3.

Notes found by both sources get combined scores and rank higher.
FROZEN notes (tier_multiplier=0) are excluded from results.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from zettelforge.graph_retriever import ScoredResult
from zettelforge.note_schema import MemoryNote

# Default weights when policy is absent or incomplete
DEFAULT_VECTOR_WEIGHT = 0.5
DEFAULT_GRAPH_WEIGHT = 0.5

# Salience boost: (score - 0.5) × weight
DEFAULT_SALIENCE_WEIGHT = 0.5

# Tier multipliers — frozen=0 excludes from retrieval
DEFAULT_TIER_MULTIPLIERS = {
    "hot": 1.0,
    "warm": 0.5,
    "cold": 0.1,
    "frozen": 0.0,
}


class BlendedRetriever:
    """Blend vector and graph retrieval results using policy weights."""

    def blend(
        self,
        vector_results: List[MemoryNote],
        graph_results: List[ScoredResult],
        policy: Dict[str, float],
        note_lookup: Callable[[str], Optional[MemoryNote]],
        k: int = 10,
        salience_scores: Dict[str, float] | None = None,
        tier_multipliers: Dict[str, float] | None = None,
        salience_weight: float = DEFAULT_SALIENCE_WEIGHT,
    ) -> List[MemoryNote]:
        """
        Blend and rank results from vector and graph retrieval.

        Applies RFC-008 Phase 3 scoring:
          final_score = base_score
                      × (1 + salience_boost)      # 0-boost for score=0.5, +50% for score=1.0
                      × tier_multiplier           # frozen=0 → excluded

        Args:
            vector_results: Notes from VectorRetriever
            graph_results: ScoredResults from GraphRetriever
            policy: Retrieval weights {vector: float, graph: float}
            note_lookup: Callable to fetch full note by id
            k: Maximum results to return
            salience_scores: {note_id: score} where score is 0.0–1.0
            tier_multipliers: {tier: multiplier}, default TIER_MULTIPLIERS
            salience_weight: Weight of salience boost (default 0.5)
        """
        vector_weight = policy.get("vector", DEFAULT_VECTOR_WEIGHT)
        graph_weight = policy.get("graph", DEFAULT_GRAPH_WEIGHT)
        if tier_multipliers is None:
            tier_multipliers = DEFAULT_TIER_MULTIPLIERS
        if salience_scores is None:
            salience_scores = {}

        scores: Dict[str, tuple] = {}

        for i, note in enumerate(vector_results):
            position_score = 1.0 / (1.0 + i)
            blended = position_score * vector_weight
            scores[note.id] = (blended, note)

        for gr in graph_results:
            graph_score = gr.score * graph_weight
            if gr.note_id in scores:
                existing_score, existing_note = scores[gr.note_id]
                scores[gr.note_id] = (existing_score + graph_score, existing_note)
            else:
                note = note_lookup(gr.note_id)
                if note:
                    scores[gr.note_id] = (graph_score, note)

        # Apply RFC-008 Phase 3 boosts and filter FROZEN notes
        final_scored: List[Tuple[float, MemoryNote]] = []
        for note_id, (base_score, note) in scores.items():
            # Tier multiplier — FROZEN notes excluded
            tier = note.metadata.memory_tier or "warm"
            tier_mult = tier_multipliers.get(tier, 0.5)
            if tier_mult == 0.0:
                continue  # Exclude frozen notes

            # Salience boost
            salience = salience_scores.get(note_id, 0.5)
            salience_boost = (salience - 0.5) * salience_weight

            final_score = base_score * (1.0 + salience_boost) * tier_mult
            final_scored.append((final_score, note))

        ranked = sorted(final_scored, key=lambda x: x[0], reverse=True)
        return [note for _, note in ranked[:k]]

    def blend_rrf(
        self,
        vector_results: List[MemoryNote],
        graph_results: List[ScoredResult],
        note_lookup: Callable[[str], Optional[MemoryNote]],
        k: int = 10,
        rrf_k: int = 60,
        salience_scores: Dict[str, float] | None = None,
        tier_multipliers: Dict[str, float] | None = None,
        salience_weight: float = DEFAULT_SALIENCE_WEIGHT,
    ) -> List[MemoryNote]:
        """
        Reciprocal Rank Fusion variant — robust when one source dominates.

        Uses RRF formula: score = sum(1 / (k + rank)) per source.
        Salience and tier boosts applied after fusion as in blend().
        """
        if tier_multipliers is None:
            tier_multipliers = DEFAULT_TIER_MULTIPLIERS
        if salience_scores is None:
            salience_scores = {}

        rrf_scores: Dict[str, float] = {}
        note_map: Dict[str, MemoryNote] = {}

        # Vector RRF
        for i, note in enumerate(vector_results):
            rrf = 1.0 / (rrf_k + i + 1)
            rrf_scores[note.id] = rrf_scores.get(note.id, 0.0) + rrf
            note_map[note.id] = note

        # Graph RRF
        ranked_graph = sorted(graph_results, key=lambda g: g.score, reverse=True)
        for i, gr in enumerate(ranked_graph):
            rrf = 1.0 / (rrf_k + i + 1)
            rrf_scores[gr.note_id] = rrf_scores.get(gr.note_id, 0.0) + rrf
            if gr.note_id not in note_map:
                note = note_lookup(gr.note_id)
                if note:
                    note_map[gr.note_id] = note

        # Apply boosts and filter FROZEN
        final_scored: List[Tuple[float, MemoryNote]] = []
        for note_id, rrf_score in rrf_scores.items():
            if note_id not in note_map:
                continue
            note = note_map[note_id]

            tier = note.metadata.memory_tier or "warm"
            tier_mult = tier_multipliers.get(tier, 0.5)
            if tier_mult == 0.0:
                continue

            salience = salience_scores.get(note_id, 0.5)
            salience_boost = (salience - 0.5) * salience_weight

            final_score = rrf_score * (1.0 + salience_boost) * tier_mult
            final_scored.append((final_score, note))

        ranked = sorted(final_scored, key=lambda x: x[0], reverse=True)
        return [note for _, note in ranked[:k]]
