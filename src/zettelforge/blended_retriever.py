"""
Blended Retriever - Combines vector and graph retrieval results.

Merges results from VectorRetriever and GraphRetriever using
intent-based policy weights. Notes found by both sources get
combined scores and rank higher.
"""

from typing import Callable, Dict, List, Optional

from zettelforge.graph_retriever import ScoredResult
from zettelforge.note_schema import MemoryNote


class BlendedRetriever:
    """Blend vector and graph retrieval results using policy weights."""

    def blend(
        self,
        vector_results: List[MemoryNote],
        graph_results: List[ScoredResult],
        policy: Dict[str, float],
        note_lookup: Callable[[str], Optional[MemoryNote]],
        k: int = 10,
    ) -> List[MemoryNote]:
        vector_weight = policy.get("vector", 0.5)
        graph_weight = policy.get("graph", 0.5)

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

        ranked = sorted(scores.values(), key=lambda x: x[0], reverse=True)
        return [note for _, note in ranked[:k]]
