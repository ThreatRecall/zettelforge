#!/usr/bin/env python3
"""Summarize daily telemetry JSONL into actionable operational metrics.

Reads ``~/.amem/telemetry/telemetry_YYYY-MM-DD.jsonl`` and outputs a JSON
report to ``~/.amem/telemetry/daily_report_YYYY-MM-DD.json``.

    python -m zettelforge.scripts.telemetry_aggregator  --date YYYY-MM-DD
    python -m zettelforge.scripts.telemetry_aggregator            # yesterday

No crash if the telemetry file is missing — produces an empty report with
``null`` fields.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass
class DailyMetrics:
    """Aggregated telemetry report for a single day."""

    date: str
    total_queries: int | None = None
    total_synthesis: int | None = None
    avg_recall_latency_ms: float | None = None
    avg_synthesis_latency_ms: float | None = None
    avg_confidence: float | None = None
    notes_per_query: float | None = None
    tier_distribution: dict[str, int] = field(default_factory=dict)
    feedback_count: int | None = None
    avg_utility: float | None = None
    top_utility_notes: list[str] = field(default_factory=list)
    unused_notes_count: int | None = None


def _load_events(data_dir: str, date_str: str) -> list[dict[str, Any]]:
    """Load today's telemetry JSONL, return empty list if missing."""
    path = Path(data_dir) / f"telemetry_{date_str}.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            events.append(json.loads(line))
    return events


def _aggregate(events: list[dict[str, Any]], date_str: str, data_dir: str) -> dict[str, Any]:
    """Aggregate all events for one day into the daily report schema."""
    if not events:
        report = DailyMetrics(date=date_str)
        return asdict(report)

    recall_events = [e for e in events if e["event_type"] == "recall"]
    synthesis_events = [e for e in events if e["event_type"] == "synthesis"]
    feedback_events = [e for e in events if e["event_type"] == "feedback"]

    # Unique query count (one query_id = one query)
    unique_queries = len(set(e["query_id"] for e in recall_events))

    # Latency averages
    avg_recall_latency = (
        sum(e["duration_ms"] for e in recall_events) / len(recall_events) if recall_events else None
    )
    avg_synthesis_latency = (
        sum(e["duration_ms"] for e in synthesis_events) / len(synthesis_events)
        if synthesis_events
        else None
    )

    # Average confidence from synthesis events
    confidences = []
    for ev in synthesis_events:
        debug = ev.get("confidence")
        if debug is not None:
            confidences.append(debug)
    avg_confidence = sum(confidences) / len(confidences) if confidences else None

    # Notes per query
    notes_per_query = (
        sum(e.get("result_count", 0) for e in recall_events) / unique_queries
        if unique_queries > 0
        else None
    )

    # Tier distribution (merge from all events that have it)
    tier_dist: Counter = Counter()
    for ev in recall_events:
        td = ev.get("tier_distribution")
        if td and isinstance(td, dict):
            tier_dist.update(td)
        # Also count from per-note tier fields
        for note in ev.get("notes", []):
            tier = note.get("tier")
            if tier:
                tier_dist[tier] += 1

    # Feedback stats
    feedback_count = len(feedback_events)
    if feedback_events:
        avg_utility = sum(e.get("utility", 0) for e in feedback_events) / feedback_count
        # Top 10 utility notes
        note_utilities: Counter = Counter()
        for e in feedback_events:
            nid = e.get("note_id")
            u = e.get("utility", 0)
            if nid and u > 0:
                note_utilities[nid] += u
        top_utility = [nid for nid, _ in note_utilities.most_common(10)]
    else:
        avg_utility = None
        top_utility = []

    # Unused notes: notes that were retrieved but never cited in synthesis
    all_retrieved_ids = set()
    for ev in recall_events:
        for note in ev.get("notes", []):
            nid = note.get("id")
            if nid:
                all_retrieved_ids.add(nid)

    all_cited_ids = set()
    for ev in synthesis_events:
        for nid in ev.get("cited_notes", []):
            all_cited_ids.add(nid)

    unused_count = len(all_retrieved_ids - all_cited_ids) if all_retrieved_ids else None

    return {
        "date": date_str,
        "total_queries": unique_queries,
        "total_synthesis": len(synthesis_events),
        "avg_recall_latency_ms": round(avg_recall_latency, 2) if avg_recall_latency else None,
        "avg_synthesis_latency_ms": round(avg_synthesis_latency, 2)
        if avg_synthesis_latency
        else None,
        "avg_confidence": round(avg_confidence, 4) if avg_confidence else None,
        "notes_per_query": round(notes_per_query, 2) if notes_per_query else None,
        "tier_distribution": dict(sorted(tier_dist.items())),
        "feedback_count": feedback_count,
        "avg_utility": round(avg_utility, 2) if avg_utility else None,
        "top_utility_notes": top_utility,
        "unused_notes_count": unused_count,
    }


def main(date_str: str | None = None) -> None:
    data_dir = Path.home() / ".amem" / "telemetry"

    if date_str is None:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    report = _aggregate(_load_events(str(data_dir), date_str), date_str, str(data_dir))

    output_path = data_dir / f"daily_report_{date_str}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str))

    # Also print to stdout for cron compatibility
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aggregate daily telemetry into a JSON report")
    parser.add_argument(
        "--date", default=None, help="Date to aggregate (YYYY-MM-DD), defaults to yesterday"
    )
    args = parser.parse_args()
    main(args.date)
