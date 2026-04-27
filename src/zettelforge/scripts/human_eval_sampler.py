"""Human evaluation sampler for US-004.

Selects 20 random synthesis briefings from telemetry JSONL files and
formats them as a structured Markdown template for Roland's monthly review.

    python -m zettelforge.scripts.human_eval_sampler --date YYYY-MM-DD
    python -m zettelforge.scripts.human_eval_sampler --dates-dir ~/.amem/telemetry --count 20

Outputs to stdout as Markdown. Append human_eval events to telemetry via
--write-events (writes to ~/.amem/telemetry/human_eval.jsonl).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _read_telemetry(data_dir: str) -> list[dict[str, Any]]:
    """Read all synthesis events from all daily telemetry JSONL files."""
    events: list[dict[str, Any]] = []
    base = Path(data_dir)
    for path in sorted(base.glob("telemetry_*.jsonl")):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("event_type") == "synthesis":
                events.append(ev)
    return events


def _format_briefing(event: dict[str, Any], index: int) -> str:
    """Format a single synthesis event as a reviewable briefing."""
    query = event.get("query", "(no query text)")
    confidence = event.get("confidence")
    sources_count = event.get("result_count", 0)
    duration_ms = event.get("duration_ms", 0)
    cited = event.get("cited_notes", [])
    actor = event.get("actor", "unknown")
    ts = event.get("ts", event.get("timestamp", "unknown"))

    lines = [f"### Briefing #{index}\n"]
    lines.append(f"- **Query:** `{query}`")
    lines.append(f"- **Agent:** {actor}")
    lines.append(f"- **Sources:** {sources_count}")
    lines.append(f"- **Cited Notes:** {len(cited)}")
    lines.append(f"- **Confidence:** {confidence}")
    lines.append(f"- **Latency:** {duration_ms}ms")
    lines.append(f"- **Timestamp:** {ts}")
    lines.append("")
    lines.append(f"**Notes cited:** `{cited}`")
    lines.append("")
    return "\n".join(lines)


def _build_rubric_template() -> str:
    """Build the 6-question human evaluation rubric template."""
    rubric = """
## Human Evaluation Rubric (1-5 scale)

| # | Criterion | Score | Notes |
|---|-----------|-------|-------|
| 1 | **Recall relevance** — Did the recall surface relevant, high-quality notes? | | |
| 2 | **Synthesis value** — Was the synthesized briefing useful and actionable for CTI analysis? | | |
| 3 | **Critical notes missing** — Were any important notes not retrieved? If so, what might have helped? | | |
| 4 | **Unsupported claims** — Did the synthesis make claims not backed by the retrieved notes? | | |
| 5 | **Latency perception** — Was the response time acceptable given the depth of analysis? | | |
| 6 | **Overall trust** — Would you trust this briefing for operational CTI analysis? | | |
"""
    return rubric.strip()


def main(
    dates_dir: str = str(Path.home() / ".amem" / "telemetry"),
    date_str: str | None = None,
    count: int = 20,
    write_events: bool = False,
) -> str:
    """Select random briefings and format for human review.

    Returns the formatted Markdown string.
    """
    if date_str:
        # Single date mode
        path = Path(dates_dir) / f"telemetry_{date_str}.jsonl"
        if not path.exists():
            print(f"No telemetry file found for {date_str}", file=sys.stderr)
            return ""
        events = [json.loads(ln) for ln in path.read_text().strip().split("\n") if ln.strip()]
        events = [e for e in events if e.get("event_type") == "synthesis"]
    else:
        events = _read_telemetry(dates_dir)

    if not events:
        print("No synthesis events found.", file=sys.stderr)
        return ""

    k = min(count, len(events))
    selected = random.sample(events, k)

    # Sort by timestamp for temporal ordering
    selected.sort(key=lambda e: e.get("ts", e.get("timestamp", "")))

    output_lines = [
        f"# Human Evaluation — {k} Random Briefings",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Sources: {len(events)} total synthesis events across telemetry files",
        "",
        _build_rubric_template(),
        "",
        "---",
        "",
        "# Review Briefings",
        "",
    ]

    for i, ev in enumerate(selected, 1):
        output_lines.append(_format_briefing(ev, i))
        output_lines.append("---")
        output_lines.append("")

    result = "\n".join(output_lines)

    if write_events:
        eval_path = Path(dates_dir) / "human_eval.jsonl"
        eval_path.parent.mkdir(parents=True, exist_ok=True)
        for ev in selected:
            record = {
                "event_type": "human_eval",
                "evaluated_at": datetime.now().isoformat(),
                "source_query": ev.get("query", ""),
                "source_ts": ev.get("ts", ev.get("timestamp", "")),
            }
            eval_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    return result


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Select random synthesis briefings for human evaluation"
    )
    parser.add_argument(
        "--dates-dir",
        default=str(Path.home() / ".amem" / "telemetry"),
        help="Directory containing telemetry JSONL files",
    )
    parser.add_argument("--date", default=None, help="Single date to evaluate (YYYY-MM-DD)")
    parser.add_argument(
        "--count", type=int, default=20, help="Number of random briefings to select"
    )
    parser.add_argument(
        "--write-events", action="store_true", help="Write human_eval events to telemetry JSONL"
    )
    args = parser.parse_args()

    result = main(
        dates_dir=args.dates_dir,
        date_str=args.date,
        count=args.count,
        write_events=args.write_events,
    )
    print(result)


if __name__ == "__main__":
    cli()
