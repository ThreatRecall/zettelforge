---
name: zettelforge
description: "ZettelForge v2.0.0 — Production CTI agentic memory system. Hybrid TypeDB (STIX 2.1 ontology) + LanceDB (vector search). Zero external AI dependencies: fastembed for embeddings, llama-cpp-python for LLM. 75% accuracy on CTI queries, 18% on LOCOMO. Use when agents need persistent memory, threat intel retrieval, entity extraction, graph traversal, or RAG synthesis."
---

# ZettelForge v2.0.0: Agentic Memory System

Production-grade memory for CTI analysis. Hybrid TypeDB (STIX 2.1) + LanceDB (vectors). Zero external AI dependencies.

## Status (2026-04-10)

All systems operational:
- ✅ Vector retrieval (fastembed, in-memory cosine similarity)
- ✅ Knowledge graph (TypeDB STIX 2.1 with JSONL fallback)
- ✅ Entity extraction (10 types: CVE, actor, tool, campaign, person, location, org, event, activity, temporal)
- ✅ Two-phase extraction pipeline (FactExtractor → MemoryUpdater)
- ✅ Cross-encoder reranking (ms-marco-MiniLM)
- ✅ Synthesis layer (direct_answer, synthesized_brief, timeline_analysis, relationship_map)
- ✅ 36 CTI aliases seeded (APT28/Fancy Bear/Strontium, etc.)

## Benchmarks

| Benchmark | Score | What it tests |
|-----------|-------|--------------|
| **CTI Retrieval** | **75.0%** | Attribution, CVE linkage, tools, temporal, multi-hop |
| **LOCOMO** | **18.0%** | Conversational memory recall |
| **RAGAS** | **78.1%** | Retrieval quality (keyword presence) |

## Quick Start

```python
from zettelforge import MemoryManager

mm = MemoryManager()

# Store threat intel
note, status = mm.remember(
    "APT28 uses Cobalt Strike for lateral movement via CVE-2024-1111",
    domain="cti"
)

# Two-phase extraction (selective, deduplicating)
results = mm.remember_with_extraction(
    "APT28 dropped DROPBEAR, now exploits edge devices.",
    domain="cti"
)

# Ingest reports (auto-chunks)
results = mm.remember_report(
    content="Full threat report text...",
    source_url="https://example.com/report",
    domain="cti"
)

# Retrieve — blended vector + graph, cross-encoder reranked
results = mm.recall("What tools does APT28 use?", k=10)

# Alias resolution works automatically
results = mm.recall_actor("Fancy Bear")  # resolves to APT28

# Entity lookups
mm.recall_cve("CVE-2024-3094")
mm.recall_tool("cobalt-strike")

# Graph traversal
paths = mm.traverse_graph("actor", "apt28", max_depth=2)

# Synthesize answers
result = mm.synthesize("Summarize APT28 activity", format="synthesized_brief")
```

## Architecture

```
Agent → MemoryManager
  ├─ NoteConstructor → EntityExtractor (10 types, regex + optional LLM NER)
  ├─ FactExtractor → MemoryUpdater (ADD/UPDATE/DELETE/NOOP)
  ├─ TypeDB (STIX 2.1: 9 entity types, 8 relation types, inference)
  │   └─ JSONL fallback if TypeDB unavailable
  ├─ LanceDB (768-dim fastembed vectors, IVF_PQ index)
  │   └─ In-memory cosine similarity fallback
  ├─ BlendedRetriever (vector + graph, intent-weighted)
  ├─ Cross-encoder reranker (ms-marco-MiniLM, 80MB)
  ├─ Entity-augmented recall (entity index supplements vector results)
  ├─ Temporal boost (date extraction for temporal queries)
  └─ SynthesisGenerator (RAG, 4 output formats)
```

## Retrieval Pipeline

```
Query → IntentClassifier (factual/temporal/relational/causal/exploratory)
  → VectorRetriever (cosine similarity + entity boost)
  → GraphRetriever (BFS from query entities, hop-distance scoring)
  → BlendedRetriever (policy-weighted merge)
  → Entity-augmented recall (entity index supplements)
  → Temporal boost (for temporal queries)
  → Cross-encoder reranking (ms-marco-MiniLM)
  → List[MemoryNote]
```

## Configuration

```yaml
# config.yaml
embedding:
  provider: fastembed           # or "ollama"
  model: nomic-ai/nomic-embed-text-v1.5-Q
llm:
  provider: local               # or "ollama"
  model: Qwen/Qwen2.5-3B-Instruct-GGUF
typedb:
  host: localhost
  port: 1729
backend: typedb                  # or "jsonl"
```

Environment variables:
```bash
ZETTELFORGE_BACKEND=jsonl                    # Skip TypeDB
ZETTELFORGE_EMBEDDING_PROVIDER=ollama        # Use Ollama for embeddings
ZETTELFORGE_LLM_PROVIDER=ollama              # Use Ollama for LLM
```

## API Reference

| Method | Description |
|--------|------------|
| `remember(content, domain)` | Store a note (append-only) |
| `remember_with_extraction(content, domain)` | Two-phase: extract facts → ADD/UPDATE/DELETE/NOOP |
| `remember_report(content, source_url)` | Chunked report ingestion |
| `recall(query, k, domain)` | Blended retrieval (vector + graph + reranking) |
| `recall_actor(name)` / `recall_cve(id)` / `recall_tool(name)` | Fast entity lookup |
| `synthesize(query, format)` | RAG synthesis (direct_answer, brief, timeline, relationship_map) |
| `traverse_graph(type, value, max_depth)` | Knowledge graph traversal |
| `get_context(query, token_budget)` | Formatted context for prompt injection |

## STIX 2.1 Entity Types

threat-actor, malware, tool, attack-pattern, vulnerability, campaign, indicator, infrastructure, zettel-note (bridge to LanceDB)

## STIX Relationship Types

uses, targets, attributed-to, indicates, mitigates, mentioned-in, supersedes, alias-of

## Dependencies (zero external servers for AI)

| Component | Package | Server needed? |
|-----------|---------|:-:|
| Embeddings | fastembed (ONNX, 130MB) | No |
| LLM | llama-cpp-python (GGUF, 2GB) | No |
| Vectors | LanceDB | No |
| Ontology | TypeDB (Docker) | Yes |
| Reranking | fastembed cross-encoder (80MB) | No |

## License

MIT
