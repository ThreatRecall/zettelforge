#!/usr/bin/env python3
"""
ZettelForge Scale Benchmark - Stress Test at 500+ Notes
Run: python tests/benchmark_scale.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/src')

import time
import tempfile
import shutil
from pathlib import Path

from zettelforge import MemoryManager
from zettelforge.entity_indexer import EntityIndexer


def run_scale_benchmark(note_counts=[100, 250, 500]):
    """Run benchmark at increasing scale."""
    results = []
    
    for count in note_counts:
        print(f"\n{'='*60}")
        print(f"SCALE BENCHMARK: {count} NOTES")
        print(f"{'='*60}")
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        jsonl_path = f"{temp_dir}/notes.jsonl"
        lance_path = f"{temp_dir}/vectordb"
        
        try:
            mm = MemoryManager(jsonl_path=jsonl_path, lance_path=lance_path)
            
            # Ingestion benchmark
            print(f"\n[INGESTION] Writing {count} notes...")
            start = time.time()
            
            actors = ["APT28", "APT29", "APT41", "Lazarus", "Volt Typhoon"]
            tools = ["Cobalt Strike", "Mimikatz", "XAgent", "CHOPSTICK"]
            cves = ["CVE-2024-3094", "CVE-2024-1111", "CVE-2025-14816"]
            
            for i in range(count):
                actor = actors[i % len(actors)]
                tool = tools[i % len(tools)]
                cve = cves[i % len(cves)] if i % 3 == 0 else None
                
                if cve:
                    content = f"{actor} uses {tool} and exploits {cve} to target organizations"
                else:
                    content = f"{actor} uses {tool} for espionage operations"
                
                mm.remember(content, domain="security_ops")
            
            ingestion_time = time.time() - start
            notes_per_sec = count / ingestion_time
            print(f"  Ingestion: {ingestion_time:.2f}s ({notes_per_sec:.1f} notes/sec)")
            
            # Entity recall benchmark
            print(f"\n[ENTITY RECALL] Testing actor lookup...")
            start = time.time()
            results_entity = mm.recall_actor("apt28", k=10)
            entity_latency = (time.time() - start) * 1000
            print(f"  Latency: {entity_latency:.1f}ms")
            print(f"  Results: {len(results_entity)} notes")
            
            # Vector recall benchmark
            print(f"\n[VECTOR RECALL] Testing semantic search...")
            start = time.time()
            results_vector = mm.recall("Russian espionage operations", k=10)
            vector_latency = (time.time() - start) * 1000
            print(f"  Latency: {vector_latency:.1f}ms")
            print(f"  Results: {len(results_vector)} notes")
            
            # Synthesis benchmark
            print(f"\n[SYNTHESIS] Testing RAG-as-answer...")
            start = time.time()
            synthesis = mm.synthesize("What tools does APT28 use?")
            synthesis_latency = (time.time() - start) * 1000
            sources = synthesis["metadata"]["sources_count"]
            print(f"  Latency: {synthesis_latency:.1f}ms")
            print(f"  Sources: {sources}")
            
            # LanceDB check
            print(f"\n[LANCEDB] Checking vector storage...")
            if mm.store.lancedb:
                result = mm.store.lancedb.list_tables()
                if hasattr(result, 'tables'):
                    tables = result.tables
                else:
                    tables = []
                print(f"  Tables: {tables}")
                for t in tables:
                    if t.startswith('notes_'):
                        tbl = mm.store.lancedb.open_table(t)
                        print(f"    {t}: {len(tbl)} rows")
            
            results.append({
                "notes": count,
                "ingestion_sec": ingestion_time,
                "notes_per_sec": notes_per_sec,
                "entity_latency_ms": entity_latency,
                "vector_latency_ms": vector_latency,
                "synthesis_latency_ms": synthesis_latency,
                "entity_results": len(results_entity),
                "vector_results": len(results_vector),
                "synthesis_sources": sources
            })
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    # Print summary
    print(f"\n{'='*60}")
    print("SCALE BENCHMARK SUMMARY")
    print(f"{'='*60}")
    print(f"{'Notes':<8} {'Ingest/s':<12} {'Entity(ms)':<12} {'Vector(ms)':<12} {'Synth(ms)':<12}")
    print("-" * 60)
    for r in results:
        print(f"{r['notes']:<8} {r['notes_per_sec']:<12.1f} {r['entity_latency_ms']:<12.1f} {r['vector_latency_ms']:<12.1f} {r['synthesis_latency_ms']:<12.1f}")
    
    # Performance assertions (adjusted for scale)
    print(f"\n[CHECKS]")
    for r in results:
        assert r["entity_results"] > 0, f"Entity recall failed at {r['notes']} notes"
        assert r["vector_results"] > 0, f"Vector recall failed at {r['notes']} notes"
        assert r["synthesis_sources"] > 0, f"Synthesis failed at {r['notes']} notes"
        # Entity latency grows with index size - allow up to 1 second
        assert r["entity_latency_ms"] < 1000, f"Entity latency too high at {r['notes']} notes: {r['entity_latency_ms']:.1f}ms"
        assert r["vector_latency_ms"] < 1000, f"Vector latency too high at {r['notes']} notes"
        print(f"  {r['notes']} notes: ✓ PASS")
    
    print(f"\n✓ ALL SCALE BENCHMARKS PASSED")
    return results


if __name__ == "__main__":
    run_scale_benchmark()