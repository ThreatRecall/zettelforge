"""
Note Constructor - LLM-powered note enrichment
A-MEM Agentic Memory Architecture V1.0

Causal Triple Extension (2026-04-06):
- Added LLM-based causal triple extraction from note content
- Stores causal edges (subject, relation, object) in KnowledgeGraph
- Relations: causes, enables, targets, uses, exploits, attributed_to
"""

import re
from datetime import datetime
from typing import ClassVar

from zettelforge.alias_resolver import AliasResolver
from zettelforge.json_parse import extract_json
from zettelforge.log import get_logger

_logger = get_logger("zettelforge.constructor")

from zettelforge.knowledge_graph import get_knowledge_graph
from zettelforge.note_schema import Content, Embedding, MemoryNote, Metadata, Semantic
from zettelforge.vector_memory import get_embedding


class NoteConstructor:
    """Construct enriched memory notes from raw content"""

    def extract_entities(self, text: str) -> dict[str, list[str]]:
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

    def _extract_keywords(self, text: str) -> list[str]:
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

    CAUSAL_RELATIONS: ClassVar[list[str]] = [
        "causes",
        "enables",
        "targets",
        "uses",
        "exploits",
        "attributed_to",
        "related_to",
    ]

    def extract_causal_triples(self, text: str, note_id: str = "") -> list[dict[str, str]]:
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

            # 8000 tokens for causal extraction — the highest cap in the
            # codebase. This prompt asks the model to enumerate every causal
            # relation in a passage, which triggers the longest reasoning
            # chains anywhere in the system. Empirical: qwen3.5:9b at
            # num_predict=4000 was *stochastically* sufficient (~70% success
            # rate), eval_count varied between 2.8k (success) and 4k+ (still
            # in <think> tags when budget exhausted). 8000 keeps the
            # success rate >95% on the same model. v2.5.2 CHANGELOG.
            output = generate(prompt, max_tokens=8000, temperature=0.1)

            parsed = extract_json(output, expect="array")
            if parsed is None:
                _logger.warning("parse_failed", schema="causal_triples", raw=(output or "")[:200])
                return []

            # Normalize to list of dicts (handle array-of-arrays or array-of-objects)
            triples = []
            for item in parsed:
                if isinstance(item, list) and len(item) >= 3:
                    # Array format: [subject, relation, object]
                    triples.append({"subject": item[0], "relation": item[1], "object": item[2]})
                elif isinstance(item, dict):
                    triples.append(item)

            # Validate relations against allowlist
            valid_relations = set(self.CAUSAL_RELATIONS)
            validated = []
            for triple in triples:
                relation = triple.get("relation", "").strip().lower()
                if relation not in valid_relations:
                    _logger.warning(
                        "invalid_causal_relation",
                        relation=relation,
                        triple=str(triple)[:100],
                    )
                    continue
                validated.append(triple)
            triples = validated

            # Add note_id to each triple
            for t in triples:
                t["note_id"] = note_id

            return triples

        except Exception as e:
            _logger.warning("causal_extraction_failed", error=str(e))
            return []

    def store_causal_edges(self, triples: list[dict], note_id: str = "", backend=None) -> int:
        """
        Store causal triples as edges in KnowledgeGraph.
        Returns number of edges added.

        Args:
            triples: List of causal triple dicts.
            note_id: Source note ID for provenance.
            backend: Optional StorageBackend; falls back to JSONL KG singleton.
        """
        if not triples:
            return 0

        resolver = AliasResolver()
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

                    # Resolve aliases before storing to prevent duplicate nodes
                    subject = resolver.resolve(from_type, subject)
                    obj = resolver.resolve(to_type, obj)

                    edge_props = {
                        "note_id": note_id,
                        "source": "llm_extraction",
                        "edge_type": "causal",
                    }

                    if backend is not None:
                        backend.add_kg_edge(
                            from_type=from_type,
                            from_value=subject,
                            to_type=to_type,
                            to_value=obj,
                            relationship=relation,
                            note_id=note_id,
                            properties=edge_props,
                        )
                    else:
                        kg = get_knowledge_graph()
                        kg.add_edge(
                            from_type=from_type,
                            from_value=subject,
                            to_type=to_type,
                            to_value=obj,
                            relationship=relation,
                            properties=edge_props,
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

        # STIX 2.1 intrusion sets: named adversary groups such as APT28,
        # UNC/TA/FIN clusters, and common group aliases.
        intrusion_set_patterns = [
            r"\bapt\d+\b",
            r"\bunc\d+\b",
            r"\bta\d+\b",
            r"\bfin\d+\b",
            "lazarus",
            "sandworm",
            "fancy bear",
            "cozy bear",
            "volt typhoon",
        ]
        if any(re.search(pat, entity_lower) for pat in intrusion_set_patterns):
            return "intrusion_set"

        # STIX 2.1 threat actors are individuals or loosely scoped actor
        # categories, not named intrusion sets.
        actor_patterns = [
            "north korea",
            "russian threat actor",
            "iranian threat actor",
            "chinese threat actor",
        ]
        if any(pat in entity_lower for pat in actor_patterns):
            return "threat_actor"

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
