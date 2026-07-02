# ADR-003: In-process LLM (llama-cpp-python)

**Date:** 2026-07-02

**Status:** Accepted

## Context

ZettelForge targets security teams and CTI analysts, many of whom operate in air-gapped or strictly egress-controlled environments where sending investigation notes to a cloud LLM API is a non-starter. Requiring API keys would also add onboarding friction and an ongoing cost for every user.

## Decision

Ship an in-process local LLM backend built on llama-cpp-python as the default provider, with Ollama and mock providers behind a common provider interface, rather than making the system API-only.

## Consequences

**Pros:**

- Offline-first: extraction, evolution, and synthesis all work with no network access — no data leaves the host.
- No API keys, accounts, or per-token billing; `pip install` is the entire setup.
- Meets the threat model of security-conscious users who cannot share intel with third-party services.
- The provider abstraction still allows swapping in Ollama or other backends when users want them.

**Cons:**

- Local models are smaller and less capable than frontier API models, so extraction and synthesis quality is bounded by what runs on analyst hardware.
- Model weights must be downloaded and consume disk and RAM; inference competes with other workloads on the host.
- llama-cpp-python lacks features like native structured output (`response_format`), requiring prompt-level workarounds for JSON mode.
