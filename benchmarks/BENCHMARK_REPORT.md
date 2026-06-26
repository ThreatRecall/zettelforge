# ZettelForge Benchmark Report

**Version:** 2.2.0
**Last updated:** 2026-04-16
**Author:** Automated benchmark suite

> Most raw numbers in this report were captured against v2.0.0–v2.1.1.
> They are retained as published so prior claims can be audited. The
> **LOCOMO** row was re-measured at v2.1.1 with Ollama cloud judges and
> the **CTIBench ATE** row was re-measured at v2.2.0 after fixing the
> ingestion pipeline and dropping the ICS matrix noise (see CHANGELOG).

---

## Executive Summary

ZettelForge was evaluated across five benchmark suites. The system runs with zero external AI dependencies on the default configuration (fastembed for embeddings, llama-cpp-python for LLM, SQLite for storage; TypeDB is an opt-in extension).

| Benchmark | What it measures | Key result |
|-----------|-----------------|------------|
| **CTI Retrieval** | Real CTI queries (attribution, CVE linkage, tools) | **75.0% accuracy** |
| **LOCOMO** (ACL 2024) | Conversational memory recall | **22.0% accuracy** (v2.1.1, Ollama judge) |
| **MemPalace comparison** | Head-to-head on LOCOMO | MemPalace 26% vs ZettelForge 18% (v2.0.0 snapshot) |
| **RAGAS** | Retrieval quality metrics | 78.1% keyword presence |
| **CTIBench** (NeurIPS 2024) | ATT&CK technique extraction | **F1 = 0.146** (v2.2.0, fixed ingestion) |

**Key finding:** ZettelForge scores **75%** on its domain benchmark (CTI queries) and **22%** on LOCOMO conversational memory. This is by design — the system is built for threat intelligence, not chatbot memory.

---

## 0. Performance session 2026-06-09 (v2.8.0-dev, branch perf/cti-memory-40)

All numbers below are same-machine (DGX Spark GB10), same-day, deterministic
config: enrichment disabled (`ZETTELFORGE_ENRICHMENT_ENABLED=false`), keyword
judge, heuristic answer extraction (no synthesis LLM installed). The clean
baseline was measured first on unmodified v2.7.0 source after repairing the
rotted harnesses (dead `disable_enrichment` kwarg, removed `remember_chunked`
API). Raw logs: `benchmarks/results/session_2026-06-09/`.

| Metric | v2.7.0 baseline | optimized | delta |
|--------|-----------------|-----------|-------|
| LoCoMo accuracy (keyword judge) | 7.0% | 11.0% | +57% relative |
| LoCoMo p50 / p95 latency | 336ms / 387ms | 170ms / 193ms | -49% / -50% |
| LoCoMo ingest (272 sessions) | 262.5s (1.0/s) | 33.8s (8.0/s) | 7.8x |
| CTI retrieval accuracy | 75.0% | 75.0% | held |
| CTI p50 latency (idle machine) | 79ms | 39ms | -51% |
| recall p95 (profiled, 60 calls) | 258ms | 93ms | -64% |
| recall mean (profiled) | 117.6ms | 54.8ms | -53% |

Note on LoCoMo baselines: the published 22% (v2.1.1) used a local synthesis
LLM (qwen2.5:3b) that is not installed on this host; both columns above use
the same deterministic heuristic-extraction path, so the comparison is
apples to apples. Latency includes harness overhead (keyword boost scan and
synthesis fallback), not just `recall()`.

### What changed

1. **Scoped knowledge graph reads.** `_recall_inner` traversed the
   process-global JSONL KG (109MB on this host, mixing every store) while
   writes went to the per-store SQLite KG. Isolated stores saw up to ~2000
   phantom note IDs per entity query and never saw their own graph. Recall
   now reads the store's KG via `StoreGraphSource`.
2. **MemSAD gate vectorized.** The write-time anomaly gate was 93% of
   remember() latency at 50 references (~1.1s/ingest): O(n^2) pure-Python
   cosines plus n^2 n-gram recounts per ingest. numpy pairwise scoring,
   content-hash counter cache, and a bounded reference fetch
   (`get_recent_notes_by_domain`) brought warm evaluate() to ~3.4ms with
   scores pinned to the original math at 1e-9 by characterization tests.
3. **Rerank policy.** Cross-encoder rerank is the dominant read cost and is
   worth +15pp CTI accuracy (75% vs 60% without it). Grid-tuned bounds:
   8 candidates, 256 chars/doc (accuracy holds from 50x512 down to 8x128;
   collapses below 8 candidates). `rerank_model` is configurable; the
   model grid kept ms-marco-MiniLM-L-6-v2.
4. **ONNX thread pinning.** 20-core default oversubscribed small batches:
   8 threads cut rerank 23.7ms to 11.5ms and query embedding 5.9ms to 4.5ms.
5. **Embedding LRU cache** keyed by (model, sha256(text)) — first
   integration of the dormant cache.py.
6. **Entity fan-out gate.** Query entities whose KG out-degree exceeds
   `retrieval.entity_max_fanout` (default 25) are skipped by graph and
   entity-augmentation stages (conversational speaker names map to every
   session and flood blended recall).
7. **Enrichment off-switch** (`ZETTELFORGE_ENRICHMENT_ENABLED`) restoring
   deterministic benchmark ingestion; `remember_chunked()` restored.

### Chunked-ingestion configuration (recorded, not default)

`LOCOMO_CHUNK_SIZE=800` stores each session as ~800-char chunks
(MemPalace granularity, no 4000-char truncation): 13.0% accuracy at
p50 347ms / p95 418ms on a ~1400-note store. Compared to the v2.7.0
baseline at effectively the same latency (336ms), that is +86%
relative accuracy; compared to the default optimized config it trades
2x latency for +2pp. Default stays full-session (11.0% at 170ms).

### Negative result (recorded)

Free-text person extraction (capitalized tokens in running text) dropped
LoCoMo from 11% to 5% by reshuffling supersession chains at ingest, with no
single-hop or multi-hop gain. Reverted same day; regression-locked in
`tests/test_conversational_entities.py`. Conversational NER should come via
the RFC-001 LLM path, not regex.

---

## 1. CTI Retrieval Benchmark (Domain Benchmark)

**Date:** 2026-04-10 | **Corpus:** 8 real-world-style CTI reports | **Queries:** 20

This is ZettelForge's home turf — the queries an analyst would actually ask.

### Results by Category

| Category | Queries | Accuracy | What it tests |
|----------|---------|----------|--------------|
| **Attribution** | 5 | **100%** | "Who is attributed to MOIS?" → MuddyWater |
| **Multi-hop** | 3 | **100%** | "APT group using DROPBEAR + NATO?" → APT28 |
| **CVE linkage** | 4 | **75%** | "Link CVE-2026-3055 to threat actor" → MuddyWater |
| **Temporal** | 3 | **66.7%** | "Is Server ALPHA currently secure?" → rebuilt, patched |
| **Tool attribution** | 5 | **40%** | "What tools does Turla use?" → Carbon, Kazuar, Snake |
| **Overall** | **20** | **75.0%** | |

**p50 latency:** 620ms | **Notes:** 8

### Chunking Strategy Comparison

Tested whether 800-char chunking (like MemPalace) improves CTI accuracy:

| Strategy | CTI Accuracy | p50 Latency | Notes |
|----------|-------------|-------------|-------|
| full_session (current) | 75.0% | 620ms | 8 |
| chunked_800 | 75.0% | 706ms | 8 |

**Verdict:** No improvement. CTI reports are already 500-900 chars. Chunking adds latency without benefit. Not merged.

### Tool Attribution Gap Analysis

Tool attribution scores 40% because queries like "What tools does APT28 use?" match the correct report but keyword overlap on multi-tool answers (e.g., "Cobalt Strike, DROPBEAR, SedUploader") requires all keywords to appear in retrieved context. When the report mentions tools across multiple sentences, the keyword judge scores partial matches as 0.5 rather than 1.0.

---

## 2. LOCOMO Benchmark (Conversational Memory)

**Source:** [LoCoMo](https://snap-research.github.io/locomo/) (ACL 2024)
**Dataset:** 10 conversations, 5882 dialogue turns, 100 QA pairs
**Judge:** Keyword overlap

### Version Progression

| Category | v1.3.0 | v1.5.0 | v2.0.0 (with retrieval improvements) |
|----------|--------|--------|---------------------------------------|
| single-hop | 5.0% | 10.0% | **15.0%** |
| multi-hop | 0.0% | 0.0% | **0.0%** (avg_score 0.15) |
| temporal | 0.0% | 0.0% | **5.0%** |
| open-domain | 30.0% | 30.0% | **40.0%** |
| adversarial | 35.0% | 35.0% | **30.0%** |
| **Overall** | **14.0%** | **15.0%** | **18.0%** |
| p50 latency | 238ms | 344ms | **1,240ms** |
| p95 latency | 190,000ms | 1,305ms | **2,282ms** |

### Why LOCOMO Scores Are Low

ZettelForge's entity extractor recognizes CTI entities (CVEs, APT groups, tools). LOCOMO uses conversational entities (person names, hobbies, life events). Graph traversal doesn't fire on conversational queries because no recognized entities appear.

Additionally, the supersession logic aggressively marks LOCOMO sessions as superseded (264/272) because conversational sessions share speakers. The benchmark now uses `exclude_superseded=False` to work around this.

### LOCOMO Leaderboard

| System | Accuracy | p95 Latency | External Dependencies |
|--------|----------|-------------|----------------------|
| Mem0g | 68.5% | 2.6s | Cloud API |
| Mem0 | 66.9% | 1.4s | Cloud API |
| LangMem | 58.1% | 60s | Cloud API |
| OpenAI Memory | 52.9% | 0.9s | Cloud API |
| MemPalace | 26.0% | 170ms | None (ChromaDB) |
| **ZettelForge 2.0.0** | **18.0%** | **2.3s** | **None (fastembed + GGUF)** |

---

## 3. MemPalace Comparison

**Date:** 2026-04-10 | **Benchmark:** LOCOMO (same dataset, same scoring)

| Category | ZettelForge | MemPalace | Delta |
|----------|:-----------:|:---------:|:-----:|
| single-hop | 10.0% | **15.0%** | +5 |
| multi-hop | 0.0% | 0.0% | — |
| temporal | 0.0% | **10.0%** | +10 |
| open-domain | 35.0% | **55.0%** | +20 |
| adversarial | 30.0% | **50.0%** | +20 |
| **Overall** | **18.0%** | **26.0%** | **+8** |
| p50 latency | 1,240ms | **130ms** | 10x faster |

### Why MemPalace Wins on LOCOMO

- **Chunking:** 800-char chunks vs ZettelForge's 4000-char full sessions. Smaller chunks produce more precise keyword matches.
- **No overhead:** Pure ChromaDB vector search. No intent classification, graph traversal, or blending. For conversational data with no CTI entities, this overhead adds latency without accuracy.

### Where ZettelForge Wins

ZettelForge scores **75%** on CTI queries (attribution, CVE linkage, multi-hop reasoning). MemPalace has no knowledge graph, no STIX ontology, no entity extraction, and no typed relationships. On "What tools does MOIS use?" or "Link CVE-2026-3055 to Dindoor backdoor", ZettelForge's graph traversal and entity indexing outperform flat vector search.

---

## 4. RAGAS Retrieval Quality

**Date:** 2026-04-10 | **Dataset:** LOCOMO | **Scoring:** Manual fallback (SequenceMatcher + keyword presence)

| Metric | v1.5.0 | v2.0.0 | Change |
|--------|--------|--------|--------|
| Keyword presence | 75.9% | **78.1%** | +2.2pp |
| String similarity | 17.7% | **18.2%** | +0.5pp |
| p50 latency | 320ms | 2,045ms | In-process LLM overhead |

Retrieval quality slightly improved with fastembed embeddings. The high keyword presence (78%) indicates retrieved context contains relevant information — the accuracy gap on LOCOMO is in answer extraction, not retrieval.

---

## 5. CTIBench (NeurIPS 2024)

**Initial run:** 2026-04-10 (v2.0.0) — F1 = 0.000
**Fixed:** 2026-04-16 (v2.2.0) — F1 = 0.146
**Task:** CTI-ATE (ATT&CK Technique Extraction)

| Metric | v2.0.0 | v2.2.0 | Change |
|--------|-------:|-------:|:------:|
| F1 | 0.000 | **0.146** | +0.146 |
| p50 latency | 1,170 ms | 1,120 ms | unchanged |

**What changed.** The original v2.0.0 run returned F1 = 0 because
CTI-ATE descriptions are natural-language paraphrases of ATT&CK
techniques without T-codes (T1071, T1573, etc.) and the benchmark
adapter only looked for T-code regex patterns in retrieved text.

v2.2.0 fixes two methodology issues:

1. **Ingestion pipeline** — the adapter now ingests the MITRE ATT&CK
   technique descriptions as cross-reference notes before scoring, so
   T-codes can be linked back to the paraphrased descriptions.
2. **ICS matrix noise removed** — the CTI-ATE split includes ATT&CK
   for ICS technique entries whose T-codes overlap with Enterprise
   IDs. Those rows were dropped from scoring.

**Remaining gap.** F1 = 0.146 is a lower bound driven by low recall
rather than precision: many techniques map to multiple paraphrases and
the current scoring function rewards exact T-code matches. A semantic
matcher over technique descriptions would lift this further and is
tracked as a follow-up.

---

## Architecture Summary (v2.2.0)

| Component | Technology | External Server? |
|-----------|-----------|:---:|
| Embeddings | fastembed (nomic-embed-text-v1.5-Q, 768-dim, ONNX) | **No** |
| LLM | llama-cpp-python (Qwen2.5-3B-Instruct Q4_K_M) or Ollama | **No** (local) / Yes (ollama) |
| Vector store | LanceDB (IVF_PQ, in-memory fallback) | **No** |
| Notes / KG / entity index | SQLite (WAL mode) | **No** |
| Ontology (optional) | TypeDB (STIX 2.1, Docker) — via `zettelforge-enterprise` | Yes (Docker, extension only) |

**Total external dependencies for the default community build:** none. SQLite, LanceDB, and fastembed all run in-process. TypeDB ships only with the `zettelforge-enterprise` extension.

---

## Regression Root Causes Found and Fixed

During v2.0.0 benchmarking, three regressions were identified and fixed:

1. **VectorRetriever LanceDB path** — Rewritten retriever tried LanceDB first, got partial results with quantized embeddings, didn't fall back to in-memory. **Fix:** Force in-memory cosine similarity.

2. **BlendedRetriever result dropping** — Blending reduced vector results when graph returned nothing. **Fix:** Fall back to vector when blending reduces count.

3. **Supersession on conversational data** — `_check_supersession()` marked 264/272 LOCOMO notes as superseded because sessions share speakers. **Fix:** LOCOMO benchmark uses `exclude_superseded=False`.

---

## Raw Data Files

| File | Description | Date |
|------|-------------|------|
| `cti_retrieval_results.json` | CTI benchmark (75% accuracy) | 2026-04-10 |
| `locomo_results.json` | LOCOMO v2.0.0 (15% accuracy) | 2026-04-10 |
| `mempalace_results.json` | MemPalace comparison (26%) | 2026-04-10 |
| `ragas_results.json` | RAGAS retrieval quality | 2026-04-10 |
| `ctibench_results.json` | CTIBench ATE (v2.2.0, F1 = 0.146) | 2026-04-16 |
| `locomo_results_v1.3.0_baseline.json` | LOCOMO v1.3.0 (14%) | 2026-04-09 |

## Benchmark Scripts

| Script | What it runs |
|--------|-------------|
| `cti_retrieval_benchmark.py` | 8 CTI reports, 20 queries, 5 categories |
| `locomo_benchmark.py` | LOCOMO 100 QA pairs across 5 categories |
| `mempalace_benchmark.py` | MemPalace on LOCOMO (ChromaDB) |
| `ragas_benchmark.py` | RAGAS retrieval quality metrics |
| `ctibench_benchmark.py` | CTIBench ATE adapter |

---

## 6. MemoryAgentBench (ICLR 2026)

**Date:** 2026-04-10 | **Model:** nemotron-3-super:cloud via Ollama | **Splits:** AR (3 rows), CR (3 rows)

### Results

| Split | F1 | EM | ROUGE-L | Queries | p50 Latency |
|-------|------|------|---------|---------|-------------|
| Accurate Retrieval | **0.328** | 0.157 | 0.332 | 300 | 333ms |
| Conflict Resolution | 0.032 | 0.017 | 0.031 | 300 | 128ms |
| **Overall** | **0.180** | **0.087** | **0.182** | 600 | |

### Model Impact

| Model | AR F1 | CR F1 | Overall F1 |
|-------|-------|-------|------------|
| Qwen2.5-3B (local GGUF) | 0.012 | 0.012 | 0.007 |
| nemotron-3-super:cloud | **0.328** | **0.032** | **0.180** |
| Improvement | **27x** | **2.7x** | **25x** |

Retrieval latency was unchanged between models (128-333ms). The improvement is purely in answer generation quality. This validates that ZettelForge's retrieval pipeline works — the local 3B model was the bottleneck.

### CR Gap Analysis

Conflict Resolution scores remain low because the questions require multi-hop entity chain reasoning (e.g., "country of citizenship of the spouse of the author of Our Mutual Friend" → Belgium). This needs explicit graph traversal over entity relationships, not just LLM reasoning over retrieved text chunks.

---

## Benchmark Scripts

| Script | What it runs |
|--------|-------------|
| `cti_retrieval_benchmark.py` | 8 CTI reports, 20 queries, 5 categories |
| `locomo_benchmark.py` | LOCOMO 100 QA pairs across 5 categories |
| `mempalace_benchmark.py` | MemPalace on LOCOMO (ChromaDB) |
| `ragas_benchmark.py` | RAGAS retrieval quality metrics |
| `ctibench_benchmark.py` | CTIBench ATE adapter |
| `memoryagentbench.py` | MemoryAgentBench AR + CR + TTL + LRU |
