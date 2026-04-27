---
title: "Integrate with CrewAI"
description: "Use ZettelForge as a memory and synthesis backend for CrewAI agents, providing recall, remember, and synthesize tools for CTI workflows."
diataxis_type: "how-to"
audience: "CrewAI developers building multi-agent CTI systems, security engineers adding persistent memory to agent crews"
tags: [crewai, agents, memory, recall, synthesize, integration]
last_updated: "2026-04-27"
version: "2.7.0"
---

# Integrate with CrewAI

Integrate ZettelForge as a persistent memory backend for CrewAI agents. Three
CrewAI-compatible tools are provided: recall (blended vector + graph search),
remember (persist findings with auto-extraction), and synthesize (LLM-generated
answers over stored memory).

## Prerequisites

- ZettelForge installed with CrewAI extra: `pip install zettelforge[crewai]`
- Embedding and LLM models available (download automatically on first use)
- CrewAI installed (pulled automatically by the extra)

## Steps

### 1. Create a MemoryManager instance

```python
from zettelforge import MemoryManager

mm = MemoryManager()
```

### 2. Create the CrewAI tools

Three tools map to ZettelForge's core operations:

```python
from zettelforge.integrations.crewai import (
    ZettelForgeRecallTool,
    ZettelForgeRememberTool,
    ZettelForgeSynthesizeTool,
)

recall = ZettelForgeRecallTool(memory_manager=mm, k=5)
remember = ZettelForgeRememberTool(memory_manager=mm)
synthesize = ZettelForgeSynthesizeTool(memory_manager=mm, k=10)
```

### 3. Attach tools to a CrewAI agent

```python
from crewai import Agent

analyst = Agent(
    role="CTI analyst",
    goal="Investigate threat-actor activity using prior intel",
    backstory="Senior analyst with access to the team's knowledge base.",
    tools=[recall, remember, synthesize],
)
```

### 4. Use the tools in a CrewAI task

```python
from crewai import Task, Crew

investigate_task = Task(
    description="Research APT28's latest TTPs using our memory knowledge base",
    expected_output="A summary of known APT28 techniques with source citations",
    agent=analyst,
)

crew = Crew(
    agents=[analyst],
    tasks=[investigate_task],
    verbose=True,
)

result = crew.kickoff()
```

### 5. Configure individual tool parameters

Each tool accepts configuration parameters at construction time:

```python
# Recall: filter by domain, limit results
recall = ZettelForgeRecallTool(
    memory_manager=mm,
    k=10,
    domain="cti",         # Only search notes in the "cti" domain
)

# Remember: set domain and source type, enable memory evolution
remember = ZettelForgeRememberTool(
    memory_manager=mm,
    domain="cti",
    source_type="crewai_agent",
    evolve=True,           # Run LLM fact-extraction + dedup pipeline
)

# Synthesize: control format and tier filter
synthesize = ZettelForgeSynthesizeTool(
    memory_manager=mm,
    k=10,
    format="direct_answer",  # or "synthesized_brief", "timeline_analysis", "relationship_map"
    tier_filter=["A", "B"],  # Only use authoritative and operational sources
)
```

> [!TIP]
> Set `evolve=True` on `ZettelForgeRememberTool` to deduplicate stored
> notes via LLM fact extraction. This is slower but produces a tighter
> knowledge graph. The default is `False` for speed.

### 6. Use the tools programmatically (without CrewAI)

The tools can also be invoked directly via their `_run()` method:

```python
# Recall
result = recall._run(query="APT28 lateral movement techniques")
print(result)

# Remember
result = remember._run(
    content="Lazarus Group observed using novel macOS payload in 2025-Q1.",
    source_ref="incident/2025-q1-lazarus",
)
print(result)

# Synthesize
result = synthesize._run(query="Summarize known APT28 TTPs")
print(result)
```

### 7. Understand the output format

The recall tool returns formatted text optimized for agent reasoning, not
human reading:

```text
Found 2 note(s) for query: "APT28 lateral movement techniques"

[1] id=note-abc tier=A confidence=0.9 domain=cti
    source: report/mandiant-apt28-q1-2026
    entities: apt28, cobalt strike, mimikatz
    content: APT28 (Fancy Bear) deployed Cobalt Strike beacons...
```

The remember tool returns a confirmation string:

```text
Stored note id=note-def status=created tier=B entities=lazarus, macos
```

The synthesize tool returns the answer with confidence and source citations:

```text
APT28 used Cobalt Strike for lateral movement during the ...
confidence: 0.85
sources:
  - note-abc (tier=A)
  - note-xyz (tier=B)
```

## LLM Quick Reference

**Task**: Give CrewAI agents persistent CTI memory backed by ZettelForge.

**Install**: `pip install zettelforge[crewai]`

**Three tools**:

- `ZettelForgeRecallTool(memory_manager, k=10, domain=None)` — blended
  vector + graph search. Returns formatted text with note IDs, tiers, confidence,
  entities, and content. Agent-oriented format (not human reading).

- `ZettelForgeRememberTool(memory_manager, domain="cti", source_type="crewai_agent",
  evolve=False)` — persist a finding. Auto-extracts CVEs, threat actors, ATT&CK
  techniques, and IOCs. Returns note ID and extracted entity summary.

- `ZettelForgeSynthesizeTool(memory_manager, k=10, format="direct_answer",
  tier_filter=None)` — LLM-synthesized answer over retrieved memory. Slower than
  recall; reserve for final-answer composition.

**Configuration**: All tools accept `memory_manager` (required), `k`, `domain`,
and format-specific parameters at construction time.

**Agent integration**: Create tool instances, attach to one or more agents via
the `tools` parameter, and CrewAI handles routing. The same `MemoryManager`
instance can be shared across agents in the same crew.

**Note content length**: Recall content is truncated to 500 characters for the
agent view. The full content is always preserved in storage.

**Memory evolution**: `evolve=True` on the remember tool extracts facts via LLM,
compares each against existing notes, and decides ADD/UPDATE/DELETE/NOOP per
fact. This is the same evolution pipeline used by `mm.remember(evolve=True)`.

**Error handling**: All three tools surface errors through their return strings
rather than raising exceptions, matching CrewAI's tool contract.
