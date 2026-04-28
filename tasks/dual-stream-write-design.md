# Dual-Stream Write Path — Design & Analysis

**Date:** 2026-04-14
**Agents:** Backend Architect (latency), AI Engineer (recall impact), Software Architect (implementation)
**Status:** IMPLEMENTED (Sprint 3)

---

## Architecture

```
remember(content)
  │
  ├── FAST PATH (sync, returns to caller in ~45ms)
  │   ├── Governance check           <1ms
  │   ├── Embedding (fastembed)      5-15ms
  │   ├── JSONL write                2-3ms
  │   ├── LanceDB index             8-15ms
  │   ├── Regex entity extraction    <1ms
  │   ├── Entity index (in-memory)   <1ms
  │   ├── Supersession check         5-25ms
  │   └── Heuristic KG edges         2-20ms
  │
  └── SLOW PATH (async worker thread)
      └── LLM causal triple extraction   500-3000ms
          └── Causal edge storage         1-5ms
```

## Key Decision: Only Causal Triples Are Deferred

Three agents independently confirmed:
- Entity index MUST be synchronous (recall_entity fails without it)
- Heuristic KG edges MUST be synchronous (multi-hop BFS fails without them)
- Supersession MUST be synchronous (stale notes survive recall without it)
- Causal triples are the ONLY LLM call, and they only affect CAUSAL intent queries

## Implementation

- `threading.Thread` + `queue.Queue(maxsize=500)` daemon worker
- `_EnrichmentJob` dataclass carries note_id (worker re-fetches to avoid staleness)
- `sync=False` default; `sync=True` for tests and blocking callers
- `atexit` drain with 10-second timeout
- Queue overflow: log warning, skip enrichment (note is safe)
- No `note.status` field — invisible to callers

## Performance Impact

| Metric | Before | After |
|---|---|---|
| remember() CTI note (fastembed) | 700-3500ms | ~45ms |
| remember() CTI note (Ollama embed) | 1000-4000ms | ~230ms |
| LOCOMO accuracy | 22% | 22% (unchanged) |
