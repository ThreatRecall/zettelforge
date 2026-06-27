#!/usr/bin/env python3
"""Mine remember() phase_timings_ms distributions from a benchmark log.

The write path logs per-phase wall times on every remember() call
(RFC-009 Phase 0.5). This aggregates p50/p95 per phase from a captured
log so ingest optimization targets the real cost center.

Usage:
  python benchmarks/mine_phase_timings.py /tmp/locomo_clean_baseline.log
"""
import json
import statistics
import sys


def main(path: str) -> None:
    phases: dict[str, list[float]] = {}
    durations: list[float] = []
    with open(path) as f:
        for line in f:
            # OCSF sink uses activity_name; structlog console uses operation
            if '"operation": "remember"' not in line and '"activity_name": "remember"' not in line:
                continue
            try:
                rec = json.loads(line[line.index('{'):])
            except (ValueError, json.JSONDecodeError):
                continue
            if rec.get('operation') != 'remember' and rec.get('activity_name') != 'remember':
                continue
            durations.append(float(rec.get('duration_ms', 0)))
            timings = rec.get('phase_timings_ms') or rec.get('unmapped', {}).get('phase_timings_ms') or {}
            for phase, ms in timings.items():
                phases.setdefault(phase, []).append(float(ms))

    if not durations:
        print('no remember() records found')
        return

    durations.sort()
    print(f'remember() calls: {len(durations)}')
    print(f'total p50={statistics.median(durations):.1f}ms '
          f'p95={durations[int(len(durations) * 0.95)]:.1f}ms '
          f'mean={statistics.mean(durations):.1f}ms')
    print(f'\n{"phase":<24} {"n":>5} {"p50ms":>8} {"p95ms":>8} {"mean":>8} {"share":>7}')
    total_mean = statistics.mean(durations)
    for phase, vals in sorted(phases.items(), key=lambda kv: -statistics.mean(kv[1])):
        vals.sort()
        mean = statistics.mean(vals)
        print(
            f'{phase:<24} {len(vals):>5} {statistics.median(vals):>8.1f} '
            f'{vals[int(len(vals) * 0.95)]:>8.1f} {mean:>8.1f} {mean / total_mean * 100:>6.1f}%'
        )


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/locomo_clean_baseline.log')
