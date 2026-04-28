"""
Vector Retrieval - Memory Note Search
A-MEM Agentic Memory Architecture V1.0

Retrieves relevant notes based on embedding similarity with domain filtering.
"""

from typing import List, Optional

import numpy as np

from zettelforge.alias_resolver import AliasResolver
from zettelforge.entity_indexer import EntityExtractor
from zettelforge.log import get_logger
from zettelforge.memory_store import MemoryStore
from zettelforge.note_schema import MemoryNote
from zettelforge.vector_memory import get_embedding

_logger = get_logger("zettelforge.retriever")


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


class VectorRetriever:
    """Retrieve notes by embedding similarity with domain filtering"""

    def __init__(
        self,
        similarity_threshold: float = 0.15,  # Lowered from 0.25 - was too strict
        entity_boost: float = 2.5,
        exact_match_boost: float = 1.0,
        regenerate_invalid_embeddings: bool = True,  # NEW: Regenerate if missing/invalid
        memory_store: Optional[MemoryStore] = None,
    ):
        self.similarity_threshold = similarity_threshold
        self.entity_boost = entity_boost
        self.exact_match_boost = exact_match_boost
        self.regenerate_invalid_embeddings = regenerate_invalid_embeddings
        self.store = memory_store or MemoryStore()
        self.extractor = EntityExtractor()
        self.resolver = AliasResolver()

    def _is_valid_embedding(self, vector: Optional[List[float]]) -> bool:
        """Check if embedding vector is valid (non-None, correct dims, non-zero)."""
        if vector is None:
            return False
        if len(vector) != 768:
            return False
        # Check if all zeros or all identical (deterministic mock)
        if all(v == 0.0 for v in vector):
            return False
        # Check variance - real embeddings have variance
        var = np.var(vector)
        if var < 0.001:  # Suspiciously low variance
            return False
        return True

    def _ensure_note_embedding(self, note: MemoryNote) -> Optional[List[float]]:
        """Ensure note has valid embedding, regenerating if necessary."""
        if self._is_valid_embedding(note.embedding.vector):
            return note.embedding.vector

        if not self.regenerate_invalid_embeddings:
            return note.embedding.vector  # Return as-is even if invalid

        # Regenerate embedding from content
        try:
            new_vector = get_embedding(note.content.raw[:1000])
            if self._is_valid_embedding(new_vector):
                note.embedding.vector = new_vector
                return new_vector
        except Exception as e:
            _logger.warning("embedding_regeneration_failed", note_id=note.id, error=str(e))

        return note.embedding.vector

    def _get_candidates(self, domain: Optional[str] = None) -> List[MemoryNote]:
        """Get candidate notes, optionally filtered by domain."""
        all_notes = list(self.store.iterate_notes())
        if domain:
            return [n for n in all_notes if n.metadata.domain == domain]
        return all_notes

    def retrieve(
        self,
        query: str,
        domain: Optional[str] = None,
        k: int = 10,
        include_links: bool = True,
        use_lancedb: bool = True,  # NEW: Enable LanceDB vector search
    ) -> List[MemoryNote]:
        """
        Retrieve notes relevant to query using LanceDB vector search.
        Falls back to in-memory search if LanceDB unavailable.
        """
        # Try LanceDB first (IVF_FLAT index, no double-quantization)
        if use_lancedb and self.store.lancedb is not None:
            try:
                results = self._retrieve_via_lancedb(query, domain, k, include_links)
                if results:
                    return results
            except Exception:
                _logger.warning("lancedb_retrieval_failed_fallback_memory", exc_info=True)

        # Fallback: In-memory cosine similarity (always works)
        return self._retrieve_via_memory(query, domain, k, include_links)

    def _retrieve_via_lancedb(
        self, query: str, domain: Optional[str], k: int, include_links: bool
    ) -> List[MemoryNote]:
        """Retrieve using LanceDB vector similarity search."""

        query_vector = get_embedding(query)

        # Get all domain tables to search
        if domain:
            table_names = [f"notes_{domain}"]
        else:
            # Search all domain tables - handle lancedb API variations
            result = self.store.lancedb.list_tables()
            if hasattr(result, "tables"):
                all_tables = result.tables
            elif isinstance(result, dict):
                all_tables = result.get("tables", [])
            elif hasattr(result, "__iter__"):
                all_tables = []
                for item in result:
                    if isinstance(item, tuple) and item[0] == "tables":
                        all_tables = item[1]
                        break
            else:
                all_tables = []
            table_names = [t for t in all_tables if t.startswith("notes_")]

        all_results = []

        for table_name in table_names:
            try:
                table = self.store.lancedb.open_table(table_name)

                # Perform vector search using correct LanceDB API
                search_results = table.search(query_vector).limit(k * 2).to_list()

                # Convert to MemoryNote objects
                for row in search_results:
                    note_id = row.get("id")
                    # Get full note from JSONL for complete data
                    note = self.store.get_note_by_id(note_id)
                    if note:
                        score = row.get("_distance", 0)
                        # Convert distance to similarity (LanceDB returns distance, lower is better)
                        # For cosine: similarity = 1 - distance
                        all_results.append((note, 1.0 - score))

            except Exception as e:
                _logger.error(
                    "lancedb_search_failed", table_name=table_name, error=str(e), exc_info=True
                )
                continue

        # Sort by similarity score (higher is better)
        all_results.sort(key=lambda x: x[1], reverse=True)
        results = [note for note, score in all_results[:k]]

        # Apply entity boost post-retrieval
        results = self._apply_entity_boost(results, query)

        if include_links and results:
            results = self._expand_via_links(results, k * 2)

        for note in results:
            note.increment_access()

        return results

    def _apply_entity_boost(self, results: List[MemoryNote], query: str) -> List[MemoryNote]:
        """Apply entity boost to retrieved results."""
        raw_query_entities = self.extractor.extract_all(query)
        query_entities = set()
        for etype, elist in raw_query_entities.items():
            for e in elist:
                query_entities.add(self.resolver.resolve(etype, e))

        if not query_entities:
            return results

        # Re-sort with entity boost
        boosted = []
        for note in results:
            note_entities = set(note.semantic.entities)
            overlap = len(query_entities & note_entities)
            boost = self.entity_boost**overlap if overlap > 0 else 1.0

            # Exact match boost
            for qe in query_entities:
                if qe.lower() in note.content.raw.lower():
                    boost *= self.exact_match_boost

            boosted.append((note, boost))

        boosted.sort(key=lambda x: x[1], reverse=True)
        return [note for note, _ in boosted]

    def _retrieve_via_memory(
        self, query: str, domain: Optional[str], k: int, include_links: bool
    ) -> List[MemoryNote]:
        """Fallback: In-memory cosine similarity (original implementation)."""
        query_vector = get_embedding(query)
        candidates = self._get_candidates(domain)

        if not candidates:
            return []

        # Extract query entities
        raw_query_entities = self.extractor.extract_all(query)
        query_entities = set()
        for etype, elist in raw_query_entities.items():
            for e in elist:
                query_entities.add(self.resolver.resolve(etype, e))

        scored = []
        invalid_embeddings = 0
        for note in candidates:
            # Ensure valid embedding before comparison
            note_vector = self._ensure_note_embedding(note)

            if not self._is_valid_embedding(note_vector):
                invalid_embeddings += 1
                continue

            sim = cosine_similarity(query_vector, note_vector)

            # Apply Entity Boost
            note_entities = set(note.semantic.entities)
            if query_entities:
                overlap = len(query_entities & note_entities)
                if overlap > 0:
                    sim *= self.entity_boost**overlap

                # Apply Exact Match Boost (e.g. for CVE IDs)
                for qe in query_entities:
                    if qe.lower() in note.content.raw.lower():
                        sim *= self.exact_match_boost

            if sim >= self.similarity_threshold:
                scored.append((note, sim))

        # Log debug info
        if invalid_embeddings > 0:
            _logger.warning("invalid_embeddings_skipped", count=invalid_embeddings)

        scored.sort(key=lambda x: x[1], reverse=True)
        results = [note for note, sim in scored[:k]]

        if include_links and results:
            results = self._expand_via_links(results, k * 2)

        for note in results:
            note.increment_access()

        return results

    def _expand_via_links(
        self, initial_results: List[MemoryNote], max_results: int
    ) -> List[MemoryNote]:
        """Expand results by including directly linked notes"""
        all_ids = set(n.id for n in initial_results)
        expanded = list(initial_results)

        for note in initial_results:
            for linked_id in note.links.related:
                if len(expanded) >= max_results:
                    break
                linked_note = self.store.get_note_by_id(linked_id)
                if linked_note and linked_note.id not in all_ids:
                    expanded.append(linked_note)
                    all_ids.add(linked_note.id)

        return expanded[:max_results]

    def get_memory_context(
        self, query: str, domain: Optional[str] = None, k: int = 10, token_budget: int = 4000
    ) -> str:
        """
        Format retrieved notes for injection into agent prompt.
        """
        notes = self.retrieve(query=query, domain=domain, k=k)

        if not notes:
            return "No relevant memories found."

        context_parts = [f"## Relevant Memories ({len(notes)} notes)\n"]

        for i, note in enumerate(notes, 1):
            confidence = note.metadata.confidence
            recency = note.created_at[:10]

            context_parts.append(f"\n### [{i}] {note.id} (confidence: {confidence:.2f}, {recency})")
            context_parts.append(f"Context: {note.semantic.context}")
            context_parts.append(f"Content: {note.content.raw[:300]}...")

            if note.links.related:
                context_parts.append(f"Related: {', '.join(note.links.related)}")

        context = "\n".join(context_parts)
        if len(context) > token_budget * 4:
            context = context[: token_budget * 4] + "\n\n[truncated...]"

        return context
