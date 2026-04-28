---
title: "Why TypeDB + LanceDB"
description: "Architectural rationale for ThreatRecall's hybrid two-database design"
diataxis_type: explanation
audience: "Senior CTI Practitioner"
tags: [architecture, typedb, lancedb, design-decisions]
last_updated: "2026-04-09"
version: "2.0.0"
---

# Why TypeDB + LanceDB (Not One or the Other)

ThreatRecall v2.0.0 uses two databases where most systems use one. This is a deliberate architectural choice, not accidental complexity.

## The Problem with One Database

CTI analysis operates on two fundamentally different data types:

1. **Structured intelligence** — entities with typed relationships, confidence scores, temporal validity, and ontological constraints. "APT28 uses Cobalt Strike" is a typed relationship between a `threat-actor` and a `malware` entity, with confidence 0.85, valid from January 2024.

2. **Unstructured context** — raw text, analyst notes, news articles, conversation logs. "The ransomware encrypted all files on the domain controller using AES-256" is a passage that should be retrievable by semantic similarity but doesn't decompose cleanly into typed entities.

No single database handles both well:

| Capability | Graph DB alone | Vector DB alone |
|:-----------|:---------------|:----------------|
| Typed relationships | Strong | None |
| Multi-hop traversal | Strong | None |
| Inference rules | Strong (TypeDB) | None |
| Semantic search | None | Strong |
| Unstructured text | Poor fit | Natural fit |
| Schema enforcement | Strong | None |
| Temporal validity | Via edge properties | Via metadata only |
| Alias resolution | Via inference | Manual lookup |

## The Hybrid Decision

```mermaid
graph LR
    subgraph "TypeDB — Ontology Layer"
        A[threat-actor: APT28]
        B[malware: Cobalt Strike]
        C[vulnerability: CVE-2024-1111]
        A -->|uses| B
        A -->|targets| C
    end

    subgraph "LanceDB — Conversational Layer"
        N1["note_001: 'APT28 uses Cobalt Strike<br/>for lateral movement...'<br/>vector: [0.12, 0.34, ...]"]
        N2["note_002: 'Cobalt Strike beacon<br/>detected on 10.0.0.15...'<br/>vector: [0.56, 0.78, ...]"]
    end

    A -.->|mentioned-in| N1
    B -.->|mentioned-in| N2

    style A fill:#1a472a,color:#fff
    style B fill:#1a472a,color:#fff
    style C fill:#1a472a,color:#fff
    style N1 fill:#1a2a47,color:#fff
    style N2 fill:#1a2a47,color:#fff
```

**TypeDB owns the truth.** When an analyst asks "what tools does APT28 use?", TypeDB answers definitively from its STIX 2.1 typed relationships. The answer includes confidence scores, temporal validity windows, and can traverse multi-hop paths (APT28 → campaign → malware) using inference.

**LanceDB owns the context.** When an analyst asks "what happened with the ransomware incident?", LanceDB finds semantically similar notes via vector search. The answer is grounded in the actual text the analyst stored, not just entity relationships.

**The bridge is `mentioned-in`.** Every time a note is stored, entity extraction identifies STIX entities in the text and creates `mentioned-in` relations in TypeDB. This means a graph query for "all notes about APT28" traverses TypeDB to find note IDs, then LanceDB retrieves the actual content. The `BlendedRetriever` merges both retrieval paths using intent-based weights.

## Why TypeDB Specifically

The choice of TypeDB over Neo4j, FalkorDB, or ArangoDB was driven by three capabilities:

**1. STIX 2.1 as a native schema.** TypeDB's type system — with abstract entity inheritance, typed relation roles, and attribute constraints — maps naturally to STIX. `threat-actor sub stix-domain-object` inherits 8 shared attributes while adding actor-specific fields. This is schema enforcement, not convention.

**2. Inference functions.** TypeDB can compute relationships that aren't explicitly stored. The `get_aliases` function resolves alias chains transitively — if "Fancy Bear" is aliased to "APT28" and "Strontium" is aliased to "APT28", a query for aliases of "Strontium" returns "Fancy Bear" without a direct edge between them.

**3. Apache-2.0 licensing.** For a CTI platform that may be deployed in government or defense environments, unambiguous open-source licensing matters.

## Why LanceDB Specifically

LanceDB was chosen for the vector layer because:

- **Embedded deployment** — no separate server process, runs in-process via Python
- **IVF_PQ indexing** — balanced performance/accuracy for the 768-dimensional embedding space
- **Columnar storage** — efficient for the append-heavy write pattern of note ingestion
- **Zero external dependencies** — just `pip install lancedb`

## In-Process AI: fastembed + llama-cpp-python

ThreatRecall v2.0.0 runs all AI inference in-process by default, with no external service dependencies:

- **Embeddings**: fastembed runs nomic-embed-text-v1.5-Q as an in-process ONNX model (768-dim, ~130 MB, ~7ms/embed). This eliminates the latency and operational overhead of an embedding server.
- **LLM**: llama-cpp-python loads Qwen2.5-3B-Instruct (Q4_K_M GGUF, ~2.0 GB) directly into the Python process (~15.6 tok/s on CPU). This handles fact extraction, intent classification, causal triple extraction, and synthesis.

Both models download automatically on first use. Ollama remains available as an optional fallback provider for users who prefer server-based inference or want to use different models -- configure via `embedding.provider: ollama` and `llm.provider: ollama` in `config.yaml`.

## The Cost of Two Databases

The hybrid architecture adds operational complexity:

- Two data stores to back up
- TypeDB requires Docker (not purely embedded)
- The `mentioned-in` bridge can become inconsistent if one database is modified without the other
- Cache invalidation spans both systems

ThreatRecall mitigates this with automatic fallback — if TypeDB is unreachable, `get_knowledge_graph()` returns the JSONL backend transparently. The system degrades to vector-only retrieval rather than failing.

## LLM Quick Reference

ThreatRecall v2.0.0 uses a hybrid two-database architecture. TypeDB (Apache-2.0, STIX 2.1 schema) serves as the ontology layer owning structured threat intelligence: 9 entity types (threat-actor, malware, tool, attack-pattern, vulnerability, campaign, indicator, infrastructure, zettel-note), 8 relation types (uses, targets, attributed-to, indicates, mitigates, mentioned-in, supersedes, alias-of), inference functions for transitive alias resolution and campaign tool attribution, confidence scoring on every relation, and temporal validity via valid-from/valid-until attributes. LanceDB serves as the conversational layer owning unstructured context: Zettelkasten-style atomic notes with 768-dimensional vector embeddings (fastembed nomic-embed-text-v1.5-Q by default, IVF_PQ index with 256 partitions and 16 sub-vectors), raw text, metadata, and links. Embeddings and LLM inference run in-process by default via fastembed (ONNX) and llama-cpp-python (Qwen2.5-3B-Instruct Q4_K_M GGUF). Ollama is available as an optional fallback provider. The bridge between the two layers is the mentioned-in relation in TypeDB which stores (entity → note-id) mappings. During recall(), the BlendedRetriever queries both layers — VectorRetriever computes cosine similarity with entity boost, GraphRetriever runs BFS from query entities with hop-distance scoring — and merges results using intent-based policy weights (factual queries weight entity index 0.7, relational queries weight graph 0.5, exploratory queries weight vector 0.5). The fallback mechanism returns JSONL KnowledgeGraph if TypeDB is unreachable, degrading to vector-only retrieval. This architecture was chosen because CTI analysis requires both typed structured relationships (which TypeDB handles with schema enforcement and inference) and semantic unstructured text retrieval (which LanceDB handles with vector similarity). Neither database alone covers both needs.
