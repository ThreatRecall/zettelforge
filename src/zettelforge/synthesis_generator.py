"""
Synthesis Generator — Phase 7 RAG-as-Answer Synthesis Layer
A-MEM Agentic Memory Architecture V1.0

Implements LLM-based answer synthesis using retrieved notes.
Supports multiple response formats: direct_answer, synthesized_brief, timeline_analysis, relationship_map.
"""

import hashlib
import json
import threading
import time
from typing import Dict, List, Optional


class SynthesisGenerator:
    """
    LLM-based answer synthesis with multiple output formats.
    Uses vector retrieval for comprehensive context.
    """

    def __init__(
        self,
        llm_model: str = "qwen2.5:3b",
        max_context_tokens: int = 3000,
        confidence_threshold: float = 0.4,
    ):
        self.llm_model = llm_model
        self.max_context_tokens = max_context_tokens
        self.confidence_threshold = confidence_threshold
        self._llm_client = None
        self._lock = threading.RLock()

    def _get_llm_client(self):
        """Get or create LLM client (kept for backward compat, not used for generation)."""
        return None

    def synthesize(
        self,
        query: str,
        memory_manager=None,
        format: str = "direct_answer",
        k: int = 10,
        tier_filter: List[str] = None,
    ) -> Dict:
        """
        Synthesize an answer from retrieved notes.

        Args:
            query: User query to answer
            memory_manager: MemoryManager instance
            format: Response format (direct_answer, synthesized_brief, timeline_analysis, relationship_map)
            k: Number of notes to retrieve
            tier_filter: Tier filter (A, B, C) - defaults to ["A", "B"]

        Returns:
            Synthesis result dictionary with answer, sources, metadata
        """
        start_time = time.time()
        tier_filter = tier_filter or ["A", "B", "C"]  # Include all tiers by default

        # Retrieve notes
        notes = self._retrieve_notes(query, memory_manager, k, tier_filter)

        # Build context
        context = self._build_context(notes)

        # Generate synthesis
        synthesis = self._generate_synthesis(query, context, format)

        # Calculate metrics
        latency_ms = int((time.time() - start_time) * 1000)
        tokens_used = self._estimate_tokens(context)

        return {
            "query": query,
            "format": format,
            "synthesis": synthesis,
            "metadata": {
                "query_id": hashlib.md5(query.encode()).hexdigest()[:12],
                "model_used": self.llm_model,
                "tokens_used": tokens_used,
                "latency_ms": latency_ms,
                "confidence_threshold": self.confidence_threshold,
                "sources_count": len(notes),
                "tier_filter": tier_filter,
            },
            "sources": [self._note_to_source(n) for n in notes[:10]],
        }

    def _retrieve_notes(self, query: str, memory_manager, k: int, tier_filter: List[str]):
        """Retrieve notes via hybrid search (entity + vector)."""
        if memory_manager is None:
            return []

        notes = []

        # First: Try entity-based recall (this path WORKS)
        from zettelforge.entity_indexer import EntityExtractor

        extractor = EntityExtractor()
        entities = extractor.extract_all(query)

        for etype, elist in entities.items():
            for evalue in elist:
                entity_notes = memory_manager.recall_entity(etype, evalue, k=5)
                notes.extend(entity_notes)

        # Second: Fall back to vector recall for semantic similarity
        if len(notes) < k:
            vector_results = memory_manager.recall(query, k=k * 2)
            notes.extend(vector_results)

        # Deduplicate and filter by tier
        seen_ids = set()
        unique_notes = []
        for n in notes:
            if n.id not in seen_ids and n.metadata.tier in tier_filter:
                seen_ids.add(n.id)
                unique_notes.append(n)

        return unique_notes[:k]

    def _build_context(self, notes: List) -> str:
        """Build context string for LLM."""
        context_parts = []
        for note in notes[:10]:
            context_parts.append(f"\n--- NOTE: {note.id} (Tier {note.metadata.tier}) ---")
            context_parts.append(f"Content: {note.content.raw[:500]}...")
            if note.semantic.context:
                context_parts.append(f"Summary: {note.semantic.context}")
        return "\n".join(context_parts)

    def _generate_synthesis(self, query: str, context: str, format: str) -> Dict:
        """Generate synthesis using LLM."""
        system_prompt = self._get_system_prompt(format)
        user_prompt = self._build_prompt(query, context, format)
        full_prompt = f"{system_prompt}\n\n{user_prompt}\n\nRespond with valid JSON only."

        try:
            from zettelforge.llm_client import generate

            raw = generate(full_prompt, max_tokens=800, temperature=0.1, system=system_prompt)
            return json.loads(raw)
        except (json.JSONDecodeError, Exception):
            return self._fallback_synthesis(query, format)

        return self._fallback_synthesis(query, format)

    def _get_system_prompt(self, format: str) -> str:
        prompts = {
            "direct_answer": "Provide a concise, factual answer based on context. Include confidence and cite sources.",
            "synthesized_brief": "Create a comprehensive brief summarizing key themes and evidence.",
            "timeline_analysis": "Build a chronological timeline of events from context.",
            "relationship_map": "Map relationships between entities from context.",
        }
        return prompts.get(format, prompts["direct_answer"])

    def _get_json_format(self, format: str) -> Dict:
        formats = {
            "direct_answer": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "confidence": {"type": "number"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["answer", "confidence", "sources"],
            },
            "synthesized_brief": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "themes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                        },
                    },
                    "confidence": {"type": "number"},
                },
                "required": ["summary", "themes", "confidence"],
            },
            "timeline_analysis": {
                "type": "object",
                "properties": {
                    "timeline": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"date": {"type": "string"}, "event": {"type": "string"}},
                        },
                    },
                    "confidence": {"type": "number"},
                },
                "required": ["timeline", "confidence"],
            },
            "relationship_map": {
                "type": "object",
                "properties": {
                    "entities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "type": {"type": "string"}},
                        },
                    },
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "type": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["entities", "relationships"],
            },
        }
        return formats.get(format, formats["direct_answer"])

    def _build_prompt(self, query: str, context: str, format: str) -> str:
        return f"""Analyze the following context and provide a {format.replace("_", " ")}.

QUERY:
{query}

CONTEXT:
{context}

Format as valid JSON matching the specified schema."""

    def _fallback_synthesis(self, query: str, format: str) -> Dict:
        if format == "direct_answer":
            return {
                "answer": f"No specific answer found for: {query[:50]}...",
                "confidence": 0.0,
                "sources": [],
            }
        elif format == "synthesized_brief":
            return {
                "summary": f"No brief available for: {query[:50]}...",
                "themes": [],
                "confidence": 0.0,
            }
        else:
            return {"error": "No data available"}

    def _note_to_source(self, note) -> Dict:
        return {
            "note_id": note.id,
            "relevance_score": min(1.0, note.metadata.confidence),
            "quote": note.content.raw[:200] if note.content.raw else "",
            "tier": note.metadata.tier,
        }

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4


_synthesis_gen: Optional[SynthesisGenerator] = None
_synthesis_lock = threading.Lock()


def get_synthesis_generator() -> SynthesisGenerator:
    global _synthesis_gen
    if _synthesis_gen is None:
        with _synthesis_lock:
            if _synthesis_gen is None:
                _synthesis_gen = SynthesisGenerator()
    return _synthesis_gen
