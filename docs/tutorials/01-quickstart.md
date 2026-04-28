---
title: "Quickstart: Your First Memory"
description: Store, recall, and synthesize threat intelligence with ThreatRecall in under 5 minutes.
diataxis_type: "tutorial"
audience: "L1/L2 SOC Analyst"
tags: [tutorial, quickstart, getting-started]
last_updated: "2026-04-09"
version: "2.0.0"
---

# Quickstart: Your First Memory

**What you will build**: A working ThreatRecall instance that stores threat intelligence about APT28 and Lazarus Group, recalls it by name, and synthesizes a brief from memory.

**What you will learn**:

- Storing CTI facts with `remember()`
- Recalling notes with `recall()` and `recall_actor()`
- Synthesizing answers with `synthesize()`

**Prerequisites**:

- [ ] [Python 3.10+](https://www.python.org/downloads/) installed
- [ ] [Docker](https://docs.docker.com/get-docker/) installed and running

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/rolandpg/zettelforge.git
cd zettelforge
```

You should see:

```
Cloning into 'zettelforge'...
```

## Step 2: Install ZettelForge

```bash
pip install -e .
```

Expected output (last lines):

```
Successfully installed zettelforge-2.0.0
```

> [!NOTE]
> If you see permission errors, use `pip install --user -e .` or activate a virtual environment first with `python -m venv venv && source venv/bin/activate`.

## Step 3: Start TypeDB

```bash
docker compose -f docker/docker-compose.yml up -d
```

Expected output:

```
[+] Running 1/1
 ✔ Container docker-typedb-1  Started
```

Wait a few seconds for TypeDB to finish its health check. Verify it is running:

```bash
docker compose -f docker/docker-compose.yml ps
```

Expected output:

```
NAME                STATUS
docker-typedb-1     running (healthy)
```

## Step 4: Store Your First Memories

> [!NOTE]
> ZettelForge runs embeddings and LLM inference in-process by default. The embedding model (~130 MB) and LLM (~2.0 GB) download automatically on first use. No Ollama setup is required. If you prefer to use Ollama as an optional fallback, see [Configuration Reference](../reference/configuration.md).

Open a Python shell or create a file called `quickstart.py`. Paste the following code and run it.

```python
from zettelforge import MemoryManager

mm = MemoryManager()

note1, status1 = mm.remember(
    "APT28 (Fancy Bear) deployed a modified X-Agent implant against "
    "Ukrainian government networks in March 2026. The implant used "
    "CVE-2025-21298 for initial access via spearphishing attachments.",
    source_type="report",
    source_ref="https://example.com/apt28-ukraine-2026",
    domain="cti"
)
print(f"Note 1: {note1.id} — {status1}")

note2, status2 = mm.remember(
    "Lazarus Group conducted Operation DreamJob targeting defense "
    "contractors in South Korea and Japan during Q1 2026. The campaign "
    "used trojanized job offer PDFs delivering the DreamJob backdoor "
    "via LinkedIn messages.",
    source_type="report",
    source_ref="https://example.com/lazarus-dreamjob-2026",
    domain="cti"
)
print(f"Note 2: {note2.id} — {status2}")

note3, status3 = mm.remember(
    "APT28 was also observed using Cobalt Strike beacons for lateral "
    "movement after initial X-Agent deployment. The beacons called back "
    "to infrastructure hosted on bulletproof providers in Moldova.",
    source_type="report",
    source_ref="https://example.com/apt28-cobalt-strike",
    domain="cti"
)
print(f"Note 3: {note3.id} — {status3}")
```

Expected output:

```
Note 1: note_a1b2c3d4 — created
Note 2: note_e5f6g7h8 — created
Note 3: note_i9j0k1l2 — created
```

> [!NOTE]
> Your note IDs will differ. The `created` status confirms each note was stored, entity-indexed, and added to the knowledge graph.

## Step 5: Recall by Query

```python
results = mm.recall("What tools does APT28 use?", domain="cti", k=5)

for note in results:
    print(f"[{note.id}] {note.content.raw[:120]}...")
```

Expected output:

```
[note_i9j0k1l2] APT28 was also observed using Cobalt Strike beacons for lateral movement after initial X-Agent deployment...
[note_a1b2c3d4] APT28 (Fancy Bear) deployed a modified X-Agent implant against Ukrainian government networks in March 2026...
```

The Cobalt Strike note appears first because graph retrieval prioritizes directly related entities.

## Step 6: Recall by Actor Name

```python
lazarus_notes = mm.recall_actor("Lazarus Group", k=5)

for note in lazarus_notes:
    print(f"[{note.id}] {note.content.raw[:120]}...")
```

Expected output:

```
[note_e5f6g7h8] Lazarus Group conducted Operation DreamJob targeting defense contractors in South Korea and Japan during Q1...
```

Alias resolution means "Lazarus Group" and "Hidden Cobra" return the same results.

## Step 7: Synthesize an Answer

```python
result = mm.synthesize(
    "Summarize what we know about APT28 activity in 2026.",
    format="synthesized_brief",
    k=10
)

print(result["synthesis"]["summary"])
print(f"\nSources: {len(result['sources'])} notes")
print(f"Confidence: {result['metadata']['confidence']}")
```

Expected output:

```
APT28 (Fancy Bear) conducted operations against Ukrainian government networks
in March 2026, deploying a modified X-Agent implant via spearphishing
attachments exploiting CVE-2025-21298. Post-compromise activity included
Cobalt Strike beacons for lateral movement, with C2 infrastructure hosted on
bulletproof providers in Moldova.

Sources: 2 notes
Confidence: 0.82
```

The SynthesisGenerator retrieved relevant notes, built a context window, and produced a fused brief with source attribution and a confidence score.

## What You Built

You now have a working ThreatRecall instance with:

- **3 stored notes** about APT28 and Lazarus Group activity
- **Entity index entries** for actors (APT28, Lazarus), tools (X-Agent, Cobalt Strike), CVEs (CVE-2025-21298), and campaigns (Operation DreamJob)
- **Knowledge graph edges** linking actors to tools, CVEs, and campaigns in TypeDB
- **Alias resolution** so "Fancy Bear" and "APT28" resolve to the same canonical entity

## Next Steps

- [How-To: Ingest a Threat Report](../how-to/) -- Use `remember_report()` to chunk and store long-form CTI documents.
- [Reference: Python API](../reference/) -- Full documentation for `MemoryManager`, `BlendedRetriever`, and all public classes.
- [Explanation: Two-Phase Extraction Pipeline](../explanation/) -- Understand why FactExtractor + MemoryUpdater prevents duplicate and stale notes.

---

## LLM Quick Reference

This tutorial demonstrated the core ThreatRecall (ZettelForge v2.0.0) workflow: `remember()` stores text as a MemoryNote, runs entity extraction (actors, tools, CVEs, campaigns), resolves aliases (e.g. "Fancy Bear" to canonical "apt28" using 36 seeded alias mappings), writes to LanceDB (768-dim nomic-embed-text-v2-moe vectors, IVF_PQ index) and TypeDB (STIX 2.1 entities and relations), checks for note supersession, and extracts causal triples for graph edges. `recall(query)` classifies intent (factual/temporal/relational/causal/exploratory) via IntentClassifier, then BlendedRetriever merges vector similarity from LanceDB with graph BFS from TypeDB using policy-weighted scores. `recall_actor(name)` (also `recall_cve(id)`, `recall_tool(name)`) performs direct entity-index lookup bypassing vector search. `synthesize(query, format)` retrieves notes and produces an LLM answer in one of four formats: direct_answer, synthesized_brief, timeline_analysis, relationship_map. Prerequisites are Python 3.10+ and Docker (for TypeDB 3.x on port 1729). Embeddings run in-process via fastembed (nomic-embed-text-v1.5-Q, 768-dim) and LLM runs in-process via llama-cpp-python (Qwen2.5-3B-Instruct Q4_K_M). Models download automatically on first use. Ollama is optional as a fallback provider. Install with `pip install -e .` from the repo root. TypeDB starts via `docker compose -f docker/docker-compose.yml up -d`. The MemoryManager constructor accepts optional `jsonl_path` and `lance_path` arguments; defaults store data in `~/.amem`. Governance policies (GOV-003, GOV-007, GOV-011, GOV-012) are enforced automatically on every `remember()` and `synthesize()` call.
