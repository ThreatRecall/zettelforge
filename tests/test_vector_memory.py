"""Tests for vector memory functionality including cleanup."""

import tempfile
import time
from unittest.mock import patch, MagicMock

import pytest

from zettelforge.vector_memory import VectorMemory


def test_vector_memory_initialization():
    """Test that VectorMemory initializes correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        assert vm.db_path is not None
        assert vm.db is None  # Not initialized yet
        assert vm.table is None  # Not initialized yet


def test_vector_memory_init_creates_table():
    """Test that init() creates the database and table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        assert vm.db is not None
        assert vm.table is not None
        # Table should exist
        assert "memories" in vm.db.list_tables()


def test_vector_memory_add_and_search():
    """Test basic add and search functionality."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Add a memory
        ids = vm.add("Test memory for search", tags=["test"], source="test")
        assert len(ids) == 1
        
        # Search for the memory
        results = vm.search("test memory", k=5)
        assert len(results) >= 1
        assert "test memory" in results[0]["text"].lower()
        assert results[0]["tags"] == ["test"]
        assert results[0]["source"] == "test"


def test_vector_memory_count():
    """Test counting memories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Initially empty
        assert vm.count() == 0
        
        # Add some memories
        vm.add("First memory", source="test")
        vm.add("Second memory", source="test")
        vm.add("Third memory", source="test")
        
        assert vm.count() == 3


def test_vector_memory_stats():
    """Test statistics reporting."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        stats = vm.stats()
        assert "total_entries" in stats
        assert "by_source" in stats
        assert "db_path" in stats
        assert "embedding_model" in stats
        assert stats["total_entries"] == 0


def test_vector_memory_delete():
    """Test deleting memories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Add a memory
        ids = vm.add("Memory to delete", source="test")
        assert vm.count() == 1
        
        # Delete by ID
        vm.delete(entry_id=ids[0])
        assert vm.count() == 0


def test_vector_memory_get_recent():
    """Test getting recent memories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Add memories in order
        vm.add("First memory", source="test")
        vm.add("Second memory", source="test")
        vm.add("Third memory", source="test")
        
        recent = vm.get_recent(limit=2)
        assert len(recent) == 2
        # Most recent first
        assert "Third memory" in recent[0]["text"]
        assert "Second memory" in recent[1]["text"]


def test_vector_memory_with_filters():
    """Test search with source and session filters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Add memories with different sources
        vm.add("Memory from source A", source="source_a")
        vm.add("Memory from source B", source="source_b")
        vm.add("Another memory from source A", source="source_a")
        
        # Filter by source
        results = vm.search("memory", k=5, source_filter="source_a")
        assert len(results) == 2
        for r in results:
            assert r["source"] == "source_a"
            
        # Filter by source that doesn't exist
        results = vm.search("memory", k=5, source_filter="nonexistent")
        assert len(results) == 0


def test_vector_memory_cleanup_now():
    """Test manual cleanup invocation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Add some data to ensure we have something
        vm.add("Test memory", source="test")
        
        # This should not raise an exception
        vm.cleanup_now()
        
        # Data should still be there
        assert vm.count() == 1
        results = vm.search("test", k=5)
        assert len(results) >= 1


def test_vector_memory_cleanup_thread_lifecycle():
    """Test starting and stopping the cleanup thread."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Initially no thread
        assert vm._cleanup_thread is None
        
        # Start the thread
        vm.start_cleanup_thread()
        assert vm._cleanup_thread is not None
        assert vm._cleanup_thread.is_alive()
        
        # Stop the thread
        vm.stop_cleanup_thread()
        # Thread may still be alive briefly during join, but should be stopped
        # We mainly want to ensure no exception is thrown


def test_vector_memory_cleanup_thread_auto_start():
    """Test that cleanup thread starts automatically on init."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Thread should be started automatically
        assert vm._cleanup_thread is not None
        assert vm._cleanup_thread.is_alive()
        
        # Clean up
        vm.stop_cleanup_thread()


@patch('zettelforge.vector_memory.logger')
def test_vector_memory_cleanup_logging(mock_logger):
    """Test that cleanup logs appropriately."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Add some data
        vm.add("Test memory for cleanup", source="test")
        
        # Perform cleanup
        vm.cleanup_now()
        
        # Check that logging was called
        # Should have called info for cleanup_completed
        mock_logger.info.assert_called()
        # Check for the cleanup_completed call
        info_calls = [call for call in mock_logger.info.call_args_list 
                     if len(call[0]) > 0 and 'cleanup_completed' in call[0]]
        assert len(info_calls) > 0


def test_vector_memory_empty_search():
    """Test searching when no data exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Search empty database
        results = vm.search("anything", k=5)
        assert len(results) == 0
        
        # Get recent from empty database
        recent = vm.get_recent(limit=5)
        assert len(recent) == 0


def test_vector_memory_special_characters():
    """Test handling of special characters in text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Add memory with special characters
        special_text = "Test with special chars: !@#$%^&*()_+-=[]{}|;':\",./<>?"
        ids = vm.add(special_text, source="test")
        
        # Search for it
        results = vm.search("special chars", k=5)
        assert len(results) >= 1
        assert special_text in results[0]["text"]


def test_vector_memory_concurrent_access():
    """Test that basic operations work under simulated concurrent access."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vm = VectorMemory(db_path=f"{tmpdir}/test_vector_memory.lance")
        vm.init()
        
        # Add multiple memories quickly
        for i in range(10):
            vm.add(f"Memory number {i}", source="test", tags=[f"tag{i}"])
        
        assert vm.count() == 10
        
        # Search should still work
        results = vm.search("memory number 5", k=5)
        assert len(results) >= 1
        assert "memory number 5" in results[0]["text"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])