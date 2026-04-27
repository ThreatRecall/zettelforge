"""Streamlit dashboard for ZettelForge telemetry (RFC-007 / US-005).

Optional visualization layer. Reads the raw telemetry JSONL at
``~/.amem/telemetry/telemetry_YYYY-MM-DD.jsonl`` and renders:

    * Query volume over time (daily recall + synthesis counts)
    * Latency trends (p50, p95 for recall and synthesis)
    * Tier distribution of retrieved notes
    * Utility score trend from feedback + human_eval events
    * Unused notes warning (notes in feedback that haven't appeared in
      any recall result during the window)

Run locally::

    pip install streamlit pandas
    streamlit run src/zettelforge/scripts/telemetry_dashboard.py

Streamlit and pandas are soft dependencies — imported at module load so
users get a clear error if they're missing, rather than a cryptic
ImportError deep inside a rendering call. They're optional by design
(aggregator + sampler cover non-visual flows).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError as e:  # pragma: no cover
    raise SystemExit("telemetry_dashboard requires pandas. Install with: pip install pandas") from e

# streamlit is imported lazily inside render() — pure compute functions
# below stay testable without Streamlit installed.


DEFAULT_DATA_DIR = "~/.amem/telemetry"


# ── Data loading ─────────────────────────────────────────────────────────


def load_events(data_dir: Path) -> list[dict[str, Any]]:
    """Load all telemetry events across every ``telemetry_*.jsonl`` file.

    Tolerates corrupt lines so one bad entry doesn't break the dashboard.
    """
    events: list[dict[str, Any]] = []
    if not data_dir.exists():
        return events
    for path in sorted(data_dir.glob("telemetry_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def to_dataframe(events: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize events into a DataFrame with a ``date`` column for grouping."""
    rows: list[dict[str, Any]] = []
    for ev in events:
        ts = ev.get("timestamp")
        if isinstance(ts, (int, float)):
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        else:
            date_str = ""
        rows.append(
            {
                "event_type": ev.get("event_type"),
                "date": date_str,
                "duration_ms": ev.get("duration_ms"),
                "confidence": ev.get("confidence"),
                "actor": ev.get("actor"),
                "query_id": ev.get("query_id"),
                "result_count": ev.get("result_count"),
                "utility": ev.get("utility"),
                "note_id": ev.get("note_id"),
                "tier_distribution": ev.get("tier_distribution"),
                "notes_list": ev.get("notes"),
            }
        )
    return pd.DataFrame(rows)


# ── Computations (pure functions — tested in test_telemetry_dashboard.py) ──


def daily_volume(df: pd.DataFrame) -> pd.DataFrame:
    """Count recall vs synthesis events per day."""
    subset = df[df["event_type"].isin(["recall", "synthesis"])]
    if subset.empty:
        return pd.DataFrame(columns=["date", "event_type", "count"])
    grouped = subset.groupby(["date", "event_type"]).size().reset_index(name="count")
    return grouped


def latency_percentiles(df: pd.DataFrame, event_type: str) -> dict[str, float]:
    """Return p50 / p95 / max latency for ``event_type`` (recall or synthesis)."""
    subset = df[(df["event_type"] == event_type) & df["duration_ms"].notna()]
    if subset.empty:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "p50": float(subset["duration_ms"].quantile(0.50)),
        "p95": float(subset["duration_ms"].quantile(0.95)),
        "max": float(subset["duration_ms"].max()),
    }


def tier_distribution(df: pd.DataFrame) -> dict[str, int]:
    """Sum tier counts across all DEBUG-mode recall events."""
    totals: Counter[str] = Counter()
    for dist in df["tier_distribution"].dropna():
        if isinstance(dist, dict):
            for tier, count in dist.items():
                totals[tier] += int(count)
    return dict(totals)


def utility_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Daily mean utility across feedback events (auto + explicit)."""
    feedback = df[(df["event_type"] == "feedback") & df["utility"].notna()]
    if feedback.empty:
        return pd.DataFrame(columns=["date", "mean_utility"])
    return feedback.groupby("date")["utility"].mean().reset_index(name="mean_utility")


def unused_notes(df: pd.DataFrame) -> list[str]:
    """Notes that appear in at least one recall result but never get cited.

    Useful signal: a note retrieved repeatedly but never cited in
    synthesis is probably a false-positive retrieval candidate — worth
    inspecting or tier-downgrading.
    """
    if df.empty:
        return []
    retrieved_ids: set[str] = set()
    if "notes_list" in df.columns:
        for notes_list in df["notes_list"].dropna():
            if isinstance(notes_list, list):
                for n in notes_list:
                    if isinstance(n, dict) and n.get("id"):
                        retrieved_ids.add(n["id"])

    cited_ids: set[str] = set()
    if "event_type" in df.columns:
        feedback = df[df["event_type"] == "feedback"]
        for _, row in feedback.iterrows():
            utility = row.get("utility")
            nid = row.get("note_id")
            if nid and utility is not None and int(utility) >= 4:
                cited_ids.add(nid)

    return sorted(retrieved_ids - cited_ids)


# ── Streamlit UI ─────────────────────────────────────────────────────────


def render(data_dir: Path) -> None:  # pragma: no cover — exercised by manual run
    """Render the dashboard at ``http://localhost:8501``."""
    try:
        import streamlit as st
    except ImportError as e:
        raise SystemExit(
            "telemetry_dashboard render() requires streamlit. Install with: pip install streamlit"
        ) from e
    st.set_page_config(page_title="ZettelForge Telemetry", layout="wide")
    st.title("ZettelForge Telemetry")
    st.caption(f"Data directory: `{data_dir}`")

    events = load_events(data_dir)
    if not events:
        st.warning(
            "No telemetry events found. Make sure "
            "`ZETTELFORGE_LOG_LEVEL=DEBUG` is set and that MemoryManager "
            "has executed at least one recall()."
        )
        return

    df = to_dataframe(events)
    st.metric("Total events", len(df))

    col1, col2, col3 = st.columns(3)
    col1.metric("Recalls", int((df["event_type"] == "recall").sum()))
    col2.metric("Syntheses", int((df["event_type"] == "synthesis").sum()))
    col3.metric("Feedback", int((df["event_type"] == "feedback").sum()))

    # Query volume
    st.subheader("Query volume over time")
    volume = daily_volume(df)
    if not volume.empty:
        pivot = volume.pivot(index="date", columns="event_type", values="count").fillna(0)
        st.bar_chart(pivot)
    else:
        st.info("No recall or synthesis events yet.")

    # Latency trends
    st.subheader("Latency (ms)")
    recall_lat = latency_percentiles(df, "recall")
    synth_lat = latency_percentiles(df, "synthesis")
    latency_df = pd.DataFrame(
        {
            "recall": [recall_lat["p50"], recall_lat["p95"], recall_lat["max"]],
            "synthesis": [synth_lat["p50"], synth_lat["p95"], synth_lat["max"]],
        },
        index=["p50", "p95", "max"],
    )
    st.dataframe(latency_df)

    # Tier distribution
    st.subheader("Tier distribution (retrieved notes, DEBUG-mode only)")
    tiers = tier_distribution(df)
    if tiers:
        st.bar_chart(pd.DataFrame.from_dict(tiers, orient="index", columns=["count"]))
    else:
        st.info("No DEBUG-mode recall events — enable ZETTELFORGE_LOG_LEVEL=DEBUG to capture.")

    # Utility trend
    st.subheader("Utility score trend")
    util = utility_trend(df)
    if not util.empty:
        st.line_chart(util.set_index("date"))
    else:
        st.info("No feedback events yet.")

    # Unused notes warning
    st.subheader("Unused notes")
    unused = unused_notes(df)
    if unused:
        st.warning(
            f"{len(unused)} notes appeared in recall results but were never cited "
            "(utility < 4 across all feedback)."
        )
        with st.expander("Show unused note IDs"):
            st.write(unused)
    else:
        st.success("All retrieved notes have at least one citation.")


def main() -> None:  # pragma: no cover
    data_dir = Path(os.path.expanduser(os.environ.get("ZF_TELEMETRY_DIR", DEFAULT_DATA_DIR)))
    render(data_dir)


if __name__ == "__main__":
    main()
