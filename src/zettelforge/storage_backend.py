"""
Storage Backend ABC -- unified interface for JSONL and SQLite persistence.

Defines the abstract interface that all storage backends (JSONL, SQLite,
PostgreSQL) must implement.  Decouples the retrieval and memory-management
layers from the specific storage technology.

BLOCKER-2 fix: includes reindex_vector() for LanceDB sync.
BLOCKER-3 prep: KG edge methods accept note_id for provenance tracking.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from zettelforge.note_schema import MemoryNote


class BackendClosedError(RuntimeError):
    """Raised when an operation is attempted on a closed storage backend.

    Surfaces a clean, catchable signal during shutdown races (e.g. atexit
    drain running after close()) instead of an opaque AttributeError on a
    nil connection.
    """


class StorageBackend(ABC):
    """Abstract storage backend for ZettelForge persistence layer."""

    # ── Note Operations ──────────────────────────────────────────────────

    @abstractmethod
    def write_note(self, note: MemoryNote) -> None:
        """Persist a new note.  Must assign note.id if empty."""
        ...

    @abstractmethod
    def rewrite_note(self, note: MemoryNote) -> None:
        """Update an existing note in place (atomic)."""
        ...

    @abstractmethod
    def get_note_by_id(self, note_id: str) -> MemoryNote | None:
        """O(1) lookup by note ID."""
        ...

    @abstractmethod
    def get_note_by_source_ref(self, source_ref: str) -> MemoryNote | None:
        """O(1) lookup by source_ref.  Returns None if not found."""
        ...

    @abstractmethod
    def iterate_notes(self) -> Iterator[MemoryNote]:
        """Yield all notes.  Used by entity index rebuild, exports."""
        ...

    @abstractmethod
    def get_notes_by_domain(self, domain: str) -> list[MemoryNote]:
        """All notes in a domain.  Used by vector retriever domain filter."""
        ...

    @abstractmethod
    def get_recent_notes(self, limit: int = 10) -> list[MemoryNote]:
        """Most recent notes by created_at."""
        ...

    @abstractmethod
    def count_notes(self) -> int:
        """Total note count."""
        ...

    @abstractmethod
    def delete_note(self, note_id: str) -> bool:
        """Delete a note by ID.  Returns True if the note existed."""
        ...

    def mark_access_dirty(self, note_id: str) -> None:
        """Increment access count and update last_accessed timestamp.

        Concrete default that fetches the note, calls increment_access(),
        and rewrites it.  Backends can override for efficiency (e.g. a
        targeted SQL UPDATE instead of a full rewrite).
        """
        note = self.get_note_by_id(note_id)
        if note is None:
            return
        note.increment_access()
        self.rewrite_note(note)

    # ── Vector Index Sync (BLOCKER-2 fix) ────────────────────────────────

    @abstractmethod
    def reindex_vector(self, note_id: str, vector: list[float]) -> None:
        """Update a note's embedding vector and trigger LanceDB re-sync.

        Called by rebuild_index.py when re-embedding notes with a new model.
        Must update both the persistence layer and the LanceDB table.
        """
        ...

    # ── Knowledge Graph Operations ───────────────────────────────────────

    @abstractmethod
    def add_kg_node(
        self,
        entity_type: str,
        entity_value: str,
        properties: dict | None = None,
    ) -> str:
        """Add or update a KG node.  Returns node_id."""
        ...

    @abstractmethod
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
        """Add a KG edge.  note_id tracks provenance (BLOCKER-3 fix).

        When note_id is provided, uniqueness is per
        (from, to, relationship, note_id) -- allowing multiple notes to
        independently assert the same relationship.
        """
        ...

    @abstractmethod
    def get_kg_node(self, entity_type: str, entity_value: str) -> dict | None:
        """Lookup a KG node by type + value."""
        ...

    @abstractmethod
    def get_kg_neighbors(
        self,
        entity_type: str,
        entity_value: str,
        relationship: str | None = None,
    ) -> list[dict]:
        """Get adjacent nodes via outgoing edges."""
        ...

    @abstractmethod
    def traverse_kg(
        self,
        start_type: str,
        start_value: str,
        max_depth: int = 2,
    ) -> list[list[dict]]:
        """BFS/DFS traversal up to max_depth.  Returns list of paths."""
        ...

    @abstractmethod
    def get_entity_timeline(self, entity_type: str, entity_value: str) -> list[dict]:
        """Get temporal timeline of states for an entity."""
        ...

    @abstractmethod
    def get_changes_since(self, timestamp: str) -> list[dict]:
        """Get all entity changes since a given ISO-8601 timestamp."""
        ...

    @abstractmethod
    def get_kg_node_by_id(self, node_id: str) -> dict | None:
        """Lookup a KG node by its internal node_id.

        Needed by provenance_chain() which accesses nodes by ID directly.
        """
        ...

    def add_temporal_edge(
        self,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        relationship: str,
        timestamp: str,
        properties: dict | None = None,
    ) -> str:
        """Add a temporal edge with timestamp baked into properties.

        Concrete default that delegates to add_kg_edge() with the
        timestamp merged into the properties dict.
        """
        props = dict(properties or {})
        props["timestamp"] = timestamp
        return self.add_kg_edge(
            from_type, from_value, to_type, to_value, relationship, properties=props
        )

    @abstractmethod
    def get_causal_edges(
        self,
        entity_type: str,
        entity_value: str,
        max_depth: int = 3,
        max_visited: int = 50,
    ) -> list[dict]:
        """BFS over outgoing causal edges — traces forward from cause to effects."""
        ...

    @abstractmethod
    def get_incoming_causal(
        self,
        entity_type: str,
        entity_value: str,
        max_depth: int = 3,
        max_visited: int = 50,
    ) -> list[dict]:
        """BFS over incoming causal edges — traces back to root causes."""
        ...

    # ── Entity Index Operations ──────────────────────────────────────────

    @abstractmethod
    def add_entity_mapping(self, entity_type: str, entity_value: str, note_id: str) -> None:
        """Map an entity occurrence to a note ID."""
        ...

    @abstractmethod
    def remove_entity_mappings_for_note(self, note_id: str) -> None:
        """Remove all entity mappings for a given note."""
        ...

    @abstractmethod
    def get_note_ids_for_entity(self, entity_type: str, entity_value: str) -> list[str]:
        """Get note IDs associated with an entity."""
        ...

    @abstractmethod
    def search_entities(self, query: str, limit: int = 10) -> dict[str, list[str]]:
        """Prefix search across entity types.  Returns type -> matching values."""
        ...

    # ── Lifecycle ────────────────────────────────────────────────────────

    @abstractmethod
    def initialize(self) -> None:
        """Perform any one-time setup (create tables, warm caches, etc.)."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Flush pending writes and release resources."""
        ...

    def health_check(self) -> dict[str, Any]:
        """Return backend health status.  Override for richer diagnostics."""
        return {"status": "ok", "backend": self.__class__.__name__}

    @abstractmethod
    def export_snapshot(self, output_path: str) -> None:
        """Export full state for backup / cold storage."""
        ...
