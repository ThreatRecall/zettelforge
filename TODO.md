# ZettelForge growth backlog

Last updated: 2026-04-28 (session: verify TODO → docs, README polish, examples E1+E3, code review skill)
Companion to: `ROADMAP.md` (engineering ordering), `CHANGELOG.md` (shipped), `docs/marketing/awesome-list-submissions.md` (D4 ready-to-paste drafts)
Goal: GitHub star growth as the leading indicator of category fit.

## Status

v2.6.2 shipped 2026-04-27 via PR #135 and is live on PyPI. Same day: added `/api/config/meta` (single source of truth for restart-required fields), completed the WAI-ARIA tabs pattern on `/config`, and resolved 6 Copilot review threads plus 2 CodeQL findings inline. 31 web-API tests pass, 2 SSE skipped.

Then in the growth-backlog execution window (2026-04-27 through 2026-04-28):

- **All 15 documentation gaps closed.** 8 how-to guides + 8 reference docs + mkdocs.yml nav resorted. See PR #138 (merged). Covers: MCP server, Sigma/YARA ingestion, detection rules, extensions, editions, CrewAI/LangChain integration, LanceDB maintenance, KG edge schema, entity indexer concurrency.
- **All 4 README polish items shipped.** R1 (no-LLM hello world), R2 (star history badge), R3 (v2.6.2 callout), R4 (MCP quickstart for Claude Desktop). PR #140 merged.
- **E4 done.** CrewAI integration shipped on `Unreleased` in CHANGELOG. PR #136 merged.
- **E1 and E3 done.** MISP JSON feed ingest (issue #44) and Jupyter notebook CTI analysis workflow (issue #41). PR #140 merged.
- **Code review skill created.** Hermes skill at `.hermes/skills/high-fidelity-code-review/` — 5-stage Python refactoring pipeline (static analysis, profiler integration, heuristic orchestration, verification subagents, empirical benchmarking). Stdlib-only, produces approval/reject decision.
- **D4 drafted.** Submission text and PR bodies for all four awesome-lists are in `docs/marketing/awesome-list-submissions.md`.

Repo metrics on 2026-04-27: 32 stars, 5 forks, 14 open issues, GitHub Discussions enabled, 20 topics tagged. Engineering maturity (CI matrix, security scanners, governance gating, Trusted Publishing on PyPI) is past where star count would predict, which means distribution is the binding constraint, not the product.

## Star-growth thesis

Stars come from three audiences that already trust the category. Distribution into those audiences, not feature work, is the highest-ROI lever right now.

1. CTI ops audience: TheDFIRReport readers, MISP users, SOC engineers, threat hunters.
2. AI engineering audience: r/LocalLLaMA, Hacker News, Latent Space, AI Eng newsletter.
3. MCP audience: Claude Desktop users, MCP server registry browsers, Anthropic dev rel orbit.

The product positioning (offline-first agentic memory for CTI, with STIX 2.1 and Claude Code MCP) hits all three wedges. The README and comparison table already do the differentiation work. The missing piece is getting people there.

---

## Priority 1: distribution (Patrick must do)

These move 50 to 500 new eyeballs onto the README per drop. Engineering cannot substitute.

### D1. Show HN launch
Title draft: "Show HN: ZettelForge, agentic memory for cyber threat intelligence (offline, MCP)"
Pre-reqs: G2 (30-second hello world that does not require Ollama), V1 (refreshed demo GIF).
Timing: Tuesday 8 to 10am ET for the upvote window.
Owner: Patrick.

### D2. r/LocalLLaMA submission
Wedge: offline-first hits the LocalLLaMA value prop directly.
Title draft: "I built an offline agent memory system, STIX knowledge graph plus MCP server, no cloud."
Top-level comment with technical detail on the Ollama backend, fastembed, SQLite, LanceDB.
Owner: Patrick.

### D3. CTI subreddit cross-post
r/cybersecurity, r/blueteamsec, r/threatintel.
Reframe from "AI tool" to "context retention for SOC turnover". Use the senior-analyst-departure framing already in the README.
Owner: Patrick.

### D4. Awesome-list PRs (Claude drafted, Patrick submits)
Submission text, PR titles, and PR bodies are in `docs/marketing/awesome-list-submissions.md` for all four target lists:

- punkpeye/awesome-mcp-servers (highest ROI; MCP audience)
- hslatman/awesome-threat-intelligence (CTI audience)
- frutik/awesome-rag (RAG/agentic memory audience)
- Shubhamsaboo/awesome-llm-apps (LLM-app builder audience)

Each PR is a one-line addition. Submission tactics, secondary targets, and outcome-tracking template all live in the marketing doc.
Pre-flight: complete R1 (no-Ollama hello-world) and V1 (refresh demo gif) first so the maintainer's `pip install` test succeeds.
Owner: Patrick to submit. Status tracking lives in `docs/marketing/awesome-list-submissions.md`.

### D5. CTI Twitter and LinkedIn
Pin a thread on the SOC turnover problem leading to the MCP demo. Engage in TheDFIRReport, Mandiant, CrowdStrike report posts where ZettelForge would have helped.
Owner: Patrick.

---

## Priority 2: demo content (Claude can prep, Patrick records)

A 60-second video in the Show HN top comment roughly triples star conversion vs. text alone.

### V1. Refresh `docs/assets/demo.gif`
The current GIF predates v2.6.0 and does not show the management SPA or the working `/config` editor. Recapture: search, recall, synthesize, then config dropdown change with apply confirmation.
Owner: Claude can produce the script and run it against the local server; Patrick records.

### V2. 60-second Loom walkthrough
Storyboard: ingest MITRE ATT&CK JSON, ingest a recent TheDFIRReport writeup, then in Claude Desktop ask "what TTPs did APT28 use in 2025?". Show the MCP citation back to the ingested notes.
Embed in README, drop in HN top comment, post to LinkedIn.
Owner: Claude drafts the script and the ingest commands; Patrick records.

---

## Priority 3: working examples (Claude can build)

Each example doubles as a star magnet because it surfaces a concrete use case and reads as social proof. All four are already filed as good-first-issues with acceptance criteria.

### E1. MISP JSON feed ingest (#44) — DONE 2026-04-28
Path: `examples/ingest_misp.py`.
Pitch in README examples table: "Drop a MISP JSON feed into ZettelForge and have your team query it in Claude Desktop." Every CTI ops team already runs MISP.
PR #140 merged at 649b4c5. 467 lines, 17 entity mapping test cases, companion sample data at `examples/sample_misp_event.json`.

### E2. Slack bot for CTI queries (#43)
Path: `examples/slack_cti_bot.py`.
Pitch: "Every team uses Slack. This is ZettelForge in your team chat." Reaches teams that will not adopt a new CLI but will adopt a Slack bot.

### E3. Jupyter notebook CTI analysis workflow (#41) — DONE 2026-04-28
Path: `examples/cti_analysis.ipynb`.
Pitch: analyst-native medium, screenshottable, embeddable in blog posts.
PR #140 merged at 649b4c5. 22 cells (9 markdown + 13 code), validated by `jupyter nbconvert --execute`.

### E4. CrewAI tool wrapper (#40) — MERGED 2026-04-27
PR #136 merged at d119c95. Issue #40 closed.

Three tools (recall, remember, synthesize) at `src/zettelforge/integrations/crewai.py`, optional extra `pip install zettelforge[crewai]`, runnable example at `examples/crewai_cti_crew.py`. Final shape: 14 tests pass against crewai 1.14.x (was 11 before review-fix push). Codex caught a real bug during review — the synthesis formatter was reading the wrong nesting level on `MemoryManager.synthesize()` and would have always returned "(no answer)" in production. Tests rewritten to use the actual wrapper shape so the bug can't reappear silently. Logged under `[Unreleased]` in CHANGELOG, will roll into v2.7.0.

Follow-ups now unblocked:

- README Integrations section: add CrewAI bullet alongside LangChain.
- After v2.7.0 ships, drop a brief "ZettelForge as CrewAI memory" post in the CrewAI Discord and on r/LocalLLaMA. Single example, before/after screenshot.
- New integration is now a talking point in Show HN (D1) and the r/LocalLLaMA submission (D2).

Order to build remaining examples: E1 (MISP), E3 (Jupyter), E2 (Slack), by audience size and shareability.

---

## Priority 4: README polish (Claude can do)

### R1. Hello world that does not require Ollama — DONE (PR #140)
Quick Start split into a 30-second no-LLM block (`remember()` + `recall()` with verified working output) and a separate "Add an LLM for synthesis" block. Uses `ZETTELFORGE_LLM_PROVIDER=mock` and `ZETTELFORGE_EMBEDDING_PROVIDER=mock`.

### R2. Star history badge — DONE (PR #140)
Inline `<api.star-history.com/svg>` badge added to the badge row. Links to the star-history.com timeline.

### R3. "What's new in v2.6.2" callout above the fold — DONE (PR #140)
Blockquote between the value-prop block and the demo gif. Links to examples and changelog.

### R4. MCP quickstart section — DONE (PR #140)
Standalone "Use ZettelForge in Claude Desktop in 60 seconds" section with `.claude.json` config snippets, references to `docs/how-to/set-up-mcp-server.md`.

### R5. Suppress litellm provider-list stderr noise on `recall()` — IN REVIEW (PR #142)
Discovered while verifying R1: `recall()` triggers ~40 stderr prints of `Provider List: https://docs.litellm.ai/docs/providers` whenever the configured model lacks a recognised litellm provider prefix (background LLM-NER hits the litellm path). The banner bypasses Python logging via raw `print()`, so structlog can't intercept it. PR #142 routes the lazy `litellm` import through a `_get_litellm()` helper that sets `litellm.suppress_debug_info = True` after import — litellm's documented escape hatch. Verified end-to-end with an fd-2-capturing harness: zero "Provider List" bytes leak through after the fix. 12 LiteLLMProvider tests pass (was 11 + new `test_generate_silences_litellm_debug_banner` regression guard).

---

## Priority 5: engineering follow-ups (Claude can do)

These do not drive stars directly. They unblock the v2.7.0 release, which itself becomes another launch moment (D1 has a sequel: "Show HN: ZettelForge v2.7 with reasoning-model autoscaling and ...").

Refer to `ROADMAP.md` for ordering and effort estimates. P0 items for v2.7.0:

- Issue #125: harden reasoning-model LLM budget plumbing (post-#124 follow-ups, four items: regression tests for `max_tokens` per call site, config-overridable budgets, `<think>` tag stripping in `json_parse.py`, `reasoning_model: bool` autoscale flag).
- Issue #73: tighten CCCS metadata regexes (SEC-6 / SEC-7).
- Issue #72: bulk-ingest path dominated by `remember(sync=True)` and YARA p95 plyara tail.

P1 / nice to have for v2.7.0:

- Issue #71: typed `DetectionMeta` extension to `MemoryNote.Metadata`.
- Issue #51: ratchet governance coverage from 67% toward 80%.

Bigger arc, deferred (each tracked individually below in the RFC backlog).
- RFC-006 (synthesis benchmark) and RFC-008 (extraction benchmark) are DRAFT and pair with RFC-002b. Useful before the cascade lands so we can measure it.

---

## Out of scope for star growth

- UI framework migration. Out of scope per ROADMAP.
- Docker. Deferred per tech stack decision.
- Cloud backend. Conflicts with the offline-first wedge that defines the product.
- Net-new features for their own sake. The product surface is past the point where new capabilities move the star number on their own.

---

## Verification (30-day check after Show HN)

- Stars: target +50 in the 30 days following Show HN.
- Awesome-list PR merges: 3 of 4 submitted.
- Example PRs landed: 3 of 4 (E4 CrewAI, E1 MISP, E3 Jupyter ✅; E2 Slack pending).
- v2.7.0 shipped with a launch post by 2026-05-09 per ROADMAP.

---

## RFC backlog (post-2026-04-27 review)

Triage outcome from the Software Architect (cascade-synthesis arc) and Model QA Specialist (benchmark protocols) reviews on 2026-04-27. Each item below tracks one held DRAFT and the specific blocking edits required before it can land. Sequencing matters: 002a → 006 → 008 → 002b, with the FT artifact as a soft dependency for 006/008.

### RFC-002 (cascading synthesis, original) — DELETED 2026-04-27
PR #139 deletes the superseded original to resolve a number collision with the shipped `RFC-002-universal-llm-provider.md`. Supersession trail preserved in 002a/002b headers and in git history. No follow-up needed.

### RFC-002a (retrieval plumbing) — MERGED 2026-04-28 (PR #139 → 59fd778)
Refreshed against v2.6.2 and landed as DRAFT. Five blocking edits applied: target version 2.7.1, Prerequisite 2 stubbed (VulnerabilityMeta shipped under RFC-009), file/line refs re-verified, 7B FT footnote tightened, RFC-003 overlap noted in Dependencies. Minor editorial tightening landed during merge (Prerequisite 1 example keys, MITRE data reference). This is now the canonical reference for the four remaining prerequisites (retrieval policy, MITRE/CVE validators, 9B normalization, prompt-chain harness).

Implementation work for RFC-002a is now unblocked but not in v2.7.0 scope. Sequence after v2.7.0 ships and RFC-003 overlap is resolved.

### RFC-002b (cascading synthesis, revised) — HELD as DRAFT
Status: untracked in working tree. Hard-blocked by RFC-002a. Soft-blocked by:

- Cascade spike must actually run (`benchmarks/cascade_spike.py` exists, results don't). Every latency cell is "TBD" until the spike produces real numbers against the chosen backend.
- Bump target version 2.5.0-proposed → v2.8.0+ (realistic given v2.7.0 freeze and 002a sequencing).
- Reconcile model baseline language if the in-flight 7B FT lands first.
- Verify "Claude Haiku 4.5" identifier against the in-tree spike script before publishing.

Land after RFC-002a is ACCEPTED and the spike has produced real exit-criteria data.

### RFC-006 (synthesis benchmark v3.4) — HELD pending edits
Status: untracked in working tree. Methodology verified by Model QA: N=100, threshold 0.62, Wilson 95% LCB = 0.5221 (clears 0.50 with margin). Seven rounds of adversarial review hold up. Blocking edits before it lands as DRAFT:

1. Fix §1.4: extraction has THREE write-path LLM call sites (`fact_extractor.py`, `memory_updater.py`, `note_constructor.py`), not one. Either expand the SUT list or explicitly carve `memory_updater` and `note_constructor` out of scope.
2. Renumber the future RFC references in §1.4. RFC-007 (operational telemetry) and RFC-009 (enrichment pipeline v2) are already taken; reserve fresh numbers (likely RFC-016 / RFC-017).
3. Add explicit dependency on the in-flight 7B FT artifact: Phase 0 cannot start until the FT is delivered with a frozen revision hash.
4. Pin the unified provider config (RFC-012) layer in env_manifest discussion (currently silent).
5. Add a one-line disclaimer that existing `benchmarks/*.py` scripts (`cti_mem_benchmark.py`, `retrieval_accuracy.py`, etc.) are independent of this protocol so readers don't assume they're the implementation.
6. Inline the three diagrams from `rfc-006-diagrams.md` directly into RFC-006 (see next item).

Do NOT promote to ACCEPTED until the FT artifact lands. Accepting a benchmark protocol whose subject doesn't exist invites silent scope creep.

### RFC-008 (extraction benchmark v1) — HELD pending RFC-006 Phase 0
Status: untracked in working tree. Inherits per-query variance, prompt-token buckets, and prefill-mode numbers from RFC-006 Phase 0; cannot land independently. Blocking edits:

1. Resolve the same 3-call-site SUT scope question RFC-006 has (apply the answer symmetrically).
2. Add a κ power calculation for Gate 4 (importance calibration κ ≥ 0.6 with LCB ≥ 0.55). At N=100 narratives × ~5 jointly-extracted facts each, the κ CI width is non-trivial. State bootstrap iteration count.
3. Re-justify the ±3pp hallucination non-regression margin against extraction-task variance, not synthesis-task variance (the margin was inherited from RFC-006 for a different metric).
4. State the FT-delivery dependency explicitly.
5. Resolve §6 Open Question 1 (negation handling) before annotator labeling starts. Answering it after labeling means re-labeling.

Land after RFC-006 has produced Phase 0 variance numbers.

### rfc-006-diagrams (visual companion) — DELETE on RFC-006 land
Status: untracked in working tree. Recommendation: inline the three diagrams into RFC-006 itself; delete this file. Standalone diagram doc adds drift risk — references stale v3.2 PNG/SVG renderings (`rfc006flowchart.png`, `rfc006sequence.png`) that need either deletion or regeneration. Same 3-call-site scope bug as RFC-006 §1.4. If kept separate against this advice, the PNG/SVG regeneration must be a tracked GitHub issue, not just a doc paragraph.

### Cross-cutting RFC dependencies

- **RFC-003 (Read-Path Depth Routing) overlap with RFC-002a** — both touch the retrieval pipeline. Sequence-decision needed before either advances. Recommendation: land RFC-002a's `RetrievalPolicy` first; have RFC-003 consume it as the policy carrier for depth routing.
- **In-flight 7B FT artifact** — soft dependency for RFC-002a Prerequisite 4 (just changes the default value), hard dependency for RFC-006/008 ACCEPTED status. Track in `memory/project_finetune_7b.md`.
- **v2.7.0 freeze** — none of these RFCs target v2.7.0. RFC-002a → v2.7.1; RFC-006/008 → after FT lands; RFC-002b → v2.8.0+.

---

# Appendix A: UI/UX 50-point backlog (from v2.6.2 evaluation)

The content below is the original UI/UX backlog Nexus produced when evaluating the v2.6.2 web interface against a 50-point checklist. Many items remain valid follow-ups for a future UI polish sweep, but they are not on the critical path for star growth and are recorded here for reference, not as P1 work.

**Evaluated against:** DM Letter Studio 50-point UI/UX checklist
**Screened by:** Nexus (AI Infrastructure Researcher, Roland Fleet)
**Date:** 2026-04-27
**Live server:** `http://localhost:8088` (v2.6.2 confirmed running)
**Overall score:** 34/50 across 8 categories

## Scorecard

| Category | Score | Priority |
|---|---|---|
| Goals & User Flows | 6/8 | Medium |
| Information Architecture | 5/7 | Medium |
| Layout & Visual Hierarchy | 4/6 | Low |
| Components & Design System | 4/7 | Medium |
| Accessibility | 3/8 | High |
| Microcopy & UX Writing | 5/7 | Medium |
| Forms & Input Validation | 4/7 | Medium |
| Loading / Empty / Error States | 3/5 | High |

## Priority 1: Accessibility (critical)

### A1. Add `<label>` element to search input
**File:** `web/ui/js/views/search.js`
**Checklist reference:** WCAG 2.1 SC 2.5.3 (label in name) fails because placeholder is sole label.
**Fix:** Add a visually hidden `<label for="search-input">Search threat intelligence</label>` before the input. The placeholder text is insufficient as a label for screen readers and keyboard-only users.
**Effort:** ~3 lines of HTML. No CSS changes needed.

### A2. Keyboard focus indicators on all interactive elements
**File:** `web/ui/colors_and_type.css` (or add to `app.js` styles)
**Checklist reference:** Focus states visible for keyboard users.
**Fix:** Add `:focus-visible` outline rings to:
- Sidebar nav items (`.sidebar-item`)
- Format selector pills
- Action buttons (compact, reload)
- All form inputs in config view

**Current state:** Only search input has focus ring. Sidebar, pills, buttons are keyboard-dead.
**Effort:** ~20 lines of CSS. No structural changes.

### A3. Color not sole signal for errors
**Files:** `web/ui/js/components/toast.js`, `web/ui/js/views/search.js`
**Checklist reference:** Color not the only signal.
**Fix:** Add icon prefix to error toasts and ensure error backgrounds have sufficient contrast beyond red-tinting. Audit all error states in config view and search view for text/background contrast.

## Priority 2: Loading / empty / error states (critical)

### E1. Empty result state for zero-match searches
**File:** `web/ui/js/views/search.js`
**Current state:** No rendering path for `results.length === 0`. User sees blank white area, indistinguishable from mid-load state.
**Fix:** Add an else branch in `renderResults()`:
```javascript
if (results.length === 0 && !this._state.loading) {
  var empty = document.createElement('div');
  empty.style.cssText = 'text-align:center;padding:var(--sp-8);color:var(--fg-2,#8B949E);';
  empty.innerHTML = '<p>No results for your query.</p><p>Try different keywords or broaden your search.</p>';
  block.appendChild(empty);
}
```
**Effort:** ~10 lines. High impact.

### E2. Progress stage label for synthesis operations
**File:** `web/ui/js/views/search.js`
**Current state:** Pulsing dot plus "Loading...", no stage, no ETA.
**Fix:** Update status to include stage during the request. Add static helper text above the search bar: "Tip: Synthesis queries may take 5 to 30 seconds depending on knowledge graph size".

### E3. Persistent error banner for failed searches
**File:** `web/ui/js/views/search.js`
**Current state:** Toast-based errors auto-dismiss; user may miss them.
**Fix:** On search error, render a persistent error card above results (not just toast). Include error message, retry button, link to docs. Cleared on next successful search.

## Priority 3: microcopy and UX writing

### M1. Explain Recall vs Synthesize mode
**File:** `web/ui/js/views/search.js`
**Fix:** Add inline help text below the mode toggle: "Recall: fast graph lookup. Synthesize: LLM-generated summary." Effort: ~3 lines.

### M2. Helpful error messages with action guidance
**File:** `web/ui/js/lib/api.js` (or error handler in views)
**Fix:** Map error codes to instructive copy:
- "Network error" to "Connection failed. Check your network and try again."
- HTTP 422 to "Invalid query. Try different keywords or simplify your question."
- HTTP 503 to "Service temporarily unavailable. Retry in a few seconds."

### M3. Placeholder text improvements
**File:** `web/ui/js/views/search.js`
**Add:** A "recent searches" hint when `_state.query === ''` to guide first-time users toward useful queries.

## Priority 4: forms and input validation

### F1. Client-side validation before config submit
**File:** `web/ui/js/views/configuration.js`
**Current state:** No pre-submission validation. User submits invalid numeric value, waits for server round-trip, gets error toast.
**Fix:** Add validation handlers for known numeric fields:
- `llm.timeout` must be positive number, max 300
- `llm.max_retries` must be 0 to 5 integer
- `retrieval.default_k` must be 1 to 100
- `governance.limits.max_content_length` must be positive

Visual feedback: red border plus inline error text below field on invalid. Green border on valid.

### F2. Required field visual markers on config form
**File:** `web/ui/js/views/configuration.js`
**Verify:** Check all sections (LLM, Embedding, Governance) have consistent `*` marking. Audit all enum fields in `ENUMS` object for completeness.

## Priority 5: information architecture

### I1. URL hinting in sidebar
**File:** `web/ui/js/components/sidebar.js`
**Fix:** On hover, show tooltip with URL path (e.g., `/#/search`). Low effort, aids power users.

### I2. Sort controls on search results
**File:** `web/ui/js/views/search.js`
**Fix:** Add sort dropdown above results: "Sort by: Relevance (default), Date (newest), Entity count". Apply to both recall and synthesize result sets.

### I3. Confirmation toast after search completes successfully
**File:** `web/ui/js/views/search.js`
**Fix:** On successful search completion, briefly flash a green toast: "Synthesis complete, {n} sources" with auto-dismiss after 3s. Especially important since synthesis takes several seconds.

## Priority 6: components and design system

### C1. Disabled state styling
**File:** `web/ui/colors_and_type.css`
**Current state:** No `disabled` attribute styling anywhere in CSS.
**Fix:**
```css
button:disabled, input:disabled, select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}
```

### C2. Loading spinner vs pulsing dot, standardize
**Files:** `web/ui/js/components/spinner.js`, `web/ui/js/views/search.js`
**Fix:** Use `SpinnerComponent.render()` consistently across all views. Replace inline pulse animations in `search.js` and `dashboard.js` with the shared component.

## Priority 7: goals and user flows

### G1. Add progress indicator to multi-step flows
**File:** `web/ui/js/views/search.js`
**Fix:** If the backend supports staged responses (extract, retrieve, synthesize), surface those stages in the UI. At minimum, add a progress label as described in E2.

### G2. "No dead ends" audit
**File:** All views.
**Exception:** Error state in config view (backend rejection) has no "back to safe state" path. User is stuck with red-tinted form. Add a "Discard changes" button when form is dirty.

## Priority 8: layout and visual hierarchy (low effort)

### L1. Conflict between primary CTA and secondary actions
**File:** `web/ui/js/views/search.js`
**Fix:** Make format pills visually subordinate (smaller font, lower contrast when inactive) so the green Search button dominates.

### L2. Line length on wide monitors
**File:** `web/ui/colors_and_type.css`
**Check:** Results cards and knowledge graph can stretch wider than 960px on large monitors. Verify readability of paragraph content at wide widths, or enforce max-width on synthesis text output.

## UI/UX verification checklist

Before each release, run through:

- [ ] Search input has `<label>` (A1)
- [ ] Tab through all interactive elements, focus ring visible on each (A2)
- [ ] Empty search returns designed empty state, not blank container (E1)
- [ ] Search for nonexistent term (e.g., `xyzabc123nonexistent`) returns empty state
- [ ] Synthesis query over 3s shows stage label, not just "Loading..."
- [ ] Network error returns instructive toast, not "Network error" alone (M2)
- [ ] Config form: submit `timeout = "abc"` shows inline validation error before submit (F1)
- [ ] Disabled button is visible but dimmed (C1)
- [ ] No console errors in browser

---

*Growth section: drafted by Claude Code on 2026-04-27 in collaboration with Patrick.*
*UI/UX section: generated by Nexus (Roland Fleet) on 2026-04-27, framework: DM Letter Studio UI/UX Design Checklist (50-point).*
