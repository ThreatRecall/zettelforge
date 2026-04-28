#!/usr/bin/env python3
"""
Test causal triple extraction in ZettelForge.
Validates Task 1: LLM-based causal edge extraction from consolidation pass.
"""
import sys
import tempfile
# Package installed via pip - no sys.path manipulation needed

from zettelforge import MemoryManager
from zettelforge.note_constructor import NoteConstructor
from zettelforge.knowledge_graph import get_knowledge_graph


def test_causal_extraction():
    print("=== Causal Triple Extraction Test ===\n")
    
    # Create temp memory manager with fresh KG
    tmpdir = tempfile.mkdtemp()
    mm = MemoryManager(
        jsonl_path=f'{tmpdir}/notes.jsonl',
        lance_path=f'{tmpdir}/vectordb'
    )
    
    # Test CTI content with causal relationships
    cti_content = """
    APT28 (Fancy Bear) continues to target critical infrastructure in the energy sector.
    The group uses DROPBEAR malware for initial access and Cobalt Strike for lateral movement.
    CVE-2024-1111 enables remote code execution on unpatched Microsoft Exchange servers.
    APT48 used this vulnerability to compromise Server ALPHA on May 15, 2024.
    The incident was contained after patching on May 20, 2024.
    """
    
    print("Input CTI content:")
    print(cti_content[:300])
    print()
    
    # Remember the note - should trigger causal extraction
    note, status = mm.remember(cti_content, domain="cti")
    print(f"Note created: {note.id}")
    print(f"Status: {status}")
    print()
    
    # Check knowledge graph for causal edges
    kg = get_knowledge_graph()
    
    print("=== Knowledge Graph Results ===")
    
    # Check edges
    print(f"\nTotal nodes: {len(kg._nodes)}")
    print(f"Total edges: {len(kg._edges)}")
    
    # List all edges
    print("\nEdges in graph:")
    for edge_id, edge in list(kg._edges.items())[:20]:
        from_node = kg._nodes.get(edge.get('from_node_id'), {})
        to_node = kg._nodes.get(edge.get('to_node_id'), {})
        print(f"  {from_node.get('entity_value')} --[{edge.get('relationship')}]--> {to_node.get('entity_value')}")
    
    # Check for causal triples specifically
    print("\n=== Causal Edges (from LLM extraction) ===")
    causal_edges = [e for e in kg._edges.values() if e.get('properties', {}).get('source') == 'llm_extraction']
    print(f"Causal edges found: {len(causal_edges)}")
    
    for edge in causal_edges:
        from_node = kg._nodes.get(edge.get('from_node_id'), {})
        to_node = kg._nodes.get(edge.get('to_node_id'), {})
        print(f"  ✓ {from_node.get('entity_value')} --[{edge.get('relationship')}]--> {to_node.get('entity_value')}")
        print(f"    Properties: {edge.get('properties')}")
    
    # Test graph traversal
    print("\n=== Graph Traversal Test ===")
    results = kg.traverse("actor", "apt28", max_depth=2)
    print(f"Traversing from APT28 (depth=2): {len(results)} paths found")
    for r in results[:5]:
        path_str = " -> ".join([f"{s['from_value']}-{s['relationship']}-{s['to_value']}" for s in r])
        print(f"  {path_str}")
    
    print("\n=== Test Complete ===")
    return len(causal_edges) > 0


if __name__ == '__main__':
    success = test_causal_extraction()
    sys.exit(0 if success else 1)