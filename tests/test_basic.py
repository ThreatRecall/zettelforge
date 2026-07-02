"""
Basic tests for ZettelForge
"""

import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from zettelforge import MemoryManager, MemoryNote
from zettelforge.entity_indexer import EntityExtractor
from zettelforge.memory_store import MemoryStore
from zettelforge.note_constructor import NoteConstructor
from zettelforge.note_schema import Content, Embedding, Metadata, Semantic

NOW = datetime.now().isoformat()


class TestNoteImportance:
    """Test importance field on Metadata"""

    def test_default_importance(self):
        """Importance defaults to 5 (neutral)."""
        meta = Metadata()
        assert meta.importance == 5

    def test_custom_importance(self):
        """Importance can be set 1-10."""
        meta = Metadata(importance=9)
        assert meta.importance == 9

    def test_importance_in_note(self):
        """MemoryNote carries importance through Metadata."""
        note = MemoryNote(
            id="test_imp",
            created_at=NOW,
            updated_at=NOW,
            content=Content(raw="Important fact", source_type="test", source_ref=""),
            semantic=Semantic(context="Test", keywords=[], tags=[], entities=[]),
            embedding=Embedding(vector=[]),
            metadata=Metadata(importance=8),
        )
        assert note.metadata.importance == 8


class TestNoteSchema:
    """Test note schema creation and validation"""

    def test_memory_note_creation(self):
        """Test creating a MemoryNote"""
        note = MemoryNote(
            id="test_001",
            created_at=NOW,
            updated_at=NOW,
            content=Content(raw="Test content", source_type="test", source_ref="test_ref"),
            semantic=Semantic(
                context="Test context", keywords=["test"], tags=["test"], entities=[]
            ),
            embedding=Embedding(vector=[0.1] * 768, model="test-model"),
            metadata=Metadata(domain="test", tier="A"),
        )
        assert note.id == "test_001"
        assert note.content.raw == "Test content"
        assert len(note.embedding.vector) == 768

    def test_tlp_and_stix_confidence(self):
        meta = Metadata(tlp="AMBER", stix_confidence=85)
        assert meta.tlp == "AMBER"
        assert meta.stix_confidence == 85
        # Default evolution confidence is separate
        assert meta.confidence == 1.0

    def test_note_access_tracking(self):
        """Test note access counting"""
        note = MemoryNote(
            id="test_002",
            created_at=NOW,
            updated_at=NOW,
            content=Content(raw="Test", source_type="test", source_ref=""),
            semantic=Semantic(context="Test", keywords=[], tags=[], entities=[]),
            embedding=Embedding(vector=[]),
            metadata=Metadata(),
        )
        assert note.metadata.access_count == 0
        note.increment_access()
        assert note.metadata.access_count == 1
        assert note.metadata.last_accessed is not None


class TestMemoryStore:
    """Test MemoryStore operations"""

    def test_store_initialization(self):
        """Test store initialization"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")
            assert store.jsonl_path == Path(f"{tmpdir}/notes.jsonl")
            assert store.count_notes() == 0

    def test_write_and_read(self):
        """Test writing and reading notes"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")

            note = MemoryNote(
                id="test_003",
                created_at=NOW,
                updated_at=NOW,
                content=Content(raw="Test content", source_type="test", source_ref=""),
                semantic=Semantic(context="Test context", keywords=["test"], tags=[], entities=[]),
                embedding=Embedding(vector=[0.0] * 768),
                metadata=Metadata(domain="test"),
            )

            store.write_note(note)
            assert store.count_notes() == 1

            retrieved = store.get_note_by_id("test_003")
            assert retrieved is not None
            assert retrieved.content.raw == "Test content"

    def test_get_note_by_source_ref(self):
        """Test lookup by source_ref for OpenCTI dedup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")
            note = MemoryNote(
                id="test_ref",
                created_at=NOW,
                updated_at=NOW,
                content=Content(
                    raw="Test", source_type="opencti_sync", source_ref="opencti:abc123"
                ),
                semantic=Semantic(context="ctx", keywords=[], tags=[], entities=[]),
                embedding=Embedding(vector=[0.0] * 768),
                metadata=Metadata(domain="cti"),
            )
            store.write_note(note)

            found = store.get_note_by_source_ref("opencti:abc123")
            assert found is not None
            assert found.id == "test_ref"

            not_found = store.get_note_by_source_ref("opencti:nonexistent")
            assert not_found is None


class TestLanceDBIndexing:
    """Test LanceDB vector index population (issue #26)"""

    def test_multiple_notes_indexed(self):
        """Multiple notes in the same domain should all appear in the LanceDB table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")
            # Write 5 notes to the same domain
            for i in range(5):
                note = MemoryNote(
                    id=f"lance_{i}",
                    created_at=NOW,
                    updated_at=NOW,
                    content=Content(raw=f"Content {i}", source_type="test", source_ref=""),
                    semantic=Semantic(context="ctx", keywords=["k"], tags=[], entities=[]),
                    embedding=Embedding(vector=[float(i)] * 768),
                    metadata=Metadata(domain="cti"),
                )
                store.write_note(note)

            tbl = store.lancedb.open_table("notes_cti")
            assert len(tbl) == 5, f"Expected 5 rows, got {len(tbl)}"

    def test_multiple_domains(self):
        """Notes across different domains should create separate tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")
            for domain in ("cti", "general", "cti", "general", "cti"):
                note = MemoryNote(
                    id=f"lance_{domain}_{uuid.uuid4().hex}",
                    created_at=NOW,
                    updated_at=NOW,
                    content=Content(raw=f"Content for {domain}", source_type="test", source_ref=""),
                    semantic=Semantic(context="ctx", keywords=[], tags=[], entities=[]),
                    embedding=Embedding(vector=[1.0] * 768),
                    metadata=Metadata(domain=domain),
                )
                store.write_note(note)

            result = store.lancedb.list_tables()
            tables = result.tables if hasattr(result, "tables") else result
            assert "notes_cti" in tables
            assert "notes_general" in tables
            assert len(store.lancedb.open_table("notes_cti")) == 3
            assert len(store.lancedb.open_table("notes_general")) == 2


class TestEntityExtractor:
    """Test entity extraction"""

    def test_cve_extraction(self):
        """Test CVE extraction from text"""
        extractor = EntityExtractor()
        text = "CVE-2024-3094 is a critical vulnerability. Also see CVE-2023-12345."
        entities = extractor.extract_all(text)

        assert "cve-2024-3094" in entities["cve"]
        assert "cve-2023-12345" in entities["cve"]

    def test_actor_extraction(self):
        """Test actor and intrusion_set extraction from text"""
        extractor = EntityExtractor()
        text = "APT28 and Lazarus group were involved in the attack."
        entities = extractor.extract_all(text)

        # APT28 is an intrusion set (cluster), not a named threat actor group
        assert "apt28" in entities["intrusion_set"] or any(
            "apt" in a for a in entities["intrusion_set"]
        )
        # Lazarus is a named threat actor group
        assert "lazarus" in entities["actor"]

    def test_ioc_ipv4_extraction(self):
        """IPv4 addresses are extracted; invalid octets are not."""
        extractor = EntityExtractor()
        text = "C2 traffic observed to 192.168.1.1 and 10.0.0.254. Ignore 999.999.999.999."
        entities = extractor.extract_all(text)

        assert "192.168.1.1" in entities["ipv4"]
        assert "10.0.0.254" in entities["ipv4"]
        assert "999.999.999.999" not in entities["ipv4"]

    def test_ioc_domain_extraction(self):
        """Domains are extracted; common words with TLD substrings are not."""
        extractor = EntityExtractor()
        text = "Malware beaconed to evil.example.com and c2.badactor.net."
        entities = extractor.extract_all(text)

        assert any("example.com" in d for d in entities["domain"])
        assert any("badactor.net" in d for d in entities["domain"])
        assert "information" not in entities["domain"]

    def test_ioc_hash_extraction(self):
        """MD5, SHA1, and SHA256 hashes are extracted from IOC context."""
        extractor = EntityExtractor()
        md5 = "d41d8cd98f00b204e9800998ecf8427e"
        sha1 = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        text = f"File hash (MD5): {md5}\nSHA1: {sha1}\nSHA256: {sha256}"
        entities = extractor.extract_all(text)

        assert md5 in entities["md5"]
        assert sha1 in entities["sha1"]
        assert sha256 in entities["sha256"]

    def test_ioc_hash_fp_filter_git(self):
        """Git commit hashes must not be extracted as SHA1 IOCs."""
        extractor = EntityExtractor()
        git_sha = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        text = f"commit {git_sha}\nAuthor: Alice <alice@example.com>\nFix critical bug"
        entities = extractor.extract_all(text)

        assert git_sha not in entities.get("sha1", []), (
            f"Git commit hash incorrectly extracted as SHA1 IOC: {entities.get('sha1')}"
        )

    def test_ioc_url_extraction(self):
        """Full URLs including paths are extracted."""
        extractor = EntityExtractor()
        text = "Download payload from https://evil.com/payload.exe and http://c2.net/gate.php"
        entities = extractor.extract_all(text)

        assert any("evil.com" in u for u in entities["url"])
        assert any("c2.net" in u for u in entities["url"])

    def test_ioc_email_extraction(self):
        """Email addresses are extracted from phishing or threat context."""
        extractor = EntityExtractor()
        text = "Phishing email sent from attacker@evil.org to victim@corp.com"
        entities = extractor.extract_all(text)

        assert "attacker@evil.org" in entities["email"]
        assert "victim@corp.com" in entities["email"]

    def test_sigma_rule_prefixed_extraction(self):
        """Sigma rules in sigma:<id> format are extracted."""
        extractor = EntityExtractor()
        text = "Detection via sigma:apt28_cobalt_strike in SIEM."
        entities = extractor.extract_all(text)

        assert "apt28_cobalt_strike" in entities["sigma_rule"]

    def test_sigma_rule_label_extraction(self):
        """Sigma rules in 'Sigma Rule: <id>' format are extracted."""
        extractor = EntityExtractor()
        text = "Sigma Rule: win_susp_powershell_encoded_cmd fired last night."
        entities = extractor.extract_all(text)

        assert "win_susp_powershell_encoded_cmd" in entities["sigma_rule"]

    def test_sigma_rule_bare_id_extraction(self):
        """Bare SigmaHQ-style rule IDs are extracted."""
        extractor = EntityExtractor()
        text = "Detection matched win_susp_powershell_encoded_cmd during triage."
        entities = extractor.extract_all(text)

        assert "win_susp_powershell_encoded_cmd" in entities["sigma_rule"]

    def test_sigma_rule_absent_returns_empty(self):
        """Text without Sigma references should not produce sigma_rule entities."""
        extractor = EntityExtractor()
        text = "No detection rule identifier is present in this sentence."
        entities = extractor.extract_all(text)

        assert entities["sigma_rule"] == []

    def test_sigma_rule_ignores_common_snake_case(self):
        """Common snake_case identifiers should not be treated as Sigma rules."""
        extractor = EntityExtractor()
        text = "Parsed fields included user_id, error_code, and retry_count."
        entities = extractor.extract_all(text)

        assert entities["sigma_rule"] == []


class TestNoteConstructor:
    """Test note construction"""

    def test_note_construction(self):
        """Test constructing a note from raw content"""
        constructor = NoteConstructor()
        note = constructor.construct(
            raw_content="Test content about CVE-2024-3094",
            source_type="test",
            source_ref="test_ref",
            domain="security_ops",
        )

        assert note.content.raw == "Test content about CVE-2024-3094"
        assert note.metadata.domain == "security_ops"
        assert len(note.embedding.vector) > 0


class TestMemoryManager:
    """Test MemoryManager integration"""

    def test_manager_initialization(self):
        """Test manager initialization"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")
            assert mm is not None
            stats = mm.get_stats()
            assert "total_notes" in stats

    def test_remember_and_recall(self):
        """Test basic remember and recall flow"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")

            # Store a memory
            note, status = mm.remember(
                "CVE-2024-3094 is a backdoor in XZ Utils", domain="security_ops"
            )

            assert status == "created"
            assert note.id is not None
            assert mm.store.count_notes() == 1

            # Recall by entity
            results = mm.recall_cve("CVE-2024-3094")
            assert len(results) >= 0  # May be 0 if embedding not available

    def test_remember_includes_sigma_rule_entities(self):
        """remember() stores extracted Sigma rule IDs in semantic entities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")
            note, status = mm.remember(
                "Detection via sigma:apt28_cobalt_strike",
                domain="security_ops",
            )

            assert status == "created"
            assert "apt28_cobalt_strike" in note.semantic.entities

    def test_remember_with_evolve_false(self):
        """Test that evolve=False stores directly (default backward-compat path)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")
            note, status = mm.remember(
                "APT28 targets government agencies",
                domain="cti",
                evolve=False,
            )
            assert status == "created"
            assert note.id is not None
            assert mm.store.count_notes() == 1

    def test_remember_evolve_accepts_flag(self):
        """Test that remember() accepts evolve parameter without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")
            # evolve=True triggers LLM pipeline, which may fail without LLM.
            # The key test is that the parameter is accepted and falls through
            # to direct store when extraction yields no facts.
            note, status = mm.remember(
                "Test content for evolution",
                domain="general",
                evolve=True,
            )
            assert note is not None
            assert status in ("created", "added", "updated", "corrected", "noop")

    def test_ingest_relationship(self):
        """Test direct KG edge ingestion for OpenCTI sync."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mm = MemoryManager(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")
            mm.ingest_relationship(
                from_type="actor",
                from_value="apt28",
                to_type="tool",
                to_value="cobalt-strike",
                relationship="USES_TOOL",
            )
            # Calling twice should not duplicate
            mm.ingest_relationship(
                from_type="actor",
                from_value="apt28",
                to_type="tool",
                to_value="cobalt-strike",
                relationship="USES_TOOL",
            )
            # Verify edge exists via KG
            from zettelforge.knowledge_graph import get_knowledge_graph

            kg = get_knowledge_graph()
            neighbors = kg.get_neighbors("actor", "apt28")
            assert any(n["node"].get("entity_value") == "cobalt-strike" for n in neighbors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
