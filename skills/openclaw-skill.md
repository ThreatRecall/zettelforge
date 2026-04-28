---
name: zettelforge
description: "ZettelForge v2.0.0 (ThreatRecall) — CTI agentic memory system. Hybrid TypeDB (STIX 2.1) + LanceDB (vectors). Zero external AI. 75% CTI accuracy, 111ms p50. Use for: storing/recalling threat intel, entity extraction, graph traversal, RAG synthesis, OpenCTI sync."
---

# ZettelForge v2.0.0: CTI Agentic Memory

Store, recall, and synthesize threat intelligence. All systems operational.

## API

```python
from zettelforge import MemoryManager
mm = MemoryManager()

# Store
note, status = mm.remember("APT28 uses Cobalt Strike via CVE-2024-1111", domain="cti")

# Two-phase extraction (selective, deduplicating)
results = mm.remember_with_extraction("APT28 dropped DROPBEAR", domain="cti")

# Ingest report (auto-chunks)
results = mm.remember_report(content="...", source_url="https://...", domain="cti")

# Recall (blended vector + graph + cross-encoder reranking)
results = mm.recall("What tools does APT28 use?", k=10)

# Entity lookup (O(1), alias resolution: Fancy Bear -> APT28)
mm.recall_actor("Fancy Bear")
mm.recall_cve("CVE-2024-3094")
mm.recall_tool("cobalt-strike")

# Graph traversal
paths = mm.traverse_graph("actor", "apt28", max_depth=2)

# Synthesize
result = mm.synthesize("Summarize APT28", format="synthesized_brief")

# OpenCTI sync
from zettelforge.opencti_sync import sync_opencti
stats = sync_opencti(mm, limit=50)
```

## Web UI

```bash
python web/app.py  # http://localhost:8088
```

## Benchmarks

| Benchmark | Score | p50 Latency |
|-----------|-------|-------------|
| CTI Retrieval | 75.0% | 111ms |
| LOCOMO | 18.0% | 157ms |
| RAGAS | 78.1% | — |
