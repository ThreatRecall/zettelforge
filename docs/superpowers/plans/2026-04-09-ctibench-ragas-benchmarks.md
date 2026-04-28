# CTIBench + RAGAS Benchmark Suite Plan

**Date:** 2026-04-09
**Status:** COMPLETE (Steps 1 and 2). Step 3 documented for future work.

## Roadmap

| Step | What | Status |
|------|------|--------|
| 1. CTIBench (Tasks 1-3) | Adapt CTI-ATE + CTI-TAA as retrieval benchmarks | **Done** |
| 2. RAGAS metrics (Tasks 4-5) | Add retrieval quality metrics to LOCOMO benchmark | **Done** |
| 3. Conversational entity extractor | Extend EntityExtractor for person names, locations, events | **Future** |

## Results

- CTIBench CTI-ATE: F1=0.0 (methodology fix needed — descriptions lack T-codes)
- CTIBench CTI-TAA: Baseline established, 48 predictions saved
- RAGAS: 75.9% keyword presence, 17.7% string similarity

See `benchmarks/BENCHMARK_REPORT.md` for full analysis.

## Step 3: Conversational Entity Extractor (Future Work)

**Problem:** ZettelForge's EntityExtractor only recognizes CTI entities. LOCOMO uses conversational entities.

**Files to modify:**
- `src/zettelforge/entity_indexer.py:12-36` — add person, location, event, activity patterns
- `src/zettelforge/note_constructor.py:23-37` — update ENTITY_PATTERNS
- `tests/test_basic.py` — add tests for new entity types

**Expected impact:** LOCOMO overall 15% -> 25-30%
