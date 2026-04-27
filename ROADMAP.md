# ZettelForge Roadmap

Last updated: 2026-04-25

This document communicates what the maintainer is building, what is on hold, and what is out of scope. It is updated when priorities shift.

---

## Current release: v2.6.1

Shipped: 2026-04-25. See `CHANGELOG.md` for details.

The v2.6 series (RFC-013 through RFC-015) delivered PII detection (Presidio), configurable content size limits, and the Web Management Interface. The v2.5 series (RFC-009 through RFC-012) delivered the enrichment pipeline v2, local LLM backends, and unified provider config.

---

## v2.7.0 targets (next release)

Target: 2026-05-09. Scope is frozen at the items below. Everything else defers to v2.8.0 unless marked **P0**.

### Must ship (P0)

- [ ] **Issue #125: Harden reasoning-model LLM budget plumbing.** Regression tests for `max_tokens` at each call site, config-overridable budgets, `thinking` tag stripping in `json_parse.py`, and a `reasoning_model: bool` auto-scaling flag. Post-#124 follow-up. (Est: 2-3 days)
- [ ] **Issue #73: Tighten CCCS metadata regexes (SEC-6 / SEC-7).** Low hanging security hardening. (Est: 0.5 day)
- [ ] **Issue #72: MemoryManager.remember(sync=True) dominates bulk ingest.** The YARA p95 plyara tail needs a timeout or chunked processing path. (Est: 1 day)

### Nice to have (P1)

- [ ] **Issue #71: Add typed DetectionMeta extension to MemoryNote.Metadata.** Paves the way for richer entity metadata downstream. (Est: 0.5 day)
- [ ] **Issue #51: Ratchet governance coverage threshold from 67% toward 80%.** Incremental. (Est: 1 day)

### Community items (open for contribution)

See the [good first issue](https://github.com/rolandpg/zettelforge/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) label. These are pre-scoped with acceptance criteria:

- #47 — IPv6 address extraction
- #46 — YARA rule reference extraction
- #45 — Sigma rule ID extraction
- #39 — Threat actor alias mappings for Chinese APT groups
- #36 — Architecture decision records (ADRs)
- #44 — Example: MISP JSON feed ingestion
- #43 — Example: Slack bot for CTI queries
- #41 — Example: Jupyter notebook CTI analysis workflow

---

## Next release (v2.7.1+)

Target: approximately 2026-05-23. Provisional scope; will be finalized after v2.7.0 ships.

- [ ] **CrewAI tool wrapper** (#40). Integration path for CrewAI agents to use ZettelForge as a memory backend.
- [ ] **OpenCTI sync overhaul**. Improving the bidirectional sync reliability from the initial implementation.
- [ ] **Detection rules as first-class entities** (#feat/detection-rules-first-class branch). Sigma/YARA rules stored and searchable as knowledge graph nodes.

---

## Backlog / on hold

These are tracked but not actively scheduled:

- **MCP registry publish** (feat/mcp-registry-publish branch). Publishing the MCP server to the official MCP registry.
- **Enterprise split**. Separating the current monolithic package into community + enterprise tiers. Governance, license boundary, and packaging work. Not blocked, but deferred until community adoption justifies the overhead.
- **TypeDB read-path hardening**. Depth routing and schema versioning for the TypeDB backend. Most users run on JSONL/SQLite; TypeDB is a small fraction of the install base.
- **Conversational entity extractor** (stash: feature/RFC-001-conversational-entity-extractor). Interactive refinement of extracted entities by analyst chat. Requires UX thinking and a frontend update.
- **Pydantic v3 upgrade prep** (stash: test-fix/pydantic-v3-prep). Preparing internal models for Pydantic v3 migration. Low urgency; no upstream pressure yet.

---

## Out of scope (not building)

These have been proposed or discussed and explicitly decided against:

- **UI framework migration** (React, Vue, Svelte, etc.). The web GUI is a vanilla JS SPA using the ZettelForge Design System. No npm build step, no JS framework. This is intentional: the SPA must remain maintainable by a solo developer and installable with `pip install zettelforge[web]` without a separate build step. Not changing.
- **Docker containerization**. Deferred to v2.x post-v1.0 per the tech stack decision. The in-process architecture already makes deployment trivial.
- **Cloud-hosted memory backend**. ZettelForge is designed for local-first, air-gapped, and on-prem deployments. A cloud sync layer would compromise the security model and is not on the roadmap.
- **LangChain / LangGraph integration as a default**. Out of scope per the CLAUDE.md rules in this repo. Community wraps are welcome (see the CrewAI issue for how integration should work).

---

## Release cadence

- **Minor releases (v2.x.0)**: roughly every 2-3 weeks, bundling feature work and hardening.
- **Patch releases (v2.x.y)**: as needed for P0 bugs, security fixes, and regressions. No pre-scheduled date.
- **Major releases (v3.0.0+)**: not yet planned. The API is still evolving. A major version bump will come with a public deprecation notice and migration guide.

## Commitment

This roadmap is a best-effort forecast, not a contract. Priorities shift based on user feedback, security findings, and the maintainer's availability (solo maintainer, GOV-006 declared).

Issues tagged with a target release are actively planned. Issues without a release tag are candidates for the next roadmap refresh.

---

[Back to README](README.md)
