"""
Note Constructor - LLM-powered note enrichment
A-MEM Agentic Memory Architecture V1.0

Causal Triple Extension (2026-04-06):
- Added LLM-based causal triple extraction from note content
- Stores causal edges (subject, relation, object) in KnowledgeGraph
- Relations: causes, enables, targets, uses, exploits, attributed_to
"""

import json
import re
from datetime import datetime
from typing import Dict, List

from zettelforge.log import get_logger

_logger = get_logger("zettelforge.constructor")

from zettelforge.knowledge_graph import get_knowledge_graph
from zettelforge.note_schema import Content, Embedding, MemoryNote, Metadata, Semantic
from zettelforge.vector_memory import get_embedding


class NoteConstructor:
    """Construct enriched memory notes from raw content"""

    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """Extract entities from text using the shared EntityExtractor."""
        from zettelforge.entity_indexer import EntityExtractor

        extractor = EntityExtractor()
        return extractor.extract_all(text)

    def construct(
        self,
        raw_content: str,
        source_type: str = "conversation",
        source_ref: str = "",
        domain: str = "general",
    ) -> MemoryNote:
        """Construct a note from raw content with automatic enrichment."""

        # Extract entities
        entities = self.extract_entities(raw_content)
        all_entities = []
        for entity_list in entities.values():
            all_entities.extend(entity_list)

        # Build semantic enrichment (simplified - no LLM)
        context = self._generate_context(raw_content)
        keywords = self._extract_keywords(raw_content)
        tags = [domain] if domain else []

        # Generate embedding
        embedding_vector = get_embedding(raw_content[:1000])

        return MemoryNote(
            id="",  # Will be set by store
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            content=Content(raw=raw_content, source_type=source_type, source_ref=source_ref),
            semantic=Semantic(
                context=context, keywords=keywords[:7], tags=tags[:5], entities=all_entities
            ),
            embedding=Embedding(vector=embedding_vector, model="nomic-embed-text"),
            metadata=Metadata(domain=domain, tier="A"),
        )

    def _generate_context(self, text: str) -> str:
        """Generate one-sentence context summary."""
        # Simple extraction: first sentence or first 100 chars
        sentences = text.split(".")
        if sentences:
            context = sentences[0].strip()
            if len(context) > 150:
                context = context[:150] + "..."
            return context
        return text[:100]

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        # Simple keyword extraction
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
        # Filter common words
        stopwords = {"this", "that", "with", "from", "have", "been", "were", "they"}
        keywords = [w for w in words if w not in stopwords]
        # Return most common
        from collections import Counter

        return [word for word, count in Counter(keywords).most_common(10)]

    # ===== Causal Triple Extraction (MAGMA-style) =====

    CAUSAL_RELATIONS = [
        "causes",
        "enables",
        "targets",
        "uses",
        "exploits",
        "attributed_to",
        "related_to",
    ]

    def extract_causal_triples(self, text: str, note_id: str = "") -> List[Dict[str, str]]:
        """
        Use LLM to extract causal triples from text.  [Enterprise]
        Returns list of {subject, relation, object, note_id}

        Example: "APT28 uses DROPBEAR malware" -> {subject: "APT28", relation: "uses", object: "DROPBEAR"}
        """
        prompt = f"""Extract causal relationships from the following text as JSON.
Return a JSON array of triples with fields: subject, relation, object.
Relations must be one of: {", ".join(self.CAUSAL_RELATIONS)}

Text:
{text[:2000]}

JSON:"""

        try:
            from zettelforge.llm_client import generate

            output = generate(prompt, max_tokens=300, temperature=0.1)

            # Handle various response formats
            # 1. Markdown code blocks
            if output.startswith("```"):
                parts = output.split("```")
                for part in parts:
                    if part.strip().startswith("[") or part.strip().startswith("{"):
                        output = part.strip()
                        break

            # 2. Find JSON array in output
            import re

            json_match = re.search(r"\[.*\]", output, re.DOTALL)
            if json_match:
                output = json_match.group(0)

            parsed = json.loads(output)

            # Normalize to list of dicts (handle array-of-arrays or array-of-objects)
            triples = []
            for item in parsed:
                if isinstance(item, list) and len(item) >= 3:
                    # Array format: [subject, relation, object]
                    triples.append({"subject": item[0], "relation": item[1], "object": item[2]})
                elif isinstance(item, dict):
                    triples.append(item)

            # Add note_id to each triple
            for t in triples:
                t["note_id"] = note_id

            return triples

        except Exception as e:
            _logger.warning("causal_extraction_failed", error=str(e))
            return []

    def store_causal_edges(self, triples: List[Dict], note_id: str = "") -> int:
        """
        Store causal triples as edges in KnowledgeGraph.
        Returns number of edges added.
        """
        if not triples:
            return 0

        kg = get_knowledge_graph()
        edges_added = 0

        for triple in triples:
            subject = triple.get("subject", "").strip()
            relation = triple.get("relation", "").strip()
            obj = triple.get("object", "").strip()

            if subject and relation and obj:
                try:
                    # Map relation to entity types
                    from_type = self._infer_entity_type(subject)
                    to_type = self._infer_entity_type(obj)

                    kg.add_edge(
                        from_type=from_type,
                        from_value=subject,
                        to_type=to_type,
                        to_value=obj,
                        relationship=relation,
                        properties={"note_id": note_id, "source": "llm_extraction"},
                    )
                    edges_added += 1
                except Exception as e:
                    _logger.warning(
                        "edge_add_failed", subject=subject, relation=relation, obj=obj, error=str(e)
                    )

        return edges_added

    def _infer_entity_type(self, entity_value: str, entity_type_hint: str = "") -> str:
        """Infer entity type from entity value string.

        Args:
            entity_value: The entity text to classify.
            entity_type_hint: Optional type hint from LLM NER output.

        Returns:
            Entity type string.
        """
        entity_lower = entity_value.lower()

        # If LLM provided a type hint, trust it (already classified)
        type_hints = {
            "person",
            "location",
            "organization",
            "event",
            "activity",
            "temporal",
        }
        if entity_type_hint in type_hints:
            return entity_type_hint

        # CVE pattern
        if "cve-" in entity_lower or re.match(r"cve-\d{4}-\d+", entity_lower, re.I):
            return "cve"

        # Threat actor patterns
        actor_patterns = [
            "apt",
            "lazarus",
            "sandworm",
            "fancy bear",
            "cozy bear",
            "volt typhoon",
            "north korea",
        ]
        if any(pat in entity_lower for pat in actor_patterns):
            return "actor"

        # Tool patterns
        tool_patterns = [
            "cobalt strike",
            "metasploit",
            "mimikatz",
            "bloodhound",
            "dropbear",
            "empire",
        ]
        if any(pat in entity_lower for pat in tool_patterns):
            return "tool"

        # Campaign patterns
        if "operation" in entity_lower or "campaign" in entity_lower:
            return "campaign"

        # Default to 'entity'
        return "entity"
