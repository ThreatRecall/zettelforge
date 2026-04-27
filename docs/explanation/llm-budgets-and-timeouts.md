---
title: "LLM budgets, timeouts, and what they cost you"
description: "How ZettelForge's LLM token budgets and HTTP timeouts trade latency for end-to-end correctness — what each knob controls, what it costs, and when to override."
diataxis_type: explanation
audience: "Operator / Developer"
tags: [llm, configuration, performance, reasoning-models, ollama]
last_updated: "2026-04-25"
version: "2.6.0"
---

# LLM budgets, timeouts, and what they cost you

ZettelForge makes five distinct kinds of LLM calls (causal triple extraction, synthesis, fact extraction, conversational NER, neighbor evolution). Each has a hardcoded `max_tokens` budget and shares a single configurable `llm.timeout`. The defaults trade ingest latency for end-to-end correctness on a reference reasoning model (`qwen3.5:9b`, Q4_K_M). This page explains why the defaults look the way they do and when you should override them.

If you just want the table of values, see the [Configuration Reference §Per-call-site `max_tokens` budgets](../reference/configuration.md#per-call-site-max_tokens-budgets-hardcoded-v252). This page is the *why*.

## The hidden-thinking-token problem

Modern reasoning models — qwen3.5+, qwen3.6, nemotron-3, deepseek-r1, gemini-thinking — generate two streams of tokens for any prompt:

1. **Reasoning tokens.** Wrapped in `<think>...</think>`, these are the model's internal scratch work. Ollama hides them from the `response` field by default but **they still count against `num_predict`**.
2. **Answer tokens.** What the model actually emits as the final user-visible output. These appear in `response`.

If `num_predict` is 300 tokens and the model uses 280 of them reasoning, you get 20 tokens of answer — usually not enough for valid JSON. If it uses all 300, you get an empty string and Ollama returns `done_reason: "length" eval_count: 300 response: ""`. The pre-2.5.2 budgets (300/400/800/1024) were sized for non-reasoning models and silently failed every call on the reasoning model that ZettelForge defaults to. v2.5.2 raised the per-call-site caps to give reasoning room *and* answer room on the same generation.

## Per-call-site budgets — and why each one is what it is

### Causal triple extraction (`note_constructor.py`, **8000 tokens**)

The largest budget anywhere in the codebase. The prompt asks the model to enumerate *every* causal relation in a passage of up to 2000 characters, validating each relation against an allowlist. Empirical: `qwen3.5:9b` at 4000 tokens succeeded only ~70% of the time (eval_count varied 2.8k–4k+, with the longer reasoning chains hitting the budget cap). 8000 keeps the success rate above 95% on the same model. Wall-clock cost: 60–140 s per call.

### Synthesis (`synthesis_generator.py`, **2500 tokens**)

Single-answer prompts converge faster than enumerate-everything prompts. 2500 covers reasoning + a paragraph of JSON answer. Wall-clock: 20–50 s per query.

### Fact extraction (`fact_extractor.py`, **2500 tokens**)

Similar profile to synthesis — bounded JSON output. The pre-2.5.2 cap was 400, which left this silently no-opping on every reasoning-model call.

### Conversational NER (`entity_indexer.py`, **2500 tokens**)

The regex fast-path covers CTI types (CVE, ATT&CK, IOCs); LLM NER fills in `person`, `location`, `organization`, `event`, `activity`, `temporal`. Output is a small JSON object so 2500 is generous. The retry path uses the same budget.

### Neighbor evolution (`memory_evolver.py`, **2500 tokens** × 2)

Two-note comparison + ADD/UPDATE/DELETE/NOOP decision. Both the first call and the parse-retry call use 2500. Parse-retry exists because reasoning models occasionally emit prose preamble before the JSON; the second call reasserts JSON-only and usually gets it.

## The shared timeout

`llm.timeout` (default **180 s** in v2.5.2; was 60 s pre-fix) governs the HTTP read deadline on every Ollama call.

The 60 s default fired before causal extraction at 8000 tokens could complete on a 9B model. The fix had to come at both ends: bigger budget *and* longer timeout. If you lower one, lower the other together — bumping the budget without bumping the timeout just trades empty-response failures for ReadTimeout failures.

## When to override

The defaults are calibrated for `qwen3.5:9b` Q4_K_M on a single GPU. You want to override if:

### You're on faster hardware (H100, multi-GPU, large batch)

You can lower `llm.timeout` to e.g. 60 s without losing correctness, since each generation completes faster. The budgets themselves are about *how much room the model needs to think*, not how fast it thinks — leave them alone unless you've measured.

### You're on a non-reasoning model (gemma4, llama-3.x base, qwen2.5)

These don't emit ` thinking` tokens. Your budgets only need to cover the actual answer length, not reasoning + answer. You can set `max_tokens` values to ~25% of the v2.5.2 defaults in config (v2.6.0 moved them to `LLMConfig` — see [issue #125](https://github.com/rolandpg/zettelforge/issues/125)). `llm.timeout: 60` is then enough.

### You're on a much larger model (70B, 120B, cloud)

Reasoning depth often *increases* with model size. The 8000-token causal cap may not be enough on a 120B reasoning model. Watch the OCSF log for `event=llm_call_empty_response done_reason=length eval_count=8000` — if you see it, raise the `max_tokens=8000` literal inside `NoteConstructor.extract_causal_triples` (in `src/zettelforge/note_constructor.py`) and re-test.

### You're triggering `sync=True` or doing bulk ingestion

The default async path moves causal extraction off the write hot path; `remember()` returns in ~50 ms while extraction happens later in the enrichment worker. **`sync=True` blocks the caller until the worker finishes.** With v2.5.2 budgets on a 9B reasoning model that's 1–3 minutes per note. For bulk ingestion (1000+ notes), prefer async and let the queue drain at its own pace; for sync use cases (test fixtures, small one-shots), accept the latency or downgrade to a non-reasoning model.

## Verifying your budgets are right

The OCSF log at `~/.amem/logs/zettelforge.log` carries every LLM call as a structured event. Two events to know:

- **`llm_call_empty_response`** — `WARNING` level, fires whenever an Ollama call returns an empty `response`. Always visible at the default `INFO` log level.
- **`llm_call_complete`** — `DEBUG` level, fires on every successful call with `eval_count`, `response_chars`, `max_tokens`, `duration_ms`, etc. Only visible when `logging.level: DEBUG` is set in `config.yaml` (or via `ZETTELFORGE_LOG_LEVEL=DEBUG`).

To spot too-small budgets at the default log level:

```bash
grep '"event":"llm_call_empty_response"' ~/.amem/logs/zettelforge.log \
  | jq -r '"\(.model) eval=\(.eval_count) of max=\(.max_tokens) dur_ms=\(.duration_ms)"' \
  | tail -20
```

`eval == max_tokens` with `done_reason: length` is the canonical token-starvation signature — raise the budget for that call site.

To verify budgets aren't *too* generous (free wall-clock to claw back), enable DEBUG logging and grep `llm_call_complete` instead. `eval_count << max_tokens` with non-empty `response_chars` means you could safely lower the cap on faster hardware.

## Background

- v2.5.2 hotfix CHANGELOG entry — full root-cause writeup and per-file diffs.
- [Issue #125](https://github.com/rolandpg/zettelforge/issues/125) — v2.6.0 plan to make these budgets config-overridable per call site, add `<think>`-tag stripping as a post-processing guard, and a `reasoning_model: bool` auto-scale flag.

## Related

- [Configuration Reference](../reference/configuration.md)
- [Troubleshoot ZettelForge](../how-to/troubleshoot.md)
