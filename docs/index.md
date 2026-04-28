---
title: ThreatRecall Documentation
description: Production-grade agentic memory system for cyber threat intelligence, powered by hybrid graph + vector retrieval over STIX 2.1 ontology.
diataxis_type: "navigation"
audience: "all"
tags: [overview, navigation]
last_updated: "2026-04-09"
version: "2.0.0"
---

# ThreatRecall Documentation

ThreatRecall is a production-grade agentic memory system for cyber threat intelligence (CTI). It combines a STIX 2.1 knowledge graph in TypeDB with vector-indexed Zettelkasten notes in LanceDB so that AI agents and SOC analysts can store, recall, and synthesize threat intelligence using natural language.

## Architecture Overview

ThreatRecall uses a hybrid storage architecture with in-process AI. TypeDB stores structured CTI entities and their relationships using the STIX 2.1 ontology. LanceDB stores unstructured notes as 768-dimensional vectors with IVF_PQ indexing. Embeddings are generated in-process by fastembed (nomic-embed-text-v1.5-Q, ONNX runtime, ~7ms/embed) and LLM inference runs in-process via llama-cpp-python (Qwen2.5-3B-Instruct Q4_K_M GGUF). No external AI services are required by default. The BlendedRetriever fuses results from both stores at query time, weighting vector similarity against graph traversal based on the classified intent of the query.

Ingestion follows a two-phase pipeline. The **FactExtractor** distills raw text into scored candidate facts using an LLM. The **MemoryUpdater** compares each fact against existing notes and decides whether to ADD, UPDATE, DELETE, or NOOP -- preventing duplicates and keeping the knowledge base current.

Retrieval is intent-driven. The **IntentClassifier** categorizes each query as factual, temporal, relational, causal, or exploratory, then assigns vector/graph weight ratios to a traversal policy. The **BlendedRetriever** merges vector similarity scores with graph BFS scores using those weights and returns a single ranked list of notes.

```mermaid
graph TB
    subgraph Ingestion
        A[Raw Text / Report] --> B[FactExtractor]
        B -->|Scored Facts| C[MemoryUpdater]
        C -->|ADD / UPDATE / DELETE| D[MemoryStore]
    end

    subgraph Storage
        D --> E[(LanceDB<br/>Vector Index<br/>768-dim IVF_PQ)]
        D --> F[(TypeDB 3.x<br/>STIX 2.1 Ontology)]
        F --- G[36 Seeded Aliases<br/>APT28, Lazarus, ...]
        F --- H[Inference Functions<br/>get_aliases, get_tools_used,<br/>get_entity_notes]
    end

    subgraph Retrieval
        I[Query] --> J[IntentClassifier]
        J -->|Policy Weights| K[BlendedRetriever]
        E --> K
        F --> K
        K --> L[Ranked Notes]
    end

    subgraph Synthesis
        L --> M[SynthesisGenerator]
        M --> N[direct_answer /<br/>synthesized_brief /<br/>timeline_analysis /<br/>relationship_map]
    end

    subgraph Governance
        O[GOV-003 Data Classification]
        P[GOV-007 Retention]
        Q[GOV-011 Access Control]
        R[GOV-012 Audit]
    end
```

## Documentation Map

This documentation follows the [Diataxis framework](https://diataxis.fr/), organized into four quadrants.

### Tutorials (Learning-Oriented)

Step-by-step guides that walk you through a working example from start to finish.

| Tutorial | Time | Description |
|----------|------|-------------|
| [Quickstart: Your First Memory](tutorials/01-quickstart.md) | 5 min | Store, recall, and synthesize your first threat intelligence. |
| [Ingest Your First CTI Report](tutorials/02-first-cti-report.md) | 10 min | Ingest a threat report end-to-end with two-phase extraction. |

### How-To Guides (Task-Oriented)

Practical recipes for specific tasks you need to accomplish.

| Guide | Description |
|-------|-------------|
| [Store a Threat Actor](how-to/store-threat-actor.md) | Use `remember()` with automatic entity extraction and knowledge graph population. |
| [Query APT Tools](how-to/query-apt-tools.md) | Use `recall()` + `synthesize()` to analyze APT tooling. |
| [Ingest a News Report](how-to/ingest-news-report.md) | Chunk and store a long-form CTI report with `remember_report()`. |
| [Resolve Aliases](how-to/resolve-aliases.md) | Map Fancy Bear to APT28 via TypeDB `alias-of` relations. |
| [Run Temporal Queries](how-to/run-temporal-query.md) | Query `valid-from`/`valid-until` edges and entity timelines. |
| [Configure TypeDB](how-to/configure-typedb.md) | Docker setup, schema deployment, and troubleshooting. |
| [Configure LanceDB](how-to/configure-lancedb.md) | Tune IVF_PQ index, similarity threshold, and entity boost. |
| [Integrate with Nexus Agent](how-to/integrate-nexus-agent.md) | Use `get_context()` and `ProactiveAgentMixin` in agent loops. |
| [Configure OpenCTI Integration](how-to/configure-opencti.md) | Bi-directional sync with OpenCTI via pycti — pull threat intelligence, push notes as STIX reports. [Enterprise] |

### Reference (Information-Oriented)

Exact specifications for every public class, method, and configuration option.

| Reference | Description |
|-----------|-------------|
| [Memory Manager API](reference/memory-manager-api.md) | `MemoryManager` — all 19 public methods with full type signatures. |
| [STIX 2.1 Schema](reference/stix-schema.md) | 9 entity types, 8 relation types, TypeDB functions, and type mappings. |
| [Configuration](reference/configuration.md) | All `config.yaml` keys, types, defaults, and environment variable overrides. |
| [Retrieval Policies](reference/retrieval-policies.md) | Intent-to-policy weight mapping, scoring formulas, merge algorithm. |
| [Governance Controls](reference/governance-controls.md) | GOV-003/007/011/012 enforcement matrix. |

### Explanation (Understanding-Oriented)

Background context and design rationale for the system's architecture.

| Topic | Description |
|-------|-------------|
| [Why TypeDB + LanceDB](explanation/architecture.md) | Architectural rationale for the hybrid two-database design. |
| [Zettelkasten Philosophy](explanation/zettelkasten-philosophy.md) | How Luhmann's note-taking method shapes ThreatRecall's memory. |
| [Two-Phase Pipeline](explanation/two-phase-pipeline.md) | FactExtractor + MemoryUpdater design and deduplication logic. |
| [STIX in ZettelForge](explanation/stix-in-zettelforge.md) | How STIX 2.1 maps to TypeDB entities and relations. |
| [Epistemic Tiers](explanation/epistemic-tiers.md) | Confidence model, tier classification, and decay mechanics. |

## Key Capabilities

- **Hybrid retrieval** -- BlendedRetriever fuses vector similarity (LanceDB) with graph traversal (TypeDB) weighted by query intent.
- **Two-phase ingestion** -- FactExtractor scores candidate facts; MemoryUpdater deduplicates against existing notes before storage.
- **STIX 2.1 knowledge graph** -- 9 entity types (threat-actor, malware, tool, attack-pattern, vulnerability, campaign, indicator, infrastructure, zettel-note) and 8 relation types (uses, targets, attributed-to, indicates, mitigates, mentioned-in, supersedes, alias-of) in TypeDB 3.x.
- **36 seeded CTI aliases** -- APT28/Fancy Bear/Strontium, Lazarus/Hidden Cobra/Diamond Sleet, and more resolve automatically.
- **Intent classification** -- Factual, temporal, relational, causal, and exploratory intents route to different retrieval strategies.
- **Synthesis formats** -- `direct_answer`, `synthesized_brief`, `timeline_analysis`, `relationship_map`.
- **Entity-indexed fast lookup** -- `recall_actor()`, `recall_cve()`, `recall_tool()` bypass vector search for known-entity queries.
- **Report ingestion** -- `remember_report()` chunks long documents, extracts facts per chunk, and stores with temporal metadata.
- **Causal triple extraction** -- LLM-extracted cause/effect triples stored as graph edges for "why" queries.
- **Governance enforcement** -- GOV-003 (data classification), GOV-007 (retention), GOV-011 (access control), GOV-012 (audit) validated on every operation.
- **Sigma rule generation** -- Produce detection rules from actor TTPs and indicators stored in memory.
- **Proactive context injection** -- `ContextInjector` pushes relevant memories into agent prompts before the agent asks.

## LLM Quick Reference

ThreatRecall (codebase: ZettelForge, v2.0.0, MIT license) is an agentic memory system for cyber threat intelligence. It requires Python 3.10+ and TypeDB 3.x via Docker on port 1729. Embeddings run in-process via fastembed (nomic-embed-text-v1.5-Q, 768-dim, ONNX) and LLM inference runs in-process via llama-cpp-python (Qwen2.5-3B-Instruct Q4_K_M GGUF). Models download automatically on first use. Ollama is optional as a fallback provider. Storage is dual: TypeDB holds a STIX 2.1 knowledge graph with 9 entity types (threat-actor, malware, tool, attack-pattern, vulnerability, campaign, indicator, infrastructure, zettel-note) and 8 relation types (uses, targets, attributed-to, indicates, mitigates, mentioned-in, supersedes, alias-of); LanceDB holds vector-indexed notes with IVF_PQ indexing. TypeDB inference functions include get_aliases, get_tools_used, and get_entity_notes. The system seeds 36 CTI aliases at startup (APT28/Fancy Bear/Strontium, APT29/Cozy Bear/Midnight Blizzard, Lazarus/Hidden Cobra/Diamond Sleet, Sandworm/Seashell Blizzard, Volt Typhoon/Bronze Silhouette, Kimsuky/Emerald Sleet, Turla/Secret Blizzard, MuddyWater/Mango Sandstorm, plus tool aliases for Cobalt Strike and Mimikatz).

The primary interface is `MemoryManager`. `remember(content)` stores a note with entity extraction, alias resolution, knowledge graph update, supersession check, and causal triple extraction. `remember_with_extraction(content)` runs the two-phase pipeline: FactExtractor distills scored facts, MemoryUpdater compares each against existing notes and applies ADD/UPDATE/DELETE/NOOP. `remember_report(content)` chunks long text and runs two-phase extraction per chunk. `recall(query)` classifies intent (factual/temporal/relational/causal/exploratory), runs BlendedRetriever with policy-weighted vector + graph scores, and returns ranked MemoryNote objects. `recall_actor(name)`, `recall_cve(id)`, `recall_tool(name)` perform fast entity-indexed lookups. `synthesize(query, format)` retrieves notes and produces an LLM-synthesized answer in one of four formats: direct_answer, synthesized_brief, timeline_analysis, or relationship_map. `get_entity_relationships(type, value)` and `traverse_graph(type, value, depth)` expose raw graph queries. Governance policies GOV-003 (data classification), GOV-007 (retention), GOV-011 (access control), and GOV-012 (audit) are enforced automatically on every operation via GovernanceValidator. Configuration lives in config.yaml with sections for storage, typedb, embedding, llm, extraction, retrieval, synthesis, cache, governance, and logging. The BlendedRetriever weights vector vs. graph results using the IntentClassifier's traversal policy: factual queries favor entity lookup, relational queries favor graph BFS, exploratory queries balance both. Notes support supersession (old note marked superseded_by, excluded from recall) and temporal edges for timeline queries.
