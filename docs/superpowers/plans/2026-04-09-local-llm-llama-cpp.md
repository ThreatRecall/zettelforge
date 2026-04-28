# Local LLM (llama-cpp-python) Implementation Plan

**Date:** 2026-04-09
**Status:** EXECUTING
**Branch:** `feat/fastembed-local-embeddings` (continuing from fastembed work)

**Goal:** Bundle Qwen 2.5 3B as the default LLM provider via llama-cpp-python. Keep Ollama as fallback via `llm.provider: ollama`.

**Model:** Qwen2.5-3B-Instruct-Q4_K_M.gguf (2.0 GB, 15.6 tok/s, Apache-2.0)
**Benchmarked:** 2.6s for fact extraction (40 tokens), 0.7s for intent classification

## Tasks

1. Create `src/zettelforge/llm_client.py` — singleton LLM with provider switching
2. Update all 5 call sites to use `llm_client` instead of direct `ollama.generate()`
3. Update config, deps, README
4. Tests
