# ADR-002: Blended retrieval (vector + graph)

**Date:** 2026-07-02

**Status:** Accepted

## Context

Vector-only retrieval works well for fuzzy semantic queries but performs poorly on CTI questions that hinge on precise entity relationships — "what tools does APT28 use?" is a graph traversal, not a similarity search. Pure graph retrieval, conversely, misses relevant notes that never mention a resolved entity by name.

## Decision

Blend two retrievers: a vector retriever (cosine similarity over embeddings, with entity-overlap boosting) and a graph retriever (BFS over the knowledge graph scored by `1/(1+hops)`). An intent classifier routes each query and weights the two signals accordingly — relational and causal queries lean on the graph, exploratory queries lean on vectors.

## Consequences

**Pros:**

- Entity-relationship questions get exact answers via graph traversal instead of fuzzy nearest-neighbor guesses.
- Semantic queries still benefit from embedding similarity across the full note corpus.
- Intent routing (factual, temporal, relational, causal, exploratory) tunes the blend per query rather than using one static weighting.
- Entity boosting lets the graph improve vector rankings even when the graph path alone is insufficient.

**Cons:**

- Two retrieval subsystems mean more code, more configuration knobs, and more tuning surface.
- Retrieval quality depends on entity extraction and alias resolution being accurate; graph errors propagate into rankings.
- Intent misclassification can weight the wrong retriever for a query.
