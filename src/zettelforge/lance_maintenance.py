"""Periodic LanceDB version-cleanup daemon (RFC-009 Phase 1.5).

On a write-heavy shard the dominant cost of
`MemoryStore._index_in_lance()` is LanceDB walking an unbounded
version chain on each insert. ``cleanup_old_versions()`` collapses
the chain back to the latest manifest; without periodic invocation
the chain grows at roughly two versions per ``remember()`` call,
reproducing the multi-GB bloat / 55-second tail latency that
motivated this RFC. See ``docs/rfcs/RFC-009-enrichment-pipeline-v2.md``
§"Phase 1.5 — LanceDB version cleanup" for the full attribution.

Design:

* One daemon thread per known ``notes_<domain>.lance`` table.
* `MemoryStore.__init__` discovers tables already on disk and starts
  threads for each. New domains created lazily by `_index_in_lance()`
  call :py:meth:`LanceVersionMaintenance.register_table` to spawn a
  thread idempotently.
* Each iteration sleeps ``cleanup_interval_minutes`` then reads
  ``cleanup_older_than_seconds`` (re-read each loop so operators can
  flip the value without restart). ``0`` for either knob disables
  the loop or skips a single iteration respectively.
* Per-cleanup OCSF telemetry: ``lance_cleanup_old_versions`` with
  ``bytes_freed``, ``versions_pruned``, ``elapsed_seconds``,
  rendered as a class_uid 1001 (File Activity) event so it lives
  alongside the existing ``ocsf_file_activity`` stream.
* Best-effort: any exception inside the cleanup call is caught,
  logged at ``warning``, and the thread continues with the next
  interval. Maintenance failure must never crash the agent.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from zettelforge.log import get_logger

_logger = get_logger("zettelforge.lance_maintenance")


class LanceVersionMaintenance:
    """Per-table version-cleanup daemon for a LanceDB connection.

    Thread-safe registration; threads are daemon=True so process exit
    does not block on them. Stop the loop cleanly via :py:meth:`stop`
    if you want graceful drain (e.g. from a future
    ``MemoryManager.shutdown()`` orchestrator).
    """

    def __init__(
        self,
        db: Any,
        interval_minutes_provider: Callable[[], int],
        older_than_seconds_provider: Callable[[], int],
        table_root: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """
        Parameters
        ----------
        db
            A ``lancedb.DBConnection`` (or duck-typed equivalent with
            ``open_table``). May be ``None`` — in that case
            :py:meth:`start` is a no-op so callers don't need to gate
            on lancedb availability.
        interval_minutes_provider
            Zero-argument callable returning the current
            ``cleanup_interval_minutes`` config value. Re-evaluated
            each loop iteration so operators can toggle without
            restart.
        older_than_seconds_provider
            Same pattern for ``cleanup_older_than_seconds``.
        table_root
            Optional directory that holds ``<name>.lance/`` subdirs.
            Used by :py:meth:`start` to enumerate existing tables.
        clock, sleep
            Injected for tests; default to ``time.monotonic``/``time.sleep``.
        """
        self._db = db
        self._interval_provider = interval_minutes_provider
        self._older_than_provider = older_than_seconds_provider
        self._table_root = table_root
        self._clock = clock
        self._sleep = sleep

        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._stop_event = threading.Event()

    # ── Lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Discover existing tables and spawn one thread per table.

        Idempotent. Safe to call when ``db`` is None or
        ``cleanup_interval_minutes`` is 0 — both paths are no-ops.
        """
        if self._db is None:
            _logger.debug("lance_maintenance_skipped", reason="no_lancedb")
            return
        if self._interval_provider() <= 0:
            _logger.info("lance_maintenance_disabled_at_start", reason="interval_zero")
            return
        if self._table_root is None:
            return
        if not Path(self._table_root).is_dir():
            return
        for entry in Path(self._table_root).iterdir():
            if entry.is_dir() and entry.name.endswith(".lance"):
                self.register_table(entry.name[: -len(".lance")])

    def register_table(self, table_name: str) -> None:
        """Start a maintenance thread for ``table_name`` if not already running.

        Called from ``MemoryStore._index_in_lance()`` every time a note
        is written, so domains created after :py:meth:`start` (lazy
        creation pattern) also get coverage. Idempotent.
        """
        if self._db is None:
            return
        if self._interval_provider() <= 0:
            return
        with self._lock:
            existing = self._threads.get(table_name)
            if existing is not None and existing.is_alive():
                return
            t = threading.Thread(
                target=self._run_for_table,
                args=(table_name,),
                name=f"lance-cleanup-{table_name}",
                daemon=True,
            )
            self._threads[table_name] = t
            t.start()
            _logger.info("lance_maintenance_thread_started", table=table_name)

    def stop(self, timeout: float | None = None) -> None:
        """Signal all threads to exit on their next loop boundary.

        Threads check :py:attr:`_stop_event` between sleep wakeups.
        Pass ``timeout`` to bound the join.
        """
        self._stop_event.set()
        with self._lock:
            threads = list(self._threads.values())
        for t in threads:
            t.join(timeout=timeout)

    # ── Internals ───────────────────────────────────────────────────────

    def _run_for_table(self, table_name: str) -> None:
        while not self._stop_event.is_set():
            interval_min = max(0, int(self._interval_provider()))
            if interval_min <= 0:
                # Operator turned cleanup off. Sleep a small grace period
                # then re-check; do not exit, so re-enabling at runtime
                # picks up without restart.
                if self._stop_event.wait(60):
                    return
                continue

            # Sleep first so a freshly-created table isn't immediately
            # cleaned (avoids a useless no-op on tables with one row).
            if self._stop_event.wait(interval_min * 60):
                return

            self._run_one(table_name)

    def _run_one(self, table_name: str) -> None:
        older_than_s = max(0, int(self._older_than_provider()))
        if older_than_s <= 0:
            _logger.debug("lance_cleanup_skipped", table=table_name, reason="older_than_zero")
            return

        size_before = _safe_dir_size(self._table_dir(table_name))
        t0 = self._clock()
        try:
            table = self._db.open_table(table_name)
            stats = table.cleanup_old_versions(older_than=timedelta(seconds=older_than_s))
        except Exception as exc:
            elapsed_s = round(self._clock() - t0, 3)
            _logger.warning(
                "lance_cleanup_failed",
                table=table_name,
                elapsed_seconds=elapsed_s,
                error=type(exc).__name__,
                exc_info=True,
            )
            return

        elapsed_s = round(self._clock() - t0, 3)
        size_after = _safe_dir_size(self._table_dir(table_name))
        bytes_freed = max(0, size_before - size_after)
        versions_pruned = _extract_versions_pruned(stats)

        _logger.info(
            "lance_cleanup_old_versions",
            table=table_name,
            bytes_freed=bytes_freed,
            versions_pruned=versions_pruned,
            elapsed_seconds=elapsed_s,
        )

    def _table_dir(self, table_name: str) -> Path | None:
        if self._table_root is None:
            return None
        return Path(self._table_root) / f"{table_name}.lance"


def _safe_dir_size(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                continue
    return total


def _extract_versions_pruned(stats: Any) -> int | None:
    """LanceDB returns a metrics object that varies by version.

    Best-effort: try common attribute names; otherwise return ``None``
    rather than fabricate a number.
    """
    if stats is None:
        return None
    for attr in ("old_versions", "versions_removed", "manifests_removed"):
        val = getattr(stats, attr, None)
        if isinstance(val, int):
            return val
    return None
