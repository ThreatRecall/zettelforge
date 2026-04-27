#!/usr/bin/env python3
"""One-shot compaction for ZettelForge LanceDB shards.

Motivation: RFC-009 Phase 0.5 live data (2026-04-24) established that 98.1%
of ``remember()`` wall-clock time is ``LanceStore._index_in_lance()`` on
shards with accumulated fragments. A CTI shard with 7,500+ uncompacted
fragments produced 60-second tail events. Fragment count grows linearly
with writes because ZettelForge has never called ``compact_files()``. This
tool is the surgical offline fix; the in-process periodic trigger is
tracked as a separate scope addition (RFC-009 Phase 1.5 / task #38).

Usage::

    # Dry-run against Vigil's workspace (inspect only, no mutation)
    python -m zettelforge.scripts.compact_lance \\
        --data-dir ~/.openclaw/workspace-vigil/.zettelforge_vigil \\
        --dry-run

    # Compact one shard only — --force is required for any mutating mode
    python -m zettelforge.scripts.compact_lance \\
        --data-dir ~/.openclaw/workspace-vigil/.zettelforge_vigil \\
        --table notes_cti --force

    # Compact every shard in the vectordb/ subtree
    python -m zettelforge.scripts.compact_lance \\
        --data-dir ~/.openclaw/workspace-vigil/.zettelforge_vigil --all --force

    # Use optimize() instead of compact_files() — also prunes old versions
    python -m zettelforge.scripts.compact_lance \\
        --data-dir ~/.openclaw/workspace-vigil/.zettelforge_vigil --all \\
        --mode optimize --force

Safety notes
------------
* ``compact_files()`` is safe alongside concurrent readers. Concurrent
  writers are in principle allowed by LanceDB but are not recommended
  for a one-shot run — prefer to quiesce agents writing to the table.
* Any mutating mode requires the explicit ``--force`` flag. Without it
  the script refuses to proceed and exits with code 2. Dry-run runs
  freely.
* ``optimize()`` with ``delete_unverified=True`` is NOT used here; that
  flag requires exclusive access and we don't assume it.
* Dry-run never touches the data. It only measures.
* A JSON report is emitted to stdout and, if ``--output`` is given, to
  the specified path. The report captures before/after fragment counts,
  on-disk size, row count, and elapsed compaction time per table.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TableReport:
    """One table's before/after compaction snapshot."""

    table: str
    mode: str  # "compact" | "optimize" | "dry-run"
    before_fragments: int = 0
    after_fragments: int | None = None
    before_bytes: int = 0
    after_bytes: int | None = None
    row_count: int | None = None
    elapsed_seconds: float | None = None
    error: str | None = None
    lance_metrics: dict[str, Any] = field(default_factory=dict)


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _count_fragments(lance_dir: Path) -> int:
    data_dir = lance_dir / "data"
    if not data_dir.is_dir():
        return 0
    return sum(1 for _ in data_dir.glob("*.lance"))


def _discover_tables(vectordb_dir: Path) -> list[str]:
    """Return the list of ``<name>`` for every ``<name>.lance/`` directory."""
    if not vectordb_dir.is_dir():
        return []
    return sorted(
        p.name[: -len(".lance")]
        for p in vectordb_dir.iterdir()
        if p.is_dir() and p.name.endswith(".lance")
    )


def _process_one(
    db: Any,
    vectordb_dir: Path,
    name: str,
    mode: str,
) -> TableReport:
    """Open a single table, capture before state, optionally compact, capture after."""
    report = TableReport(table=name, mode=mode)
    lance_dir = vectordb_dir / f"{name}.lance"

    report.before_fragments = _count_fragments(lance_dir)
    report.before_bytes = _dir_size_bytes(lance_dir)

    try:
        table = db.open_table(name)
        report.row_count = table.count_rows()
    except Exception as exc:  # pragma: no cover — surfaced to operator
        report.error = f"open_table failed: {exc}"
        return report

    if mode == "dry-run":
        return report

    t0 = time.perf_counter()
    try:
        metrics = table.optimize() if mode == "optimize" else table.compact_files()
        report.elapsed_seconds = round(time.perf_counter() - t0, 2)
        report.lance_metrics = _serialize_lance_metrics(metrics)
    except Exception as exc:
        report.error = f"{mode} failed after {round(time.perf_counter() - t0, 2)}s: {exc}"
        return report

    report.after_fragments = _count_fragments(lance_dir)
    report.after_bytes = _dir_size_bytes(lance_dir)
    return report


def _serialize_lance_metrics(metrics: Any) -> dict[str, Any]:
    """Best-effort serialize a Lance metrics object.

    Lance returns dataclass-shaped objects whose layout shifts between
    minor versions. Use ``dataclasses.asdict`` when applicable for nested
    fidelity, otherwise fall back to enumerating public attributes with a
    per-attribute ``try``/``except`` so a single misbehaving property
    cannot kill the script after compaction has already mutated the data.
    """
    if metrics is None:
        return {}
    if dataclasses.is_dataclass(metrics) and not isinstance(metrics, type):
        try:
            return dataclasses.asdict(metrics)
        except Exception:  # noqa: S110 — fall through to attribute enumeration
            pass
    out: dict[str, Any] = {}
    for k in dir(metrics):
        if k.startswith("_"):
            continue
        try:
            v = getattr(metrics, k)
        except Exception:  # noqa: S112 — skip attrs that error on getattr
            continue
        if callable(v):
            continue
        out[k] = v
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compact ZettelForge LanceDB shards to flatten insert-latency tails.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--data-dir",
        required=True,
        help="ZettelForge data directory (contains vectordb/).",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--table", help="Compact a single table by name, e.g. notes_cti.")
    group.add_argument(
        "--all",
        action="store_true",
        help="Compact every <name>.lance directory under vectordb/.",
    )
    p.add_argument(
        "--mode",
        choices=["compact", "optimize"],
        default="compact",
        help="compact_files() only, or full optimize() (compact + prune + reindex).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Measure before-state and exit without touching the tables.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "Required for any non-dry-run mutation. Acknowledges that "
            "writers should be quiesced; without it, mutating modes refuse "
            "to proceed."
        ),
    )
    p.add_argument(
        "--output",
        help="Write the JSON report to this path in addition to stdout.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        import lancedb
    except ImportError:
        print(
            "lancedb is required but could not be imported; install or repair this environment.",
            file=sys.stderr,
        )
        return 2

    data_dir = Path(args.data_dir).expanduser().resolve()
    vectordb_dir = data_dir / "vectordb"
    if not vectordb_dir.is_dir():
        print(f"No vectordb/ under {data_dir}", file=sys.stderr)
        return 2

    if args.table:
        tables = [args.table]
    elif args.all:
        tables = _discover_tables(vectordb_dir)
        if not tables:
            print(f"No .lance tables found under {vectordb_dir}", file=sys.stderr)
            return 2
    else:
        tables = _discover_tables(vectordb_dir)
        if not tables:
            print(f"No .lance tables found under {vectordb_dir}", file=sys.stderr)
            return 2
        print(
            "No --table or --all given; defaulting to --dry-run across all discovered tables.",
            file=sys.stderr,
        )
        args.dry_run = True

    mode = "dry-run" if args.dry_run else args.mode

    # Mutating runs require --force as an explicit safety acknowledgement.
    # compact_files() / optimize() are safe alongside concurrent readers but
    # not recommended alongside concurrent writers. Make the operator opt in.
    if mode != "dry-run" and not args.force:
        print(
            f"refusing to run mode={mode!r} without --force; pass --force to "
            "acknowledge that writers should be quiesced, or use --dry-run.",
            file=sys.stderr,
        )
        return 2

    db = lancedb.connect(str(vectordb_dir))

    reports: list[TableReport] = []
    for name in tables:
        print(f"[{mode}] {name} ...", file=sys.stderr)
        reports.append(_process_one(db, vectordb_dir, name, mode))

    payload: dict[str, Any] = {
        "data_dir": str(data_dir),
        "mode": mode,
        "tables": [asdict(r) for r in reports],
        "totals": {
            "before_fragments": sum(r.before_fragments for r in reports),
            # Use ``is not None`` rather than truthiness — a successful
            # compact-to-zero on an empty table would otherwise fall back
            # to the before-state and silently misreport the result.
            "after_fragments": sum(
                r.after_fragments if r.after_fragments is not None else r.before_fragments
                for r in reports
            ),
            "before_bytes": sum(r.before_bytes for r in reports),
            "after_bytes": sum(
                r.after_bytes if r.after_bytes is not None else r.before_bytes for r in reports
            ),
            "elapsed_seconds": round(sum(r.elapsed_seconds or 0.0 for r in reports), 2),
            "errors": [{"table": r.table, "error": r.error} for r in reports if r.error],
        },
    }

    text = json.dumps(payload, indent=2, default=str)
    print(text)
    if args.output:
        try:
            Path(args.output).expanduser().write_text(text, encoding="utf-8")
        except OSError as exc:
            # Stdout already carries the report — surface the write failure
            # without overriding the operation's success/failure exit code.
            print(f"warning: could not write report to {args.output}: {exc}", file=sys.stderr)

    return 0 if not payload["totals"]["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
