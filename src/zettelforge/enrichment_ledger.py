"""Deferred enrichment job ledger primitives.

RFC-018 starts with a storage-backed ledger so queued enrichment work has a
stable, observable identity before later releases make ``flush()`` fully
ledger-aware.  The model intentionally stores metadata only: no prompts, rule
bodies, raw note content, or exception text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

EnrichmentJobState = Literal[
    "queued", "running", "succeeded", "failed", "dead_lettered", "cancelled"
]

TERMINAL_ENRICHMENT_STATES: frozenset[str] = frozenset(
    {"succeeded", "failed", "dead_lettered", "cancelled"}
)


@dataclass(frozen=True)
class EnrichmentJobRecord:
    """Persisted metadata for one deferred enrichment job."""

    job_id: str
    note_id: str
    job_type: str
    state: EnrichmentJobState
    attempt_count: int = 0
    last_error_code: str = ""
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    domain: str = ""
    content_len: int = 0

    @classmethod
    def new(
        cls,
        *,
        job_id: str,
        note_id: str,
        job_type: str,
        domain: str = "",
        content_len: int = 0,
    ) -> EnrichmentJobRecord:
        """Create a queued record with the current UTC timestamp."""

        return cls(
            job_id=job_id,
            note_id=note_id,
            job_type=job_type,
            state="queued",
            created_at=datetime.now(timezone.utc).isoformat(),
            domain=domain,
            content_len=content_len,
        )
