"""Operational telemetry for ZettelForge recall/synthesis quality monitoring.

Captures per-query metrics alongside the existing OCSF structured logging
(see ``ocsf.py``). When DEBUG level is enabled on the ``zettelforge.telemetry``
logger, records detailed per-note metadata and citation-based feedback; at
INFO or higher, records aggregated counts and basic timing only.

Data is written as JSONL to ``~/.amem/telemetry/telemetry_YYYY-MM-DD.jsonl``,
one file per day. Raw note content is never persisted — only IDs, tiers,
source types, domains, and ranks. Query text is truncated to 200 characters
at INFO and 500 at DEBUG.

This module is standalone for Phase 1 (RFC-007 / US-001). ``MemoryManager``
integration ships in US-002.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_QUERY_TTL_SECONDS = 3600  # evict tracked queries older than this on start_query


@dataclass
class _QueryContext:
    """In-memory bookkeeping for an active query. Not persisted."""

    query: str
    actor: str | None
    start_ts: float
    results: list[Any] = field(default_factory=list)


class TelemetryCollector:
    """Collect per-query recall and synthesis telemetry.

    Typical flow from ``MemoryManager``::

        qid = telemetry.start_query(query, actor="vigil")
        results = run_retrieval(...)
        telemetry.log_recall(qid, results, intent="factual", ...)
        result = run_synthesis(...)
        telemetry.log_synthesis(qid, result, synthesis_latency_ms=...)
        telemetry.auto_feedback_from_synthesis(qid, results, result)
    """

    def __init__(
        self,
        data_dir: str = "~/.amem/telemetry",
        logger_name: str = "zettelforge.telemetry",
    ) -> None:
        self._data_dir = Path(os.path.expanduser(data_dir))
        self._logger_name = logger_name
        self._write_lock = threading.Lock()
        self._queries: dict[str, _QueryContext] = {}
        self._queries_lock = threading.Lock()

    # ── Query lifecycle ────────────────────────────────────────────────

    def start_query(self, query: str, actor: str | None = None) -> str:
        """Begin tracking a query. Returns ``query_id`` (UUID4 hex) for correlation.

        Evicts tracked queries older than 1 hour on each call so memory use
        stays bounded even if callers never call ``log_synthesis``.
        """
        query_id = uuid.uuid4().hex
        now = time.time()
        ctx = _QueryContext(query=query, actor=actor, start_ts=now)
        with self._queries_lock:
            self._queries[query_id] = ctx
            # Evict stale contexts
            cutoff = now - _QUERY_TTL_SECONDS
            stale = [qid for qid, c in self._queries.items() if c.start_ts < cutoff]
            for qid in stale:
                del self._queries[qid]
        return query_id

    def _get_context(self, query_id: str) -> _QueryContext | None:
        with self._queries_lock:
            return self._queries.get(query_id)

    # ── Recall / synthesis events ──────────────────────────────────────

    def log_recall(
        self,
        query_id: str,
        results: list[Any],
        intent: str,
        vector_latency_ms: int = 0,
        graph_latency_ms: int = 0,
    ) -> None:
        """Write a recall event to today's telemetry JSONL.

        ``results`` is a list of MemoryNote-shaped objects; only metadata
        (id, tier, source_type, domain, rank) is recorded — never raw content.
        DEBUG-gated fields include the per-note metadata list and latency
        breakdown.
        """
        debug = self._debug_enabled()
        ctx = self._get_context(query_id)
        duration_ms = self._duration_ms(ctx)
        query_text = self._truncate_query(ctx.query if ctx else "", debug)
        actor = ctx.actor if ctx else None

        event: dict[str, Any] = {
            "event_type": "recall",
            "timestamp": time.time(),
            "query_id": query_id,
            "actor": actor,
            "query": query_text,
            "result_count": len(results),
            "duration_ms": duration_ms,
        }
        if debug:
            event.update(
                {
                    "intent": _stringify_intent(intent),
                    "tier_distribution": _tier_distribution(results),
                    "vector_latency_ms": int(vector_latency_ms),
                    "graph_latency_ms": int(graph_latency_ms),
                    "notes": [_note_summary(n, rank=i) for i, n in enumerate(results)],
                }
            )
        self._append(event)

        if ctx is not None:
            with self._queries_lock:
                ctx.results = list(results)

    def log_synthesis(
        self,
        query_id: str,
        result: dict[str, Any],
        synthesis_latency_ms: int = 0,
    ) -> None:
        """Write a synthesis event to today's telemetry JSONL.

        ``result`` is the dict returned by ``SynthesisGenerator.synthesize()``.
        The collector extracts ``confidence``, ``sources_count``, and the
        list of cited note IDs defensively — it tolerates missing keys so
        it never breaks the caller.
        """
        debug = self._debug_enabled()
        ctx = self._get_context(query_id)
        duration_ms = self._duration_ms(ctx)
        query_text = self._truncate_query(ctx.query if ctx else "", debug)
        actor = ctx.actor if ctx else None

        cited_notes = _cited_note_ids(result)
        sources_count = _sources_count(result)

        event: dict[str, Any] = {
            "event_type": "synthesis",
            "timestamp": time.time(),
            "query_id": query_id,
            "actor": actor,
            "query": query_text,
            "result_count": sources_count,
            "duration_ms": duration_ms,
        }
        if debug:
            event.update(
                {
                    "confidence": _confidence(result),
                    "sources_count": sources_count,
                    "cited_notes": cited_notes,
                    "synthesis_latency_ms": int(synthesis_latency_ms),
                }
            )
        self._append(event)

    def log_feedback(
        self,
        query_id: str,
        note_id: str,
        utility: int,
        agent: str | None = None,
    ) -> None:
        """Write an explicit feedback event. Utility is 1–5."""
        event = {
            "event_type": "feedback",
            "timestamp": time.time(),
            "query_id": query_id,
            "note_id": note_id,
            "utility": int(utility),
            "agent": agent,
        }
        self._append(event)

    def auto_feedback_from_synthesis(
        self,
        query_id: str,
        retrieved_notes: list[Any],
        synthesis_result: dict[str, Any],
    ) -> None:
        """Infer utility from citation patterns. DEBUG mode only.

        Cited notes → utility=4 (likely useful). Retrieved-but-uncited
        notes → utility=2 (possibly irrelevant). Writes one feedback event
        per retrieved note.
        """
        if not self._debug_enabled():
            return
        cited = set(_cited_note_ids(synthesis_result))
        ctx = self._get_context(query_id)
        agent = ctx.actor if ctx else None
        for note in retrieved_notes:
            nid = _note_id(note)
            if nid is None:
                continue
            utility = 4 if nid in cited else 2
            self.log_feedback(query_id, nid, utility, agent=agent)

    # ── Internals ──────────────────────────────────────────────────────

    def _debug_enabled(self) -> bool:
        return logging.getLogger(self._logger_name).isEnabledFor(logging.DEBUG)

    def _duration_ms(self, ctx: _QueryContext | None) -> int:
        if ctx is None:
            return 0
        return int((time.time() - ctx.start_ts) * 1000)

    def _truncate_query(self, query: str, debug: bool) -> str:
        limit = 500 if debug else 200
        return query[:limit]

    def _path_for(self, when: datetime | None = None) -> Path:
        when = when or datetime.now()
        return self._data_dir / f"telemetry_{when.strftime('%Y-%m-%d')}.jsonl"

    def _append(self, event: dict[str, Any]) -> None:
        """Serialize and append one JSONL line. Creates data_dir on first write."""
        path = self._path_for()
        line = json.dumps(event, default=str)
        with self._write_lock:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


# ── Helpers (duck-typed; avoid importing MemoryNote to keep this standalone) ──


def _note_id(note: Any) -> str | None:
    return getattr(note, "id", None)


def _note_summary(note: Any, rank: int) -> dict[str, Any]:
    metadata = getattr(note, "metadata", None)
    content = getattr(note, "content", None)
    return {
        "id": getattr(note, "id", None),
        "rank": rank,
        "tier": getattr(metadata, "tier", None) if metadata is not None else None,
        "source_type": getattr(content, "source_type", None) if content is not None else None,
        "domain": getattr(metadata, "domain", None) if metadata is not None else None,
    }


def _tier_distribution(notes: list[Any]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for note in notes:
        metadata = getattr(note, "metadata", None)
        tier = getattr(metadata, "tier", None) if metadata is not None else None
        if tier is None:
            continue
        dist[tier] = dist.get(tier, 0) + 1
    return dist


def _stringify_intent(intent: Any) -> str:
    # Accept a plain string or an enum (e.g. QueryIntent.FACTUAL).
    value = getattr(intent, "value", None)
    if value is not None:
        return str(value)
    return str(intent)


def _cited_note_ids(synthesis_result: dict[str, Any]) -> list[str]:
    sources = synthesis_result.get("sources", [])
    ids: list[str] = []
    for source in sources:
        if isinstance(source, dict):
            nid = source.get("note_id")
        else:
            nid = getattr(source, "note_id", None)
        if nid:
            ids.append(nid)
    return ids


def _sources_count(synthesis_result: dict[str, Any]) -> int:
    metadata = synthesis_result.get("metadata")
    if isinstance(metadata, dict) and "sources_count" in metadata:
        return int(metadata["sources_count"])
    return len(synthesis_result.get("sources", []) or [])


def _confidence(synthesis_result: dict[str, Any]) -> float | None:
    # Synthesis schema varies — confidence may sit under "synthesis"
    # (per schema in synthesis_generator.py) or at the top level.
    synthesis = synthesis_result.get("synthesis")
    if isinstance(synthesis, dict) and synthesis.get("confidence") is not None:
        return float(synthesis["confidence"])
    if synthesis_result.get("confidence") is not None:
        return float(synthesis_result["confidence"])
    return None


# ── Singleton ──────────────────────────────────────────────────────────

_telemetry_instance: TelemetryCollector | None = None
_telemetry_singleton_lock = threading.Lock()


def get_telemetry() -> TelemetryCollector:
    """Return the process-wide TelemetryCollector instance (lazy singleton)."""
    global _telemetry_instance
    if _telemetry_instance is None:
        with _telemetry_singleton_lock:
            if _telemetry_instance is None:
                _telemetry_instance = TelemetryCollector()
    return _telemetry_instance


def reset_telemetry_for_testing() -> None:
    """Reset the singleton — test hook only; not for production use."""
    global _telemetry_instance
    with _telemetry_singleton_lock:
        _telemetry_instance = None
