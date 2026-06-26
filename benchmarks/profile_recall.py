#!/usr/bin/env python3
"""Profile the recall hot path: where does per-query latency go?

Ingests the CTI benchmark corpus into a temp store, then profiles
recall() over the 20 benchmark queries (3 passes) with cProfile and
per-stage wall timings.

Usage:
  python benchmarks/profile_recall.py
"""
import cProfile
import io
import pstats
import statistics
import tempfile
import time

from cti_retrieval_benchmark import CTI_QUERIES, CTI_REPORTS

from zettelforge import MemoryManager


def main() -> None:
    tmpdir = tempfile.mkdtemp(prefix='profile_recall_')
    mm = MemoryManager(jsonl_path=f'{tmpdir}/notes.jsonl', lance_path=f'{tmpdir}/vectordb')

    t0 = time.perf_counter()
    for report in CTI_REPORTS:
        mm.remember(report['content'], source_type='threat_report', source_ref=report['id'], domain='cti')
    print(f'ingest: {time.perf_counter() - t0:.2f}s for {len(CTI_REPORTS)} notes')

    # Warm pass (model load, caches)
    for qa in CTI_QUERIES[:3]:
        mm.recall(qa['question'], k=10, exclude_superseded=False)

    # Timed passes
    latencies = []
    for _ in range(3):
        for qa in CTI_QUERIES:
            t = time.perf_counter()
            mm.recall(qa['question'], k=10, exclude_superseded=False)
            latencies.append(time.perf_counter() - t)
    lat_ms = sorted(x * 1000 for x in latencies)
    print(f'recall over {len(latencies)} calls: p50={statistics.median(lat_ms):.1f}ms '
          f'p95={lat_ms[int(len(lat_ms) * 0.95)]:.1f}ms mean={statistics.mean(lat_ms):.1f}ms')

    # cProfile pass
    profiler = cProfile.Profile()
    profiler.enable()
    for qa in CTI_QUERIES:
        mm.recall(qa['question'], k=10, exclude_superseded=False)
    profiler.disable()

    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s)
    stats.sort_stats('cumulative').print_stats(35)
    print(s.getvalue())


if __name__ == '__main__':
    main()
