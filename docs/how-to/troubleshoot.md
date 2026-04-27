---
title: "Troubleshoot ZettelForge"
description: "Diagnose the most common ZettelForge install, ingest, and recall issues — LanceDB init failures, slow embeddings, missing LLM backend, supersession over-reach, and enrichment queue backpressure."
diataxis_type: "how-to"
audience: "Operator / Developer"
tags: [troubleshooting, debugging, errors, performance]
last_updated: "2026-04-25"
version: "2.6.0"
---

# Troubleshoot ZettelForge

A short decision tree for the most common failures, grouped by the
phase they occur in. Each entry links back to the authoritative
behaviour in code or config.

## Install / first run

### `ModuleNotFoundError: No module named 'zettelforge.mcp'`

You installed a version older than v2.2.0. The MCP server only became
importable as `zettelforge.mcp` starting in v2.2.0. Upgrade:

```bash
pip install -U 'zettelforge>=2.2.0'
python -m zettelforge.mcp   # should now start the stdio server
```

### `fastembed` download stalls on first use

fastembed pulls its ONNX model on first call. If you are behind a
proxy:

```bash
export HTTPS_PROXY=http://proxy:3128
export HF_HUB_ENABLE_HF_TRANSFER=0
```

Pre-download the model outside ZettelForge:

```python
from fastembed import TextEmbedding
# Use the full HF model id that ZettelForge defaults to internally.
# The short form "nomic-embed-text-v1.5-Q" is rejected by fastembed.
TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5-Q")
```

### Ollama backend returns empty strings

Two distinct causes share this symptom:

**1. Model not pulled.** Confirm the requested model is actually present:

```bash
ollama list                       # confirm model presence
ollama pull qwen2.5:3b             # or whatever ZETTELFORGE_LLM_MODEL points to
```

**2. Reasoning-model token starvation.** If you're on a reasoning model (qwen3.5+, qwen3.6, nemotron-3) and the OCSF log shows
`event=llm_call_empty_response done_reason=length eval_count=<num_predict>`, the model used its entire token budget on hidden `<think>...</think>` tokens before emitting a final answer.

Pre-2.5.2 budgets were too low (300–1024 tokens depending on call site) and silently failed every causal-extraction, synthesis, fact-extraction, and LLM-NER call. **Upgrade to 2.5.2+**; the per-call-site caps are now 2500–8000 tokens. See the [Configuration Reference §Per-call-site `max_tokens` budgets](../reference/configuration.md#per-call-site-max_tokens-budgets-v260-config-driven) for the exact values and now config-overridable in v2.6.0.

If you can't upgrade and you're stuck on a reasoning model, switch to a non-reasoning model (e.g. `gemma4:e4b`, `qwen2.5:3b`) which doesn't emit `<think>` tokens.

## `remember()` problems

### `GovernanceViolationError: content too short`

`GovernanceValidator` enforces `governance.min_content_length` (default
1 character). Strip-then-check: the validator rejects pure whitespace
too. For benchmark or replay scenarios, set
`governance.enabled: false` in `config.yaml`.

### `remember()` is slow (> 1 s per call)

The fast path should return in ~45 ms (v2.1.1+) or ~55 ms warm with
fastembed preload (v2.4.3+). If you are seeing multi-second latencies:

- You are on a version older than v2.1.1 and `_check_supersession` is
  running linearly. **Upgrade.** See CHANGELOG v2.1.1 P0-1.
- You're on v2.4.x or older and your `notes_<domain>.lance` shard has
  accumulated multi-gigabyte version-history overhead.
  Run `python -m zettelforge.scripts.compact_lance --data-dir
  ~/.amem --all --force` once, then **upgrade to v2.4.3+** so the
  background `lance.cleanup_*` daemon (RFC-009 Phase 1.5) keeps it
  trimmed. See the [Configuration Reference §lance section](../reference/configuration.md#lance-rfc-009-phase-15)
  for the daemon's two knobs and the operational rationale.
- You passed `sync=True`. That is expected — it blocks until the
  background enrichment queue (causal triples, LLM NER, A-Mem
  evolution) finishes. **On a 9B-Q4_K_M reasoning model in v2.5.2,
  this is now 1–3 minutes per note** because causal extraction
  uses an 8000-token budget. Use the default async path unless you
  specifically need the result inline.
- `llm_ner.enabled` is `true` and the LLM backend is slow. LLM NER
  runs asynchronously, so it should not block your `remember()` call
  — but if the enrichment queue fills up (`maxsize=500`), writes
  back-pressure. Either scale the LLM or set
  `ZETTELFORGE_LLM_NER_ENABLED=false`.

### `remember()` aborts with `KeyError: 'from_node_id'` on construct

Pre-v2.5.1 versions hard-failed `KnowledgeGraph._cache_edge` on legacy
edges that used `{source_id, target_id, relation_type}` keys instead of
the canonical `{from_node_id, to_node_id, relationship}`. This affects
any deployment with mixed-schema history in `kg_edges.jsonl` and takes
down every `recall()` and `synthesize()` at construction time. The
v2.5.1 hotfix added a normalize-on-load pass; **upgrade to 2.5.1+**.

### Entities I expect are not extracted

Regex-only extraction covers 13 types (CVE, ATT&CK technique, actor,
intrusion_set, tool, campaign, IPv4, domain, URL, MD5, SHA1, SHA256,
email). Conversational types (`person`, `location`, `organization`,
`event`, `activity`, `temporal`) require LLM NER. Check:

- `llm_ner.enabled` is `true` in your config (it is by default).
- Your LLM backend is reachable.
- Wait for enrichment to complete (or pass `sync=True`).

## `recall()` problems

### Zero results on obvious queries

- Check that the backend matches the data directory:
  `ZETTELFORGE_BACKEND=sqlite` (v2.2.0 default). A mismatched backend
  points at an empty database.
- The cross-encoder reranker drops low-similarity hits. Lower
  `retrieval.similarity_threshold` or raise `retrieval.default_k`.
- Notes may be superseded. Retry with `exclude_superseded=False`.

### Results include stale notes

Raise `retrieval.entity_boost` or set a tighter
`retrieval.similarity_threshold`. Notes with `tier="C"` can be
excluded with `synthesis.tier_filter: ["A", "B"]`.

### "Too many supersessions" on conversational data

Known behaviour — `_check_supersession()` is entity-overlap driven and
LOCOMO-style dialogue shares speakers. Pass
`exclude_superseded=False` on `recall()` or disable evolution via
`mm.remember(..., evolve=False)` for the ingest pass.

## `synthesize()` problems

### Every query returns `"No specific answer found for: …"`

The synthesis fallback string. The LLM call returned empty, malformed
JSON, or raised. Most likely cause on a reasoning model: token
starvation — see [Ollama backend returns empty strings](#ollama-backend-returns-empty-strings).

**Upgrade to v2.5.2+** which raised the synthesis budget from 800 to
2500 tokens; otherwise switch to a non-reasoning model.

You can confirm by grepping the OCSF log:

```bash
grep '"schema":"synthesis","raw":""' ~/.amem/logs/zettelforge.log | tail -5
grep '"event":"llm_call_empty_response"' ~/.amem/logs/zettelforge.log | tail -5
```

Both events appear when synthesis is silently degrading.

### `synthesize()` returned an answer but cited 0 sources

`recall()` itself returned no notes for the query. Check:

- `retrieval.similarity_threshold` — too high; lower to 0.15.
- `retrieval.default_k` — too low; raise.
- `synthesis.tier_filter` — defaulted to `["A", "B"]`; if all your
  notes are tier `"C"`, broaden the filter or annotate tier on ingest.

## Causal triple extraction problems

### `kg_edges` table has no `edge_type=causal` rows

Either the LLM call returned empty (token-starvation, see Ollama
section above) or the parser failed. Check:

```bash
sqlite3 ~/.amem/zettelforge.db \
  "SELECT edge_type, count(*) FROM kg_edges GROUP BY edge_type;"
```

If you only see `heuristic` rows, no causal triples are being
persisted. **v2.5.2** is the minimum version where this works
end-to-end on reasoning models — earlier versions silently failed
because the 300-token budget at the call site was exhausted by
`<think>` tokens.

If you're on 2.5.2+ and still seeing zero causal edges:

1. Confirm the LLM is reachable and returns non-empty responses for
   the synthesis prompt. (`json_parse.extract_json` already strips
   markdown code fences and supports `expect="array"` via a
   `\[.*\]` regex with DOTALL, so a fenced JSON-array reply is *not*
   the cause.)
2. Pass `sync=True` and watch the OCSF log for
   `event=parse_failed schema=causal_triples raw=...`. The `raw`
   preview will show what the model actually returned — usually
   either an empty string (token starvation, see Ollama section
   above) or relations outside the allowlist (`causes`, `enables`,
   `targets`, `uses`, `exploits`, `attributed_to`, `related_to`); the
   latter is logged as `event=invalid_causal_relation` with the
   offending relation string.

## MCP

### Claude Code cannot find the server

Confirm the invocation:

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

Then test the server by hand:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python -m zettelforge.mcp
```

You should see a JSON-RPC response listing seven tools. If the call
hangs for more than ~10 seconds on first use, the MemoryManager is
initialising embeddings/models — this only happens once per process.

### `zettelforge_sync` returns "requires zettelforge-enterprise"

The community build does not include OpenCTI sync. Install the
extension:

```bash
pip install zettelforge-enterprise
```

## Logs and diagnostics

ZettelForge writes structured JSON logs to rotating files under the
data directory (never to stdout by design — see GOV-012). Typical
locations:

```bash
tail -f ~/.amem/logs/zettelforge.log        # OCSF structured events (API activity, auth, file I/O)
tail -f ~/.amem/logs/audit.log              # Security-relevant events only (GOV-012)
tail -f ~/.amem/telemetry/telemetry_$(date +%F).jsonl  # Operational telemetry (RFC-007)
```

Useful log events to grep:

| Event | Meaning |
|-------|---------|
| `remember_completed` | Fast-path finished; includes note_id, duration_ms |
| `enrichment_queue_full` | Write back-pressure — scale the LLM or disable LLM NER |
| `supersession_applied` | A note was marked superseded; includes old_note_id, new_note_id |
| `lance_index_failed` | LanceDB write failed (check rebuild and disk space) |
| `governance_violation` | Input validation rejected a write |

Set `logging.level: DEBUG` in `config.yaml` for verbose output.

### Operational telemetry (RFC-007)

Every `MemoryManager.recall()` and `.synthesize()` call also emits a
per-query event to `~/.amem/telemetry/telemetry_YYYY-MM-DD.jsonl`
(parallel to the main OCSF log). In INFO mode this is aggregated
counts plus latency; at DEBUG level it adds per-note metadata, tier
distribution, vector/graph latency breakdown, and citation-based
utility feedback.

Tooling:

| Script | Purpose |
|--------|---------|
| `python -m zettelforge.scripts.telemetry_aggregator --date YYYY-MM-DD` | Daily summary report (latency averages, tier distribution, unused notes, top utility notes) |
| `python -m zettelforge.scripts.human_eval_sampler` | Sample 20 random synthesis briefings for the monthly human evaluation rubric (see `docs/human-evaluation-rubric.md`) |
| `streamlit run src/zettelforge/scripts/telemetry_dashboard.py` | Optional visualization (query volume, latency p50/p95, tier/utility trends, unused notes warning) |

Raw note content is never persisted in telemetry — only IDs, tiers,
source types, and domains. Query text is truncated to 200 chars at INFO
and 500 at DEBUG. All data stays local.

## Related

- [Configuration Reference](../reference/configuration.md)
- [Governance Controls Reference](../reference/governance-controls.md)
- [Retrieval Policies Reference](../reference/retrieval-policies.md)
