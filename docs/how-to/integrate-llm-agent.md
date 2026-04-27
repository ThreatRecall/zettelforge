---
title: "Integrate ZettelForge into an AI Agent"
description: "Connect ZettelForge as an MCP server for Claude Code or integrate with any LLM agent. Persistent CTI memory across sessions with entity extraction and graph retrieval."
diataxis_type: "how-to"
audience: "Agent developers building CTI-aware AI systems, engineers integrating ZettelForge into any LLM agent framework"
tags: [agent-integration, context-injection, proactive-mixin, llm-agent, openclaw, prompt-injection]
last_updated: "2026-04-09"
version: "2.0.0"
---

# Integrate ZettelForge into an AI Agent

Add persistent CTI memory to an AI agent using `MemoryManager` for storage/retrieval, `get_context()` for prompt injection, and `ProactiveAgentMixin` for automatic pre-task context loading.

## Prerequisites

- ZettelForge installed (`pip install zettelforge`)
- An agent framework (or a simple loop)

## Steps

### 1. Import and initialize MemoryManager

```python
from zettelforge.memory_manager import MemoryManager

mm = MemoryManager()
```

### 2. Use `get_context()` for prompt injection

Inject relevant memory context into any LLM prompt:

```python
def build_prompt(user_query: str) -> str:
    # Retrieve relevant context (respects token budget)
    context = mm.get_context(
        query=user_query,
        domain="cti",
        k=10,
        token_budget=4000
    )

    prompt = f"""You are a CTI analyst assistant with access to threat intelligence memory.

## Relevant Context
{context}

## Current Query
{user_query}

Respond using the context above. Cite specific intelligence when possible."""

    return prompt


prompt = build_prompt("What tools does APT28 currently use?")
# Pass `prompt` to your LLM of choice
```

> [!NOTE]
> `get_context()` formats retrieved notes as a string within the `token_budget` limit. It truncates lower-relevance notes to fit, preserving the most relevant context.

### 3. Store agent observations with `remember_with_extraction()`

In your agent loop, store new intelligence as the agent encounters it:

```python
def agent_loop(user_input: str) -> str:
    # 1. Build context-aware prompt
    prompt = build_prompt(user_input)

    # 2. Call LLM (placeholder - use your LLM client)
    response = call_llm(prompt)

    # 3. Store the exchange as memory
    exchange = f"User asked: {user_input}\nAnalysis: {response}"

    results = mm.remember_with_extraction(
        content=exchange,
        domain="cti",
        context=user_input,
        min_importance=3,
        max_facts=5
    )

    stored = [s for _, s in results if s != "noop"]
    if stored:
        print(f"  Stored {len(stored)} new facts from this exchange")

    return response
```

### 4. Use ProactiveAgentMixin for automatic context injection

```python
from zettelforge.context_injection import ProactiveAgentMixin
from zettelforge.memory_manager import MemoryManager


class CTIAgent(ProactiveAgentMixin):
    def __init__(self):
        super().__init__()
        self.mm = MemoryManager()
        self.init_context_injection(
            memory_manager=self.mm,
            auto_inject=True
        )

    def handle_task(self, task_description: str) -> str:
        # Automatically loads relevant context before task
        context = self.before_task(task_description)

        print(f"Task types: {context.get('task_types', [])}")
        print(f"Memory hits: {len(context.get('memory', []))}")
        print(f"Summary: {context.get('summary', '')}")

        # Use inject_into_prompt for full prompt construction
        base_prompt = f"Analyze the following: {task_description}"
        enriched_prompt = self.inject_into_prompt(task_description, base_prompt)

        # Pass enriched_prompt to LLM
        return enriched_prompt


agent = CTIAgent()
result = agent.handle_task("Investigate APT28 activity against NATO infrastructure")
```

> [!TIP]
> `ProactiveAgentMixin` classifies task context automatically. CTI-related keywords (apt, vulnerability, incident, malware) trigger targeted memory retrieval with appropriate domain filtering.

### 5. Build a full agent loop with memory

```python
from zettelforge.memory_manager import MemoryManager
from zettelforge.context_injection import ProactiveAgentMixin


class CTIMemoryAgent(ProactiveAgentMixin):
    def __init__(self):
        super().__init__()
        self.mm = MemoryManager()
        self.init_context_injection(memory_manager=self.mm)

    def run(self, task: str) -> str:
        # Phase 1: Pre-task context injection
        context = self.before_task(task)

        # Phase 2: Build prompt with memory
        memory_context = self.mm.get_context(task, domain="cti", token_budget=4000)

        prompt = f"""## Memory Context
{memory_context}

## Task
{task}

Provide a detailed CTI analysis."""

        # Phase 3: LLM call (replace with your client)
        response = call_llm(prompt)

        # Phase 4: Store results back to memory
        self.mm.remember_with_extraction(
            content=f"Task: {task}\nResult: {response}",
            domain="cti",
            context=task,
            min_importance=4,
            max_facts=3
        )

        return response


def call_llm(prompt: str) -> str:
    """Replace with your LLM client (OpenAI, Anthropic, local, etc.)."""
    from zettelforge.llm import get_llm
    llm = get_llm()
    return llm.generate(prompt)


agent = CTIMemoryAgent()
answer = agent.run("What is Lazarus Group's current toolset and target profile?")
print(answer)
```

### 6. Use entity-specific retrieval in the agent

```python
def enrich_with_entities(task: str) -> dict:
    """Extract entities from task and retrieve targeted context."""
    from zettelforge.entity_indexer import EntityIndexer

    indexer = EntityIndexer()
    entities = indexer.extractor.extract_all(task)

    context = {"actors": [], "tools": [], "cves": []}

    for actor in entities.get("actor", []):
        notes = mm.recall_actor(actor, k=3)
        context["actors"].extend([n.content.raw[:200] for n in notes])

    for tool in entities.get("tool", []):
        notes = mm.recall_tool(tool, k=3)
        context["tools"].extend([n.content.raw[:200] for n in notes])

    for cve in entities.get("cve", []):
        notes = mm.recall_cve(cve, k=3)
        context["cves"].extend([n.content.raw[:200] for n in notes])

    return context
```

> [!WARNING]
> `remember_with_extraction()` makes LLM calls for each extracted fact. In high-throughput agent loops, set `min_importance=5` and `max_facts=3` to limit LLM round-trips. Use `remember()` (no extraction) for raw storage when speed matters.

## LLM Quick Reference

**Task**: Integrate ZettelForge persistent memory into an AI agent loop.

**Prompt injection**: `mm.get_context(query, domain="cti", k=10, token_budget=4000)` returns formatted relevant notes. Inject into system or user prompt.

**Agent storage**: `mm.remember_with_extraction(content, domain="cti", context="...", min_importance=3, max_facts=5)` extracts and deduplicates facts. Returns `List[Tuple[Optional[MemoryNote], str]]`.

**ProactiveAgentMixin**: Inherit and call `init_context_injection(memory_manager=mm)`. Use `before_task(description)` for context retrieval, `inject_into_prompt(task, base_prompt)` for enrichment.

**Entity retrieval**: `mm.recall_actor()`, `mm.recall_tool()`, `mm.recall_cve()` provide O(1) indexed lookups for targeted enrichment.

**LLM provider options**: Configure via `config.yaml` `llm:` section. The default is `provider: ollama` with `model: qwen3.5:9b`. Optional extras: `pip install zettelforge[local]` for in-process GGUF inference, `pip install zettelforge[local-onnx]` for ONNX inference, `pip install zettelforge[litellm]` for LiteLLM routing to 100+ cloud providers.

**Performance**: `remember()` is fast (no LLM). `remember_with_extraction()` is slow (LLM per fact). `get_context()` is fast (vector search). Tune `min_importance` and `max_facts` for throughput.
