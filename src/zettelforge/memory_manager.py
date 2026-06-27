"""
Memory Manager - Primary Agent Interface
A-MEM Agentic Memory Architecture V1.0

Main interface for agent memory operations.

Core: vector search, JSONL graph, entity extraction, blended retrieval.
With zettelforge-enterprise: TypeDB backend, deeper traversal, extended synthesis.
"""

import atexit
import concurrent.futures
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

from zettelforge.alias_resolver import AliasResolver
from zettelforge.backend_factory import get_storage_backend
from zettelforge.config import get_config
from zettelforge.consolidation import ConsolidationMiddleware
from zettelforge.enrichment_ledger import EnrichmentJobRecord
from zettelforge.entity_indexer import EntityIndexer
from zettelforge.extensions import has_extension
from zettelforge.fact_extractor import FactExtractor
from zettelforge.governance_validator import GovernanceValidator, GovernanceViolationError
from zettelforge.log import get_logger
from zettelforge.memory_defense import MemoryAnomalyError, MemoryAnomalyGate
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
from zettelforge.prompt_injection_guard import assert_no_prompt_injection
from zettelforge.storage_backend import BackendClosedError
from zettelforge.synthesis_generator import get_synthesis_generator
from zettelforge.synthesis_validator import get_synthesis_validator
from zettelforge.telemetry import get_telemetry
from zettelforge.vector_memory import preload_embedding_model
from zettelforge.vector_retriever import VectorRetriever

# ── Reranker singletons (one per configured model) ──────────────────────────
_rerankers: dict[str, object] = {}
_reranker_lock = threading.Lock()


def _has_valid_memory_defense_vector(note: Any) -> bool:
    embedding = getattr(note, "embedding", None)
    vector = getattr(embedding, "vector", None)
    if not isinstance(vector, list) or not vector:
        return False
    try:
        return any(float(value) != 0.0 for value in vector)
    except (TypeError, ValueError):
        return False


def _get_reranker():
    """Get or create the configured cross-encoder reranker (loads once per model)."""
    retrieval_cfg = get_config().retrieval
    model = retrieval_cfg.rerank_model
    reranker = _rerankers.get(model)
    if reranker is None:
        with _reranker_lock:
            reranker = _rerankers.get(model)
            if reranker is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                threads = retrieval_cfg.rerank_threads or None
                reranker = TextCrossEncoder(model, threads=threads)
                _rerankers[model] = reranker
    return reranker


@dataclass
class _EnrichmentJob:
    """Work item for the slow-path enrichment worker."""

    note_id: str
    domain: str
    content_len: int
    resolved_entities: dict = field(default_factory=dict)
    job_type: str = "causal_extraction"  # or "neighbor_evolution" or "llm_ner"
    defer: bool = False  # If True, skip processing (used for batch-defer in remember_report)
    job_id: str = field(default_factory=lambda: f"enrich_{uuid.uuid4().hex}")
    ledger_error_code: str = ""


class MemoryManager:
    """
    Main interface for agent memory operations.
    """

    def __init__(self, jsonl_path: str | None = None, lance_path: str | None = None):
        # Derive data_dir from jsonl_path if provided (tests pass custom paths)
        _data_dir = None
        if jsonl_path:
            from pathlib import Path

            _data_dir = str(Path(jsonl_path).parent)

        # Primary storage: SQLite backend for notes, KG, and entities
        self.store = get_storage_backend(data_dir=_data_dir)
        self.store.initialize()

        # Backward-compat alias: callers (evolver, updater, consolidation) use
        # store._rewrite_note() -- delegate to the public rewrite_note() method.
        if not hasattr(self.store, "_rewrite_note"):
            self.store._rewrite_note = self.store.rewrite_note

        # LanceDB access: keep a MemoryStore for vector indexing only
        self._lance_store = MemoryStore(jsonl_path=jsonl_path, lance_path=lance_path)

        # [RFC-009 Phase 0.5 / task #39] Force fastembed to load now so the
        # first remember() doesn't pay the ~800ms model-load cost in its
        # construct phase. Best-effort: failures are swallowed by preload.
        preload_embedding_model()

        # Legacy EntityIndexer kept for extractor, stats(), and build() compatibility
        self.indexer = EntityIndexer()

        self.constructor = NoteConstructor()
        self.retriever = VectorRetriever(
            memory_store=self._lance_store,
            note_lookup=lambda nid: self.store.get_note_by_id(nid),
        )
        self.governance = GovernanceValidator(
            pii_config=get_config().governance.pii,
            limits_config=get_config().governance.limits,
        )
        self.resolver = AliasResolver()
        self.consolidation = ConsolidationMiddleware(self)
        self.memory_defense = MemoryAnomalyGate()

        self._logger = get_logger("zettelforge.memory")
        self.stats = {
            "notes_created": 0,
            "retrievals": 0,
            "entity_index_hits": 0,
            "consolidations_triggered": 0,
            # LLM NER observability (RFC-001 amendment)
            "llm_ner_success": 0,
            "llm_ner_failure": 0,
            "llm_ner_no_new": 0,
            "llm_ner_total_new_entities": 0,
            "llm_ner_total_duration_ms": 0.0,
        }

        # Operational telemetry (RFC-007 / US-002)
        self._telemetry = get_telemetry()
        # Correlation slot — recall stores its query_id/results here so
        # synthesize() can attach synthesis telemetry to the same query_id.
        self._telemetry_query_id: str | None = None
        self._telemetry_retrieved_notes: list | None = None

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
        atexit.register(self.store.close)

    def remember(
        self,
        content: str,
        source_type: str = "conversation",
        source_ref: str = "",
        domain: str = "general",
        evolve: bool = False,
        sync: bool = False,
    ) -> tuple[MemoryNote, str]:
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

        # Bind request_id to structlog context so every downstream log line
        # (fact extraction, entity indexing, evolution, LLM calls, KG writes)
        # carries this trace_id automatically. Cleared at function exit so it
        # doesn't leak across sequential remember() calls.
        structlog.contextvars.bind_contextvars(
            trace_id=request_id,
            domain=domain,
            source_type=source_type,
        )

        try:
            return self._remember_inner(
                content=content,
                source_type=source_type,
                source_ref=source_ref,
                domain=domain,
                evolve=evolve,
                sync=sync,
                request_id=request_id,
                start=start,
            )
        finally:
            structlog.contextvars.unbind_contextvars("trace_id", "domain", "source_type")

    def _remember_inner(
        self,
        content: str,
        source_type: str,
        source_ref: str,
        domain: str,
        evolve: bool,
        sync: bool,
        request_id: str,
        start: float,
    ) -> tuple[MemoryNote, str]:
        """Inner body of remember(); split out so trace_id binding can wrap it."""
        # Governance validation (may return redacted content when PII is enabled)
        try:
            content = self.governance.enforce("remember", content)
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
        # [RFC-009 Phase 0.5] Per-phase timings to attribute remember() latency.
        # Emitted in ocsf_api_activity.phase_timings_ms so the RFC-007 aggregator
        # can bucket them without schema changes.
        phase_timings_ms: dict[str, float] = {}

        _p = time.perf_counter()
        note = self.constructor.construct(
            raw_content=content, source_type=source_type, source_ref=source_ref, domain=domain
        )
        phase_timings_ms["construct"] = (time.perf_counter() - _p) * 1000

        _p = time.perf_counter()
        try:
            # Bounded reference window with sparse-vector backfill: the gate
            # keeps max_reference_notes valid-vector notes, so start bounded
            # and grow only when invalid recent notes would underfill it.
            _defense_cfg = get_config().governance.memory_defense
            reference_notes = self._memory_defense_reference_notes(
                domain,
                max_reference_notes=_defense_cfg.max_reference_notes,
                min_calibration_notes=_defense_cfg.min_calibration_notes,
            )
            self.memory_defense.enforce(
                note,
                reference_notes,
                domain=domain,
                source_type=source_type,
                source_ref=source_ref,
                request_id=request_id,
            )
        except MemoryAnomalyError as exc:
            phase_timings_ms["memory_defense"] = (time.perf_counter() - _p) * 1000
            decision = exc.decision
            log_authorization(
                actor="system",
                resource="remember",
                status_id=STATUS_FAILURE,
                severity_id=SEVERITY_HIGH,
                policy="SEC-011",
                request_id=request_id,
                violation="memory_anomaly",
                action=decision.action,
                score=decision.score,
                threshold=decision.threshold,
                content_hash=decision.content_hash,
            )
            log_api_activity(
                operation="remember",
                status_id=STATUS_FAILURE,
                severity_id=SEVERITY_HIGH,
                note_id=note.id,
                domain=domain,
                duration_ms=(time.perf_counter() - start) * 1000,
                request_id=request_id,
                memory_defense_action=decision.action,
                memory_defense_score=decision.score,
                memory_defense_threshold=decision.threshold,
                memory_defense_content_hash=decision.content_hash,
                phase_timings_ms=phase_timings_ms,
            )
            raise
        except Exception:
            self._logger.warning("memory_defense_eval_failed", request_id=request_id, exc_info=True)
        phase_timings_ms["memory_defense"] = (time.perf_counter() - _p) * 1000

        _p = time.perf_counter()
        self.store.write_note(note)
        phase_timings_ms["write_note"] = (time.perf_counter() - _p) * 1000
        self.stats["notes_created"] += 1

        # Keep LanceDB in sync for vector retrieval
        if self._lance_store.lancedb is not None:
            _p = time.perf_counter()
            try:
                self._lance_store._index_in_lance(note)
            except Exception:
                self._logger.warning("lance_index_sync_failed", note_id=note.id, exc_info=True)
            phase_timings_ms["lance_index"] = (time.perf_counter() - _p) * 1000

        # Alias resolution and indexing (regex-only for speed; LLM NER runs on recall)
        _p = time.perf_counter()
        raw_entities = self.indexer.extractor.extract_all(note.content.raw, use_llm=False)

        resolved_entities = {}
        for etype, elist in raw_entities.items():
            resolved_entities[etype] = [self.resolver.resolve(etype, e) for e in elist]

        self.indexer.add_note(note.id, resolved_entities)

        # Write entity mappings to SQLite backend
        for etype, elist in resolved_entities.items():
            for evalue in elist:
                self.store.add_entity_mapping(etype, evalue, note.id)
        phase_timings_ms["entity_index"] = (time.perf_counter() - _p) * 1000

        # GAM consolidation: observe note for semantic shift detection
        _p = time.perf_counter()
        try:
            is_shift, shift_meta = self.consolidation.before_write(
                note_entities=resolved_entities,
                note_domain=domain,
            )
            if is_shift:
                self.stats["consolidations_triggered"] += 1
                self._logger.info(
                    "semantic_shift_detected",
                    note_id=note.id,
                    signals=shift_meta.get("shift_signals", []),
                    epg_count=shift_meta.get("epg_count", 0),
                )
        except Exception as e:
            self._logger.warning("consolidation_observe_failed", error=str(e))
        phase_timings_ms["consolidation_observe"] = (time.perf_counter() - _p) * 1000

        # Phase 3: Check supersession
        _p = time.perf_counter()
        self._check_supersession(note, resolved_entities)
        phase_timings_ms["supersession"] = (time.perf_counter() - _p) * 1000

        # Phase 6: Knowledge Graph Update (heuristic edges — fast path)
        _p = time.perf_counter()
        self._update_knowledge_graph(note, resolved_entities)
        phase_timings_ms["kg_update"] = (time.perf_counter() - _p) * 1000

        # Phase 6b/6c/6d: dispatch background enrichment jobs (causal + NER + evolution).
        # The dispatch bucket measures job construction + put_nowait() + count_notes()
        # overhead only. In sync=True mode the LLM work runs inline and is intentionally
        # EXCLUDED from this bucket — mixing LLM latency into "dispatch" would corrupt
        # the Phase 0.5 attribution. sync=True is retained for tests/debug.
        # The whole block is gated by config.enrichment.enabled
        # (ZETTELFORGE_ENRICHMENT_ENABLED) so benchmarks and offline ingestion
        # get deterministic writes with no LLM dispatch.
        dispatch_start = time.perf_counter() if not sync else None
        if get_config().enrichment.enabled:
            job = _EnrichmentJob(
                note_id=note.id,
                domain=domain,
                content_len=len(content),
                resolved_entities=resolved_entities,
            )
            if sync:
                self._run_enrichment(job)
            else:
                self._enqueue_enrichment_job(job, queue_full_event="enrichment_queue_full")

            # Phase 6c: LLM NER enrichment (always-on, background — RFC-001 amendment)
            if get_config().llm_ner.enabled:
                ner_job = _EnrichmentJob(
                    note_id=note.id,
                    domain=domain,
                    content_len=len(content),
                    resolved_entities=resolved_entities,
                    job_type="llm_ner",
                )
                if sync:
                    self._run_llm_ner(ner_job)
                else:
                    self._enqueue_enrichment_job(ner_job, queue_full_event="llm_ner_queue_full")

            # Phase 6d: Neighbor evolution (A-Mem inspired — background worker)
            # Skip if fewer than 3 notes exist — not enough neighbors to evolve against
            if self.store.count_notes() >= 3:
                evolution_job = _EnrichmentJob(
                    note_id=note.id,
                    domain=domain,
                    content_len=len(content),
                    job_type="neighbor_evolution",
                )
                if sync:
                    self._run_evolution(evolution_job)
                else:
                    self._enqueue_enrichment_job(
                        evolution_job,
                        queue_full_event="evolution_queue_full",
                    )
        if dispatch_start is not None:
            phase_timings_ms["enrichment_dispatch"] = (time.perf_counter() - dispatch_start) * 1000

        duration_ms = (time.perf_counter() - start) * 1000
        log_api_activity(
            operation="remember",
            status_id=STATUS_SUCCESS,
            note_id=note.id,
            domain=domain,
            duration_ms=duration_ms,
            request_id=request_id,
            evolve=False,
            phase_timings_ms={k: round(v, 2) for k, v in phase_timings_ms.items()},
        )
        return note, "created"

    def remember_chunked(
        self,
        content: str,
        source_type: str = "conversation",
        source_ref: str = "",
        domain: str = "general",
        chunk_size: int = 800,
        sync: bool = False,
    ) -> list[MemoryNote]:
        """
        Split long content on sentence boundaries and store each chunk as its
        own note via remember().

        Smaller chunks give retrieval finer granularity on long conversational
        sessions (MemPalace-style 800-char chunks). Content at or under
        chunk_size is stored as a single note. Chunked notes carry an ordinal
        source_ref suffix ("{source_ref}#c{i}") so provenance survives the
        split.

        Args:
            content: Raw text to store.
            source_type: Origin type (conversation, threat_report, etc.).
            source_ref: Source identifier; chunks get "#c{i}" appended.
            domain: Memory domain (cti, general, etc.).
            chunk_size: Greedy sentence-packing target in characters. A single
                sentence longer than chunk_size becomes its own chunk.
            sync: Passed through to remember().

        Returns: list of stored MemoryNote, in document order.
        """
        text = content.strip()
        if len(text) <= chunk_size:
            note, _ = self.remember(
                text, source_type=source_type, source_ref=source_ref, domain=domain, sync=sync
            )
            return [note]

        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for sentence in sentences:
            if current and current_len + len(sentence) + 1 > chunk_size:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            current.append(sentence)
            current_len += len(sentence) + 1
        if current:
            chunks.append(" ".join(current))

        notes: list[MemoryNote] = []
        for i, chunk in enumerate(chunks):
            note, _ = self.remember(
                chunk,
                source_type=source_type,
                source_ref=f"{source_ref}#c{i}",
                domain=domain,
                sync=sync,
            )
            notes.append(note)
        return notes

    def remember_with_extraction(
        self,
        content: str,
        source_type: str = "conversation",
        source_ref: str = "",
        domain: str = "general",
        context: str = "",
        min_importance: int = 3,
        max_facts: int = 5,
    ) -> list[tuple[MemoryNote | None, str]]:
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
        assert_no_prompt_injection(content, field="remember_with_extraction.content")
        if context:
            assert_no_prompt_injection(context, field="remember_with_extraction.context")

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
    ) -> list[tuple[MemoryNote | None, str]]:
        """
        Ingest a news report or threat report.

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
        """
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
        domain: str | None = None,
        k: int = 10,
        include_links: bool = True,
        exclude_superseded: bool = True,
        include_expired: bool = False,
        caller: str | None = None,
        actor: str | None = None,
    ) -> list[MemoryNote]:
        """
        Retrieve memories relevant to query using blended vector + graph retrieval.

        Uses intent classifier to determine retrieval strategy weights,
        then combines vector similarity and graph traversal results
        with cross-encoder reranking.

        If governance.limits.recall_timeout_seconds is set (> 0), the
        retrieval pipeline is capped by a wall-clock timeout. Exceeding
        the timeout logs a warning and returns an empty list. This is a
        defense-in-depth control for D-03 (deep graph traversal DoS) per
        RFC-014.
        """
        assert_no_prompt_injection(query, field="recall.query")
        telemetry_caller = caller if caller is not None else actor
        timeout = get_config().governance.limits.recall_timeout_seconds
        if timeout > 0:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self._recall_inner,
                    query,
                    domain,
                    k,
                    include_links,
                    exclude_superseded,
                    include_expired,
                    telemetry_caller,
                )
                try:
                    return future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    self._logger.warning(
                        "recall_timed_out",
                        timeout_seconds=timeout,
                        query=query[:100],
                    )
                    log_api_activity(
                        operation="recall",
                        status_id=STATUS_FAILURE,
                        query=query[:200],
                        domain=domain,
                        k=k,
                        result_count=0,
                        duration_ms=timeout * 1000,
                        request_id=uuid.uuid4().hex,
                    )
                    return []
        return self._recall_inner(
            query,
            domain,
            k,
            include_links,
            exclude_superseded,
            include_expired,
            telemetry_caller,
        )

    def _recall_inner(
        self,
        query: str,
        domain: str | None = None,
        k: int = 10,
        include_links: bool = True,
        exclude_superseded: bool = True,
        include_expired: bool = False,
        caller: str | None = None,
        actor: str | None = None,
    ) -> list[MemoryNote]:
        assert_no_prompt_injection(query, field="recall.query")
        caller = caller if caller is not None else actor
        request_id = uuid.uuid4().hex
        start = time.perf_counter()
        self.stats["retrievals"] += 1

        # ── RFC-007 US-002: telemetry ─────────────────────────────────
        query_id = self._telemetry.start_query(query, caller=caller)
        self._telemetry_query_id = query_id

        # Classify query intent
        from zettelforge.intent_classifier import get_intent_classifier

        classifier = get_intent_classifier()
        intent, _intent_meta = classifier.classify(query)
        policy = classifier.get_traversal_policy(intent)

        # Extract entities from query for graph traversal
        query_entities = self.indexer.extractor.extract_all(query)
        resolved = {}
        for etype, elist in query_entities.items():
            resolved[etype] = [self.resolver.resolve(etype, e) for e in elist]
        # High-fanout entities (speaker names in every session) flood the
        # graph and entity-augmentation stages with undiscriminative notes.
        resolved = self._filter_low_signal_entities(resolved)

        # Vector retrieval (Community + Enterprise).
        # Request (note, score) tuples — BlendedRetriever's _normalize_scores
        # requires real similarity scores for min-max fusion. Without this,
        # commit 0e1c73 fails with ValueError: too many values to unpack.
        _vector_start = time.perf_counter()
        vector_scored: list[tuple] = self.retriever.retrieve(
            query=query,
            domain=domain,
            k=k,
            include_links=include_links,
            return_scores=True,
        )
        _vector_latency_ms = (time.perf_counter() - _vector_start) * 1000

        # Temporal boost: for temporal queries, prioritize notes containing dates from the query
        if intent.value == "temporal":
            import importlib.util
            import re as _re

            if importlib.util.find_spec("dateparser") is not None:
                # Extract date-like strings from query
                date_patterns = _re.findall(
                    r"\b(?:january|february|march|april|may|june|july|august|september|"
                    r"october|november|december)\s+\d{1,2}(?:,?\s+\d{4})?|\b\d{4}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
                    query,
                    _re.IGNORECASE,
                )
                if date_patterns:
                    # Boost notes containing any of the extracted dates;
                    # preserve the (note, score) shape for the blender.
                    date_lower = [d.lower() for d in date_patterns]
                    boosted = []
                    rest = []
                    for note, score in vector_scored:
                        content_lower = note.content.raw.lower()
                        if any(d in content_lower for d in date_lower):
                            boosted.append((note, score))
                        else:
                            rest.append((note, score))
                    vector_scored = boosted + rest

        # Blended retrieval: combine vector similarity with graph traversal.
        # The graph stage reads the per-store KG (same graph the write path
        # populates), not the process-global JSONL KG: the global graph mixes
        # every store on the machine, so traversing it from an isolated store
        # returns phantom note IDs and unbounded BFS cost.
        from zettelforge.blended_retriever import BlendedRetriever
        from zettelforge.graph_retriever import GraphRetriever, StoreGraphSource

        graph_retriever = GraphRetriever(StoreGraphSource(self.store))
        _graph_start = time.perf_counter()
        graph_results = graph_retriever.retrieve_note_ids(query_entities=resolved, max_depth=2)
        _graph_latency_ms = (time.perf_counter() - _graph_start) * 1000

        blender = BlendedRetriever()
        results = blender.blend(
            vector_results=vector_scored,
            graph_results=graph_results,
            policy=policy,
            note_lookup=lambda nid: self.store.get_note_by_id(nid),
            k=k,
        )

        # Fallback: if blending produced fewer results than vector alone, use
        # the bare-note projection of the scored list.
        if len(results) < len(vector_scored):
            results = [note for note, _ in vector_scored[:k]]

        # Causal retrieval boost: traverse causal edges when intent is CAUSAL
        if intent.value == "causal":
            result_ids_causal = {n.id for n in results}
            for etype, elist in resolved.items():
                for evalue in elist:
                    # Forward (what does X cause?) + backward (why did X happen?)
                    all_causal = []
                    all_causal.extend(
                        self.store.get_causal_edges(etype, evalue, max_depth=3, max_visited=50)
                    )
                    all_causal.extend(
                        self.store.get_incoming_causal(etype, evalue, max_depth=3, max_visited=50)
                    )
                    for edge in all_causal:
                        # Check both endpoints for note references
                        for endpoint in ("to_node_id", "from_node_id"):
                            node = self.store.get_kg_node_by_id(edge.get(endpoint, ""))
                            if node and node.get("entity_type") == "note":
                                nid = node.get("entity_value")
                                note = self.store.get_note_by_id(nid)
                                if note and note.id not in result_ids_causal:
                                    results.append(note)
                                    result_ids_causal.add(note.id)
                        # Also pull notes via the edge's source note_id
                        src_note_id = edge.get("properties", {}).get("note_id", "")
                        if src_note_id and src_note_id not in result_ids_causal:
                            note = self.store.get_note_by_id(src_note_id)
                            if note:
                                results.append(note)
                                result_ids_causal.add(note.id)

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

        # ── Cross-encoder reranking (policy-bounded) ────────────────────────
        # The reranker is the dominant read-path cost. Only the head of the
        # blended ranking is reranked; the tail keeps its blended order.
        retrieval_cfg = get_config().retrieval
        if retrieval_cfg.rerank_enabled and len(results) > 1:
            try:
                reranker = _get_reranker()
                if reranker is not None:
                    head = results[: retrieval_cfg.rerank_max_candidates]
                    tail = results[len(head) :]
                    docs = [n.content.raw[: retrieval_cfg.rerank_doc_chars] for n in head]
                    scores = list(reranker.rerank(query, docs))
                    # B905: strict=True — scores and docs have identical
                    # length by construction (one score per doc), so a length
                    # mismatch would be a programming error, not a silent
                    # truncation bug.
                    paired = sorted(
                        zip(scores, head, strict=True),
                        key=lambda x: x[0],
                        reverse=True,
                    )
                    results = [note for _, note in paired] + tail
            except Exception:
                self._logger.warning("reranking_failed_using_original_order", exc_info=True)

        # Filter superseded notes
        if exclude_superseded:
            results = [n for n in results if not n.links.superseded_by]

        # Filter expired notes (persistence semantics)
        if not include_expired:
            pre_filter_count = len(results)
            results = [n for n in results if not n.is_expired()]
            filtered_count = pre_filter_count - len(results)
            if filtered_count > 0:
                self._logger.info("expired_notes_filtered", count=filtered_count, query=query[:50])

        # Cap at k after entity augmentation and reranking
        results = results[:k]

        # Track access
        for note in results:
            note.increment_access()
            self.store.mark_access_dirty(note.id)

        # ── RFC-007 US-002: telemetry correlation slot ──────────────
        self._telemetry_query_id = query_id
        self._telemetry_retrieved_notes = list(results)

        duration_ms = (time.perf_counter() - start) * 1000

        # ── RFC-007 US-002: log_recall ─────────────────────────────
        intent_val = getattr(intent, "value", None)
        intent_str = intent_val if intent_val is not None else str(intent)
        self._telemetry.log_recall(
            query_id,
            results,
            intent=intent_str,
            vector_latency_ms=int(_vector_latency_ms),
            graph_latency_ms=int(_graph_latency_ms),
        )

        log_api_activity(
            operation="recall",
            status_id=STATUS_SUCCESS,
            query=query[:200],
            domain=domain,
            k=k,
            result_count=len(results),
            duration_ms=duration_ms,
            request_id=request_id,
            telemetry_query_id=query_id,
            telemetry_caller=caller,
        )
        return results

    def _filter_low_signal_entities(
        self, resolved: dict[str, list[str]], max_fanout: int | None = None
    ) -> dict[str, list[str]]:
        """Drop query entities whose note fan-out exceeds max_fanout.

        An entity mapped to a large share of the corpus (a conversational
        speaker name, for example) ranks nothing: traversing it floods the
        blended ranking with undiscriminative notes and displaces vector
        hits. IDF-style gate; threshold from retrieval.entity_max_fanout.
        """
        limit = max_fanout if max_fanout is not None else get_config().retrieval.entity_max_fanout
        if limit <= 0:
            return resolved
        filtered: dict[str, list[str]] = {}
        for etype, values in resolved.items():
            kept = []
            for value in values:
                if not value:
                    continue
                # Fan-out where flooding actually happens: note references.
                # Other graph facts, including OSINT enrichment edges, should
                # not make a discriminative entity look corpus-wide.
                node = self.store.get_kg_node(etype, value)
                fanout = self._note_fanout(node["node_id"]) if node else 0
                if fanout <= limit:
                    kept.append(value)
            filtered[etype] = kept
        return filtered

    def _memory_defense_reference_notes(
        self,
        domain: str,
        *,
        max_reference_notes: int,
        min_calibration_notes: int,
    ) -> list[MemoryNote]:
        """Fetch a bounded recent window, widening only to fill valid refs."""
        max_refs = max(0, int(max_reference_notes))
        min_refs = max(0, int(min_calibration_notes))
        fetch_limit = max(200, 4 * max_refs, 4 * min_refs)
        max_fetch_limit = max(fetch_limit, 20 * max_refs, 20 * min_refs)
        target_valid = max_refs

        while True:
            reference_notes = self.store.get_recent_notes_by_domain(domain, fetch_limit)
            valid_count = sum(
                1 for note in reference_notes if _has_valid_memory_defense_vector(note)
            )
            if valid_count >= target_valid:
                return reference_notes
            if len(reference_notes) < fetch_limit or fetch_limit >= max_fetch_limit:
                return reference_notes
            fetch_limit = min(fetch_limit * 2, max_fetch_limit)

    def _note_fanout(self, node_id: str) -> int:
        fanout = 0
        for edge in self.store.get_kg_edges_from(node_id):
            if edge.get("relationship") == "MENTIONED_IN":
                fanout += 1
                continue
            target = self.store.get_kg_node_by_id(edge.get("to_node_id", ""))
            if target and target.get("entity_type") == "note":
                fanout += 1
        return fanout

    def recall_entity(self, entity_type: str, entity_value: str, k: int = 5) -> list[MemoryNote]:
        """
        Fast lookup by entity type and value.
        entity_type: 'cve', 'actor', 'threat_actor', 'intrusion_set', 'tool',
        'campaign', 'person', 'location', 'organization', 'event', 'activity',
        'temporal'
        """
        self.stats["entity_index_hits"] += 1
        note_ids = self.store.get_note_ids_for_entity(entity_type, entity_value.lower())
        # Fall back to legacy JSON indexer if backend returns nothing
        if not note_ids:
            note_ids = self.indexer.get_note_ids(entity_type, entity_value.lower())
        notes = []
        for nid in note_ids[:k]:
            note = self.store.get_note_by_id(nid)
            if note:
                notes.append(note)
        return notes

    def recall_cve(self, cve_id: str, k: int = 5) -> list[MemoryNote]:
        """Fast lookup by CVE-ID (case-insensitive)"""
        return self.recall_entity("cve", cve_id.upper(), k)

    def recall_actor(self, actor_name: str, k: int = 5) -> list[MemoryNote]:
        """Fast lookup by threat actor name.

        Searches legacy 'actor', STIX 'threat_actor', and STIX
        'intrusion_set' entity types. APT/UNC/FIN-style designations are
        extracted as intrusion_set, but older stores may still have actor.
        """
        results = []
        seen = set()
        for entity_type in ("actor", "threat_actor", "intrusion_set"):
            if len(results) >= k:
                break
            entity_results = self.recall_entity(entity_type, actor_name.lower(), k - len(results))
            for note in entity_results:
                if note.id not in seen:
                    results.append(note)
                    seen.add(note.id)
        return results

    def recall_technique(self, technique_id: str, k: int = 25) -> list[MemoryNote]:
        """Fast lookup by MITRE ATT&CK technique ID (e.g., T1059)."""
        return self.recall_entity("attack_pattern", technique_id.upper(), k)

    def recall_tool(self, tool_name: str, k: int = 5) -> list[MemoryNote]:
        """Fast lookup by tool name"""
        return self.recall_entity("tool", tool_name.lower(), k)

    def get_context(
        self, query: str, domain: str | None = None, k: int = 10, token_budget: int = 4000
    ) -> str:
        """
        Get formatted memory context for agent prompt injection.
        """
        assert_no_prompt_injection(query, field="context.query")
        return self.retriever.get_memory_context(
            query=query, domain=domain, k=k, token_budget=token_budget
        )

    def get_stats(self) -> dict:
        """Get memory system statistics"""
        return {
            **self.stats,
            "total_notes": self.store.count_notes(),
            "entity_index": self.indexer.stats(),
        }

    def _update_knowledge_graph(self, note: MemoryNote, resolved_entities: dict[str, list[str]]):
        now = datetime.now().isoformat()
        edge_props = {"first_observed": now, "confidence": note.metadata.confidence}

        # 1. Add Note node
        self.store.add_kg_node(
            "note", note.id, {"content": note.content.raw[:200], "domain": note.metadata.domain}
        )

        # 2. Add Entity Nodes and MENTIONED_IN edges
        all_entities = []
        for etype, elist in resolved_entities.items():
            for evalue in elist:
                all_entities.append((etype, evalue))
                self.store.add_kg_edge(
                    etype, evalue, "note", note.id, "MENTIONED_IN", properties=edge_props
                )

        # 3. Inferred Entity-to-Entity Relationships (Heuristic)

        # --- CTI relationships ---
        actors = []
        for actor_type in ("actor", "threat_actor", "intrusion_set"):
            actors.extend((actor_type, value) for value in resolved_entities.get(actor_type, []))
        tools = resolved_entities.get("tool", [])
        cves = resolved_entities.get("cve", [])
        assets = resolved_entities.get("asset", [])
        campaigns = resolved_entities.get("campaign", [])

        for actor_type, actor_value in actors:
            for t in tools:
                self.store.add_kg_edge(
                    actor_type, actor_value, "tool", t, "USES_TOOL", properties=edge_props
                )
            for c in cves:
                self.store.add_kg_edge(
                    actor_type, actor_value, "cve", c, "EXPLOITS_CVE", properties=edge_props
                )
            for asset in assets:
                self.store.add_kg_edge(
                    actor_type,
                    actor_value,
                    "asset",
                    asset,
                    "TARGETS_ASSET",
                    properties=edge_props,
                )
            for camp in campaigns:
                self.store.add_kg_edge(
                    actor_type,
                    actor_value,
                    "campaign",
                    camp,
                    "CONDUCTS_CAMPAIGN",
                    properties=edge_props,
                )

        for t in tools:
            for asset in assets:
                self.store.add_kg_edge(
                    "tool", t, "asset", asset, "TARGETS_ASSET", properties=edge_props
                )
            for c in cves:
                self.store.add_kg_edge("tool", t, "cve", c, "EXPLOITS_CVE", properties=edge_props)

        attack_patterns = resolved_entities.get("attack_pattern", [])
        for actor_type, actor_value in actors:
            for ap in attack_patterns:
                self.store.add_kg_edge(
                    actor_type,
                    actor_value,
                    "attack_pattern",
                    ap,
                    "USES_TECHNIQUE",
                    properties=edge_props,
                )
        malwares = resolved_entities.get("malware", [])
        for m in malwares:
            for ap in attack_patterns:
                self.store.add_kg_edge(
                    "malware", m, "attack_pattern", ap, "IMPLEMENTS", properties=edge_props
                )

        # --- Conversational relationships (RFC-001) ---
        persons = resolved_entities.get("person", [])
        locations = resolved_entities.get("location", [])
        organizations = resolved_entities.get("organization", [])
        events = resolved_entities.get("event", [])
        activities = resolved_entities.get("activity", [])
        temporals = resolved_entities.get("temporal", [])

        for p in persons:
            for org in organizations:
                self.store.add_kg_edge(
                    "person", p, "organization", org, "AFFILIATED_WITH", properties=edge_props
                )
            for ev in events:
                self.store.add_kg_edge("person", p, "event", ev, "ATTENDED", properties=edge_props)
            for loc in locations:
                self.store.add_kg_edge(
                    "person", p, "location", loc, "LOCATED_AT", properties=edge_props
                )
            for act in activities:
                self.store.add_kg_edge(
                    "person", p, "activity", act, "PARTICIPATES_IN", properties=edge_props
                )

        for ev in events:
            for loc in locations:
                self.store.add_kg_edge(
                    "event", ev, "location", loc, "HELD_AT", properties=edge_props
                )
            for org in organizations:
                self.store.add_kg_edge(
                    "event", ev, "organization", org, "ORGANIZED_BY", properties=edge_props
                )
            for tmp in temporals:
                self.store.add_kg_edge(
                    "event", ev, "temporal", tmp, "OCCURRED_ON", properties=edge_props
                )

        for org in organizations:
            for loc in locations:
                self.store.add_kg_edge(
                    "organization", org, "location", loc, "BASED_IN", properties=edge_props
                )

        # NOTE: LLM causal triple extraction moved to _run_enrichment() (slow path)

    # ── Dual-stream: slow path enrichment worker ──────────────────────────

    def _enqueue_enrichment_job(self, job: _EnrichmentJob, *, queue_full_event: str) -> bool:
        """Queue an enrichment job and record its ledger row.

        RFC-018's first implementation slice records durable job metadata while
        keeping execution in the existing in-process queue.  Queue-full events
        are marked terminal in the ledger so operators can distinguish jobs
        that never ran from jobs still waiting.
        """
        record = EnrichmentJobRecord.new(
            job_id=job.job_id,
            note_id=job.note_id,
            job_type=job.job_type,
            domain=job.domain,
            content_len=job.content_len,
        )
        create_job = getattr(self.store, "create_enrichment_job", None)
        if create_job is not None:
            create_job(record)
        try:
            self._enrichment_queue.put_nowait(job)
            self._pending_enrichment.add(job.note_id)
            return True
        except queue.Full:
            mark_terminal = getattr(self.store, "mark_enrichment_job_terminal", None)
            if mark_terminal is not None:
                mark_terminal(job.job_id, "failed", error_code="queue_full")
            self._logger.warning(queue_full_event, note_id=job.note_id)
            return False

    def _mark_enrichment_job_running(self, job: _EnrichmentJob) -> None:
        mark_running = getattr(self.store, "mark_enrichment_job_running", None)
        if mark_running is not None:
            mark_running(job.job_id)

    def _mark_enrichment_job_terminal(
        self,
        job: _EnrichmentJob,
        state: str,
        *,
        error_code: str = "",
    ) -> None:
        mark_terminal = getattr(self.store, "mark_enrichment_job_terminal", None)
        if mark_terminal is not None:
            mark_terminal(job.job_id, state, error_code=error_code)

    def _enrichment_loop(self) -> None:
        """Background worker: process enrichment jobs until process exits."""
        while True:
            job = None
            try:
                job = self._enrichment_queue.get(timeout=1.0)
                if job.defer:
                    # Batch-deferred job — skip for now, will be swept later
                    self._mark_enrichment_job_terminal(job, "cancelled", error_code="deferred")
                    continue
                self._mark_enrichment_job_running(job)
                if job.job_type == "neighbor_evolution":
                    self._run_evolution(job)
                elif job.job_type == "llm_ner":
                    self._run_llm_ner(job)
                else:
                    self._run_enrichment(job)
                if job.ledger_error_code:
                    self._mark_enrichment_job_terminal(
                        job, "failed", error_code=job.ledger_error_code
                    )
                else:
                    self._mark_enrichment_job_terminal(job, "succeeded")
            except queue.Empty:
                continue
            except BackendClosedError:
                # Storage backend has shut down — exit the worker cleanly.
                return
            except Exception:
                if job is not None:
                    self._mark_enrichment_job_terminal(job, "failed", error_code="worker_error")
                self._logger.error("enrichment_worker_error", exc_info=True)
            finally:
                if job is not None:
                    self._enrichment_queue.task_done()

    def flush(self, timeout: float | None = None) -> bool:
        """Wait until queued and in-flight enrichment jobs complete.

        Returns ``True`` when all jobs are done. If ``timeout`` is provided
        and expires first, returns ``False``.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._enrichment_queue.all_tasks_done:
            while self._enrichment_queue.unfinished_tasks:
                if deadline is None:
                    self._enrichment_queue.all_tasks_done.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._enrichment_queue.all_tasks_done.wait(remaining)
        return True

    def _run_enrichment(self, job: _EnrichmentJob) -> None:
        """Execute slow-path LLM causal triple extraction for one note."""
        should_enrich = job.domain in ["cti", "incident", "threat_intel"] or job.content_len > 200
        if not should_enrich:
            self._pending_enrichment.discard(job.note_id)
            return

        note = self.store.get_note_by_id(job.note_id)
        if note is None:
            job.ledger_error_code = "note_missing"
            self._pending_enrichment.discard(job.note_id)
            return

        try:
            triples = self.constructor.extract_causal_triples(note.content.raw, note.id)
            if triples:
                edges = self.constructor.store_causal_edges(triples, note.id, backend=self.store)
                self._logger.info(
                    "causal_triples_stored", note_id=note.id, triples=len(triples), edges=edges
                )
        except Exception:
            job.ledger_error_code = "enrichment_failed"
            self._logger.warning("enrichment_failed", note_id=note.id, exc_info=True)
        finally:
            self._pending_enrichment.discard(job.note_id)

    def _run_llm_ner(self, job: _EnrichmentJob) -> None:
        """Execute slow-path LLM NER entity extraction for one note.

        Runs LLM-based NER, merges new entities with existing regex-extracted
        entities (extend, not overwrite), and persists the amended entity index.
        """
        note = self.store.get_note_by_id(job.note_id)
        if note is None:
            job.ledger_error_code = "note_missing"
            self._pending_enrichment.discard(job.note_id)
            return

        start = time.perf_counter()
        try:
            from zettelforge.entity_indexer import EntityExtractor

            extractor = EntityExtractor()
            llm_entities = extractor.extract_llm(note.content.raw)

            if not any(llm_entities.values()):
                # LLM found nothing new — skip
                self._pending_enrichment.discard(job.note_id)
                return

            # Merge with existing entities (extend, don't overwrite)
            existing = note.semantic.entities if note.semantic.entities else []
            new_flat = []
            for etype, values in llm_entities.items():
                for v in values:
                    tag = f"{etype}:{v}"
                    if tag not in existing:
                        new_flat.append(tag)

            duration_ms = (time.perf_counter() - start) * 1000
            self.stats["llm_ner_total_duration_ms"] += duration_ms

            if new_flat:
                # Update entity index in storage backend
                for etype, values in llm_entities.items():
                    for v in values:
                        self.store.add_entity_mapping(etype, v, note.id)

                # Update legacy EntityIndexer (JSON)
                self.indexer.add_note(note.id, llm_entities)

                self.stats["llm_ner_success"] += 1
                self.stats["llm_ner_total_new_entities"] += len(new_flat)
                self._logger.info(
                    "llm_ner_complete",
                    note_id=note.id,
                    new_entities=len(new_flat),
                    duration_ms=round(duration_ms, 1),
                )
            else:
                self.stats["llm_ner_no_new"] += 1
                self._logger.debug(
                    "llm_ner_no_new_entities",
                    note_id=note.id,
                    duration_ms=round(duration_ms, 1),
                )
        except Exception:
            job.ledger_error_code = "llm_ner_failed"
            self.stats["llm_ner_failure"] += 1
            self._logger.warning("llm_ner_failed", note_id=job.note_id, exc_info=True)
        finally:
            self._pending_enrichment.discard(job.note_id)

    def _run_evolution(self, job: _EnrichmentJob) -> None:
        """Execute neighbor evolution for one note."""
        note = self.store.get_note_by_id(job.note_id)
        if note is None:
            job.ledger_error_code = "note_missing"
            self._pending_enrichment.discard(job.note_id)
            return

        try:
            from zettelforge.memory_evolver import MemoryEvolver

            evolver = MemoryEvolver(self)
            report = evolver.evolve_neighbors(note)
            self._logger.info(
                "neighbor_evolution_complete",
                note_id=job.note_id,
                candidates_found=report["candidates_found"],
                evolved=report["evolved"],
                kept=report["kept"],
                errors=report["errors"],
            )
        except Exception:
            job.ledger_error_code = "neighbor_evolution_failed"
            self._logger.warning("neighbor_evolution_failed", note_id=job.note_id, exc_info=True)
        finally:
            self._pending_enrichment.discard(job.note_id)

    def _drain_enrichment_queue(self) -> None:
        """atexit: process remaining enrichment jobs within a 10-second window."""
        deadline = time.monotonic() + 10.0
        while not self._enrichment_queue.empty() and time.monotonic() < deadline:
            job = None
            try:
                job = self._enrichment_queue.get_nowait()
                if job.defer:
                    self._mark_enrichment_job_terminal(job, "cancelled", error_code="deferred")
                    continue
                self._mark_enrichment_job_running(job)
                if job.job_type == "neighbor_evolution":
                    self._run_evolution(job)
                elif job.job_type == "llm_ner":
                    self._run_llm_ner(job)
                else:
                    self._run_enrichment(job)
                if job.ledger_error_code:
                    self._mark_enrichment_job_terminal(
                        job, "failed", error_code=job.ledger_error_code
                    )
                else:
                    self._mark_enrichment_job_terminal(job, "succeeded")
            except queue.Empty:
                break
            except BackendClosedError:
                # Backend already closed — nothing left to drain against.
                return
            except Exception:
                if job is not None:
                    self._mark_enrichment_job_terminal(job, "failed", error_code="drain_error")
                self._logger.warning("enrichment_drain_failed", exc_info=True)
            finally:
                if job is not None:
                    self._enrichment_queue.task_done()

    def evolve_note(self, note_id: str, sync: bool = False) -> dict | None:
        """Trigger neighbor evolution for an existing note.

        Intended for manual or MCP invocation.

        Args:
            note_id: The note to evolve neighbors around.
            sync: If True, run inline (blocking). Otherwise queue to background worker.

        Returns:
            Evolution report dict when sync=True, None when queued or note not found.
        """
        note = self.store.get_note_by_id(note_id)
        if note is None:
            self._logger.warning("evolve_note_not_found", note_id=note_id)
            return None

        job = _EnrichmentJob(
            note_id=note_id,
            domain=note.metadata.domain,
            content_len=len(note.content.raw),
            job_type="neighbor_evolution",
        )

        if sync:
            from zettelforge.memory_evolver import MemoryEvolver

            evolver = MemoryEvolver(self)
            return evolver.evolve_neighbors(note)

        self._enqueue_enrichment_job(job, queue_full_event="evolution_queue_full")
        return None

    def mark_note_superseded(self, note_id: str, superseded_by_id: str) -> bool:
        old_note = self.store.get_note_by_id(note_id)
        new_note = self.store.get_note_by_id(superseded_by_id)
        if not old_note or not new_note:
            return False

        old_note.links.superseded_by = superseded_by_id
        if note_id not in new_note.links.supersedes:
            new_note.links.supersedes.append(note_id)

        self.store.rewrite_note(old_note)
        self.store.rewrite_note(new_note)

        # Remove superseded note from entity index so recall_entity() won't return it
        self.indexer.remove_note(note_id)
        self.store.remove_entity_mappings_for_note(note_id)

        # Add temporal edge to knowledge graph (Task 2)
        self.store.add_temporal_edge(
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
        self, new_note: MemoryNote, resolved_entities: dict[str, list[str]]
    ) -> MemoryNote | None:
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
        new_entities: dict[str, set] = {
            k: set(e.lower() for e in resolved_entities.get(k, [])) for k in _entity_keys
        }

        # Use the entity index to collect only candidate note IDs that share at
        # least one entity value with the new note — O(E) instead of O(N).
        # Also pre-compute per-candidate overlap counts while traversing the index
        # so we never need to re-extract entities from raw content.
        candidate_overlap: dict[str, int] = {}
        for key in _entity_keys:
            for evalue in new_entities[key]:
                nids = self.store.get_note_ids_for_entity(key, evalue)
                if not nids:
                    nids = self.indexer.get_note_ids(key, evalue)
                for nid in nids:
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
        properties: dict | None = None,
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
        self.store.add_kg_edge(
            from_type,
            from_value,
            to_type,
            to_value,
            relationship,
            properties=properties or {},
        )
        # Also write to legacy JSONL KG for backward compatibility
        from zettelforge.knowledge_graph import get_knowledge_graph

        kg = get_knowledge_graph()
        kg.add_edge(from_type, from_value, to_type, to_value, relationship, properties or {})

    def provenance_chain(
        self,
        entity_type: str,
        entity_value: str,
        max_depth: int = 3,
        direction: str = "forward",
    ) -> list[dict]:
        """Trace causal provenance chain from an entity.

        Args:
            direction: "forward" = what does X cause/enable? (outgoing causal edges)
                       "backward" = why did X happen? (incoming causal edges)

        Returns list of steps:
            [{from_entity, relationship, to_entity, edge_type, note_id}]
        """
        canonical = self.resolver.resolve(entity_type, entity_value)

        if direction not in ("forward", "backward"):
            raise ValueError(f"direction must be 'forward' or 'backward', got '{direction}'")

        if direction == "backward":
            causal_edges = self.store.get_incoming_causal(
                entity_type, canonical, max_depth=max_depth
            )
        else:
            causal_edges = self.store.get_causal_edges(entity_type, canonical, max_depth=max_depth)

        chain = []
        for edge in causal_edges:
            from_node = self.store.get_kg_node_by_id(edge.get("from_node_id", "")) or {}
            to_node = self.store.get_kg_node_by_id(edge.get("to_node_id", "")) or {}
            chain.append(
                {
                    "from_entity": (
                        f"{from_node.get('entity_type')}:{from_node.get('entity_value')}"
                    ),
                    "relationship": edge.get("relationship"),
                    "to_entity": (f"{to_node.get('entity_type')}:{to_node.get('entity_value')}"),
                    "edge_type": edge.get("edge_type", "unknown"),
                    "note_id": edge.get("properties", {}).get("note_id", ""),
                }
            )
        return chain

    def get_entity_relationships(self, entity_type: str, entity_value: str) -> list[dict]:
        """Get direct relationships for an entity from the knowledge graph."""
        # Resolve alias if necessary
        canonical = self.resolver.resolve(entity_type, entity_value)

        return self.store.get_kg_neighbors(entity_type, canonical)

    def traverse_graph(self, start_type: str, start_value: str, max_depth: int = 2) -> list[dict]:
        """Traverse relationships from a starting entity.

        Depth is capped at 2 without the enterprise extension.
        Install zettelforge-enterprise for deeper TypeDB traversal.
        """
        if max_depth > 2 and not has_extension("enterprise"):
            max_depth = 2
            self._logger.info(
                "traverse_depth_capped",
                max_depth=2,
                reason="Install zettelforge-enterprise for deeper TypeDB traversal",
            )
        canonical = self.resolver.resolve(start_type, start_value)

        return self.store.traverse_kg(start_type, canonical, max_depth)

    # === Phase 7: Synthesis Layer ===

    def synthesize(
        self,
        query: str,
        format: str = "direct_answer",
        k: int = 10,
        tier_filter: list[str] | None = None,
        caller: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """
        Synthesize an answer from retrieved memories (Phase 7 RAG-as-Answer).

        Extended formats ("synthesized_brief", "timeline_analysis", "relationship_map")
        require the enterprise extension; without it they fall back to "direct_answer".

        Args:
            query: The question to answer
            format: Output format (see above)
            k: Number of notes to retrieve for context
            tier_filter: Filter by tier ["A", "B"] or ["A", "B", "C"]

        Returns:
            Dictionary with synthesis result, metadata, and sources
        """
        assert_no_prompt_injection(query, field="synthesize.query")
        telemetry_caller = caller if caller is not None else actor
        _extended_formats = {"synthesized_brief", "timeline_analysis", "relationship_map"}
        if format in _extended_formats and not has_extension("enterprise"):
            self._logger.info("synthesis_format_fallback", requested=format, using="direct_answer")
            format = "direct_answer"

        request_id = uuid.uuid4().hex
        start = time.perf_counter()

        # Reuse query_id from the last recall() so synthesis telemetry
        # correlates to the same query. If the caller supplied attribution
        # directly without a preceding recall() call, start a fresh query.
        query_id = self._telemetry_query_id or self._telemetry.start_query(
            query, caller=telemetry_caller
        )
        if query_id and self._telemetry_query_id is None:
            # Fresh query started here — keep the id for consistency
            self._telemetry_query_id = query_id

        gen = get_synthesis_generator()
        result = gen.synthesize(
            query=query, memory_manager=self, format=format, k=k, tier_filter=tier_filter
        )

        duration_ms = (time.perf_counter() - start) * 1000
        synthesis_latency_ms = (
            time.perf_counter() - start
        ) * 1000  # gen.synthesize is the synthesis work
        source_count = len(result.get("sources", []))

        # ── RFC-007 US-002: log_synthesis ─────────────────────────────
        if query_id is not None:
            self._telemetry.log_synthesis(
                query_id, result, synthesis_latency_ms=int(synthesis_latency_ms)
            )
            # Auto-feedback is DEBUG-only inside the collector
            retrieved = self._telemetry_retrieved_notes or []
            self._telemetry.auto_feedback_from_synthesis(query_id, retrieved, result)

        log_api_activity(
            operation="synthesize",
            status_id=STATUS_SUCCESS,
            query=query[:200],
            format=format,
            source_count=source_count,
            duration_ms=duration_ms,
            request_id=request_id,
            telemetry_query_id=query_id,
            telemetry_caller=telemetry_caller,
        )
        return result

    def validate_synthesis(self, response: dict) -> tuple[bool, list[str]]:
        """
        Validate a synthesis response for quality.

        Returns:
            (is_valid, list_of_errors)
        """
        validator = get_synthesis_validator()
        return validator.validate_response(response)

    def check_synthesis_quality(self, response: dict) -> dict:
        """
        Compute quality score for a synthesis response.

        Returns quality metrics including score (0-1) and grade.
        """
        validator = get_synthesis_validator()
        return validator.check_quality_score(response)


# Global memory manager instance
_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """Get or create global memory manager instance"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
