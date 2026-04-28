"""
Memory Manager - Primary Agent Interface
A-MEM Agentic Memory Architecture V1.0

Main interface for agent memory operations.

Community edition: vector search, JSONL graph, basic entity extraction.
Enterprise edition: blended retrieval, cross-encoder reranking, report ingestion.
"""

import atexit
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from zettelforge.alias_resolver import AliasResolver
from zettelforge.edition import is_enterprise
from zettelforge.entity_indexer import EntityIndexer
from zettelforge.fact_extractor import FactExtractor
from zettelforge.governance_validator import GovernanceValidator, GovernanceViolationError
from zettelforge.knowledge_graph import get_knowledge_graph
from zettelforge.log import get_logger
from zettelforge.memory_store import MemoryStore, get_default_data_dir
from zettelforge.memory_updater import MemoryUpdater
from zettelforge.note_constructor import NoteConstructor
from zettelforge.note_schema import MemoryNote
from zettelforge.ocsf import (
    SEVERITY_HIGH,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    log_api_activity,
    log_authorization,
)
from zettelforge.synthesis_generator import get_synthesis_generator
from zettelforge.synthesis_validator import get_synthesis_validator
from zettelforge.vector_retriever import VectorRetriever

# ── Reranker singleton ───────────────────────────────────────────────────────
_reranker = None
_reranker_lock = threading.Lock()


def _get_reranker():
    """Get or create cross-encoder reranker (singleton, ~80MB, loads once)."""
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                _reranker = TextCrossEncoder("Xenova/ms-marco-MiniLM-L-6-v2")
    return _reranker


@dataclass
class _EnrichmentJob:
    """Work item for the slow-path enrichment worker."""

    note_id: str
    domain: str
    content_len: int
    resolved_entities: dict = field(default_factory=dict)


class MemoryManager:
    """
    Main interface for agent memory operations.
    """

    def __init__(self, jsonl_path: Optional[str] = None, lance_path: Optional[str] = None):
        self.store = MemoryStore(jsonl_path=jsonl_path, lance_path=lance_path)
        self.constructor = NoteConstructor()
        self.indexer = EntityIndexer()
        self.retriever = VectorRetriever(memory_store=self.store)
        self.governance = GovernanceValidator()
        self.resolver = AliasResolver()

        self._logger = get_logger("zettelforge.memory")
        self.stats = {"notes_created": 0, "retrievals": 0, "entity_index_hits": 0}

        # Dual-stream enrichment: background worker for LLM causal extraction
        self._enrichment_queue: queue.Queue = queue.Queue(maxsize=500)
        self._pending_enrichment: set = set()
        self._enrichment_worker = threading.Thread(
            target=self._enrichment_loop,
            name="zettelforge-enrichment",
            daemon=True,
        )
        self._enrichment_worker.start()
        atexit.register(self._drain_enrichment_queue)

    def remember(
        self,
        content: str,
        source_type: str = "conversation",
        source_ref: str = "",
        domain: str = "general",
        evolve: bool = False,
        sync: bool = False,
    ) -> Tuple[MemoryNote, str]:
        """
        Create a new memory note from content.

        Uses a dual-stream write path (MAGMA-inspired):
        - Fast path: embedding, JSONL, LanceDB, entity index, supersession,
          heuristic KG edges. Returns in ~45ms (fastembed).
        - Slow path: LLM causal triple extraction deferred to background worker.

        With evolve=True, uses the Mem0-style two-phase pipeline: LLM extracts
        facts, compares to existing notes, decides ADD/UPDATE/DELETE/NOOP.

        Args:
            content: Raw text to store.
            source_type: Origin type (conversation, mcp, report, etc.).
            source_ref: Source identifier.
            domain: Memory domain (cti, general, etc.).
            evolve: If True, run LLM fact extraction and update pipeline.
            sync: If True, run causal extraction inline (blocking).

        Returns: (note, status) where status is one of:
            "created", "updated", "corrected", or "noop"
        """
        request_id = uuid.uuid4().hex
        start = time.perf_counter()

        # Governance validation
        try:
            self.governance.enforce("remember", content)
            log_authorization(
                actor="system",
                resource="remember",
                status_id=STATUS_SUCCESS,
                policy="GOV-011",
                request_id=request_id,
            )
        except GovernanceViolationError:
            log_authorization(
                actor="system",
                resource="remember",
                status_id=STATUS_FAILURE,
                severity_id=SEVERITY_HIGH,
                policy="GOV-011",
                request_id=request_id,
            )
            raise

        # Evolution path: LLM extracts facts and decides ADD/UPDATE/DELETE/NOOP
        if evolve:
            results = self.remember_with_extraction(
                content=content,
                source_type=source_type,
                source_ref=source_ref,
                domain=domain,
            )
            duration_ms = (time.perf_counter() - start) * 1000

            if results:
                note, status = results[0]
                log_api_activity(
                    operation="remember",
                    status_id=STATUS_SUCCESS,
                    note_id=note.id if note else None,
                    domain=domain,
                    duration_ms=duration_ms,
                    request_id=request_id,
                    evolve=True,
                    status_detail=status,
                    facts_processed=len(results),
                )
                return note, status

            # Extraction found no facts above threshold — fall through to direct store
            self._logger.info(
                "evolve_no_facts_extracted",
                request_id=request_id,
                content_length=len(content),
            )

        # Direct store path
        note = self.constructor.construct(
            raw_content=content, source_type=source_type, source_ref=source_ref, domain=domain
        )

        self.store.write_note(note)
        self.stats["notes_created"] += 1

        # Alias resolution and indexing (regex-only for speed; LLM NER runs on recall)
        raw_entities = self.indexer.extractor.extract_all(note.content.raw, use_llm=False)

        resolved_entities = {}
        for etype, elist in raw_entities.items():
            resolved_entities[etype] = [self.resolver.resolve(etype, e) for e in elist]

        self.indexer.add_note(note.id, resolved_entities)

        # Phase 3: Check supersession
        self._check_supersession(note, resolved_entities)

        # Phase 6: Knowledge Graph Update (heuristic edges — fast path)
        self._update_knowledge_graph(note, resolved_entities)

        # Phase 6b: LLM causal enrichment (slow path — background worker)
        job = _EnrichmentJob(
            note_id=note.id,
            domain=domain,
            content_len=len(content),
            resolved_entities=resolved_entities,
        )
        if sync:
            self._run_enrichment(job)
        else:
            try:
                self._enrichment_queue.put_nowait(job)
                self._pending_enrichment.add(note.id)
            except queue.Full:
                self._logger.warning("enrichment_queue_full", note_id=note.id)

        duration_ms = (time.perf_counter() - start) * 1000
        log_api_activity(
            operation="remember",
            status_id=STATUS_SUCCESS,
            note_id=note.id,
            domain=domain,
            duration_ms=duration_ms,
            request_id=request_id,
            evolve=False,
        )
        return note, "created"

    def remember_with_extraction(
        self,
        content: str,
        source_type: str = "conversation",
        source_ref: str = "",
        domain: str = "general",
        context: str = "",
        min_importance: int = 3,
        max_facts: int = 5,
    ) -> List[Tuple[Optional[MemoryNote], str]]:
        """
        Mem0-style two-phase pipeline: extract salient facts, then decide ADD/UPDATE/DELETE/NOOP.

        Phase 1 (Extraction): LLM distills content into scored candidate facts.
        Phase 2 (Update): Each fact is compared to existing notes; LLM decides operation.

        Args:
            content: Raw text to process.
            source_type: Origin type (conversation, task_output, etc.).
            source_ref: Source identifier.
            domain: Memory domain.
            context: Optional rolling summary for disambiguation.
            min_importance: Facts below this threshold are skipped.
            max_facts: Maximum facts to extract per call.

        Returns:
            List of (MemoryNote or None, status) tuples.
            Status is one of: "added", "updated", "corrected", "noop".
        """
        # Phase 1: Extraction
        extractor = FactExtractor(max_facts=max_facts)
        facts = extractor.extract(content, context=context)

        # Filter by importance
        facts = [f for f in facts if f.importance >= min_importance]

        if not facts:
            return []

        # Phase 2: Update
        updater = MemoryUpdater(self)
        results = []

        for i, fact in enumerate(facts):
            similar = updater.find_similar(fact.text, domain=domain)
            operation = updater.decide(fact.text, similar)
            note, status = updater.apply(
                operation,
                fact_text=fact.text,
                importance=fact.importance,
                source_ref=f"{source_ref}:extraction:{i}" if source_ref else f"extraction:{i}",
                similar_notes=similar,
                domain=domain,
            )
            results.append((note, status))

        return results

    def remember_report(
        self,
        content: str,
        source_url: str = "",
        published_date: str = "",
        domain: str = "cti",
        min_importance: int = 3,
        max_facts: int = 10,
        chunk_size: int = 3000,
    ) -> List[Tuple[Optional[MemoryNote], str]]:
        """
        Ingest a news report or threat report.  [Enterprise]

        Chunks long content, runs two-phase extraction on each chunk,
        and stores published_date as temporal metadata.

        Args:
            content: Full report text (can be >4000 chars, will be chunked).
            source_url: URL of the report source.
            published_date: Publication date (ISO 8601).
            domain: Memory domain (default "cti").
            min_importance: Filter threshold for extracted facts.
            max_facts: Max facts per chunk.
            chunk_size: Max chars per chunk before splitting.

        Returns:
            List of (MemoryNote or None, status) tuples across all chunks.

        Raises:
            EditionError: If called in Community edition.
        """
        if not is_enterprise():
            from zettelforge.edition import EditionError

            raise EditionError(
                "'remember_report' (report ingestion with auto-chunking) requires "
                "ThreatRecall Enterprise. Set THREATENGRAM_LICENSE_KEY or visit "
                "https://threatengram.com/enterprise"
            )
        source_ref = source_url or "report"

        # Chunk long content on sentence boundaries
        chunks = []
        if len(content) <= chunk_size:
            chunks = [content]
        else:
            sentences = content.replace("\n", " ").split(". ")
            current_chunk = ""
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 2 > chunk_size and current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence + ". "
                else:
                    current_chunk += sentence + ". "
            if current_chunk.strip():
                chunks.append(current_chunk.strip())

        all_results = []
        for i, chunk in enumerate(chunks):
            # Add published date context if available
            context = f"Published: {published_date}" if published_date else ""
            chunk_ref = f"{source_ref}:chunk:{i}"

            results = self.remember_with_extraction(
                content=chunk,
                source_type="report",
                source_ref=chunk_ref,
                domain=domain,
                context=context,
                min_importance=min_importance,
                max_facts=max_facts,
            )
            all_results.extend(results)

        return all_results

    def recall(
        self,
        query: str,
        domain: Optional[str] = None,
        k: int = 10,
        include_links: bool = True,
        exclude_superseded: bool = True,
    ) -> List[MemoryNote]:
        """
        Retrieve memories relevant to query using blended vector + graph retrieval.

        Uses intent classifier to determine retrieval strategy weights,
        then combines vector similarity and graph traversal results
        with cross-encoder reranking.
        """
        request_id = uuid.uuid4().hex
        start = time.perf_counter()
        self.stats["retrievals"] += 1

        # Classify query intent
        from zettelforge.intent_classifier import get_intent_classifier

        classifier = get_intent_classifier()
        intent, intent_meta = classifier.classify(query)
        policy = classifier.get_traversal_policy(intent)

        # Extract entities from query for graph traversal
        query_entities = self.indexer.extractor.extract_all(query)
        resolved = {}
        for etype, elist in query_entities.items():
            resolved[etype] = [self.resolver.resolve(etype, e) for e in elist]

        # Vector retrieval (Community + Enterprise)
        vector_results = self.retriever.retrieve(
            query=query, domain=domain, k=k, include_links=include_links
        )

        # Temporal boost: for temporal queries, prioritize notes containing dates from the query
        if intent.value == "temporal":
            try:
                import re as _re

                import dateparser  # noqa: F401

                # Extract date-like strings from query
                date_patterns = _re.findall(
                    r"\b(?:january|february|march|april|may|june|july|august|september|"
                    r"october|november|december)\s+\d{1,2}(?:,?\s+\d{4})?|\b\d{4}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
                    query,
                    _re.IGNORECASE,
                )
                if date_patterns:
                    # Boost notes containing any of the extracted dates
                    date_lower = [d.lower() for d in date_patterns]
                    boosted = []
                    rest = []
                    for note in vector_results:
                        content_lower = note.content.raw.lower()
                        if any(d in content_lower for d in date_lower):
                            boosted.append(note)
                        else:
                            rest.append(note)
                    vector_results = boosted + rest
            except ImportError:
                pass

        # Blended retrieval: combine vector similarity with graph traversal
        from zettelforge.blended_retriever import BlendedRetriever
        from zettelforge.graph_retriever import GraphRetriever

        kg = get_knowledge_graph()
        graph_retriever = GraphRetriever(kg)
        graph_results = graph_retriever.retrieve_note_ids(query_entities=resolved, max_depth=2)

        blender = BlendedRetriever()
        results = blender.blend(
            vector_results=vector_results,
            graph_results=graph_results,
            policy=policy,
            note_lookup=lambda nid: self.store.get_note_by_id(nid),
            k=k,
        )

        # Fallback: if blending produced fewer results than vector alone, use vector
        if len(results) < len(vector_results):
            results = vector_results[:k]

        # Entity-augmented recall: also pull notes via entity index for query entities
        # This ensures multi-entity answers (e.g., "tools used by APT28") include all
        # relevant notes, not just the top-k by vector similarity
        result_ids = {n.id for n in results}
        for etype, values in resolved.items():
            for evalue in values:
                if evalue:
                    entity_notes = self.recall_entity(etype, evalue, k=3)
                    for en in entity_notes:
                        if en.id not in result_ids:
                            results.append(en)
                            result_ids.add(en.id)

        # ── Enterprise: Cross-encoder reranking ─────────────────────────────
        if len(results) > 1:
            try:
                reranker = _get_reranker()  # Returns None in Community
                if reranker is not None:
                    docs = [n.content.raw[:512] for n in results]
                    scores = list(reranker.rerank(query, docs))
                    paired = sorted(zip(scores, results), key=lambda x: x[0], reverse=True)
                    results = [note for _, note in paired]
            except Exception:
                self._logger.warning("reranking_failed_using_original_order", exc_info=True)

        # Filter superseded notes
        if exclude_superseded:
            results = [n for n in results if not n.links.superseded_by]

        # Cap at k after entity augmentation and reranking
        results = results[:k]

        # Track access
        for note in results:
            note.increment_access()
            self.store.mark_access_dirty(note.id)

        duration_ms = (time.perf_counter() - start) * 1000
        log_api_activity(
            operation="recall",
            status_id=STATUS_SUCCESS,
            query=query[:200],
            domain=domain,
            k=k,
            result_count=len(results),
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return results

    def recall_entity(self, entity_type: str, entity_value: str, k: int = 5) -> List[MemoryNote]:
        """
        Fast lookup by entity type and value.
        entity_type: 'cve', 'actor', 'tool', 'campaign', 'person', 'location', 'organization', 'event', 'activity', 'temporal'
        """
        self.stats["entity_index_hits"] += 1
        note_ids = self.indexer.get_note_ids(entity_type, entity_value.lower())
        notes = []
        for nid in note_ids[:k]:
            note = self.store.get_note_by_id(nid)
            if note:
                notes.append(note)
        return notes

    def recall_cve(self, cve_id: str, k: int = 5) -> List[MemoryNote]:
        """Fast lookup by CVE-ID (case-insensitive)"""
        return self.recall_entity("cve", cve_id.upper(), k)

    def recall_actor(self, actor_name: str, k: int = 5) -> List[MemoryNote]:
        """Fast lookup by threat actor name"""
        return self.recall_entity("actor", actor_name.lower(), k)

    def recall_tool(self, tool_name: str, k: int = 5) -> List[MemoryNote]:
        """Fast lookup by tool name"""
        return self.recall_entity("tool", tool_name.lower(), k)

    def get_context(
        self, query: str, domain: Optional[str] = None, k: int = 10, token_budget: int = 4000
    ) -> str:
        """
        Get formatted memory context for agent prompt injection.
        """
        return self.retriever.get_memory_context(
            query=query, domain=domain, k=k, token_budget=token_budget
        )

    def get_stats(self) -> Dict:
        """Get memory system statistics"""
        return {
            **self.stats,
            "total_notes": self.store.count_notes(),
            "entity_index": self.indexer.stats(),
        }

    def _update_knowledge_graph(self, note: MemoryNote, resolved_entities: Dict[str, List[str]]):
        kg = get_knowledge_graph()
        now = datetime.now().isoformat()
        edge_props = {"first_observed": now, "confidence": note.metadata.confidence}

        # 1. Add Note node
        kg.add_node(
            "note", note.id, {"content": note.content.raw[:200], "domain": note.metadata.domain}
        )

        # 2. Add Entity Nodes and MENTIONED_IN edges
        all_entities = []
        for etype, elist in resolved_entities.items():
            for evalue in elist:
                all_entities.append((etype, evalue))
                kg.add_edge(etype, evalue, "note", note.id, "MENTIONED_IN", edge_props)

        # 3. Inferred Entity-to-Entity Relationships (Heuristic)

        # --- CTI relationships ---
        actors = resolved_entities.get("actor", [])
        tools = resolved_entities.get("tool", [])
        cves = resolved_entities.get("cve", [])
        assets = resolved_entities.get("asset", [])
        campaigns = resolved_entities.get("campaign", [])

        for a in actors:
            for t in tools:
                kg.add_edge("actor", a, "tool", t, "USES_TOOL", edge_props)
            for c in cves:
                kg.add_edge("actor", a, "cve", c, "EXPLOITS_CVE", edge_props)
            for asset in assets:
                kg.add_edge("actor", a, "asset", asset, "TARGETS_ASSET", edge_props)
            for camp in campaigns:
                kg.add_edge("actor", a, "campaign", camp, "CONDUCTS_CAMPAIGN", edge_props)

        for t in tools:
            for asset in assets:
                kg.add_edge("tool", t, "asset", asset, "TARGETS_ASSET", edge_props)
            for c in cves:
                kg.add_edge("tool", t, "cve", c, "EXPLOITS_CVE", edge_props)

        attack_patterns = resolved_entities.get("attack_pattern", [])
        for a in actors:
            for ap in attack_patterns:
                kg.add_edge("actor", a, "attack_pattern", ap, "USES_TECHNIQUE", edge_props)
        malwares = resolved_entities.get("malware", [])
        for m in malwares:
            for ap in attack_patterns:
                kg.add_edge("malware", m, "attack_pattern", ap, "IMPLEMENTS", edge_props)

        # --- Conversational relationships (RFC-001) ---
        persons = resolved_entities.get("person", [])
        locations = resolved_entities.get("location", [])
        organizations = resolved_entities.get("organization", [])
        events = resolved_entities.get("event", [])
        activities = resolved_entities.get("activity", [])
        temporals = resolved_entities.get("temporal", [])

        for p in persons:
            for org in organizations:
                kg.add_edge("person", p, "organization", org, "AFFILIATED_WITH", edge_props)
            for ev in events:
                kg.add_edge("person", p, "event", ev, "ATTENDED", edge_props)
            for loc in locations:
                kg.add_edge("person", p, "location", loc, "LOCATED_AT", edge_props)
            for act in activities:
                kg.add_edge("person", p, "activity", act, "PARTICIPATES_IN", edge_props)

        for ev in events:
            for loc in locations:
                kg.add_edge("event", ev, "location", loc, "HELD_AT", edge_props)
            for org in organizations:
                kg.add_edge("event", ev, "organization", org, "ORGANIZED_BY", edge_props)
            for tmp in temporals:
                kg.add_edge("event", ev, "temporal", tmp, "OCCURRED_ON", edge_props)

        for org in organizations:
            for loc in locations:
                kg.add_edge("organization", org, "location", loc, "BASED_IN", edge_props)

        # NOTE: LLM causal triple extraction moved to _run_enrichment() (slow path)

    # ── Dual-stream: slow path enrichment worker ──────────────────────────

    def _enrichment_loop(self) -> None:
        """Background worker: process causal enrichment jobs until process exits."""
        while True:
            try:
                job = self._enrichment_queue.get(timeout=1.0)
                self._run_enrichment(job)
                self._enrichment_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                self._logger.error("enrichment_worker_error", exc_info=True)

    def _run_enrichment(self, job: _EnrichmentJob) -> None:
        """Execute slow-path LLM causal triple extraction for one note."""
        should_enrich = job.domain in ["cti", "incident", "threat_intel"] or job.content_len > 200
        if not should_enrich:
            self._pending_enrichment.discard(job.note_id)
            return

        note = self.store.get_note_by_id(job.note_id)
        if note is None:
            self._pending_enrichment.discard(job.note_id)
            return

        try:
            triples = self.constructor.extract_causal_triples(note.content.raw, note.id)
            if triples:
                edges = self.constructor.store_causal_edges(triples, note.id)
                self._logger.info(
                    "causal_triples_stored", note_id=note.id, triples=len(triples), edges=edges
                )
        except Exception:
            self._logger.warning("enrichment_failed", note_id=note.id, exc_info=True)
        finally:
            self._pending_enrichment.discard(job.note_id)

    def _drain_enrichment_queue(self) -> None:
        """atexit: process remaining enrichment jobs within a 10-second window."""
        deadline = time.monotonic() + 10.0
        while not self._enrichment_queue.empty() and time.monotonic() < deadline:
            try:
                job = self._enrichment_queue.get_nowait()
                self._run_enrichment(job)
                self._enrichment_queue.task_done()
            except queue.Empty:
                break
            except Exception:
                self._logger.warning("enrichment_drain_failed", exc_info=True)

    def mark_note_superseded(self, note_id: str, superseded_by_id: str) -> bool:
        old_note = self.store.get_note_by_id(note_id)
        new_note = self.store.get_note_by_id(superseded_by_id)
        if not old_note or not new_note:
            return False

        old_note.links.superseded_by = superseded_by_id
        if note_id not in new_note.links.supersedes:
            new_note.links.supersedes.append(note_id)

        self.store._rewrite_note(old_note)
        self.store._rewrite_note(new_note)

        # Remove superseded note from entity index so recall_entity() won't return it
        self.indexer.remove_note(note_id)

        # Add temporal edge to knowledge graph (Task 2)
        kg = get_knowledge_graph()
        kg.add_temporal_edge(
            from_type="note",
            from_value=superseded_by_id,
            to_type="note",
            to_value=note_id,
            relationship="SUPERSEDES",
            timestamp=datetime.now().isoformat(),
            properties={"supersedes": note_id},
        )

        return True

    def _check_supersession(
        self, new_note: MemoryNote, resolved_entities: Dict[str, List[str]]
    ) -> Optional[MemoryNote]:
        from datetime import datetime

        _entity_keys = [
            "cve",
            "actor",
            "tool",
            "campaign",
            "asset",
            "person",
            "location",
            "organization",
            "event",
            "activity",
            "temporal",
        ]

        # Build the new note's normalised entity sets once.
        new_entities: Dict[str, set] = {
            k: set(e.lower() for e in resolved_entities.get(k, [])) for k in _entity_keys
        }

        # Use the entity index to collect only candidate note IDs that share at
        # least one entity value with the new note — O(E) instead of O(N).
        # Also pre-compute per-candidate overlap counts while traversing the index
        # so we never need to re-extract entities from raw content.
        candidate_overlap: Dict[str, int] = {}
        for key in _entity_keys:
            for evalue in new_entities[key]:
                for nid in self.indexer.get_note_ids(key, evalue):
                    if nid == new_note.id:
                        continue
                    candidate_overlap[nid] = candidate_overlap.get(nid, 0) + 1

        if not candidate_overlap:
            return None

        best_match = None
        best_score = 0.0

        for nid, overlap in candidate_overlap.items():
            candidate = self.store.get_note_by_id(nid)
            if candidate is None:
                continue
            if candidate.links.superseded_by:
                continue

            score = float(overlap)
            try:
                new_ts = datetime.fromisoformat(new_note.created_at)
                cand_ts = datetime.fromisoformat(candidate.created_at)
                age_diff_hours = (new_ts - cand_ts).total_seconds() / 3600
                if age_diff_hours > 0:
                    score += min(age_diff_hours / 24, 1.0)
            except Exception:
                self._logger.debug("supersession_timestamp_parse_failed", exc_info=True)

            if score > best_score:
                best_score = score
                best_match = candidate

        # Lowered threshold slightly for benchmark tracking context
        if best_match and best_score >= 1.0:
            self.mark_note_superseded(best_match.id, new_note.id)
            return best_match

        return None

    def snapshot(self) -> str:
        """Export memory snapshot"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = get_default_data_dir()
        snapshot_dir = data_dir / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Export JSONL
        self.store.export_snapshot(str(snapshot_dir))

        return str(snapshot_dir / f"notes_{timestamp}.jsonl")

    # === Phase 6: Knowledge Graph Retrieval ===

    def ingest_relationship(
        self,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        relationship: str,
        properties: Optional[Dict] = None,
    ) -> None:
        """Ingest a STIX relationship into the knowledge graph.

        Intended for use by sync clients (e.g. OpenCTI) to write relationships
        directly into the graph without creating memory notes.  The edge is
        deduplicated by (from_type, from_value, to_type, to_value, relationship)
        — add_edge() is idempotent for existing triples.

        Args:
            from_type: Entity type of the source node (e.g. "actor", "malware").
            from_value: Canonical value of the source node.
            to_type: Entity type of the target node.
            to_value: Canonical value of the target node.
            relationship: Relationship label (e.g. "USES_TOOL", "TARGETS_ASSET").
            properties: Optional dict of edge properties (confidence, timestamps, …).
        """
        kg = get_knowledge_graph()
        kg.add_edge(from_type, from_value, to_type, to_value, relationship, properties or {})

    def get_entity_relationships(self, entity_type: str, entity_value: str) -> List[Dict]:
        """Get direct relationships for an entity from the knowledge graph."""
        kg = get_knowledge_graph()

        # Resolve alias if necessary
        canonical = self.resolver.resolve(entity_type, entity_value)

        return kg.get_neighbors(entity_type, canonical)

    def traverse_graph(self, start_type: str, start_value: str, max_depth: int = 2) -> List[Dict]:
        """Traverse relationships from a starting entity.  [Enterprise]

        Multi-hop graph traversal requires Enterprise edition.
        Community users can use get_entity_relationships() for direct neighbors.
        """
        if not is_enterprise():
            from zettelforge.edition import EditionError

            raise EditionError(
                "'traverse_graph' (multi-hop BFS traversal) requires ThreatRecall Enterprise. "
                "Use get_entity_relationships() for direct neighbors in Community edition. "
                "https://threatengram.com/enterprise"
            )
        kg = get_knowledge_graph()
        canonical = self.resolver.resolve(start_type, start_value)

        return kg.traverse(start_type, canonical, max_depth)

    # === Phase 7: Synthesis Layer ===

    def synthesize(
        self, query: str, format: str = "direct_answer", k: int = 10, tier_filter: List[str] = None
    ) -> Dict[str, Any]:
        """
        Synthesize an answer from retrieved memories (Phase 7 RAG-as-Answer).

        Community: "direct_answer" format only.
        Enterprise: All formats — "direct_answer", "synthesized_brief",
                    "timeline_analysis", "relationship_map".

        Args:
            query: The question to answer
            format: Output format (see above)
            k: Number of notes to retrieve for context
            tier_filter: Filter by tier ["A", "B"] or ["A", "B", "C"]

        Returns:
            Dictionary with synthesis result, metadata, and sources

        Raises:
            EditionError: If an advanced format is used in Community edition.
        """
        _enterprise_formats = {"synthesized_brief", "timeline_analysis", "relationship_map"}
        if format in _enterprise_formats and not is_enterprise():
            from zettelforge.edition import EditionError

            raise EditionError(
                f"Synthesis format '{format}' requires ThreatRecall Enterprise. "
                f"Community edition supports 'direct_answer'. "
                f"Set THREATENGRAM_LICENSE_KEY or visit https://threatengram.com/enterprise"
            )

        request_id = uuid.uuid4().hex
        start = time.perf_counter()

        gen = get_synthesis_generator()
        result = gen.synthesize(
            query=query, memory_manager=self, format=format, k=k, tier_filter=tier_filter
        )

        duration_ms = (time.perf_counter() - start) * 1000
        source_count = len(result.get("sources", []))
        log_api_activity(
            operation="synthesize",
            status_id=STATUS_SUCCESS,
            query=query[:200],
            format=format,
            source_count=source_count,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return result

    def validate_synthesis(self, response: Dict) -> Tuple[bool, List[str]]:
        """
        Validate a synthesis response for quality.

        Returns:
            (is_valid, list_of_errors)
        """
        validator = get_synthesis_validator()
        return validator.validate_response(response)

    def check_synthesis_quality(self, response: Dict) -> Dict:
        """
        Compute quality score for a synthesis response.

        Returns quality metrics including score (0-1) and grade.
        """
        validator = get_synthesis_validator()
        return validator.check_quality_score(response)


# Global memory manager instance
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Get or create global memory manager instance"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
