"""Tests for SQLiteBackend — WAL mode storage backend."""

import tempfile

import pytest

from zettelforge.note_schema import Content, Embedding, Links, Metadata, MemoryNote, Semantic
from zettelforge.sqlite_backend import SQLiteBackend
from zettelforge.storage_backend import BackendClosedError


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    backend = SQLiteBackend(db_path=f"{tmpdir}/test.db")
    backend.initialize()
    yield backend
    backend.close()


def _make_note(
    note_id="n1",
    content="APT28 uses Cobalt Strike",
    domain="cti",
    source_ref="",
):
    from datetime import datetime

    now = datetime.now().isoformat()
    return MemoryNote(
        id=note_id,
        created_at=now,
        updated_at=now,
        content=Content(raw=content, source_type="test", source_ref=source_ref),
        semantic=Semantic(
            context="ctx",
            keywords=["apt28"],
            tags=["threat"],
            entities=["apt28", "cobalt-strike"],
        ),
        embedding=Embedding(vector=[0.1] * 768),
        metadata=Metadata(domain=domain),
        links=Links(),
    )


# ---------------------------------------------------------------------------
# Note CRUD
# ---------------------------------------------------------------------------


class TestSQLiteNotes:
    def test_write_and_read(self, db):
        note = _make_note()
        db.write_note(note)
        result = db.get_note_by_id("n1")
        assert result is not None
        assert result.content.raw == "APT28 uses Cobalt Strike"
        assert result.semantic.keywords == ["apt28"]
        assert result.metadata.domain == "cti"

    def test_iterate_notes(self, db):
        db.write_note(_make_note("n1"))
        db.write_note(_make_note("n2", "Lazarus targets crypto"))
        notes = list(db.iterate_notes())
        assert len(notes) == 2

    def test_count_notes(self, db):
        assert db.count_notes() == 0
        db.write_note(_make_note("n1"))
        assert db.count_notes() == 1

    def test_rewrite_note(self, db):
        note = _make_note()
        db.write_note(note)
        note.content = Content(raw="Updated content", source_type="test", source_ref="")
        db.rewrite_note(note)
        result = db.get_note_by_id("n1")
        assert result.content.raw == "Updated content"

    def test_delete_note(self, db):
        db.write_note(_make_note())
        assert db.delete_note("n1") is True
        assert db.get_note_by_id("n1") is None
        # Deleting non-existent returns False
        assert db.delete_note("n1") is False

    def test_get_note_by_source_ref(self, db):
        db.write_note(_make_note("n1", source_ref="src:abc"))
        result = db.get_note_by_source_ref("src:abc")
        assert result is not None
        assert result.id == "n1"
        assert db.get_note_by_source_ref("src:nonexist") is None

    def test_get_notes_by_domain(self, db):
        db.write_note(_make_note("n1", domain="cti"))
        db.write_note(_make_note("n2", domain="general"))
        db.write_note(_make_note("n3", domain="cti"))
        cti_notes = db.get_notes_by_domain("cti")
        assert len(cti_notes) == 2

    def test_get_recent_notes(self, db):
        for i in range(15):
            db.write_note(_make_note(f"n{i}"))
        recent = db.get_recent_notes(limit=5)
        assert len(recent) == 5

    def test_embedding_vector_roundtrip(self, db):
        note = _make_note()
        db.write_note(note)
        result = db.get_note_by_id("n1")
        assert len(result.embedding.vector) == 768
        assert abs(result.embedding.vector[0] - 0.1) < 1e-6

    def test_reindex_vector(self, db):
        db.write_note(_make_note())
        new_vec = [0.5] * 768
        db.reindex_vector("n1", new_vec)
        result = db.get_note_by_id("n1")
        assert abs(result.embedding.vector[0] - 0.5) < 1e-6

    def test_reindex_vector_missing_note(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.reindex_vector("nonexist", [0.0] * 768)


# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------


class TestSQLiteKG:
    def test_add_and_get_node(self, db):
        node_id = db.add_kg_node("actor", "apt28")
        assert node_id.startswith("node_")
        node = db.get_kg_node("actor", "apt28")
        assert node is not None
        assert node["entity_value"] == "apt28"
        assert node["entity_type"] == "actor"

    def test_add_node_idempotent(self, db):
        id1 = db.add_kg_node("actor", "apt28")
        id2 = db.add_kg_node("actor", "apt28")
        assert id1 == id2

    def test_add_node_with_properties(self, db):
        db.add_kg_node("actor", "apt28", properties={"country": "Russia"})
        node = db.get_kg_node("actor", "apt28")
        assert node["properties"]["country"] == "Russia"

    def test_add_and_get_edge(self, db):
        db.add_kg_node("actor", "apt28")
        db.add_kg_node("tool", "cobalt-strike")
        edge_id = db.add_kg_edge("actor", "apt28", "tool", "cobalt-strike", "USES_TOOL")
        assert edge_id.startswith("edge_")
        neighbors = db.get_kg_neighbors("actor", "apt28")
        assert len(neighbors) >= 1
        assert neighbors[0]["node"]["entity_value"] == "cobalt-strike"

    def test_edge_provenance_different_notes(self, db):
        """BLOCKER-3: Same relationship from different notes creates separate edges."""
        db.add_kg_node("actor", "apt28")
        db.add_kg_node("tool", "cobalt-strike")
        e1 = db.add_kg_edge(
            "actor",
            "apt28",
            "tool",
            "cobalt-strike",
            "USES_TOOL",
            note_id="note_001",
        )
        e2 = db.add_kg_edge(
            "actor",
            "apt28",
            "tool",
            "cobalt-strike",
            "USES_TOOL",
            note_id="note_002",
        )
        # Different note_id -> different edges
        assert e1 != e2

    def test_edge_provenance_same_note_idempotent(self, db):
        """Same edge from the same note should return the same edge_id."""
        db.add_kg_node("actor", "apt28")
        db.add_kg_node("tool", "cobalt-strike")
        e1 = db.add_kg_edge(
            "actor",
            "apt28",
            "tool",
            "cobalt-strike",
            "USES_TOOL",
            note_id="note_001",
        )
        e2 = db.add_kg_edge(
            "actor",
            "apt28",
            "tool",
            "cobalt-strike",
            "USES_TOOL",
            note_id="note_001",
        )
        assert e1 == e2

    def test_edge_properties_via_note_id_in_props(self, db):
        """Edge provenance via properties dict (backward compat)."""
        db.add_kg_node("actor", "apt28")
        db.add_kg_node("tool", "cobalt-strike")
        e1 = db.add_kg_edge(
            "actor",
            "apt28",
            "tool",
            "cobalt-strike",
            "USES_TOOL",
            properties={"note_id": "n1"},
        )
        e2 = db.add_kg_edge(
            "actor",
            "apt28",
            "tool",
            "cobalt-strike",
            "USES_TOOL",
            properties={"note_id": "n2"},
        )
        assert e1 != e2

    def test_get_neighbors_with_filter(self, db):
        db.add_kg_edge("actor", "apt28", "tool", "cobalt-strike", "USES_TOOL")
        db.add_kg_edge("actor", "apt28", "campaign", "fancy-bear", "PART_OF")
        uses = db.get_kg_neighbors("actor", "apt28", relationship="USES_TOOL")
        assert len(uses) == 1
        assert uses[0]["node"]["entity_value"] == "cobalt-strike"

    def test_get_neighbors_nonexistent(self, db):
        result = db.get_kg_neighbors("actor", "nonexist")
        assert result == []

    def test_traverse_kg(self, db):
        db.add_kg_edge("actor", "apt28", "tool", "cobalt-strike", "USES_TOOL")
        db.add_kg_edge("tool", "cobalt-strike", "technique", "t1059", "IMPLEMENTS")
        paths = db.traverse_kg("actor", "apt28", max_depth=2)
        assert len(paths) >= 2  # apt28->cobalt-strike, apt28->cobalt-strike->t1059

    def test_traverse_kg_nonexistent(self, db):
        paths = db.traverse_kg("actor", "nonexist")
        assert paths == []


# ---------------------------------------------------------------------------
# Entity Index
# ---------------------------------------------------------------------------


class TestSQLiteEntityIndex:
    def test_add_and_lookup(self, db):
        db.add_entity_mapping("actor", "apt28", "n1")
        db.add_entity_mapping("tool", "cobalt-strike", "n1")
        ids = db.get_note_ids_for_entity("actor", "apt28")
        assert "n1" in ids

    def test_multiple_notes_per_entity(self, db):
        db.add_entity_mapping("actor", "apt28", "n1")
        db.add_entity_mapping("actor", "apt28", "n2")
        ids = db.get_note_ids_for_entity("actor", "apt28")
        assert set(ids) == {"n1", "n2"}

    def test_remove_mappings(self, db):
        db.add_entity_mapping("actor", "apt28", "n1")
        db.add_entity_mapping("tool", "cobalt-strike", "n1")
        db.remove_entity_mappings_for_note("n1")
        assert "n1" not in db.get_note_ids_for_entity("actor", "apt28")
        assert "n1" not in db.get_note_ids_for_entity("tool", "cobalt-strike")

    def test_search_entities(self, db):
        db.add_entity_mapping("actor", "apt28", "n1")
        db.add_entity_mapping("actor", "apt29", "n2")
        db.add_entity_mapping("tool", "cobalt-strike", "n3")
        results = db.search_entities("apt")
        assert "actor" in results
        assert len(results["actor"]) == 2

    def test_idempotent_mapping(self, db):
        db.add_entity_mapping("actor", "apt28", "n1")
        db.add_entity_mapping("actor", "apt28", "n1")  # duplicate, should not raise
        ids = db.get_note_ids_for_entity("actor", "apt28")
        assert ids == ["n1"]


# ---------------------------------------------------------------------------
# Lifecycle & health
# ---------------------------------------------------------------------------


class TestSQLiteLifecycle:
    def test_health_check(self, db):
        health = db.health_check()
        assert health["status"] == "ok"
        assert health["backend"] == "SQLiteBackend"

    def test_export_snapshot(self, db):
        import os
        import sqlite3
        import tempfile

        db.write_note(_make_note())
        outdir = tempfile.mkdtemp()
        db.export_snapshot(outdir)

        # Exported file exists and opens as a valid SQLite database with
        # the expected row (Connection.backup produces a consistent copy,
        # not a torn file like shutil.copy2 of a live WAL).
        files = [f for f in os.listdir(outdir) if f.startswith("zettelforge_") and f.endswith(".db")]
        assert len(files) == 1
        dest = os.path.join(outdir, files[0])
        conn = sqlite3.connect(dest)
        try:
            count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            assert count == 1
            row = conn.execute("SELECT content_raw FROM notes WHERE id = ?", ("n1",)).fetchone()
            assert row[0] == "APT28 uses Cobalt Strike"
        finally:
            conn.close()

    def test_reindex_vector_preserves_other_fields(self, db):
        """reindex_vector must not clobber concurrent edits to other columns.

        Simulates a concurrent mark_access_dirty bump happening between
        reindex_vector's read and write — the old RMW path would lose
        the access_count increment; the targeted UPDATE preserves it.
        """
        db.write_note(_make_note())
        # Bump access_count via the targeted UPDATE path
        db.mark_access_dirty("n1")
        db.mark_access_dirty("n1")
        before = db.get_note_by_id("n1")
        assert before.metadata.access_count == 2

        # reindex_vector should update only the vector column
        new_vec = [0.9] * 768
        db.reindex_vector("n1", new_vec)

        after = db.get_note_by_id("n1")
        assert abs(after.embedding.vector[0] - 0.9) < 1e-6
        # access_count is preserved (not clobbered by a full-row rewrite)
        assert after.metadata.access_count == 2

    def test_close_is_idempotent(self, db):
        """close() must be safe to call multiple times — atexit may race."""
        db.close()
        db.close()  # second call must not raise
        assert db.health_check()["status"] == "closed"

    def test_readers_raise_backend_closed_error_after_close(self):
        """After close(), readers raise BackendClosedError instead of NPE.

        Production log (2026-04-23) showed 170 AttributeError: 'NoneType'
        on the drain path. BackendClosedError is the clean signal callers
        can catch without scanning stack traces.
        """
        tmpdir = tempfile.mkdtemp()
        backend = SQLiteBackend(db_path=f"{tmpdir}/closed.db")
        backend.initialize()
        backend.write_note(_make_note())
        backend.close()

        with pytest.raises(BackendClosedError):
            backend.get_note_by_id("n1")
        with pytest.raises(BackendClosedError):
            backend.count_notes()
        with pytest.raises(BackendClosedError):
            backend.write_note(_make_note("n2"))

    def test_initialize_is_idempotent(self):
        """initialize() called twice must not reopen the connection."""
        tmpdir = tempfile.mkdtemp()
        backend = SQLiteBackend(db_path=f"{tmpdir}/idem.db")
        backend.initialize()
        conn1 = backend._conn
        backend.initialize()  # no-op
        assert backend._conn is conn1
        backend.close()

    def test_close_and_reopen(self):
        tmpdir = tempfile.mkdtemp()
        path = f"{tmpdir}/persist.db"

        backend = SQLiteBackend(db_path=path)
        backend.initialize()
        backend.write_note(_make_note())
        assert backend.count_notes() == 1
        backend.close()

        # Reopen and verify persistence
        backend2 = SQLiteBackend(db_path=path)
        backend2.initialize()
        assert backend2.count_notes() == 1
        result = backend2.get_note_by_id("n1")
        assert result is not None
        assert result.content.raw == "APT28 uses Cobalt Strike"
        backend2.close()


# ---------------------------------------------------------------------------
# Enrichment job ledger
# ---------------------------------------------------------------------------


class TestSQLiteEnrichmentLedger:
    def test_create_and_list_enrichment_job(self, db):
        from zettelforge.enrichment_ledger import EnrichmentJobRecord

        record = EnrichmentJobRecord.new(
            job_id="job-1",
            note_id="note-1",
            job_type="llm_ner",
            domain="cti",
            content_len=123,
        )

        db.create_enrichment_job(record)

        jobs = db.list_enrichment_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == "job-1"
        assert jobs[0]["note_id"] == "note-1"
        assert jobs[0]["job_type"] == "llm_ner"
        assert jobs[0]["state"] == "queued"
        assert jobs[0]["domain"] == "cti"
        assert jobs[0]["content_len"] == 123
        assert db.count_enrichment_jobs_by_state() == {"queued": 1}

    def test_enrichment_job_state_transitions(self, db):
        from zettelforge.enrichment_ledger import EnrichmentJobRecord

        db.create_enrichment_job(
            EnrichmentJobRecord.new(
                job_id="job-1", note_id="note-1", job_type="causal_extraction"
            )
        )

        db.mark_enrichment_job_running("job-1")
        [running] = db.list_enrichment_jobs(state="running")
        assert running["attempt_count"] == 1
        assert running["started_at"]

        db.mark_enrichment_job_terminal("job-1", "failed", error_code="queue_full")
        [failed] = db.list_enrichment_jobs(state="failed")
        assert failed["last_error_code"] == "queue_full"
        assert failed["finished_at"]
        assert db.count_enrichment_jobs_by_state() == {"failed": 1}

    def test_invalid_terminal_state_rejected(self, db):
        with pytest.raises(ValueError, match="Invalid terminal"):
            db.mark_enrichment_job_terminal("job-1", "running")
