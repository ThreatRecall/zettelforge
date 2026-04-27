"""
SQLite Storage Backend — WAL mode, full StorageBackend ABC implementation.

Replaces JSONL persistence with SQLite for notes, knowledge graph, and entity
index.  WAL mode provides concurrent reads during writes.  Each MemoryNote is
stored as individual columns (not a JSON blob) for direct SQL queryability.

WARNING-3: synchronous=NORMAL means the last transaction before an OS crash
(power failure, kernel panic) may be lost.  Application-level crashes are safe.
"""

import contextlib
import json
import sqlite3
import threading
import uuid
from collections import defaultdict, deque
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from zettelforge.note_schema import (
    Content,
    Embedding,
    Links,
    MemoryNote,
    Metadata,
    Semantic,
    VulnerabilityMeta,
)
from zettelforge.ocsf import log_file_activity
from zettelforge.storage_backend import BackendClosedError, StorageBackend

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    content_raw TEXT NOT NULL,
    content_source_type TEXT DEFAULT 'conversation',
    content_source_ref TEXT DEFAULT '',
    content_previous_raw TEXT,
    context TEXT DEFAULT '',
    keywords TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    entities TEXT DEFAULT '[]',
    embedding_vector TEXT DEFAULT '[]',
    embedding_model TEXT DEFAULT '',
    embedding_hash TEXT DEFAULT '',
    embedding_dimensions INTEGER DEFAULT 768,
    domain TEXT DEFAULT 'general',
    tier TEXT DEFAULT 'B',
    importance REAL DEFAULT 5,
    confidence REAL DEFAULT 1.0,
    access_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    tlp TEXT DEFAULT '',
    stix_confidence INTEGER DEFAULT -1,
    persistence_semantics TEXT DEFAULT 'memory',
    ttl_anchor TEXT,
    ttl INTEGER,
    evolution_count INTEGER DEFAULT 0,
    superseded_by TEXT DEFAULT '',
    supersedes TEXT DEFAULT '[]',
    related TEXT DEFAULT '[]',
    causal_chain TEXT DEFAULT '[]',
    version INTEGER DEFAULT 1,
    evolved_from TEXT,
    evolved_by TEXT DEFAULT '[]',
    vuln_meta TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_notes_domain ON notes(domain);
CREATE INDEX IF NOT EXISTS idx_notes_source_ref ON notes(content_source_ref)
    WHERE content_source_ref != '';
CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at);

CREATE TABLE IF NOT EXISTS kg_nodes (
    node_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_value TEXT NOT NULL,
    properties TEXT DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(entity_type, entity_value)
);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_type_value
    ON kg_nodes(entity_type, entity_value);

CREATE TABLE IF NOT EXISTS kg_edges (
    edge_id TEXT PRIMARY KEY,
    from_node_id TEXT NOT NULL,
    to_node_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    edge_type TEXT DEFAULT 'heuristic',
    note_id TEXT DEFAULT '',
    properties TEXT DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(from_node_id, to_node_id, relationship, note_id)
);
CREATE INDEX IF NOT EXISTS idx_kg_edges_from ON kg_edges(from_node_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_to ON kg_edges(to_node_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_rel ON kg_edges(relationship);
CREATE INDEX IF NOT EXISTS idx_kg_edges_type ON kg_edges(edge_type);

CREATE TABLE IF NOT EXISTS entity_index (
    entity_type TEXT NOT NULL,
    entity_value TEXT NOT NULL,
    note_id TEXT NOT NULL,
    PRIMARY KEY(entity_type, entity_value, note_id)
);
CREATE INDEX IF NOT EXISTS idx_entity_lookup
    ON entity_index(entity_type, entity_value);
CREATE INDEX IF NOT EXISTS idx_entity_note ON entity_index(note_id);
"""


# ---------------------------------------------------------------------------
# Helpers: MemoryNote <-> row
# ---------------------------------------------------------------------------


def _note_to_row(note: MemoryNote) -> dict:
    """Serialize a MemoryNote into a flat dict suitable for INSERT."""
    return {
        "id": note.id,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "content_raw": note.content.raw,
        "content_source_type": note.content.source_type,
        "content_source_ref": note.content.source_ref or "",
        "content_previous_raw": note.content.previous_raw,
        "context": note.semantic.context,
        "keywords": json.dumps(note.semantic.keywords),
        "tags": json.dumps(note.semantic.tags),
        "entities": json.dumps(note.semantic.entities),
        "embedding_vector": json.dumps(note.embedding.vector),
        "embedding_model": note.embedding.model,
        "embedding_hash": note.embedding.input_hash,
        "embedding_dimensions": note.embedding.dimensions,
        "domain": note.metadata.domain,
        "tier": note.metadata.tier,
        "importance": float(note.metadata.importance),
        "confidence": note.metadata.confidence,
        "access_count": note.metadata.access_count,
        "last_accessed": note.metadata.last_accessed,
        "tlp": note.metadata.tlp,
        "stix_confidence": note.metadata.stix_confidence,
        "persistence_semantics": note.metadata.persistence_semantics,
        "ttl_anchor": note.metadata.ttl_anchor,
        "ttl": note.metadata.ttl,
        "evolution_count": note.metadata.evolution_count,
        "superseded_by": note.links.superseded_by or "",
        "supersedes": json.dumps(note.links.supersedes),
        "related": json.dumps(note.links.related),
        "causal_chain": json.dumps(note.links.causal_chain),
        "version": note.version,
        "evolved_from": note.evolved_from,
        "evolved_by": json.dumps(note.evolved_by),
        "vuln_meta": json.dumps(note.metadata.vuln.model_dump()) if note.metadata.vuln else None,
    }


def _row_to_note(row: sqlite3.Row) -> MemoryNote:
    """Deserialize a sqlite3.Row into a MemoryNote."""
    r = dict(row)
    superseded_by = r.get("superseded_by") or None
    if superseded_by == "":
        superseded_by = None

    return MemoryNote(
        id=r["id"],
        version=r.get("version", 1),
        created_at=r["created_at"],
        updated_at=r.get("updated_at") or r["created_at"],
        evolved_from=r.get("evolved_from"),
        evolved_by=json.loads(r.get("evolved_by") or "[]"),
        content=Content(
            raw=r["content_raw"] or "",
            source_type=r.get("content_source_type") or "conversation",
            source_ref=r.get("content_source_ref") or "",
            previous_raw=r.get("content_previous_raw"),
        ),
        semantic=Semantic(
            context=r.get("context") or "",
            keywords=json.loads(r.get("keywords") or "[]"),
            tags=json.loads(r.get("tags") or "[]"),
            entities=json.loads(r.get("entities") or "[]"),
        ),
        embedding=Embedding(
            model=r.get("embedding_model") or "nomic-ai/nomic-embed-text-v1.5-Q",
            vector=json.loads(r.get("embedding_vector") or "[]"),
            dimensions=r.get("embedding_dimensions") or 768,
            input_hash=r.get("embedding_hash") or "",
        ),
        links=Links(
            related=json.loads(r.get("related") or "[]"),
            superseded_by=superseded_by,
            supersedes=json.loads(r.get("supersedes") or "[]"),
            causal_chain=json.loads(r.get("causal_chain") or "[]"),
        ),
        metadata=Metadata(
            access_count=r.get("access_count") or 0,
            last_accessed=r.get("last_accessed"),
            evolution_count=r.get("evolution_count") or 0,
            confidence=r.get("confidence") if r.get("confidence") is not None else 1.0,
            ttl=r.get("ttl"),
            domain=r.get("domain") or "general",
            persistence_semantics=r.get("persistence_semantics") or "memory",
            ttl_anchor=r.get("ttl_anchor"),
            tier=r.get("tier") or "B",
            importance=int(r.get("importance") or 5),
            tlp=r.get("tlp") or "",
            stix_confidence=r.get("stix_confidence")
            if r.get("stix_confidence") is not None
            else -1,
            vuln=VulnerabilityMeta(**json.loads(r["vuln_meta"])) if r.get("vuln_meta") else None,
        ),
    )


# ---------------------------------------------------------------------------
# SQLiteBackend
# ---------------------------------------------------------------------------

# Column names for INSERT (must match _note_to_row keys)
_NOTE_COLUMNS = [
    "id",
    "created_at",
    "updated_at",
    "content_raw",
    "content_source_type",
    "content_source_ref",
    "content_previous_raw",
    "context",
    "keywords",
    "tags",
    "entities",
    "embedding_vector",
    "embedding_model",
    "embedding_hash",
    "embedding_dimensions",
    "domain",
    "tier",
    "importance",
    "confidence",
    "access_count",
    "last_accessed",
    "tlp",
    "stix_confidence",
    "persistence_semantics",
    "ttl_anchor",
    "ttl",
    "evolution_count",
    "superseded_by",
    "supersedes",
    "related",
    "causal_chain",
    "version",
    "evolved_from",
    "evolved_by",
    "vuln_meta",
]

# _NOTE_COLUMNS is a module-level constant; row values are ?-bound. Safe.
_INSERT_NOTE_SQL = (
    f"INSERT OR REPLACE INTO notes ({', '.join(_NOTE_COLUMNS)}) "  # noqa: S608
    f"VALUES ({', '.join('?' for _ in _NOTE_COLUMNS)})"
)


class SQLiteBackend(StorageBackend):
    """SQLite-backed storage with WAL mode for ZettelForge."""

    def __init__(
        self,
        db_path: str | None = None,
        data_dir: str | Path | None = None,
    ):
        from zettelforge.memory_store import get_default_data_dir

        if data_dir is not None:
            self.db_path = str(Path(data_dir) / "zettelforge.db")
        else:
            self.db_path = db_path or str(get_default_data_dir() / "zettelforge.db")
        self._conn: sqlite3.Connection | None = None
        self._write_lock = threading.RLock()

    def _check_open(self) -> None:
        # Call inside _write_lock. Surfaces close()/never-initialized as a
        # clean BackendClosedError instead of AttributeError on None.
        if self._conn is None:
            raise BackendClosedError(f"SQLiteBackend({self.db_path}) is closed")

    # ── Lifecycle ───────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Create connection, enable WAL, create tables. Idempotent."""
        import os

        with self._write_lock:
            if self._conn is not None:
                return
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(_SCHEMA_DDL)
            conn.commit()
            self._conn = conn

    def close(self) -> None:
        """Checkpoint WAL and close. Idempotent; safe to call from atexit."""
        with self._write_lock:
            conn = self._conn
            if conn is None:
                return
            self._conn = None
            with contextlib.suppress(Exception):
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()

    def health_check(self) -> dict[str, Any]:
        if self._conn is None:
            return {
                "status": "closed",
                "backend": "SQLiteBackend",
                "db_path": self.db_path,
                "note_count": -1,
            }
        return {
            "status": "ok",
            "backend": "SQLiteBackend",
            "db_path": self.db_path,
            "note_count": self.count_notes(),
        }

    # ── Note Operations ─────────────────────────────────────────────────

    def write_note(self, note: MemoryNote) -> None:
        if not note.id:
            note.id = f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        if not note.created_at:
            note.created_at = datetime.now().isoformat()
        if not note.updated_at:
            note.updated_at = datetime.now().isoformat()

        row = _note_to_row(note)
        values = [row[c] for c in _NOTE_COLUMNS]
        with self._write_lock:
            self._check_open()
            self._conn.execute(_INSERT_NOTE_SQL, values)
            self._conn.commit()
        log_file_activity(self.db_path, "Create", actor="SQLiteBackend.write_note", note_id=note.id)

    def rewrite_note(self, note: MemoryNote) -> None:
        note.updated_at = datetime.now().isoformat()
        row = _note_to_row(note)
        values = [row[c] for c in _NOTE_COLUMNS]
        with self._write_lock:
            self._check_open()
            self._conn.execute(_INSERT_NOTE_SQL, values)
            self._conn.commit()
        log_file_activity(
            self.db_path, "Update", actor="SQLiteBackend.rewrite_note", note_id=note.id
        )

    def get_note_by_id(self, note_id: str) -> MemoryNote | None:
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_note(row)

    def get_note_by_source_ref(self, source_ref: str) -> MemoryNote | None:
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "SELECT * FROM notes WHERE content_source_ref = ? LIMIT 1",
                (source_ref,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_note(row)

    def iterate_notes(self) -> Iterator[MemoryNote]:
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute("SELECT * FROM notes")
        while True:
            with self._write_lock:
                self._check_open()
                rows = cur.fetchmany(100)
            if not rows:
                break
            for row in rows:
                yield _row_to_note(row)

    def get_notes_by_domain(self, domain: str) -> list[MemoryNote]:
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute("SELECT * FROM notes WHERE domain = ?", (domain,))
            rows = cur.fetchall()
        return [_row_to_note(r) for r in rows]

    def get_recent_notes(self, limit: int = 10) -> list[MemoryNote]:
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "SELECT * FROM notes ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            rows = cur.fetchall()
        return [_row_to_note(r) for r in rows]

    def count_notes(self) -> int:
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute("SELECT COUNT(*) FROM notes")
            return cur.fetchone()[0]

    def delete_note(self, note_id: str) -> bool:
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self._conn.commit()
        deleted = cur.rowcount > 0
        if deleted:
            log_file_activity(
                self.db_path, "Delete", actor="SQLiteBackend.delete_note", note_id=note_id
            )
        return deleted

    def mark_access_dirty(self, note_id: str) -> None:
        """Targeted UPDATE for access tracking — avoids full note rewrite."""
        now = datetime.now().isoformat()
        with self._write_lock:
            self._check_open()
            self._conn.execute(
                "UPDATE notes SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                (now, note_id),
            )
            self._conn.commit()

    # ── Vector Index Sync ───────────────────────────────────────────────

    def reindex_vector(self, note_id: str, vector: list[float]) -> None:
        """Update embedding vector in SQLite.  LanceDB sync is external.

        Targeted UPDATE inside a single lock acquisition — avoids the
        read-modify-write race where a concurrent mark_access_dirty /
        rewrite_note edit would be clobbered by the full-row rewrite.
        """
        vec_json = json.dumps(vector)
        now = datetime.now().isoformat()
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "UPDATE notes SET embedding_vector = ?, updated_at = ? WHERE id = ?",
                (vec_json, now, note_id),
            )
            self._conn.commit()
            rowcount = cur.rowcount
        if rowcount == 0:
            raise ValueError(f"Note {note_id} not found")

    # ── Knowledge Graph: Nodes ──────────────────────────────────────────

    def add_kg_node(
        self,
        entity_type: str,
        entity_value: str,
        properties: dict | None = None,
    ) -> str:
        now = datetime.now().isoformat()
        props_json = json.dumps(properties or {})

        with self._write_lock:
            self._check_open()
            # Try to find existing node
            cur = self._conn.execute(
                "SELECT node_id FROM kg_nodes WHERE entity_type = ? AND entity_value = ?",
                (entity_type, entity_value),
            )
            existing = cur.fetchone()
            if existing:
                node_id = existing["node_id"]
                if properties:
                    self._conn.execute(
                        "UPDATE kg_nodes SET properties = ?, updated_at = ? WHERE node_id = ?",
                        (props_json, now, node_id),
                    )
                    self._conn.commit()
                return node_id

            node_id = f"node_{uuid.uuid4().hex[:12]}"
            self._conn.execute(
                "INSERT INTO kg_nodes (node_id, entity_type, entity_value, properties, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (node_id, entity_type, entity_value, props_json, now, now),
            )
            self._conn.commit()
        return node_id

    def get_kg_node(self, entity_type: str, entity_value: str) -> dict | None:
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "SELECT * FROM kg_nodes WHERE entity_type = ? AND entity_value = ?",
                (entity_type, entity_value),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "node_id": row["node_id"],
            "entity_type": row["entity_type"],
            "entity_value": row["entity_value"],
            "properties": json.loads(row["properties"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ── Knowledge Graph: Edges ──────────────────────────────────────────

    def add_kg_edge(
        self,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        relationship: str,
        note_id: str | None = None,
        properties: dict | None = None,
    ) -> str:
        with self._write_lock:
            self._check_open()
            from_node_id = self.add_kg_node(from_type, from_value)
            to_node_id = self.add_kg_node(to_type, to_value)
            now = datetime.now().isoformat()

            props = dict(properties or {})
            edge_type = props.pop("edge_type", "heuristic")
            effective_note_id = note_id or props.pop("note_id", "") or ""
            props_json = json.dumps(props)

            # Check for existing edge with same provenance
            cur = self._conn.execute(
                "SELECT edge_id FROM kg_edges "
                "WHERE from_node_id = ? AND to_node_id = ? AND relationship = ? AND note_id = ?",
                (from_node_id, to_node_id, relationship, effective_note_id),
            )
            existing = cur.fetchone()
            if existing:
                if props:
                    self._conn.execute(
                        "UPDATE kg_edges SET properties = ?, updated_at = ? WHERE edge_id = ?",
                        (props_json, now, existing["edge_id"]),
                    )
                    self._conn.commit()
                return existing["edge_id"]

            edge_id = f"edge_{uuid.uuid4().hex[:12]}"
            self._conn.execute(
                "INSERT INTO kg_edges "
                "(edge_id, from_node_id, to_node_id, relationship, edge_type, note_id, properties, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    edge_id,
                    from_node_id,
                    to_node_id,
                    relationship,
                    edge_type,
                    effective_note_id,
                    props_json,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return edge_id

    def get_kg_neighbors(
        self,
        entity_type: str,
        entity_value: str,
        relationship: str | None = None,
    ) -> list[dict]:
        with self._write_lock:
            self._check_open()
            # Resolve node_id
            cur = self._conn.execute(
                "SELECT node_id FROM kg_nodes WHERE entity_type = ? AND entity_value = ?",
                (entity_type, entity_value),
            )
            row = cur.fetchone()
            if row is None:
                return []
            node_id = row["node_id"]

            if relationship:
                edges_cur = self._conn.execute(
                    "SELECT e.*, n.entity_type AS to_type, n.entity_value AS to_value, n.properties AS to_props "
                    "FROM kg_edges e JOIN kg_nodes n ON e.to_node_id = n.node_id "
                    "WHERE e.from_node_id = ? AND e.relationship = ?",
                    (node_id, relationship),
                )
            else:
                edges_cur = self._conn.execute(
                    "SELECT e.*, n.entity_type AS to_type, n.entity_value AS to_value, n.properties AS to_props "
                    "FROM kg_edges e JOIN kg_nodes n ON e.to_node_id = n.node_id "
                    "WHERE e.from_node_id = ?",
                    (node_id,),
                )
            erows = edges_cur.fetchall()

        neighbors = []
        for erow in erows:
            neighbors.append(
                {
                    "node": {
                        "node_id": erow["to_node_id"],
                        "entity_type": erow["to_type"],
                        "entity_value": erow["to_value"],
                        "properties": json.loads(erow["to_props"] or "{}"),
                    },
                    "relationship": erow["relationship"],
                    "edge_properties": json.loads(erow["properties"] or "{}"),
                    "note_id": erow["note_id"],
                }
            )
        return neighbors

    def traverse_kg(
        self,
        start_type: str,
        start_value: str,
        max_depth: int = 2,
    ) -> list[list[dict]]:
        """BFS/DFS traversal up to max_depth.  Returns list of paths."""
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "SELECT node_id FROM kg_nodes WHERE entity_type = ? AND entity_value = ?",
                (start_type, start_value),
            )
            row = cur.fetchone()
        if row is None:
            return []

        start_node_id = row["node_id"]
        visited: set = set()
        results: list[list[dict]] = []

        def _dfs(current_id: str, depth: int, path: list[dict]):
            if depth > max_depth or current_id in visited:
                return
            visited.add(current_id)

            with self._write_lock:
                self._check_open()
                edges_cur = self._conn.execute(
                    "SELECT e.to_node_id, e.relationship, "
                    "nf.entity_type AS from_type, nf.entity_value AS from_value, "
                    "nt.entity_type AS to_type, nt.entity_value AS to_value "
                    "FROM kg_edges e "
                    "JOIN kg_nodes nf ON e.from_node_id = nf.node_id "
                    "JOIN kg_nodes nt ON e.to_node_id = nt.node_id "
                    "WHERE e.from_node_id = ?",
                    (current_id,),
                )
                erows = edges_cur.fetchall()
            for erow in erows:
                step = {
                    "from_type": erow["from_type"],
                    "from_value": erow["from_value"],
                    "relationship": erow["relationship"],
                    "to_type": erow["to_type"],
                    "to_value": erow["to_value"],
                }
                new_path = [*path, step]
                results.append(new_path)
                _dfs(erow["to_node_id"], depth + 1, new_path)

        _dfs(start_node_id, 1, [])
        return results

    # ── Temporal KG ─────────────────────────────────────────────────────

    def get_entity_timeline(self, entity_type: str, entity_value: str) -> list[dict]:
        """Get temporal timeline of states for an entity via temporal edges."""
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "SELECT node_id FROM kg_nodes WHERE entity_type = ? AND entity_value = ?",
                (entity_type, entity_value),
            )
            row = cur.fetchone()
            if row is None:
                return []
            node_id = row["node_id"]

            edges_cur = self._conn.execute(
                "SELECT e.*, nt.entity_type AS to_type, nt.entity_value AS to_value "
                "FROM kg_edges e JOIN kg_nodes nt ON e.to_node_id = nt.node_id "
                "WHERE e.from_node_id = ? AND "
                "(e.relationship LIKE 'TEMPORAL_%' OR e.relationship = 'SUPERSEDES') "
                "ORDER BY e.created_at",
                (node_id,),
            )
            erows = edges_cur.fetchall()
        timeline = []
        for erow in erows:
            props = json.loads(erow["properties"] or "{}")
            ts = props.get("timestamp") or erow["created_at"] or ""
            timeline.append(
                {
                    "edge": dict(erow),
                    "timestamp": ts,
                    "to_entity": f"{erow['to_type']}:{erow['to_value']}",
                }
            )
        timeline.sort(key=lambda x: x["timestamp"] or "")
        return timeline

    def get_changes_since(self, timestamp: str) -> list[dict]:
        """Get all temporal edge changes since a given ISO-8601 timestamp."""
        with self._write_lock:
            self._check_open()
            edges_cur = self._conn.execute(
                "SELECT e.*, "
                "nf.entity_type AS from_type, nf.entity_value AS from_value, "
                "nt.entity_type AS to_type, nt.entity_value AS to_value "
                "FROM kg_edges e "
                "JOIN kg_nodes nf ON e.from_node_id = nf.node_id "
                "JOIN kg_nodes nt ON e.to_node_id = nt.node_id "
                "WHERE (e.relationship LIKE 'TEMPORAL_%' OR e.relationship = 'SUPERSEDES') "
                "AND e.created_at >= ? "
                "ORDER BY e.created_at",
                (timestamp,),
            )
            erows = edges_cur.fetchall()
        changes = []
        for erow in erows:
            changes.append(
                {
                    "timestamp": erow["created_at"],
                    "from": f"{erow['from_type']}:{erow['from_value']}",
                    "relationship": erow["relationship"],
                    "to": f"{erow['to_type']}:{erow['to_value']}",
                }
            )
        return changes

    def get_kg_node_by_id(self, node_id: str) -> dict | None:
        """Lookup a KG node by its internal node_id."""
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute("SELECT * FROM kg_nodes WHERE node_id = ?", (node_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "node_id": row["node_id"],
            "entity_type": row["entity_type"],
            "entity_value": row["entity_value"],
            "properties": json.loads(row["properties"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_causal_edges(
        self,
        entity_type: str,
        entity_value: str,
        max_depth: int = 3,
        max_visited: int = 50,
    ) -> list[dict]:
        """BFS over outgoing causal edges — traces forward from cause to effects."""
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "SELECT node_id FROM kg_nodes WHERE entity_type = ? AND entity_value = ?",
                (entity_type, entity_value),
            )
            row = cur.fetchone()
        if row is None:
            return []

        start_id = row["node_id"]
        visited: set = set()
        bfs_queue: deque = deque([(start_id, 0)])
        causal_edges: list[dict] = []

        while bfs_queue and len(visited) < max_visited:
            current_id, depth = bfs_queue.popleft()
            if depth > max_depth or current_id in visited:
                continue
            visited.add(current_id)

            with self._write_lock:
                self._check_open()
                edges_cur = self._conn.execute(
                    "SELECT * FROM kg_edges WHERE from_node_id = ? AND edge_type = 'causal'",
                    (current_id,),
                )
                erows = edges_cur.fetchall()
            for erow in erows:
                edge = dict(erow)
                edge["properties"] = json.loads(edge.get("properties") or "{}")
                causal_edges.append(edge)
                to_id = edge["to_node_id"]
                if to_id not in visited:
                    bfs_queue.append((to_id, depth + 1))

        return causal_edges

    def get_incoming_causal(
        self,
        entity_type: str,
        entity_value: str,
        max_depth: int = 3,
        max_visited: int = 50,
    ) -> list[dict]:
        """BFS over incoming causal edges — traces back to root causes."""
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "SELECT node_id FROM kg_nodes WHERE entity_type = ? AND entity_value = ?",
                (entity_type, entity_value),
            )
            row = cur.fetchone()
        if row is None:
            return []

        start_id = row["node_id"]
        visited: set = set()
        bfs_queue: deque = deque([(start_id, 0)])
        causal_edges: list[dict] = []

        while bfs_queue and len(visited) < max_visited:
            current_id, depth = bfs_queue.popleft()
            if depth > max_depth or current_id in visited:
                continue
            visited.add(current_id)

            with self._write_lock:
                self._check_open()
                edges_cur = self._conn.execute(
                    "SELECT * FROM kg_edges WHERE to_node_id = ? AND edge_type = 'causal'",
                    (current_id,),
                )
                erows = edges_cur.fetchall()
            for erow in erows:
                edge = dict(erow)
                edge["properties"] = json.loads(edge.get("properties") or "{}")
                causal_edges.append(edge)
                from_id = edge["from_node_id"]
                if from_id not in visited:
                    bfs_queue.append((from_id, depth + 1))

        return causal_edges

    # ── Entity Index ────────────────────────────────────────────────────

    def add_entity_mapping(self, entity_type: str, entity_value: str, note_id: str) -> None:
        with self._write_lock:
            self._check_open()
            self._conn.execute(
                "INSERT OR IGNORE INTO entity_index (entity_type, entity_value, note_id) "
                "VALUES (?, ?, ?)",
                (entity_type, entity_value, note_id),
            )
            self._conn.commit()

    def remove_entity_mappings_for_note(self, note_id: str) -> None:
        with self._write_lock:
            self._check_open()
            self._conn.execute("DELETE FROM entity_index WHERE note_id = ?", (note_id,))
            self._conn.commit()

    def get_note_ids_for_entity(self, entity_type: str, entity_value: str) -> list[str]:
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "SELECT note_id FROM entity_index WHERE entity_type = ? AND entity_value = ?",
                (entity_type, entity_value),
            )
            rows = cur.fetchall()
        return [r["note_id"] for r in rows]

    def search_entities(self, query: str, limit: int = 10) -> dict[str, list[str]]:
        """Prefix search across entity types."""
        with self._write_lock:
            self._check_open()
            cur = self._conn.execute(
                "SELECT DISTINCT entity_type, entity_value FROM entity_index "
                "WHERE entity_value LIKE ? LIMIT ?",
                (f"{query}%", limit),
            )
            rows = cur.fetchall()
        result: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            result[row["entity_type"]].append(row["entity_value"])
        return dict(result)

    # ── Export ──────────────────────────────────────────────────────────

    def export_snapshot(self, output_path: str) -> None:
        """Export full SQLite database via the online backup API.

        Uses sqlite3.Connection.backup() for a page-consistent snapshot
        that correctly handles WAL + sidecar files — shutil.copy2 of a
        live WAL database can produce a torn copy missing -wal / -shm.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = f"{output_path}/zettelforge_{ts}.db"
        with self._write_lock:
            self._check_open()
            dst = sqlite3.connect(dest)
            try:
                self._conn.backup(dst)
            finally:
                dst.close()
        log_file_activity(dest, "Create", actor="SQLiteBackend.export_snapshot")
