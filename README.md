# ZettelForge

<!-- mcp-name: io.github.rolandpg/zettelforge -->

**The only agentic memory system built for cyber threat intelligence.**

When a senior analyst leaves, two or three years of context walks out with them — customer environments, prior investigations, actor TTPs, false-positive patterns, every hard-won "wait, we've seen this before." ZettelForge is an agentic memory system built so that context stays with the team.

It extracts CVEs, threat actors, IOCs, and ATT&CK techniques from analyst notes and threat reports, resolves aliases (APT28 = Fancy Bear = STRONTIUM = Sofacy), builds a STIX 2.1 knowledge graph, and serves every past investigation back to your analysts — and to Claude Code via MCP — in natural language. Runs entirely in-process. No API keys. No cloud. No data leaves the host.

[![PyPI](https://img.shields.io/pypi/v/zettelforge)](https://pypi.org/project/zettelforge/)
[![Downloads/month](https://static.pepy.tech/personalized-badge/zettelforge?period=month&units=international_system&left_color=grey&right_color=blue&left_text=downloads%2Fmonth)](https://pepy.tech/projects/zettelforge)
[![Star History](https://api.star-history.com/svg?repos=rolandpg/zettelforge&type=Date)](https://star-history.com/#rolandpg/zettelforge&Date)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/rolandpg/zettelforge/actions/workflows/ci.yml/badge.svg)](https://github.com/rolandpg/zettelforge/actions)
[![Open Issues](https://img.shields.io/github/issues/rolandpg/zettelforge?color=blue)](https://github.com/rolandpg/zettelforge/issues)

**[Star](https://github.com/rolandpg/zettelforge) · [`pip install zettelforge`](https://pypi.org/project/zettelforge/) · [Docs](https://docs.threatrecall.ai/) · [ThreatRecall (hosted)](https://threatrecall.ai) · [Changelog](CHANGELOG.md)**

> **v2.6.2** (2026-04-27): Config web editor ships with working dropdowns for all enum fields (LLM/embedding provider, log level, PII action, synthesis format) and a working Apply button. New `[crewai]` extra exposes ZettelForge as CrewAI tools -- `pip install zettelforge[crewai]`. [Full changelog](CHANGELOG.md)

<p align="center">
  <img src="https://raw.githubusercontent.com/rolandpg/zettelforge/master/docs/assets/demo.gif" width="720" alt="ZettelForge demo -- CTI agentic memory in action">
</p>

> If ZettelForge fits a CTI workflow you run, a star is the fastest signal that this category is worth continuing to invest in.

## The problem

Every SOC loses analysts. When they leave, investigation context, actor attribution, and environment-specific false-positive patterns go with them. Their replacements re-open the same tickets, re-read the same reports, and re-build the same mental models from scratch.

General-purpose AI memory systems don't fix this for security teams. They can't tell APT28 from Fancy Bear, don't know that CVE-2024-3094 is the XZ Utils backdoor, can't parse Sigma or YARA, and have no concept of MITRE ATT&CK technique IDs. When a CTI analyst gives them a year of intel reports, they get back fuzzy semantic search over chat history.

ZettelForge was built for analysts who think in threat graphs. It extracts CVEs, threat actors, IOCs, and ATT&CK techniques automatically, resolves aliases across naming conventions, builds a knowledge graph with causal relationships, and retrieves memories using intent-aware blended search -- all in-process, with no external API dependency.

> Memory augmentation closes 33% of the gap between small and large models on CTI tasks ([CTI-REALM, Microsoft 2026](https://www.microsoft.com/en-us/security/blog/2026/03/20/cti-realm-a-new-benchmark-for-end-to-end-detection-rule-generation-with-ai-agents/), using GPT-4 as the large-model baseline). See [full benchmark report](benchmarks/BENCHMARK_REPORT.md) for methodology and comparisons.

| Capability | ZettelForge | Mem0 | Graphiti | Cognee |
|---|---|---|---|---|
| CTI entity extraction (CVEs, actors, IOCs) | Yes | No | No | No |
| STIX 2.1 ontology | Yes | No | No | No |
| Threat actor alias resolution | Yes (APT28 = Fancy Bear) | No | No | No |
| Knowledge graph with causal triples | Yes | No | Yes | Yes |
| Intent-classified retrieval (5 types) | Yes | No | No | No |
| In-process / no external API required | Yes | No | No | No |
| Audit logs in OCSF schema | Yes | No | No | No |
| MCP server (Claude Code) | Yes | No | No | No |

## Data Pipeline
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/rolandpg/zettelforge/master/docs/assets/zettelforge_architecture.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/rolandpg/zettelforge/master/docs/assets/zettelforge_architecture-light.svg">
    <img src="https://raw.githubusercontent.com/rolandpg/zettelforge/master/docs/assets/zettelforge_architecture.svg" width="720" alt="ZettelForge architecture -- neural recall loop: ingest, enrich, retrieve, synthesize, backed by SQLite + LanceDB">
  </picture>
</p>


## Features

**Entity Extraction** -- Automatically identifies CVEs, threat actors, IOCs (IPs, domains, hashes, URLs, emails), MITRE ATT&CK techniques, campaigns, intrusion sets, tools, people, locations, and organizations. Regex + LLM NER with STIX 2.1 types throughout.

**Knowledge Graph** -- Entities become nodes, co-occurrence becomes edges. LLM infers causal triples ("APT28 *uses* Cobalt Strike"). Temporal edges and supersession track how intelligence evolves.

**Alias Resolution** -- APT28, Fancy Bear, Sofacy, STRONTIUM all resolve to the same actor node. Works automatically on store and recall.

**Blended Retrieval** -- Vector similarity (768-dim fastembed, ONNX) + graph traversal (BFS over knowledge graph edges), weighted by intent classification. Five intent types: factual, temporal, relational, exploratory, causal.

**Memory Evolution** -- With `evolve=True`, new intel is compared to existing memory. LLM decides ADD, UPDATE, DELETE, or NOOP. Stale intel gets superseded. Contradictions get resolved. Duplicates get skipped.

**RAG Synthesis** -- Synthesize answers across all stored memories with `direct_answer` format.

**In-process by architecture** -- fastembed (ONNX) for embeddings, llama-cpp-python for optional local LLM inference, SQLite + LanceDB for storage, and Ollama on localhost by default. No external API keys are required. Outbound network access may occur on first run when embedding/LLM models are downloaded; after models are preloaded, it can run fully offline (including on air-gapped hosts).

**Audit logging in OCSF schema** -- Every operation emits a structured event in the Open Cybersecurity Schema Framework format. What you do with the log stream (SIEM, WORM store, nothing) is up to you.

## Quick Start

### 30-second hello world (no LLM required)

```bash
pip install zettelforge
```

```python
from zettelforge import MemoryManager

mm = MemoryManager()

# Store CTI -- entities (CVEs, actors, ATT&CK IDs, IOCs) extracted via regex
mm.remember("APT28 uses Cobalt Strike for lateral movement via T1021")
mm.remember("APT28 (Fancy Bear) targets NATO defense contractors with spear-phishing")
mm.remember("CVE-2024-3094 is the XZ Utils backdoor (CVSS 10.0) affecting sshd")

# Recall blends vector + graph search; alias resolution kicks in (Fancy Bear -> APT28)
for note in mm.recall("What tools does Fancy Bear use?", k=3):
    print(f"[{note.metadata.tier}] {note.content.raw}")
```

That works on a fresh `pip install` with no external services. Embeddings run in-process via fastembed (~80MB ONNX model downloaded on first call). `MemoryManager()` writes to `~/.amem/` by default; override with `ZETTELFORGE_DATA_DIR` or via config. A runnable copy lives at [`examples/quickstart.py`](examples/quickstart.py).

### Add an LLM for synthesis and richer extraction

```bash
ollama pull qwen3.5:9b && ollama serve
```

```python
# With Ollama running, synthesize() returns a real summary across stored notes
answer = mm.synthesize("Summarize known APT28 TTPs")
print(answer["synthesis"]["answer"])
# Background LLM NER also enriches stored notes with additional entities
```

ZettelForge auto-detects Ollama. To use a different provider (`local` llama-cpp, `litellm` for 100+ providers, `mock` for tests), see [Configuration](#configuration). Without an LLM, `synthesize()` still returns a structured response but the `answer` field is a fallback placeholder -- only `remember` and `recall` produce useful results in pip-only mode.

### Memory Evolution

```python
# New intel arrives -- evolve=True enables memory evolution:
# LLM extracts facts, compares to existing notes, decides ADD/UPDATE/DELETE/NOOP
mm.remember(
    "APT28 has shifted tactics. They dropped DROPBEAR and now exploit edge devices.",
    domain="cti",
    evolve=True,   # existing APT28 note gets superseded, not duplicated
)
```

## How It Works

Every `remember()` call triggers a pipeline:

1. **Entity Extraction** -- regex + LLM NER identifies CVEs, intrusion sets, threat actors, tools, campaigns, ATT&CK techniques, IOCs (IPv4, domain, URL, MD5/SHA1/SHA256, email), people, locations, organizations, events, activities, and temporal references (19 types)
2. **Knowledge Graph Update** -- entities become nodes, co-occurrence becomes edges, LLM infers causal triples
3. **Vector Embedding** -- 768-dim fastembed (ONNX, in-process, 7ms/embed) stored in LanceDB
4. **Supersession Check** -- entity overlap detection marks stale notes as superseded
5. **Dual-Stream Write** -- fast path returns in ~45ms; causal enrichment is deferred to a background worker

Every `recall()` call blends two retrieval strategies:

1. **Vector similarity** -- semantic search over embeddings
2. **Graph traversal** -- BFS over knowledge graph edges, scored by hop distance
3. **Intent routing** -- query classified as factual/temporal/relational/causal/exploratory, weights adjusted per type
4. **Cross-encoder reranking** -- ms-marco-MiniLM reorders final results by relevance

## Use ZettelForge in Claude Desktop in 60 seconds

```bash
pip install zettelforge
```

Create or edit `.claude.json` in your project root (or `~/.claude/.claude.json` for global access):

```json
{
  "mcpServers": {
    "zettelforge": {
      "command": "python3",
      "args": ["-m", "zettelforge.mcp"]
    }
  }
}
```

If ZettelForge is installed in a virtual environment, use the full path to that Python interpreter:

```json
{
  "mcpServers": {
    "zettelforge": {
      "command": "/home/user/.venvs/zettelforge/bin/python",
      "args": ["-m", "zettelforge.mcp"]
    }
  }
}
```

Start Claude Code and verify the tools are available:

```bash
claude
# Inside the session, ask: "What tools do you have available from zettelforge?"
```

Seven tools are exposed: `zettelforge_remember`, `zettelforge_recall`, `zettelforge_synthesize`, `zettelforge_entity`, `zettelforge_graph`, `zettelforge_stats`, and `zettelforge_sync` (requires enterprise package). See the [MCP protocol reference](docs/reference/mcp-protocol.md) for full schemas, JSON-RPC request/response examples, error codes, and the lazy-singleton lifecycle. For troubleshooting, virtualenv paths, and manual tool testing, see [set-up-mcp-server](docs/how-to/set-up-mcp-server.md).

## Benchmarks

Evaluated against published academic benchmarks:

| Benchmark | What it measures | Score |
|---|---|---|
| **CTI Retrieval** (CTIBench subset) | Attribution, CVE linkage, multi-hop | **75.0%** |
| **RAGAS** | Retrieval quality (keyword presence) | **78.1%** |
| **LOCOMO** (ACL 2024) | Conversational memory recall | **22.0%** |

The **Score** column reports ZettelForge measurements run with Ollama-hosted models, with one exception: the LOCOMO row was re-measured at v2.1.1 using an Ollama cloud judge for evaluation grading (not local generation). See the [full benchmark report](benchmarks/BENCHMARK_REPORT.md) for benchmark-specific methodology, version history, and per-suite judge configuration.

## Detection Rules as Memory (Sigma + YARA)

Sigma and YARA rules are first-class memory primitives. Parse, validate, and ingest a rule and its tags become graph edges: MITRE ATT&CK techniques, CVEs, threat-actor aliases, tools, and malware families resolve against the same ontology as every other note. A shared `DetectionRule` supertype carries `SigmaRule` and `YaraRule` subtypes, so a single rule UUID is addressable across both formats.

Sigma rules are validated against the vendored [SigmaHQ JSON schema](https://github.com/SigmaHQ/sigma-specification). YARA rules are parsed with plyara and checked against the [CCCS YARA metadata standard](https://github.com/CybercentreCanada/CCCS-Yara) (tiers: `strict`, `warn`, `non_cccs`). Ingest is idempotent -- re-ingesting an unchanged rule returns the original note via a content-hashed `source_ref`.

```python
from zettelforge import MemoryManager
from zettelforge.sigma import ingest_rule as ingest_sigma
from zettelforge.yara import ingest_rule as ingest_yara

mm = MemoryManager()
ingest_sigma("rules/proc_creation_win_office_macro.yml", mm)
ingest_yara("rules/webshell_china_chopper.yar", mm, tier="warn")
```

```bash
# Bulk ingest from SigmaHQ or a private rule repo
python -m zettelforge.sigma.ingest /path/to/sigma/rules/
python -m zettelforge.yara.ingest /path/to/yara/rules/ --tier warn

# CI fixture check -- parse + validate, no writes
python -m zettelforge.sigma.ingest rules/ --dry-run
```

An LLM rule explainer (`zettelforge.detection.explainer.explain`) produces a structured JSON summary -- intent, key fields, evasion notes, false-positive hypotheses -- for any `DetectionRule`. It runs synchronously on demand in v1; async enrichment-queue wiring is v1.1. Rate-limited via `ZETTELFORGE_EXPLAIN_RPM` (default 60 calls/minute).

References: [Sigma spec](https://github.com/SigmaHQ/sigma-specification), [SigmaHQ rules](https://github.com/SigmaHQ/sigma), [CCCS YARA](https://github.com/CybercentreCanada/CCCS-Yara), [YARA docs](https://yara.readthedocs.io).

## Integrations

### ATHF (Agentic Threat Hunting Framework)

Ingest completed [ATHF](https://github.com/Nebulock-Inc/agentic-threat-hunting-framework) hunts into ZettelForge memory. MITRE techniques and IOCs are extracted and linked in the knowledge graph.

```bash
python examples/athf_bridge.py /path/to/hunts/
# 12 hunt(s) parsed
# Ingested 12/12 hunts into ZettelForge
```

See [examples/athf_bridge.py](examples/athf_bridge.py).


## ThreatRecall (Hosted)

[ThreatRecall](https://threatrecall.ai) is the commercial distribution of ZettelForge with enterprise extensions enabled. It is offered as managed SaaS by default, with optional self-hosted on-prem and air-gapped deployments for classified environments. Enterprise add-ons:

- **TypeDB STIX 2.1 backend** -- schema-enforced ontology with inference rules
- **OpenCTI sync** -- bi-directional sync with your OpenCTI instance
- **Multi-tenant auth** -- OAuth/JWT with per-tenant data isolation
- **Sigma rule generation** -- detection rules from extracted IOCs (upcoming)

SaaS deploys in minutes with no infrastructure to maintain. Self-hosted ships as a deployable bundle for environments where outbound network egress is restricted or prohibited.

**[Join the waitlist](https://threatrecall.ai)** -- currently onboarding design partners.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `AMEM_DATA_DIR` | `~/.amem` | Data directory |
| `ZETTELFORGE_BACKEND` | `sqlite` | SQLite community backend. TypeDB available via extension. |
| `ZETTELFORGE_LLM_PROVIDER` | `local` | `local` (llama-cpp) or `ollama` |

See [config.default.yaml](config.default.yaml) for all options.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup.

## License

MIT -- See [LICENSE](LICENSE).

Built by **Patrick Roland** -- [LinkedIn](https://www.linkedin.com/in/patrickgroland/) | Director of SOC Services, Summit 7 Systems | Navy nuclear veteran | CISSP, CCP (CMMC 2.0 Professional)

## Support the Project

ZettelForge is MIT-licensed. Star the repo, open issues, and submit PRs — all contributions are welcome.

## Acknowledgments

- Inspired by [Zettelkasten](https://en.wikipedia.org/wiki/Zettelkasten) and [A-Mem](https://arxiv.org/abs/2602.10715) (NeurIPS 2025)
- Two-phase pipeline inspired by [Mem0](https://mem0.ai/research)
- STIX 2.1 schema informed by [typedb-cti](https://github.com/typedb-osi/typedb-cti)
- Benchmarked against [LOCOMO](https://snap-research.github.io/locomo/) (ACL 2024) and [CTIBench](https://arxiv.org/abs/2406.07599) (NeurIPS 2024)
- [LanceDB](https://lancedb.com) | [fastembed](https://github.com/qdrant/fastembed) | [Pydantic](https://pydantic.dev) | [TypeDB](https://typedb.com)

