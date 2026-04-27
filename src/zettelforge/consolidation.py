"""
GAM-Style Consolidation Layer for ZettelForge
Based on: Hierarchical Graph-based Agentic Memory (arXiv:2604.12285)

Architecture:
  EPG (Event Progression Graph) — active, transient events
  TAN (Topic Associative Network) — consolidated, stable knowledge

Consolidation trigger: Semantic shift detection
  When a new note's topic/entity distribution diverges significantly
  from the current EPG state, the EPG is consolidated into TAN.

This addresses SAGA Gap 2: Temporal Memory Maintenance.
"""

import threading
import time
from datetime import datetime
from typing import Any

from zettelforge.log import get_logger
from zettelforge.ocsf import STATUS_SUCCESS, log_api_activity
from zettelforge.storage_backend import BackendClosedError

logger = get_logger("zettelforge.consolidation")


# ── Semantic Shift Detector ────────────────────────────────────────────────


class SemanticShiftDetector:
    """
    Detects when incoming information represents a semantic shift
    from the current active memory state (EPG).

    A semantic shift occurs when:
    1. New entities appear that weren't in the active window
    2. Topic distribution changes significantly (cosine similarity < threshold)
    3. Temporal gap exceeds threshold (freshness decay)

    CTI-specific: APT TTP changes, new CVE campaigns, evolving IOCs
    all trigger semantic shifts that warrant consolidation.
    """

    def __init__(
        self,
        entity_shift_threshold: float = 0.4,
        topic_shift_threshold: float = 0.5,
        temporal_gap_hours: float = 4.0,
        min_epg_size: int = 3,
    ):
        self.entity_shift_threshold = entity_shift_threshold
        self.topic_shift_threshold = topic_shift_threshold
        self.temporal_gap_hours = temporal_gap_hours
        self.min_epg_size = min_epg_size

        # Active window state
        self._epg_entities: dict[str, int] = {}  # entity -> count
        self._epg_topics: dict[str, float] = {}  # domain -> weight
        self._epg_count: int = 0
        self._last_note_time: datetime | None = None
        self._lock = threading.Lock()

    def observe(self, note_entities: dict[str, list[str]], note_domain: str) -> None:
        """Update the EPG state with a new note's entities and domain."""
        with self._lock:
            self._epg_count += 1

            # Update entity counts
            for etype, values in note_entities.items():
                for val in values:
                    key = f"{etype}:{val}"
                    self._epg_entities[key] = self._epg_entities.get(key, 0) + 1

            # Update topic distribution (exponential moving average)
            alpha = 0.3
            for topic in self._epg_topics:
                self._epg_topics[topic] *= 1 - alpha
            self._epg_topics[note_domain] = self._epg_topics.get(note_domain, 0) + alpha

            self._last_note_time = datetime.now()

    def detect_shift(
        self,
        note_entities: dict[str, list[str]],
        note_domain: str,
        note_time: datetime | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """
        Check whether a new note represents a semantic shift from the EPG.

        Returns (is_shift, shift_metadata).
        """
        with self._lock:
            # Don't trigger consolidation on small EPG
            if self._epg_count < self.min_epg_size:
                return False, {"reason": "epg_too_small", "epg_count": self._epg_count}

            shift_signals = []
            metadata: dict[str, Any] = {"epg_count": self._epg_count}

            # --- Signal 1: Entity novelty ---
            new_entities = 0
            total_entities = 0
            for etype, values in note_entities.items():
                for val in values:
                    key = f"{etype}:{val}"
                    total_entities += 1
                    if key not in self._epg_entities:
                        new_entities += 1

            if total_entities > 0:
                novelty_ratio = new_entities / total_entities
                metadata["entity_novelty"] = novelty_ratio
                if novelty_ratio >= self.entity_shift_threshold:
                    shift_signals.append("entity_novelty")
                    metadata["entity_novelty_exceeded"] = True

            # --- Signal 2: Topic distribution shift ---
            if self._epg_topics:
                # Normalize current topic distribution
                total_weight = sum(self._epg_topics.values())
                if total_weight > 0:
                    # Check if note domain is a significant departure
                    domain_weight = self._epg_topics.get(note_domain, 0) / total_weight
                    metadata["domain_weight"] = domain_weight
                    if (
                        domain_weight
                        < (1.0 / max(len(self._epg_topics), 1)) * self.topic_shift_threshold
                    ):
                        shift_signals.append("topic_shift")
                        metadata["topic_shift_exceeded"] = True

            # --- Signal 3: Temporal gap ---
            if self._last_note_time and note_time:
                gap_hours = (note_time - self._last_note_time).total_seconds() / 3600
                metadata["temporal_gap_hours"] = gap_hours
                if gap_hours >= self.temporal_gap_hours:
                    shift_signals.append("temporal_gap")
                    metadata["temporal_gap_exceeded"] = True

            is_shift = len(shift_signals) >= 1
            metadata["shift_signals"] = shift_signals
            metadata["shift_count"] = len(shift_signals)

            return is_shift, metadata

    def reset(self) -> None:
        """Reset EPG state after consolidation."""
        with self._lock:
            self._epg_entities.clear()
            self._epg_topics.clear()
            self._epg_count = 0
            self._last_note_time = None

    def get_state(self) -> dict[str, Any]:
        """Get current EPG state for diagnostics."""
        with self._lock:
            return {
                "epg_count": self._epg_count,
                "unique_entities": len(self._epg_entities),
                "topics": dict(self._epg_topics),
                "last_note_time": self._last_note_time.isoformat()
                if self._last_note_time
                else None,
            }


# ── Consolidation Engine ────────────────────────────────────────────────────


class ConsolidationEngine:
    """
    Consolidates EPG (active events) into TAN (stable knowledge).

    Process:
    1. Identify notes in EPG that are candidates for consolidation
    2. Group by topic/domain and entity clusters
    3. For each group, check for contradictions (SSGM consistency verification)
    4. Merge/update notes, supersede old versions
    5. Promote consolidated notes to TAN (stable tier)
    6. Reset EPG state

    SSGM integration: Pre-consolidation validation using NLI-style
    contradiction checks before promoting to TAN.
    """

    def __init__(self, memory_manager, shift_detector: SemanticShiftDetector | None = None):
        self._mm = memory_manager
        self._detector = shift_detector or SemanticShiftDetector()
        self._logger = get_logger("zettelforge.consolidation.engine")
        self._consolidation_count: int = 0
        self._last_consolidation_time: str | None = None

    def should_consolidate(
        self,
        note_entities: dict[str, list[str]],
        note_domain: str,
        note_time: datetime | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """Check if consolidation should be triggered for this note."""
        return self._detector.detect_shift(note_entities, note_domain, note_time)

    def consolidate(self, force: bool = False) -> dict[str, Any]:
        """
        Execute consolidation: EPG → TAN.

        Returns consolidation report with stats.
        """
        start = time.perf_counter()
        report: dict[str, Any] = {
            "triggered_at": datetime.now().isoformat(),
            "forced": force,
            "notes_examined": 0,
            "notes_consolidated": 0,
            "notes_superseded": 0,
            "contradictions_found": 0,
            "errors": [],
        }

        # [RFC-010] fast-path guard — skip when the backing MemoryManager has
        # begun shutdown. Prevents the shutdown-race `BackendClosedError` that
        # surfaced in production logs 2026-04-24T17:25:48Z from
        # consolidation.py:224 (iterate_notes). RFC-009 Section 4.3 replaces
        # this with explicit cursor tracking; until then, this guard + the
        # catch in the iteration below form a two-layer defense.
        if not getattr(self._mm, "_accepting", True):
            report["status"] = "skipped"
            report["reason"] = "backend not accepting (shutdown in progress)"
            return report

        try:
            # Gather recent notes (EPG candidates)
            # Only notes created since the last consolidation window
            epg_notes = []
            for note in self._mm.store.iterate_notes():
                if not note.links.superseded_by:
                    if (
                        self._last_consolidation_time
                        and note.created_at < self._last_consolidation_time
                    ):
                        continue
                    epg_notes.append(note)

            report["notes_examined"] = len(epg_notes)

            if len(epg_notes) < self._detector.min_epg_size:
                report["skipped"] = True
                report["reason"] = "too_few_notes"
                return report

            # Build entity cache before domain grouping (avoid redundant extraction)
            entity_cache: dict[str, dict[str, list[str]]] = {}
            for note in epg_notes:
                entity_cache[note.id] = self._mm.indexer.extractor.extract_all(
                    note.content.raw, use_llm=False
                )

            # Group by domain
            domain_groups: dict[str, list] = {}
            for note in epg_notes:
                domain = note.metadata.domain or "general"
                domain_groups.setdefault(domain, []).append(note)

            # Consolidate each domain group
            for _domain, notes in domain_groups.items():
                if len(notes) < 2:
                    continue

                # Find overlapping entity pairs for potential merges
                entity_map: dict[str, list[str]] = {}  # entity_key -> [note_ids]
                for note in notes:
                    entities = entity_cache[note.id]
                    for etype, values in entities.items():
                        for val in values:
                            key = f"{etype}:{val}"
                            entity_map.setdefault(key, []).append(note.id)

                # Identify notes sharing 2+ entities (candidates for merge)
                merge_candidates = set()
                for _entity_key, note_ids in entity_map.items():
                    if len(note_ids) >= 2:
                        for nid in note_ids:
                            merge_candidates.add(nid)

                # Check for contradictions among merge candidates (SSGM gate)
                candidate_notes = [n for n in notes if n.id in merge_candidates]
                contradictions = self._detect_contradictions(candidate_notes, entity_cache)
                report["contradictions_found"] += len(contradictions)

                # Notes without contradictions can be consolidated
                # (In a full implementation, we'd merge overlapping notes here)
                # For now, mark consolidation-eligible notes with a TAN tier
                for note in candidate_notes:
                    if note.id not in contradictions:
                        # Promote to TAN by updating tier
                        if hasattr(note.metadata, "tier"):
                            note.metadata.tier = "A"  # Tier A = consolidated/stable
                        try:
                            self._mm.store._rewrite_note(note)
                        except Exception as e:
                            self._logger.warning(
                                "tier_persist_failed", note_id=note.id, error=str(e)
                            )
                        report["notes_consolidated"] += 1

            # Reset EPG state after consolidation
            self._detector.reset()
            self._consolidation_count += 1

        except BackendClosedError:
            # [RFC-010] Narrow race: _accepting was true at the guard check
            # above, but flipped to false before iterate_notes yielded its
            # first row. Treat as a clean skip rather than a noisy error.
            report["status"] = "skipped"
            report["reason"] = "backend closed mid-iteration"
            return report
        except Exception as e:
            self._logger.error("consolidation_failed", error=str(e), exc_info=True)
            report["errors"].append(str(e))

        self._last_consolidation_time = datetime.now().isoformat()

        duration_ms = (time.perf_counter() - start) * 1000
        report["duration_ms"] = duration_ms
        report["consolidation_number"] = self._consolidation_count

        log_api_activity(
            operation="consolidate",
            status_id=STATUS_SUCCESS,
            duration_ms=duration_ms,
            **{
                k: v
                for k, v in report.items()
                if isinstance(v, (int, float, str, bool)) and k not in ("duration_ms",)
            },
        )

        return report

    def _detect_contradictions(
        self, notes: list, entity_cache: dict[str, dict[str, list[str]]]
    ) -> set:
        """
        SSGM-inspired contradiction detection.

        Checks for notes that make conflicting claims about the same entity.
        Returns set of note IDs that are contradicted.

        For CTI: "APT28 uses X" vs "APT28 never uses X"
        """
        contradicted = set()
        # Simple heuristic: if two notes about the same entity have
        # negation markers in opposing directions, flag as contradiction
        negation_words = {"not", "never", "no longer", "ceased", "discontinued", "denied"}

        for i, n1 in enumerate(notes):
            for n2 in notes[i + 1 :]:
                # Use cached entities instead of re-extracting
                e1 = entity_cache.get(n1.id, {})
                e2 = entity_cache.get(n2.id, {})

                # Check entity overlap
                shared = False
                for etype in set(e1.keys()) & set(e2.keys()):
                    if set(e1[etype]) & set(e2[etype]):
                        shared = True
                        break

                if shared:
                    w1 = n1.content.raw.lower().split()
                    w2 = n2.content.raw.lower().split()
                    n1_neg = any(nw in " ".join(w1) for nw in negation_words)
                    n2_neg = any(nw in " ".join(w2) for nw in negation_words)

                    # One negated, one not = potential contradiction
                    if n1_neg != n2_neg:
                        # Newer note takes precedence (temporal authority)
                        if n1.created_at < n2.created_at:
                            contradicted.add(n1.id)
                        else:
                            contradicted.add(n2.id)

        return contradicted

    def get_stats(self) -> dict[str, Any]:
        """Get consolidation engine statistics."""
        return {
            "consolidation_count": self._consolidation_count,
            "detector_state": self._detector.get_state(),
        }


# ── Consolidation Middleware ────────────────────────────────────────────────


class ConsolidationMiddleware:
    """
    Drop-in middleware for MemoryManager.remember().

    Hooks into the write path to:
    1. Observe each new note for shift detection
    2. Trigger consolidation when semantic shift is detected
    3. Run consolidation asynchronously (non-blocking)

    Usage:
        mm = MemoryManager()
        cm = ConsolidationMiddleware(mm)
        # In remember(), call cm.before_write() before store.write_note()
    """

    def __init__(
        self,
        memory_manager,
        entity_shift_threshold: float = 0.4,
        topic_shift_threshold: float = 0.5,
        temporal_gap_hours: float = 4.0,
        auto_consolidate: bool = True,
    ):
        self._mm = memory_manager
        self._detector = SemanticShiftDetector(
            entity_shift_threshold=entity_shift_threshold,
            topic_shift_threshold=topic_shift_threshold,
            temporal_gap_hours=temporal_gap_hours,
        )
        self._engine = ConsolidationEngine(memory_manager, self._detector)
        self.auto_consolidate = auto_consolidate
        self._async_thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._logger = get_logger("zettelforge.consolidation.middleware")

    def before_write(
        self,
        note_entities: dict[str, list[str]],
        note_domain: str,
        note_time: datetime | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        """
        Call before writing a note to the store.

        Checks for semantic shift FIRST (before observing),
        then updates EPG state.

        Returns (should_consolidate, shift_metadata).
        """
        # Check for semantic shift BEFORE updating EPG
        # (so new entities aren't already in the state)
        is_shift, metadata = self._detector.detect_shift(note_entities, note_domain, note_time)

        # Now update EPG state with this note
        self._detector.observe(note_entities, note_domain)

        if is_shift and self.auto_consolidate:
            # Run consolidation asynchronously
            self._run_async_consolidation()

        return is_shift, metadata

    def _run_async_consolidation(self) -> None:
        """Run consolidation in a background thread."""
        with self._thread_lock:
            if self._async_thread and self._async_thread.is_alive():
                self._logger.info("consolidation_already_running_skipping")
                return

            def _consolidate():
                try:
                    report = self._engine.consolidate()
                    self._logger.info(
                        "consolidation_complete",
                        notes_examined=report.get("notes_examined", 0),
                        notes_consolidated=report.get("notes_consolidated", 0),
                        contradictions=report.get("contradictions_found", 0),
                        duration_ms=report.get("duration_ms", 0),
                    )
                except Exception as e:
                    self._logger.error("async_consolidation_failed", error=str(e), exc_info=True)

            self._async_thread = threading.Thread(target=_consolidate, daemon=True)
            self._async_thread.start()

    def consolidate_now(self) -> dict[str, Any]:
        """Manually trigger consolidation (blocking)."""
        return self._engine.consolidate(force=True)

    def get_stats(self) -> dict[str, Any]:
        """Get middleware statistics."""
        stats = self._engine.get_stats()
        stats["auto_consolidate"] = self.auto_consolidate
        return stats
