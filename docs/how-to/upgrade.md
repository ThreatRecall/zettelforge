---
title: "Upgrade ZettelForge"
description: "Upgrade paths between ZettelForge releases, with required migration steps, breaking changes to watch for, and rollback instructions."
diataxis_type: "how-to"
audience: "Operator / Maintainer"
tags: [upgrade, migration, release, breaking-changes]
last_updated: "2026-04-25"
version: "2.6.0"
---

# Upgrade ZettelForge

Use this as a checklist whenever you move between minor releases. For
the full list of changes per release see
[CHANGELOG.md](https://github.com/rolandpg/zettelforge/blob/master/CHANGELOG.md).

## Upgrade matrix

| From -> To | Required action | Data migration? |
|-----------|-----------------|-----------------|
| 2.5.0 / 2.5.1 / 2.5.2 -> 2.6.0 | `pip install -U zettelforge` (read v2.6.0 notes above) | No |
| 2.4.x -> 2.5.x | `pip install -U zettelforge` (read v2.5.0/2.5.1/2.5.2 notes below) | No |
| 2.2.x -> 2.4.x | `pip install -U zettelforge` | No |
| 2.1.x -> 2.2.x | `pip install -U zettelforge` + run JSONL -> SQLite migration | **Yes** |
| 2.0.x -> 2.2.x | Upgrade in two hops via 2.1.x is recommended but not required | **Yes** |
| < 2.0 | Not supported -- export notes manually, fresh-install 2.2.x |

## 2.5.x -> 2.6.0 (content limits + config-driven token budgets)

### What's new

- **Configurable content size limits** (RFC-014). `GovernanceConfig.limits.max_content_length` (default 50 MB) prevents oversized content from exhausting memory or blocking the enrichment queue. Set to `0` to disable. Environment override: `ZETTELFORGE_LIMITS_MAX_CONTENT_LENGTH`.
- **Per-call-site `max_tokens` budgets moved to config.** `LLMConfig` now exposes `max_tokens_causal`, `max_tokens_synthesis`, `max_tokens_fact`, `max_tokens_ner`, and `max_tokens_evolution` (defaults match v2.5.2 values). No more monkey-patching.
- **`llm.timeout` default remains 180 s** (set in v2.5.2). Now symmetrically overridable alongside per-call-site budgets.

### Steps

1. `pip install -U 'zettelforge>=2.6.0'`
2. If you had a custom `config.yaml` that overrode `llm.timeout`, it still works. No YAML changes required — existing configs are backward-compatible.
3. (Optional) Override per-call-site budgets in your `config.yaml`:

   ```yaml
   llm:
     max_tokens_causal: 12000     # default 8000
     max_tokens_synthesis: 4000   # default 2500
     max_tokens_fact: 4000        # default 2500
   ```

   See the [Configuration Reference](../reference/configuration.md#per-call-site-max_tokens-budgets-v260-config-driven) for all knobs.

### Operational impact

- **None if you're on v2.5.2 defaults.** Budget values are unchanged. The only difference is they are now configurable instead of hardcoded.
- **If you had v2.5.0/v2.5.1:** this upgrade includes the v2.5.2 reasoning-model fix. Apply the same steps listed below in the v2.5.2 section.

## 2.5.x -> 2.5.2 (recommended for everyone on a reasoning model)

**Read first** if you're running ZettelForge against `qwen3.5+`, `qwen3.6`, `nemotron-3`, or any other model that emits `<think>...</think>` tokens. Pre-2.5.2 deployments with these models were silently failing every causal-extraction, synthesis, fact-extraction, and LLM-NER call — the per-call-site `max_tokens` budgets were too small for the reasoning phase, leaving the JSON answer empty.

### What changed

- **Per-call-site `max_tokens` budgets bumped** to give reasoning models headroom: causal extraction 300 → 8000, synthesis 800 → 2500, fact extraction 400 → 2500, LLM NER 300 → 2500, memory evolution 1024 → 2500. These were hardcoded until v2.6.0 moved them to `LLMConfig`.
- **`llm.timeout` default bumped 60 s -> 180 s** (`LLMConfig.timeout`, `OllamaProvider`, `config.default.yaml`). The 60 s default fired before causal extraction at 8000 tokens could complete on a 9B model.

### Operational impact you should know about

- **Causal extraction now takes 60-140 s per call on a 9B-Q4_K_M reasoning model.** `remember(sync=True)` blocks 1-3 minutes per note. Default async path (background enrichment queue) is unaffected — only `sync=True` and bulk-ingest workflows feel the latency. Switch to async if you weren't already.
- **`llm_call_empty_response` warnings should disappear** from your OCSF log. If they don't, see [LLM budgets and timeouts](../explanation/llm-budgets-and-timeouts.md) for the verification recipe.

### Steps

1. `pip install -U 'zettelforge>=2.5.2'`
2. If you have a custom `config.yaml` that explicitly sets `llm.timeout: 60.0`, raise it to `180.0` (or remove the override and inherit the new default).
3. Read [LLM budgets and timeouts](../explanation/llm-budgets-and-timeouts.md) if you operate on faster hardware or a non-reasoning model and want to tune downward.

## 2.4.x -> 2.5.1 (KG schema tolerance hotfix)

If you have a long-running deployment with mixed-schema entries in `kg_edges.jsonl` (legacy `{source_id, target_id, relation_type}` rows alongside canonical `{from_node_id, to_node_id, relationship}` rows), pre-v2.5.1 versions hard-failed `KnowledgeGraph._cache_edge` on the legacy entries with `KeyError: 'from_node_id'` — taking down every `recall()` and `synthesize()` at construction time.

The v2.5.1 hotfix added a normalize-on-load pass that remaps legacy keys and silently drops un-normalizable entries with a WARNING log. **No data migration required**; legacy rows continue to live in `kg_edges.jsonl` untouched, they just get translated in-memory.

### Steps

1. `pip install -U 'zettelforge>=2.5.1'`
2. (Optional) After first start-up, grep the log for the skip count:
   ```bash
   grep '"event":"kg_edges_skipped_malformed"' ~/.amem/zettelforge.log
   ```
   If `count` is non-zero, those rows are un-normalizable (typically missing `edge_id` or both source/target ids); they were not contributing useful data anyway.

## 2.2.x -> 2.5.x

No data migration required. The following new features are available as optional extras:

### Local LLM backend selection (RFC-011)

`provider: local` now supports two in-process inference engines via `local_backend`:

- **`llama-cpp-python`** (default) -- GGUF models. No config change needed if you already use `provider: local`.
- **`onnxruntime-genai`** -- ONNX models with AMD ROCm, Intel OpenVINO, Apple CoreML support. Requires `pip install zettelforge[local-onnx]` and `local_backend: onnxruntime-genai` in config.

The `LlamaCppBackend` code was extracted from `LocalProvider` into its own class. Behavior is identical for existing users. See the [Configuration Reference](reference/configuration.md#llm) for example configs.

### LiteLLM unified provider (RFC-012)

A new `provider: litellm` option routes to 100+ LLM providers through a single interface, replacing the need for separate `openai_compat`, `anthropic`, `bedrock`, and `vertex` providers.

To use: `pip install zettelforge[litellm]`, then configure:

```yaml
llm:
  provider: litellm
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}
```

Model name prefix routing determines the backend automatically: `gpt-4o` -> OpenAI, `claude-sonnet-4-20250514` -> Anthropic, `groq/llama-3.3-70b-versatile` -> Groq, etc.

### Steps

1. `pip install -U 'zettelforge>=2.5.0'`
2. (Optional) Install optional extras:
   ```bash
   pip install zettelforge[local-onnx]   # ONNX local inference
   pip install zettelforge[litellm]      # LiteLLM cloud provider routing
   pip install zettelforge[local-all]    # both local backends
   ```
3. Update `config.yaml` if you want to use new providers (existing configs continue to work unchanged).

## 2.1.x → 2.2.x

The headline change is the **SQLite default backend**. Notes, the
knowledge graph, and the entity index now live in
`<data_dir>/zettelforge.db` instead of a loose set of JSONL files.

### Steps

1. `pip install -U 'zettelforge>=2.2.0'`
2. Back up your data directory:
   ```bash
   cp -a ~/.amem ~/.amem.pre-2.2
   ```
3. Run the migration — see
   [Migrate JSONL to SQLite](migrate-jsonl-to-sqlite.md).
4. Confirm with `mm.get_stats()` that `total_notes` matches the
   migration log.

### What else changed in v2.2.0

- **Causal chain retrieval** now works for `why did X happen?` queries.
  If you relied on the old (silent) behaviour, audit existing
  downstream code — `edge_type="causal"` is now filterable.
- **Memory evolution is on by default** on `remember()` once the
  store has ≥ 3 notes. Pass `evolve=False` to opt out.
- **STIX alignment:** APT/UNC/TA/FIN groups now store as
  `intrusion_set`. `recall_actor()` remains backward-compatible and
  searches `actor`, `threat_actor`, and `intrusion_set`.
- **Governance controls consolidated** into
  `governance/controls.yaml`. CI now runs spec-drift detection
  automatically — no action required unless you have forked the
  governance test suite.
- **MCP server is now a first-class module:**
  `python -m zettelforge.mcp` replaces the v2.1.x shim at
  `web/mcp_server.py` (the shim still works for backward compat).

## 2.0.x → 2.1.x (interim notes)

- Dual-stream write path lands in 2.1.1. `remember()` now returns in
  ~45 ms; pass `sync=True` where you need the background enrichment
  complete before a subsequent `recall()`.
- P0 security fixes — SQL injection in `VectorMemory.search/delete`
  was fixed in 2.1.1. Upgrade immediately.
- File locking on JSONL and entity-index writes added in 2.1.1.

## Rollback

All of ZettelForge's state lives in the configured data directory,
plus the installed package. To roll back:

```bash
# 1. Pin the previous version
pip install 'zettelforge==2.1.1'

# 2. Restore the JSONL data directory (the SQLite file is ignored by
#    older releases)
rm -rf ~/.amem
cp -a ~/.amem.pre-2.2 ~/.amem
```

The SQLite database file (`zettelforge.db`) is harmless left in place
— older versions will not read it, and deleting it does not affect
JSONL data.

## Related

- [Migrate JSONL to SQLite](migrate-jsonl-to-sqlite.md)
- [Troubleshoot](troubleshoot.md)
- [CHANGELOG.md](https://github.com/rolandpg/zettelforge/blob/master/CHANGELOG.md)
