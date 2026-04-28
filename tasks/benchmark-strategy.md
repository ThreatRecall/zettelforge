# Benchmark Strategy — ZettelForge v2.1.1

**Date:** 2026-04-14
**Agent:** Performance Benchmarker
**Status:** Plan complete, awaiting execution

## Priority Matrix (Top 5)

| # | Benchmark | Marketing Value | Engineering Value | Effort | ROI |
|---|---|---|---|---|---|
| 1 | CTIBench ATE fix | HIGH | HIGH | 4 hours | Highest |
| 2 | CTI-Specific Benchmark v2 | VERY HIGH | VERY HIGH | 3 days | Strategic |
| 3 | Scale benchmark (10K notes) | HIGH | HIGH | 1 day | Enterprise-critical |
| 4 | evolve=True quality benchmark | HIGH | VERY HIGH | 2 days | Differentiator |
| 5 | RAGAS over CTI corpus | MEDIUM | MEDIUM | 4 hours | Quick win |

## Immediate Actions (This Week)

1. Fix `auto_ralph.py` numpy import bug (line 43)
2. Fix CTIBench ATE — download enterprise-attack.json, add cross-reference loader
3. Run RAGAS with --domain cti flag

## Bug Found

`benchmarks/auto_ralph.py:43` — `np.linspace()` used before `import numpy as np` (at line 93).

## Full plan saved at tasks/benchmark-strategy-full.md
