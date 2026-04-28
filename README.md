# ZettelForge

**Give your AI agents memory that persists, connects, and reasons.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/rolandpg/zettelforge/actions/workflows/ci.yml/badge.svg)](https://github.com/rolandpg/zettelforge/actions)
[![Version](https://img.shields.io/badge/version-2.1.1-green.svg)](https://github.com/rolandpg/zettelforge/releases)

## The Problem

Your AI agent starts from zero every session. Context from yesterday's threat hunt, last week's incident, or the report you read an hour ago -- gone. The agent has no memory, no entity relationships, no sense of what changed since the last time it ran.

You've tried RAG over documents. You get semantic search but no structure -- no "APT28 uses Cobalt Strike which exploits CVE-2024-1111" chain of reasoning. No deduplication. No contradiction detection. No way to ask "what changed since Tuesday?"

ZettelForge fixes this.

## What It Does

ZettelForge is an **agentic memory system** -- a structured, persistent knowledge store that AI agents can write to, read from, and reason over. Purpose-built for cyber threat intelligence, but works for any domain.

```python
from zettelforge import MemoryManager

mm = MemoryManager()

# Store intelligence -- entities are auto-extracted, graph edges are built
mm.remember("APT28 uses Cobalt Strike for lateral movement via CVE-2024-1111", domain="cti")

# New intel arrives -- evolve=True enables memory evolution:
# LLM extracts facts, compares to existing notes, decides ADD/UPDATE/DELETE/NOOP
mm.remember(
    "APT28 has shifted tactics. They dropped DROPBEAR and now exploit edge devices.",
    domain="cti",
    evolve=True,   # existing APT28 note gets superseded, not duplicated
    # sync=True,   # block until background causal enrichment completes (default: False)
)

# Retrieve -- blends vector similarity + knowledge graph traversal
results = mm.recall("What tools does APT28 use?")
# Returns Cobalt Strike note (high confidence), DROPBEAR note (superseded)

# Alias resolution works automatically
mm.recall_actor("Fancy Bear")  # resolves to APT28

# Synthesize answers from memory
mm.synthesize("Summarize APT28 activity")
```

No cloud. No API keys. Runs entirely on your laptop.

## How It Works

Every `remember()` call triggers a pipeline:

1. **Entity Extraction** -- regex + LLM NER identifies CVEs, actors, tools, campaigns, people, locations, orgs (10 types)
2. **Knowledge Graph Update** -- entities become nodes, co-occurrence becomes edges, LLM infers causal triples ("APT28 *uses* Cobalt Strike")
3. **Vector Embedding** -- 768-dim fastembed (ONNX, in-process, 7ms/embed) stored in LanceDB
4. **Supersession Check** -- entity overlap detection marks stale notes as superseded
5. **Dual-Stream Write** -- fast path returns in ~45ms; causal enrichment is deferred to a background worker

With `evolve=True`, the **memory evolution** pipeline adds two LLM-driven steps:

- **Phase 1 (Extraction)**: LLM extracts salient facts with importance scores
- **Phase 2 (Update Decision)**: Each fact is compared to existing memory -- LLM decides ADD, UPDATE, DELETE, or NOOP

This means your agent's memory self-corrects. Stale intel gets superseded. Contradictions get resolved. Duplicates get skipped. The MCP server and web API default to `evolve=True`.

Every `recall()` call blends two retrieval strategies:

1. **Vector similarity** -- semantic search over embeddings
2. **Graph traversal** -- BFS over knowledge graph edges, scored by hop distance
3. **Intent routing** -- query classified as factual/temporal/relational/causal/exploratory, weights adjusted per type
4. **Cross-encoder reranking** -- ms-marco-MiniLM reorders final results by relevance

## Benchmarks

Evaluated against published academic benchmarks:

| Benchmark | What it measures | Score |
|-----------|-----------------|-------|
| **CTI Retrieval** | Attribution, CVE linkage, multi-hop | **75.0%** |
| **RAGAS** | Retrieval quality (keyword presence) | **78.1%** |
| **LOCOMO** (ACL 2024) | Conversational memory recall | **22.0%** *(with Ollama cloud models)* |

See the [full benchmark report](benchmarks/BENCHMARK_REPORT.md) for methodology and analysis.

## Quick Start

```bash
git clone https://github.com/rolandpg/zettelforge.git
cd zettelforge
pip install -e .
```

```python
from zettelforge import MemoryManager
mm = MemoryManager()
note, _ = mm.remember("APT28 uses Cobalt Strike for lateral movement", domain="cti")
results = mm.recall("What tools does APT28 use?")
print(results[0].content.raw)
```

No TypeDB, no Ollama, no Docker -- just `pip install`. Embeddings run in-process via fastembed. LLM features (extraction, synthesis) activate when Ollama is available.

### With Ollama (enables LLM features)

```bash
ollama pull qwen2.5:3b && ollama serve
# ZettelForge auto-detects Ollama for extraction and synthesis
```

### MCP Server (Claude Code / AI agent integration)

```bash
python web/mcp_server.py
# Exposes: remember, recall, synthesize, entity, graph, stats
```

Add to `.claude.json`:
```json
{
  "mcpServers": {
    "threatrecall": {
      "command": "python3",
      "args": ["web/mcp_server.py"]
    }
  }
}
```

## Integrations

### ATHF (Agentic Threat Hunting Framework)

Ingest completed [ATHF](https://github.com/Nebulock-Inc/agentic-threat-hunting-framework) hunts into ZettelForge memory. MITRE techniques and IOCs are extracted and linked in the knowledge graph.

```bash
python examples/athf_bridge.py /path/to/hunts/
# 12 hunt(s) parsed
# Ingested 12/12 hunts into ZettelForge
```

See [examples/athf_bridge.py](examples/athf_bridge.py).

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                           MemoryManager                              │
│  remember()  remember_with_extraction()  recall()  synthesize()      │
├──────────┬───────────┬──────────────┬───────────┬────────────────────┤
│  Note    │  Fact     │   Memory     │  Blended  │   Synthesis        │
│Constructor│ Extractor │  Updater     │ Retriever │   Generator        │
│(enrich)  │(Phase 1)  │(Phase 2)     │(vec+graph)│   (RAG)            │
├──────────┴───────────┴──────────────┼───────────┴────────────────────┤
│       Entity Indexer + Alias        │  Intent Classifier             │
│       Resolver                      │  (factual/temporal/causal)     │
├─────────────────────────────────────┼────────────────────────────────┤
│   Knowledge Graph (JSONL)           │  LanceDB (Vectors)             │
│   Entity nodes + edges              │  768-dim fastembed (ONNX)      │
│   Causal triple inference           │  Zettelkasten notes            │
│   [Enterprise: TypeDB STIX 2.1]    │  IVF_PQ index                  │
└─────────────────────────────────────┴────────────────────────────────┘
```

## Community vs Enterprise

**ZettelForge Community** (MIT) is everything above -- a complete, production-ready agentic memory system. Free, open-source, local-first.

**[ThreatRecall Enterprise](https://threatengram.com/enterprise)** (BSL-1.1) adds what teams need in production:

| Feature | What it adds |
|---------|-------------|
| TypeDB STIX 2.1 ontology | Replaces JSONL graph at scale -- inference rules, 9 entity types, 8 relation types, 36 CTI aliases |
| Temporal KG queries | "What changed since Tuesday?" -- `get_changes_since()`, `get_entity_timeline()` |
| Multi-hop graph traversal | `traverse_graph()` with BFS across relationship chains |
| Advanced synthesis | `synthesized_brief`, `timeline_analysis`, `relationship_map` |
| Report ingestion | `remember_report()` with auto-chunking for long threat reports |
| OpenCTI integration | Bi-directional sync with OpenCTI via pycti — pull attack patterns, intrusion sets, malware, indicators, vulnerabilities, and reports; push notes back as STIX reports. Preserves TLP markings, STIX confidence, CVSS v3/EPSS scores. Deduplicates on re-sync. |
| Sigma rule generation | Sigma YAML detection rules from IOCs |
| Multi-tenant auth | OAuth/JWT with per-tenant data isolation |
| Context injection | Auto-load relevant context before agent tasks |

```bash
pip install zettelforge-enterprise
export THREATENGRAM_LICENSE_KEY="TG-xxxx-xxxx-xxxx-xxxx"
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AMEM_DATA_DIR` | `~/.amem` | Data directory |
| `ZETTELFORGE_BACKEND` | `jsonl` | `jsonl` or `typedb` [Enterprise] |
| `ZETTELFORGE_LLM_PROVIDER` | `local` | `local` (llama-cpp) or `ollama` |
| `THREATENGRAM_LICENSE_KEY` | | Enterprise license key |

See [config.default.yaml](config.default.yaml) for all options.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and the Community/Enterprise boundary.

## License

- **Community**: [MIT](LICENSE)
- **Enterprise**: [BSL-1.1](LICENSE-ENTERPRISE) (converts to Apache-2.0 after 4 years)

Built by [Threatengram](https://threatengram.com).

## Acknowledgments

- Inspired by [Zettelkasten](https://en.wikipedia.org/wiki/Zettelkasten) and [A-Mem](https://arxiv.org/abs/2602.10715) (NeurIPS 2025)
- Two-phase pipeline inspired by [Mem0](https://mem0.ai/research)
- STIX 2.1 schema informed by [typedb-cti](https://github.com/typedb-osi/typedb-cti)
- Benchmarked against [LOCOMO](https://snap-research.github.io/locomo/) (ACL 2024) and [CTIBench](https://arxiv.org/abs/2406.07599) (NeurIPS 2024)
- [LanceDB](https://lancedb.com) | [fastembed](https://github.com/qdrant/fastembed) | [Pydantic](https://pydantic.dev) | [TypeDB](https://typedb.com)
