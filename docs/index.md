---
title: Agentic Memory for Cyber Threat Intelligence
description: ZettelForge documentation — tutorials, API reference, and architecture guides for the open-source CTI memory system with STIX knowledge graphs, alias resolution, and agent-native retrieval.
diataxis_type: "navigation"
audience: "all"
tags: [overview, navigation]
last_updated: "2026-04-25"
version: "2.6.0"
---

# ZettelForge Documentation

**Your SOC's most expensive asset walks out the door every day.**

When a senior analyst leaves, two or three years of context walks out with them -- customer environments, prior investigations, actor TTPs, false-positive patterns, every hard-won "wait, we've seen this before." ZettelForge is an agentic memory system built so that context stays with the team.

It extracts CVEs, threat actors, IOCs, and ATT&CK techniques from analyst notes and threat reports, resolves aliases (APT28 = Fancy Bear = STRONTIUM = Sofacy), and indexes vector-embedded Zettelkasten notes in LanceDB for retrieval in natural language by analysts and Claude Code via MCP. Community defaults use SQLite + LanceDB, while TypeDB-backed STIX 2.1 graph storage is optional. No external API keys are required by default. Fully offline operation is possible with the `local` provider after preloading models. For cloud-connected deployments, the `litellm` provider routes to OpenAI, Anthropic, Google, Groq, and 100+ other backends through a single interface.

**New here?** Start with the [5-minute Quickstart](tutorials/01-quickstart.md), or `pip install zettelforge`.

**Prefer a GUI?** The [Web Management Interface](how-to/use-web-interface.md) provides a full browser-based dashboard with search, knowledge graph exploration, live logs and telemetry, bulk ingestion, and live configuration editing. Start it with `python web/app.py` (requires `pip install zettelforge[web]`).

## Architecture Overview

ZettelForge uses a hybrid storage architecture with in-process AI. TypeDB stores structured CTI entities and their relationships using the STIX 2.1 ontology. LanceDB stores unstructured notes as 768-dimensional vectors with IVF_PQ indexing. Embeddings are generated in-process by fastembed (nomic-embed-text-v1.5-Q, ONNX runtime, ~7ms/embed). LLM inference runs through one of four backends selected by `llm.provider`: in-process GGUF via `llama-cpp-python`, in-process ONNX via `onnxruntime-genai`, Ollama HTTP, or LiteLLM routing to 100+ cloud providers. No external AI services are required by default. The BlendedRetriever fuses results from both stores at query time, weighting vector similarity against graph traversal based on the classified intent of the query.

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

## LLM Provider Options

ZettelForge offers four LLM provider options, configured via `llm.provider` in `config.yaml`:

| Provider | Installation | Use Case | Configuration |
|:---------|:-------------|:---------|:--------------|
| `local` | `pip install zettelforge[local]` | Fully offline GGUF inference | `provider: local` + `local_backend: llama-cpp-python` |
| `local` (ONNX) | `pip install zettelforge[local-onnx]` | Offline ONNX, AMD ROCm, DirectML | `provider: local` + `local_backend: onnxruntime-genai` |
| `ollama` | core (no extra) | Local Ollama server (default) | `provider: ollama` + `url: http://localhost:11434` |
| `litellm` | `pip install zettelforge[litellm]` | 100+ cloud providers, single interface | `provider: litellm` + `model: gpt-4o` |

See the [Configuration Reference](reference/configuration.md) for full details on all provider options, API key management, and example configurations.

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
| [Integrate with Your LLM Agent](how-to/integrate-llm-agent.md) | Use `get_context()` and `ProactiveAgentMixin` in agent loops. |
| [Configure OpenCTI Integration](how-to/configure-opencti.md) | Bi-directional sync with OpenCTI via pycti. (requires zettelforge-enterprise) |

### Reference (Information-Oriented)

Exact specifications for every public class, method, and configuration option.

| Reference | Description |
|-----------|-------------|
| [Memory Manager API](reference/memory-manager-api.md) | `MemoryManager` -- all 19 public methods with full type signatures. |
| [STIX 2.1 Schema](reference/stix-schema.md) | 9 entity types, 8 relation types, TypeDB functions, and type mappings. |
| [Configuration](reference/configuration.md) | All `config.yaml` keys, types, defaults, environment variable overrides, provider quick-reference, and example configs by use case. |
| [Retrieval Policies](reference/retrieval-policies.md) | Intent-to-policy weight mapping, scoring formulas, merge algorithm. |
| [Governance Controls](reference/governance-controls.md) | GOV-003/007/011/012 enforcement matrix. |

### Explanation (Understanding-Oriented)

Background context and design rationale for the system's architecture.

| Topic | Description |
|-------|-------------|
| [Why TypeDB + LanceDB](explanation/architecture.md) | Architectural rationale for the hybrid two-database design. |
| [Zettelkasten Philosophy](explanation/zettelkasten-philosophy.md) | How Luhmann's note-taking method shapes ZettelForge's memory. |
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
- **Multi-backend LLM** -- Four provider options: in-process GGUF (llama-cpp-python), in-process ONNX (onnxruntime-genai), Ollama HTTP, and LiteLLM unified routing to 100+ cloud providers.

## LLM Quick Reference

ZettelForge (v2.6.0, MIT license) is an agentic memory system for cyber threat intelligence. It requires Python 3.10+. By default, storage uses SQLite together with LanceDB for vector-indexed notes; TypeDB 3.x via Docker on port 1729 is an optional graph backend. Embeddings run in-process via fastembed (nomic-embed-text-v1.5-Q, 768-dim, ONNX). The default LLM provider is Ollama (`provider: ollama`, `model: qwen3.5:9b`).

Three additional LLM providers are available as optional extras:

- **`provider: local`** with `pip install zettelforge[local]` for in-process GGUF inference via llama-cpp-python (fully offline, Qwen2.5-3B-Instruct Q4_K_M default).
- **`provider: local` with `local_backend: onnxruntime-genai`** and `pip install zettelforge[local-onnx]` for in-process ONNX inference (AMD ROCm, Intel OpenVINO, Apple CoreML support).
- **`provider: litellm`** with `pip install zettelforge[litellm]` for unified routing to 100+ providers (OpenAI, Anthropic, Google, Groq, Together AI, AWS Bedrock, OpenRouter, and more) via model name prefix matching. API keys via config or standard environment variables.

Storage defaults to SQLite + LanceDB, while optional TypeDB-backed deployments can hold a STIX 2.1 knowledge graph with 9 entity types (threat-actor, malware, tool, attack-pattern, vulnerability, campaign, indicator, infrastructure, zettel-note) and 8 relation types (uses, targets, attributed-to, indicates, mitigates, mentioned-in, supersedes, alias-of). When TypeDB is enabled, graph-oriented functions include get_aliases, get_tools_used, and get_entity_notes. The system seeds 36 CTI aliases at startup (APT28/Fancy Bear/Strontium, APT29/Cozy Bear/Midnight Blizzard, Lazarus/Hidden Cobra/Diamond Sleet, Sandworm/Seashell Blizzard, Volt Typhoon/Bronze Silhouette, Kimsuky/Emerald Sleet, Turla/Secret Blizzard, MuddyWater/Mango Sandstorm, plus tool aliases for Cobalt Strike and Mimikatz).

The primary interface is `MemoryManager`. `remember(content)` stores a note with entity extraction, alias resolution, knowledge graph update, supersession check, and causal triple extraction. `remember_with_extraction(content)` runs the two-phase pipeline: FactExtractor distills scored facts, MemoryUpdater compares each against existing notes and applies ADD/UPDATE/DELETE/NOOP. `remember_report(content)` chunks long text and runs two-phase extraction per chunk. `recall(query)` classifies intent (factual/temporal/relational/causal/exploratory), runs BlendedRetriever with policy-weighted vector + graph scores, and returns ranked MemoryNote objects. `recall_actor(name)`, `recall_cve(id)`, `recall_tool(name)` perform fast entity-indexed lookups. `synthesize(query, format)` retrieves notes and produces an LLM-synthesized answer in one of four formats: direct_answer, synthesized_brief, timeline_analysis, or relationship_map. `get_entity_relationships(type, value)` and `traverse_graph(type, value, depth)` expose raw graph queries. Governance policies GOV-003 (data classification), GOV-007 (retention), GOV-011 (access control), and GOV-012 (audit) are enforced automatically on every operation via GovernanceValidator. Configuration lives in config.yaml with sections for storage, typedb, embedding, llm, extraction, retrieval, synthesis, cache, governance, logging, lance, and opencti. The BlendedRetriever weights vector vs. graph results using the IntentClassifier's traversal policy: factual queries favor entity lookup, relational queries favor graph BFS, exploratory queries balance both. Notes support supersession (old note marked superseded_by, excluded from recall) and temporal edges for timeline queries.
