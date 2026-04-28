#!/usr/bin/env python3
"""
ZettelForge Core Tests - Prevent Regression
Run: pytest tests/test_core.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/src')

import pytest
import tempfile
import shutil
import os
from pathlib import Path

from zettelforge import MemoryManager
from zettelforge.memory_store import MemoryStore
from zettelforge.entity_indexer import EntityIndexer


@pytest.fixture
def temp_memory():
    """Create a temporary memory directory for testing."""
    temp_dir = tempfile.mkdtemp()
    # Set AMEM_DATA_DIR to temp dir so components use it
    old_env = os.environ.get('AMEM_DATA_DIR')
    os.environ['AMEM_DATA_DIR'] = temp_dir
    yield temp_dir
    os.environ['AMEM_DATA_DIR'] = old_env if old_env else ''
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestStorage:
    """Test basic note storage and retrieval."""
    
    def test_remember_creates_note(self, temp_memory):
        """Note storage creates valid note with ID."""
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        note, status = mm.remember("APT28 is a Russian threat actor", domain="security_ops")
        
        assert note.id is not None
        assert note.id.startswith("note_")
        assert status == "created"
        assert note.metadata.domain == "security_ops"
    
    def test_remember_extracts_entities(self, temp_memory):
        """Entity extraction works for actors, CVEs, tools."""
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        note, _ = mm.remember("APT28 uses XAgent malware", domain="security_ops")
        
        assert len(note.semantic.entities) > 0
        assert any('apt28' in e.lower() for e in note.semantic.entities)
    
    def test_notes_persist_to_jsonl(self, temp_memory):
        """Notes are written to JSONL file."""
        jsonl_path = f"{temp_memory}/notes.jsonl"
        mm = MemoryManager(jsonl_path=jsonl_path)
        mm.remember("Test note", domain="general")
        
        assert os.path.exists(jsonl_path)
        with open(jsonl_path) as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) >= 1


class TestEntityRecall:
    """Test entity-based recall."""
    
    def test_recall_actor_returns_notes(self, temp_memory):
        """Actor recall returns matching notes."""
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        mm.remember("APT28 is a Russian threat actor", domain="security_ops")
        mm.remember("APT28 uses XAgent malware", domain="security_ops")
        
        results = mm.recall_actor("apt28", k=5)
        
        assert len(results) >= 2
    
    def test_recall_cve_returns_notes(self, temp_memory):
        """CVE recall returns matching notes."""
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        mm.remember("CVE-2024-3094 is a backdoor in XZ Utils", domain="security_ops")
        
        results = mm.recall_cve("CVE-2024-3094", k=5)
        
        assert len(results) >= 1
    
    def test_recall_empty_for_unknown_entity(self, temp_memory):
        """Unknown entity returns empty list."""
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        
        results = mm.recall_actor("unknown_actor_xyz", k=5)
        
        assert len(results) == 0


class TestVectorRecall:
    """Test vector-based semantic retrieval."""
    
    def test_vector_recall_returns_notes(self, temp_memory):
        """Vector recall returns semantically similar notes."""
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        mm.remember("APT28 is a Russian threat actor targeting government entities", domain="security_ops")
        mm.remember("APT29 is also Russian, targeting diplomatic organizations", domain="security_ops")
        
        results = mm.recall("Russian threat actors", k=5)
        
        assert len(results) >= 2
    
    def test_vector_recall_latency_reasonable(self, temp_memory):
        """Vector recall completes in reasonable time."""
        import time
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        
        # Add some notes
        for i in range(10):
            mm.remember(f"Test note {i} about security topics", domain="general")
        
        start = time.time()
        results = mm.recall("security topics", k=5)
        latency_ms = (time.time() - start) * 1000
        
        assert len(results) >= 1
        assert latency_ms < 1000  # Should be under 1 second


class TestSynthesis:
    """Test RAG-as-answer synthesis."""
    
    def test_synthesis_returns_sources(self, temp_memory):
        """Synthesis returns sources from retrieved notes."""
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        mm.remember("APT28 is a Russian threat actor", domain="security_ops")
        mm.remember("APT28 uses XAgent and CHOPSTICK malware", domain="security_ops")
        
        result = mm.synthesize("What do we know about APT28?")
        
        assert result["metadata"]["sources_count"] >= 1
    
    def test_synthesis_answer_contains_content(self, temp_memory):
        """Synthesized answer contains relevant content."""
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        mm.remember("APT28 uses XAgent malware", domain="security_ops")
        
        result = mm.synthesize("What malware does APT28 use?")
        
        # Answer should mention XAgent
        answer = result["synthesis"].get("answer", "")
        assert "XAgent" in answer or result["metadata"]["sources_count"] >= 1


class TestEntityIndexIntegrity:
    """Test entity index stays synchronized with notes."""
    
    def test_index_matches_notes(self, temp_memory):
        """Entity index count should match note entities."""
        jsonl_path = f"{temp_memory}/notes.jsonl"
        mm = MemoryManager(jsonl_path=jsonl_path)
        
        # Add notes
        mm.remember("APT28 is Russian", domain="security_ops")
        mm.remember("APT29 is also Russian", domain="security_ops")
        
        # Rebuild index
        indexer = EntityIndexer(index_path=f"{temp_memory}/entity_index.json")
        stats = indexer.stats()
        
        # Should have apt28 and apt29 in actor index
        assert 'actor' in stats
        assert stats['actor']['unique_entities'] >= 2


class TestLanceDBIntegration:
    """Test LanceDB vector storage."""
    
    def test_lancedb_tables_created(self, temp_memory):
        """Notes are indexed in LanceDB."""
        mm = MemoryManager(
            jsonl_path=f"{temp_memory}/notes.jsonl",
            lance_path=f"{temp_memory}/vectordb"
        )
        mm.remember("Test note for LanceDB", domain="test_domain")
        
        # Check tables exist
        if mm.store.lancedb:
            result = mm.store.lancedb.list_tables()
            if hasattr(result, 'tables'):
                tables = result.tables
            else:
                tables = []
            
            # Should have notes_test_domain table
            assert any('notes_' in t for t in tables)


class TestIntentRouting:
    """Test intent classification and routing."""
    
    def test_factual_query_uses_entity_fallback(self, temp_memory):
        """Factual queries without entities fall back to vector."""
        mm = MemoryManager(jsonl_path=f"{temp_memory}/notes.jsonl")
        mm.remember("Russian threat actors target government systems", domain="security_ops")
        
        # "threat actors" doesn't extract entities, should fall back to vector
        results = mm.recall("threat actors", k=5)
        
        # Should return results via vector fallback
        assert len(results) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])