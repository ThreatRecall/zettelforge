"""
Memory Note Storage - JSONL Read/Write Utilities
A-MEM Agentic Memory Architecture V1.0
"""

import atexit
import fcntl
import glob
import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from zettelforge.log import get_logger
from zettelforge.note_schema import MemoryNote
from zettelforge.ocsf import (
    SEVERITY_HIGH,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    log_file_activity,
)

_logger = get_logger("zettelforge.store")


def get_default_data_dir() -> Path:
    """Get default data directory from environment or default to ~/.amem"""
    env_path = os.environ.get("AMEM_DATA_DIR")
    if env_path:
        return Path(env_path)
    return Path.home() / ".amem"


class MemoryStore:
    """JSONL-based memory note storage with LanceDB vector indexing"""

    def __init__(
        self,
        jsonl_path: Optional[str] = None,
        lance_path: Optional[str] = None,
        embedding_dim: Optional[int] = None,
    ):
        data_dir = get_default_data_dir()

        self.jsonl_path = Path(jsonl_path) if jsonl_path else data_dir / "notes.jsonl"
        self.lance_path = Path(lance_path) if lance_path else data_dir / "vectordb"

        # Resolve embedding dimensions from parameter, config, or env
        if embedding_dim:
            self.embedding_dim = embedding_dim
        else:
            dim_env = os.environ.get("ZETTELFORGE_EMBEDDING_DIM")
            if dim_env:
                self.embedding_dim = int(dim_env)
            else:
                from zettelforge.config import get_config

                self.embedding_dim = get_config().embedding.dimensions

        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self.lance_path.mkdir(parents=True, exist_ok=True)
        self._lancedb = None
        self._note_cache: Optional[Dict[str, MemoryNote]] = None
        self._source_ref_index: Optional[Dict[str, str]] = None  # source_ref -> note_id

        self._dirty_access: set = set()  # note IDs with unsaved access updates
        self._access_flush_timer: Optional[threading.Timer] = None
        self._access_flush_lock = threading.Lock()
        atexit.register(self._flush_access)

        # Clean orphaned temp files from crashed _rewrite_note() calls
        for tmp in glob.glob(str(self.jsonl_path.parent / "tmp*.jsonl")):
            try:
                if Path(tmp).stat().st_mtime < time.time() - 3600:  # older than 1 hour
                    os.unlink(tmp)
            except OSError:
                pass

    @property
    def lancedb(self):
        """Lazy-load LanceDB"""
        if self._lancedb is None:
            try:
                import lancedb

                self._lancedb = lancedb.connect(str(self.lance_path))
            except Exception as e:
                _logger.error("lancedb_connection_failed", error=str(e), exc_info=True)
                self._lancedb = None
        return self._lancedb

    def compute_input_hash(self, note: MemoryNote) -> str:
        """Compute SHA256 hash of note's text fields for change detection"""
        text = (
            note.content.raw
            + note.semantic.context
            + " ".join(note.semantic.keywords)
            + " ".join(note.semantic.tags)
        )
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def generate_note_id(self) -> str:
        """Generate unique note ID"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        import random

        suffix = str(random.randint(0, 9999)).zfill(4)
        return f"note_{ts}_{suffix}"

    def _ensure_cache(self):
        """Load all notes into memory cache on first access."""
        if self._note_cache is not None:
            return
        self._note_cache = {}
        self._source_ref_index = {}
        if not self.jsonl_path.exists():
            return
        with open(self.jsonl_path, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        note = MemoryNote(**data)
                        self._note_cache[note.id] = note
                        if note.content.source_ref:
                            self._source_ref_index[note.content.source_ref] = note.id
                    except Exception:
                        _logger.debug("note_cache_warmup_skipped", exc_info=True)

    def write_note(self, note: MemoryNote) -> None:
        """Append a note to the JSONL store"""
        note.id = note.id or self.generate_note_id()
        note.created_at = note.created_at or datetime.now().isoformat()
        note.updated_at = datetime.now().isoformat()

        # Compute input hash for change detection
        note.embedding.input_hash = self.compute_input_hash(note)

        # Write to JSONL
        with open(self.jsonl_path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(note.model_dump_json() + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)

        # Update in-memory cache and source_ref index
        if self._note_cache is not None:
            self._note_cache[note.id] = note
        if self._source_ref_index is not None and note.content.source_ref:
            self._source_ref_index[note.content.source_ref] = note.id

        # Index in LanceDB if available
        if self.lancedb is not None:
            self._index_in_lance(note)

    def _index_in_lance(self, note: MemoryNote) -> None:
        """Index note in LanceDB vector store"""
        start = time.perf_counter()
        table_name = f"notes_{note.metadata.domain}"
        try:
            import pyarrow as pa

            # Validate embedding dimensions match config
            vec = note.embedding.vector
            if vec and len(vec) != self.embedding_dim:
                _logger.error(
                    "embedding_dimension_mismatch",
                    note_id=note.id,
                    expected=self.embedding_dim,
                    actual=len(vec),
                    hint="Set embedding.dimensions in config.yaml to match your model, then run rebuild_index.py",
                )
                return

            note_data = {
                "id": note.id,
                "vector": note.embedding.vector
                if note.embedding.vector
                else [0.0] * self.embedding_dim,
                "content": note.content.raw[:500],
                "context": note.semantic.context,
                "keywords": ",".join(note.semantic.keywords),
                "tags": ",".join(note.semantic.tags),
                "created_at": note.created_at,
            }

            result = self.lancedb.list_tables()
            tables = (
                result.tables
                if hasattr(result, "tables")
                else (result if isinstance(result, list) else [])
            )

            if table_name not in tables:
                schema = pa.schema(
                    [
                        ("id", pa.string()),
                        ("vector", pa.list_(pa.float32(), self.embedding_dim)),
                        ("content", pa.string()),
                        ("context", pa.string()),
                        ("keywords", pa.string()),
                        ("tags", pa.string()),
                        ("created_at", pa.string()),
                    ]
                )
                self.lancedb.create_table(table_name, data=[note_data], schema=schema)
                activity = "Create"
            else:
                tbl = self.lancedb.open_table(table_name)
                # Remove existing row if present (prevents ghost duplicates)
                try:
                    tbl.delete(f"id = '{note.id}'")
                except Exception:
                    pass  # Table may be empty or ID may not exist
                tbl.add([note_data])
                activity = "Update"

            duration_ms = (time.perf_counter() - start) * 1000
            log_file_activity(
                file_path=table_name,
                activity=activity,
                status_id=STATUS_SUCCESS,
                note_id=note.id,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            _logger.error(
                "lancedb_indexing_failed",
                table_name=table_name,
                note_id=note.id,
                error=str(e),
                duration_ms=round(duration_ms, 2),
                exc_info=True,
            )
            log_file_activity(
                file_path=table_name,
                activity="Update",
                status_id=STATUS_FAILURE,
                severity_id=SEVERITY_HIGH,
                note_id=note.id,
                error=str(e),
                duration_ms=duration_ms,
            )

    def read_all_notes(self) -> List[MemoryNote]:
        """Read all notes from JSONL store"""
        notes = []
        if not self.jsonl_path.exists():
            return notes

        with open(self.jsonl_path, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        notes.append(MemoryNote(**data))
                    except Exception as e:
                        _logger.warning("note_parse_failed", error=str(e))
        return notes

    def iterate_notes(self) -> Iterator[MemoryNote]:
        """Iterate through notes. Uses in-memory cache after first load."""
        self._ensure_cache()
        yield from self._note_cache.values()
        return
        # Dead code below — kept for reference of old disk-based path
        if not self.jsonl_path.exists():
            return
        with open(self.jsonl_path, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        yield MemoryNote(**data)
                    except Exception as e:
                        _logger.warning("note_parse_failed", error=str(e))

    def get_note_by_id(self, note_id: str) -> Optional[MemoryNote]:
        """Retrieve a specific note by ID. O(1) via cache."""
        self._ensure_cache()
        return self._note_cache.get(note_id)

    def get_note_by_source_ref(self, source_ref: str) -> Optional[MemoryNote]:
        """Find a note by its source_ref field. O(1) via index. Returns None if not found."""
        self._ensure_cache()
        note_id = self._source_ref_index.get(source_ref)
        if note_id is None:
            return None
        return self._note_cache.get(note_id)

    def get_notes_by_domain(self, domain: str) -> List[MemoryNote]:
        """Retrieve all notes for a specific domain"""
        return [n for n in self.iterate_notes() if n.metadata.domain == domain]

    def get_recent_notes(self, limit: int = 10) -> List[MemoryNote]:
        """Get most recent notes"""
        notes = list(self.iterate_notes())
        notes.sort(key=lambda n: n.created_at, reverse=True)
        return notes[:limit]

    def count_notes(self) -> int:
        """Count total notes"""
        if not self.jsonl_path.exists():
            return 0
        with open(self.jsonl_path, "r") as f:
            return sum(1 for line in f if line.strip())

    def _rewrite_note(self, note: MemoryNote) -> None:
        """Rewrite a note in place (for updates) — atomic via temp file + os.replace()."""
        if not self.jsonl_path.exists():
            return

        # Hold an exclusive lock on the canonical file for the entire read-write-replace cycle
        with open(self.jsonl_path, "r") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                # Read all notes under the lock
                notes = []
                updated = False
                for line in lock_fh:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            if data.get("id") == note.id:
                                notes.append(note.model_dump())
                                updated = True
                            else:
                                notes.append(data)
                        except Exception:
                            pass

                if not updated:
                    notes.append(note.model_dump())

                # Write to temp file in same directory, then atomically replace
                dir_path = self.jsonl_path.parent
                fd, tmp_path = tempfile.mkstemp(suffix=".jsonl", dir=str(dir_path))
                try:
                    with os.fdopen(fd, "w") as f:
                        for n in notes:
                            f.write(json.dumps(n) + "\n")
                    os.replace(tmp_path, self.jsonl_path)  # atomic on POSIX
                    # Update cache
                    if self._note_cache is not None:
                        self._note_cache[note.id] = note
                except:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                    raise
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

    def mark_access_dirty(self, note_id: str) -> None:
        """Mark a note's access stats as needing persistence."""
        self._dirty_access.add(note_id)
        self._schedule_access_flush()

    def _schedule_access_flush(self) -> None:
        with self._access_flush_lock:
            if self._access_flush_timer is None or not self._access_flush_timer.is_alive():
                self._access_flush_timer = threading.Timer(60.0, self._flush_access)
                self._access_flush_timer.daemon = True
                self._access_flush_timer.start()

    def _flush_access(self) -> None:
        """Write dirty access counts back to JSONL."""
        if not self._dirty_access:
            return
        dirty = self._dirty_access.copy()
        self._dirty_access.clear()
        for note_id in dirty:
            note = self.get_note_by_id(note_id)
            if note:
                self._rewrite_note(note)

    def export_snapshot(self, output_path: str) -> None:
        """Export full memory state for cold storage"""
        import shutil

        if self.jsonl_path.exists():
            shutil.copy(
                self.jsonl_path,
                f"{output_path}/notes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl",
            )
