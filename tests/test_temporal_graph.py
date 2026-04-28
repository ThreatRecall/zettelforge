#!/usr/bin/env python3
"""
Test temporal graph functionality in ZettelForge.
Validates Task 2: Temporal graph indexing and queries.

Note: Temporal queries are Enterprise features. Tests use the
enable_enterprise fixture from conftest.py.
"""
import sys
import tempfile
import time
import pytest

# Package installed via pip - no sys.path manipulation needed
from zettelforge import MemoryManager
from zettelforge.knowledge_graph import KnowledgeGraph, get_knowledge_graph


@pytest.fixture(autouse=True)
def _enterprise(enable_enterprise):
    """All temporal graph tests require Enterprise."""
    pass


def test_temporal_graph():
    print("=== Temporal Graph Test ===\n")
    
    # Create temp memory manager with fresh KG
    tmpdir = tempfile.mkdtemp()
    mm = MemoryManager(
        jsonl_path=f'{tmpdir}/notes.jsonl',
        lance_path=f'{tmpdir}/vectordb'
    )
    
    # Create test notes with different timestamps (simulated via different remember calls)
    print("[1] Creating test notes...")
    
    note1_content = "Server ALPHA is COMPROMISED - attacker gained root access via CVE-2024-1111"
    note1, _ = mm.remember(note1_content, domain="incident")
    print(f"  Note 1: {note1.id}")
    
    time.sleep(0.1)
    
    note2_content = "Server ALPHA has been PATCHED - CVE-2024-1111 remediated, system secured"
    note2, _ = mm.remember(note2_content, domain="incident")
    print(f"  Note 2: {note2.id}")
    
    # Trigger supersession (note2 supersedes note1)
    print("\n[2] Triggering supersession...")
    mm._check_supersession(note2, mm.indexer.extractor.extract_all(note2.content.raw))
    
    # Get knowledge graph
    kg = get_knowledge_graph()
    
    print("\n[3] Checking temporal edges...")
    print(f"  Total edges in KG: {len(kg._edges)}")
    
    # Look for SUPERSEDES edges
    supersedes_edges = [e for e in kg._edges.values() if e.get('relationship') == 'SUPERSEDES']
    print(f"  SUPERSEDES edges: {len(supersedes_edges)}")
    
    for edge in supersedes_edges:
        from_node = kg._nodes.get(edge.get('from_node_id'), {})
        to_node = kg._nodes.get(edge.get('to_node_id'), {})
        print(f"    {from_node.get('entity_value')} SUPERSEDES {to_node.get('entity_value')}")
        print(f"    Timestamp: {edge.get('properties', {}).get('timestamp')}")
    
    print("\n[4] Testing timeline queries...")
    
    # Get timeline for Server ALPHA
    timeline = kg.get_entity_timeline("note", note1.id)
    print(f"  Timeline for note1: {len(timeline)} events")
    for event in timeline:
        print(f"    {event['timestamp']}: {event['to_entity']}")
    
    # Get changes since old timestamp
    changes = kg.get_changes_since("2020-01-01")
    print(f"  Changes since 2020-01-01: {len(changes)}")
    
    print("\n[5] Testing get_latest_state...")
    latest = kg.get_latest_state("note", note2.id)
    if latest:
        print(f"  Latest state of note2: {latest.get('to_entity')}")
    
    print("\n=== Test Complete ===")
    return len(supersedes_edges) > 0


if __name__ == '__main__':
    success = test_temporal_graph()
    sys.exit(0 if success else 1)