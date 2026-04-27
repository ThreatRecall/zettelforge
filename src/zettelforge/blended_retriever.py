"""
Blended Retriever - Combines vector and graph retrieval results.

Merges results from VectorRetriever and GraphRetriever using
normalized score fusion (RRF-inspired). Notes found by both
sources get combined scores and rank higher.

v2.3.1: Replaced broken position-rank scoring with actual
similarity scores from VectorRetriever. Uses min-max normalization
per signal before weighted fusion.
"""

from collections.abc import Callable

from zettelforge.graph_retriever import ScoredResult
from zettelforge.note_schema import MemoryNote


def _normalize_scores(scored_list: list[tuple]) -> list[tuple]:
    """Min-max normalize scores to [0, 1] range.

    If all scores are equal or list is empty, returns uniform scores.
    """
    if not scored_list:
        return scored_list

    scores = [s for _, s in scored_list]
    min_s = min(scores)
    max_s = max(scores)

    if max_s - min_s < 1e-9:
        # All scores equal — give uniform 0.5
        return [(note, 0.5) for note, _ in scored_list]

    return [(note, (s - min_s) / (max_s - min_s)) for note, s in scored_list]


class BlendedRetriever:
    """Blend vector and graph retrieval results using normalized score fusion."""

    def blend(
        self,
        vector_results: list[tuple],  # List[Tuple[MemoryNote, float]] - actual similarity scores
        graph_results: list[ScoredResult],
        policy: dict[str, float],
        note_lookup: Callable[[str], MemoryNote | None],
        k: int = 10,
    ) -> list[MemoryNote]:
        """
        Blend vector and graph results with normalized score fusion.

        Scoring:
        1. Normalize vector scores to [0,1] via min-max
        2. Normalize graph scores to [0,1] via min-max
        3. Combine with policy weights
        4. Notes found by BOTH sources get additive score bonus
        5. Sort by combined score, return top-k
        """
        vector_weight = policy.get("vector", 0.5)
        graph_weight = policy.get("graph", 0.5)

        # Normalize vector scores
        norm_vector = _normalize_scores(vector_results)

        # Normalize graph scores
        graph_scored = [(gr.note_id, gr.score) for gr in graph_results]
        norm_graph = _normalize_scores(graph_scored)

        # Build combined score map: note_id -> (blended_score, MemoryNote)
        scores: dict[str, tuple] = {}

        # Vector signal
        for note, norm_score in norm_vector:
            blended = norm_score * vector_weight
            scores[note.id] = (blended, note)

        # Graph signal
        for note_id, norm_score in norm_graph:
            graph_score = norm_score * graph_weight
            if note_id in scores:
                # Found by BOTH — additive combination
                existing_score, existing_note = scores[note_id]
                scores[note_id] = (existing_score + graph_score, existing_note)
            else:
                note = note_lookup(note_id)
                if note:
                    scores[note_id] = (graph_score, note)

        ranked = sorted(scores.values(), key=lambda x: x[0], reverse=True)
        return [note for _, note in ranked[:k]]

    def blend_rrf(
        self,
        vector_results: list[tuple],  # List[Tuple[MemoryNote, float]]
        graph_results: list[ScoredResult],
        note_lookup: Callable[[str], MemoryNote | None],
        k: int = 10,
        rrf_k: int = 60,
    ) -> list[MemoryNote]:
        """
        Reciprocal Rank Fusion (RRF) — rank-based fusion that is robust
        to score scale differences.

        RRF score = sum(1 / (k + rank)) across all signals.
        This is the standard fusion method used in production retrieval
        systems (Elastic, Vespa, etc.).
        """
        scores: dict[str, tuple] = {}

        # Vector signal — rank by original similarity score
        sorted_vector = sorted(vector_results, key=lambda x: x[1], reverse=True)
        for rank, (note, _) in enumerate(sorted_vector, 1):
            rrf_score = 1.0 / (rrf_k + rank)
            scores[note.id] = (rrf_score, note)

        # Graph signal — already sorted by score
        for rank, gr in enumerate(graph_results, 1):
            rrf_score = 1.0 / (rrf_k + rank)
            if gr.note_id in scores:
                existing_score, existing_note = scores[gr.note_id]
                scores[gr.note_id] = (existing_score + rrf_score, existing_note)
            else:
                note = note_lookup(gr.note_id)
                if note:
                    scores[gr.note_id] = (rrf_score, note)

        ranked = sorted(scores.values(), key=lambda x: x[0], reverse=True)
        return [note for _, note in ranked[:k]]
