# Awesome-list submission drafts

Ready-to-paste entries for the four highest-ROI awesome-lists ZettelForge belongs on. Each entry follows the target list's existing format conventions. Open one PR per list, link them all back here.

Companion to: `TODO.md` D4.

## Submission summary

| List | Repo | Section | Status |
|---|---|---|---|
| 1. MCP servers | punkpeye/awesome-mcp-servers | Other tools and integrations / Knowledge & Memory | Draft below |
| 2. Threat intelligence | hslatman/awesome-threat-intelligence | Tools / Frameworks | Draft below |
| 3. RAG | frutik/awesome-rag | Frameworks / Open Source | Draft below |
| 4. LLM apps | Shubhamsaboo/awesome-llm-apps | RAG Apps / Agent Memory | Draft below |

Pre-flight checklist before submitting:

- [ ] README's "30-second hello world" works without Ollama (TODO R1). Reviewers click `pip install` and try it. If it fails, the PR stalls.
- [ ] Demo gif on README is current (TODO V1). Outdated screenshots get flagged.
- [ ] PyPI version matches GitHub master (it does at v2.6.2).

---

## 1. punkpeye/awesome-mcp-servers

**URL:** https://github.com/punkpeye/awesome-mcp-servers
**Why this list:** highest-traffic MCP discovery surface; Anthropic dev rel and Claude Desktop users browse it for new servers.
**Section to add to:** "Knowledge & Memory" subsection if it exists, otherwise "Search & Data Extraction" or "Other Tools and Integrations". Verify before opening the PR — section names shift.
**Entry format:** the list uses one-line markdown bullets with emoji legend prefixes for language and platform.

### Entry to paste

```markdown
- [rolandpg/zettelforge](https://github.com/rolandpg/zettelforge) 🐍 🏠 - Agentic memory for cyber threat intelligence. STIX 2.1 knowledge graph, threat-actor alias resolution, intent-classified retrieval, runs in-process with no cloud dependency.
```

Legend the list uses (verify against current README): 🐍 Python, 🏠 self-hosted, ☁️ cloud, 📇 keyword/symbolic. We are 🐍 + 🏠.

### PR title

```
Add ZettelForge - agentic memory for CTI (Python, self-hosted)
```

### PR body

```markdown
Adding [ZettelForge](https://github.com/rolandpg/zettelforge), a Python MCP server for cyber threat intelligence memory.

What it does for MCP users:
- Persists CTI findings (CVEs, threat actors, ATT&CK techniques, IOCs) across Claude Desktop sessions.
- Resolves threat-actor aliases (APT28 = Fancy Bear = STRONTIUM = Sofacy) so questions land on the right entity.
- Returns notes ranked by blended vector + graph relevance.
- Runs in-process, no cloud dependency, no external API key required.

Install: `pip install zettelforge`
Docs: https://docs.threatrecall.ai
PyPI: https://pypi.org/project/zettelforge/

Happy to adjust the section or wording to match list conventions.
```

---

## 2. hslatman/awesome-threat-intelligence

**URL:** https://github.com/hslatman/awesome-threat-intelligence
**Why this list:** the canonical CTI tooling reference. SOC engineers, threat hunters, and intel analysts use it as a start-here index.
**Section to add to:** Look for a "Frameworks" or "Tools" or "Platforms" section. Likely fit: "Frameworks" subsection. If a "Memory / Knowledge Management" subsection exists, prefer that.
**Entry format:** descriptive bullet, links and short prose.

### Entry to paste

```markdown
- [ZettelForge](https://github.com/rolandpg/zettelforge) - Agentic memory system built specifically for cyber threat intelligence. Auto-extracts CVEs, threat actors, IOCs, and ATT&CK techniques from analyst notes and reports, resolves threat-actor aliases across naming conventions, and builds a STIX 2.1 knowledge graph with causal triples. Offline-first, in-process Python, and exposes an MCP server for Claude Code. Designed to retain SOC institutional context across analyst turnover.
```

### PR title

```
Add ZettelForge - agentic CTI memory with STIX 2.1 knowledge graph
```

### PR body

```markdown
Adding [ZettelForge](https://github.com/rolandpg/zettelforge) under Tools/Frameworks (open to suggestion on the right section).

Why it fits this list:
- CTI-specific entity extraction (CVEs, threat actors, IOCs, ATT&CK technique IDs)
- Threat-actor alias resolution (APT28/Fancy Bear/STRONTIUM/Sofacy)
- STIX 2.1 ontology
- Audit logs in OCSF schema
- Intent-classified retrieval (5 intent types)
- Offline-first, in-process Python, no cloud
- MCP server for Claude Code

Apache-licensed predecessor work was MIT for ZettelForge proper. Active development, currently at v2.6.2.

Install: `pip install zettelforge`
Docs: https://docs.threatrecall.ai
```

---

## 3. frutik/awesome-rag

**URL:** https://github.com/frutik/awesome-rag
**Why this list:** RAG-centric audience overlaps heavily with the "agentic memory" search intent that brings people to ZettelForge.
**Section to add to:** "Frameworks", "Tools", or "Memory" subsection. Verify before submission. If there is no memory subsection, propose adding one in the PR.
**Entry format:** check if the list uses a table or a bullet list; format below assumes bullets.

### Entry to paste

```markdown
- [ZettelForge](https://github.com/rolandpg/zettelforge) - Agentic memory and RAG framework specialized for cyber threat intelligence. Domain-aware extraction (CVEs, threat actors, ATT&CK, IOCs) feeds a STIX 2.1 knowledge graph with causal triples, and retrieval blends vector + graph + intent classification. Offline-first, in-process Python (FastEmbed + LanceDB + SQLite), with optional Ollama LLM backend. MCP server included.
```

### PR title

```
Add ZettelForge - agentic memory + RAG for cyber threat intelligence
```

### PR body

```markdown
Adding [ZettelForge](https://github.com/rolandpg/zettelforge), an agentic memory + RAG framework focused on cyber threat intelligence.

Differentiators vs. general-purpose RAG:
- Domain-specific entity extraction (CVE IDs, threat actor names, ATT&CK technique IDs, IOCs) instead of relying purely on chunk embeddings
- Knowledge graph with causal triples ("APT28 used CVE-2024-3094 against target X")
- Intent classification on the query side (5 intent types) routes retrieval differently per question type
- Offline-first: ships with FastEmbed (in-process ONNX), SQLite, LanceDB; Ollama backend for the LLM is optional and can be swapped for any provider
- MCP server for Claude Code / Claude Desktop integration

Open to feedback on section placement.

Install: `pip install zettelforge`
PyPI: https://pypi.org/project/zettelforge/
```

---

## 4. Shubhamsaboo/awesome-llm-apps

**URL:** https://github.com/Shubhamsaboo/awesome-llm-apps
**Why this list:** LLM-app builder audience, very active community, excellent inbound for "I'm building an agent and need memory" searches.
**Section to add to:** "RAG Apps" or "Agent Memory" or "Knowledge Bases". This list groups by concrete app category. If a "Memory" or "Agentic Memory" section doesn't exist, propose it in the PR (the list maintainer is responsive to good additions).
**Entry format:** the list uses bold name, then short prose, then optional sub-bullets for tech stack.

### Entry to paste

```markdown
### ZettelForge - agentic memory for cyber threat intelligence
**[rolandpg/zettelforge](https://github.com/rolandpg/zettelforge)** - Domain-specific agentic memory built for CTI workflows. Auto-extracts CVEs, threat actors, IOCs, and ATT&CK techniques into a STIX 2.1 knowledge graph; resolves threat-actor aliases; retrieves with blended vector + graph search. Drop-in CrewAI and LangChain integrations, plus an MCP server for Claude Desktop. Runs entirely in-process - no cloud dependency, no external API key required.

- **Stack:** Python 3.10+, FastEmbed, LanceDB, SQLite, optional Ollama for LLM
- **Integrations:** CrewAI tools, LangChain retriever, MCP server, OpenCTI sync
- **Install:** `pip install zettelforge`
```

### PR title

```
Add ZettelForge - agentic memory for cyber threat intelligence
```

### PR body

```markdown
Adding [ZettelForge](https://github.com/rolandpg/zettelforge) under RAG Apps / Agent Memory (open to a different placement).

What makes it interesting for this list:
- Specific use case (CTI memory) with concrete extraction logic, not just chunk embeddings
- Drop-in CrewAI tools (`zettelforge.integrations.crewai`) and a LangChain `BaseRetriever` (`zettelforge.integrations.langchain_retriever`)
- MCP server for Claude Desktop
- All offline-capable, no cloud dependency

If you'd consider adding an "Agent Memory" section, ZettelForge would fit alongside Mem0/Letta/Zep with the angle of "CTI-domain-specific memory."

Install: `pip install zettelforge`
PyPI: https://pypi.org/project/zettelforge/
Docs: https://docs.threatrecall.ai
```

---

## Submission tactics

1. Open all four PRs in the same week so the merges (when they happen) cluster as inbound traffic on similar dates rather than spreading thin.
2. Wait 48 hours after each PR for maintainer reaction. If a maintainer asks for changes, address quickly while the PR is still in their attention queue.
3. If a maintainer rejects citing scope, do not argue. Move to the secondary target.
4. Track outcomes in this file by appending a "Status" column to the table at the top:

| List | Repo | PR | Merged | Stars from list (30d) |
|---|---|---|---|---|

## Secondary targets (if any of the above rejects)

- MCP: wong2/awesome-mcp-servers
- CTI: correlatedsecurity/Awesome-Threat-Intelligence-Reports (different angle: report aggregation, but maintainer may host adjacent tools)
- RAG: NirDiamant/RAG_Techniques (techniques-focused rather than tools, but high-traffic)
- LLM apps: Hannibal046/Awesome-LLM (broader scope)

## What to do once a PR merges

1. Note the merge date and PR URL in the status table above.
2. Drop a brief mention in the next dev log / release post (cross-link gives the awesome list a small reciprocal benefit).
3. If 30-day star delta from the list is measurable (PyPI download spikes correlate with star spikes; you can also use star-history.com), feed that signal back into the TODO growth thesis.
