#!/usr/bin/env python3
"""
Test intent classifier in ZettelForge.
Validates Task 3: Lightweight intent classifier for adaptive query routing.
"""
import sys
# Package installed via pip - no sys.path manipulation needed

from zettelforge.intent_classifier import IntentClassifier, get_intent_classifier, QueryIntent


def test_intent_classification():
    print("=== Intent Classifier Test ===\n")
    
    classifier = get_intent_classifier()
    
    # Test queries
    test_queries = [
        # FACTUAL
        ("What CVE was used in the SolarWinds attack?", QueryIntent.FACTUAL),
        ("Which APT group targets energy sector?", QueryIntent.FACTUAL),
        ("What malware does APT28 use?", QueryIntent.FACTUAL),
        
        # TEMPORAL
        ("What changed since May 2024?", QueryIntent.TEMPORAL),
        ("When was Server ALPHA compromised?", QueryIntent.TEMPORAL),
        ("What is the history of this vulnerability?", QueryIntent.TEMPORAL),
        
        # RELATIONAL
        ("Who uses Cobalt Strike?", QueryIntent.RELATIONAL),
        ("Which actors target healthcare?", QueryIntent.RELATIONAL),
        
        # CAUSAL
        ("Why did the incident happen?", QueryIntent.CAUSAL),
        ("What caused the breach?", QueryIntent.CAUSAL),
        
        # EXPLORATORY
        ("Tell me about APT28", QueryIntent.EXPLORATORY),
        ("Explain the threat landscape", QueryIntent.EXPLORATORY),
    ]
    
    results = []
    for query, expected in test_queries:
        intent, meta = classifier.classify(query)
        match = "✓" if intent == expected else "✗"
        results.append(match)
        print(f"{match} Query: \"{query}\"")
        print(f"   Expected: {expected.value}, Got: {intent.value} (conf={meta.get('confidence', 0):.2f}, method={meta.get('method')})")
        
        # Test traversal policy
        policy = classifier.get_traversal_policy(intent)
        print(f"   Policy: vector={policy['vector']}, graph={policy['graph']}, temporal={policy['temporal']}")
        print()
    
    # Summary
    correct = sum(1 for r in results if r == "✓")
    print(f"=== Results: {correct}/{len(test_queries)} correct ===")
    
    # Test adaptive recall
    print("\n[Testing Adaptive Recall]")
    
    import tempfile
    from zettelforge import MemoryManager
    
    tmpdir = tempfile.mkdtemp()
    mm = MemoryManager(
        jsonl_path=f'{tmpdir}/notes.jsonl',
        lance_path=f'{tmpdir}/vectordb'
    )
    
    # Add some notes
    mm.remember("CVE-2024-1111 is a critical vulnerability in Microsoft Exchange", domain="cti")
    mm.remember("APT28 uses Cobalt Strike for lateral movement", domain="cti")
    
    # Test factual recall
    print("\n[Factual Query: What CVE?]")
    results = mm.recall("What CVE was mentioned?", k=3)
    print(f"  Retrieved {len(results)} notes")
    
    # Test relational recall
    print("\n[Relational Query: Who uses what?]")
    results = mm.recall("Who uses Cobalt Strike?", k=3)
    print(f"  Retrieved {len(results)} notes")
    
    print("\n=== Test Complete ===")
    return correct >= len(test_queries) * 0.7


if __name__ == '__main__':
    success = test_intent_classification()
    sys.exit(0 if success else 1)