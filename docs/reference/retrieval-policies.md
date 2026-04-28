---
title: "Retrieval Policies Reference"
description: "Intent classification, policy weight mapping, scoring formulas, and merge algorithm for the BlendedRetriever pipeline."
diataxis_type: "reference"
audience: "Senior CTI Practitioner"
tags:
  - retrieval
  - intent-classification
  - vector-search
  - graph-traversal
  - blended-retriever
last_updated: "2026-04-09"
version: "2.0.0"
---

# Retrieval Policies Reference

Modules: `zettelforge.intent_classifier`, `zettelforge.vector_retriever`, `zettelforge.graph_retriever`, `zettelforge.blended_retriever`

---

## Intent Types

```python
from zettelforge.intent_classifier import QueryIntent

class QueryIntent(Enum):
    FACTUAL = "factual"
    TEMPORAL = "temporal"
    RELATIONAL = "relational"
    CAUSAL = "causal"
    EXPLORATORY = "exploratory"
    UNKNOWN = "unknown"
```

| Intent | Description | Example Query |
|:-------|:------------|:--------------|
| `FACTUAL` | Entity lookup, direct fact retrieval | "What CVE was used in the SolarWinds attack?" |
| `TEMPORAL` | Time-based queries, timeline reconstruction | "What changed since the last incident?" |
| `RELATIONAL` | Graph traversal, relationship mapping | "Who uses Cobalt Strike?" |
| `CAUSAL` | Cause-effect chains | "Why did the attacker pivot to the domain controller?" |
| `EXPLORATORY` | General exploration, broad context | "Tell me about APT28" |
| `UNKNOWN` | Ambiguous or unclassifiable | Fallback when classification confidence is low |

---

## Intent Classification

### Keyword Matching (Primary)

The classifier scores each intent by counting keyword matches against the query.

| Intent | Keywords |
|:-------|:---------|
| `FACTUAL` | `cve-`, `cve `, `vulnerability`, `exploit`, `malware`, `tool`, `actor`, `apt`, `threat`, `what is`, `what was`, `which` |
| `TEMPORAL` | `when`, `timeline`, `since`, `before`, `after`, `changed`, `history`, `previously`, `earlier`, `latest`, `recent` |
| `RELATIONAL` | `who uses`, `who targets`, `who conducts`, `related to`, `connected to`, `associated with`, `linked to`, `uses tool` |
| `CAUSAL` | `why`, `because`, `caused by`, `enables`, `leads to`, `results in`, `due to`, `reason for` |
| `EXPLORATORY` | `tell me about`, `explain`, `describe`, `overview`, `information on`, `details about`, `context` |

**Classification logic:**
1. Count keyword hits per intent.
2. If best score >= 2: return intent with confidence = `min(1.0, score / 4)`. Method: `keyword`.
3. If best score < 2 and LLM fallback enabled: classify via LLM. Method: `llm`. Confidence: `0.8`.
4. If LLM fallback disabled or fails: return `EXPLORATORY` with confidence `0.3`. Method: `default`.

### LLM Fallback

Model: configured via `llm.model` (default `qwen2.5:3b`). Temperature: `0.1`. Max tokens: `20`.

---

## Policy Weights

Each intent maps to a retrieval policy that controls how results from different retrievers are weighted and merged.

| Intent | `vector` | `entity_index` | `graph` | `temporal` | `top_k` |
|:-------|:---------|:----------------|:--------|:-----------|:--------|
| `FACTUAL` | 0.3 | 0.7 | 0.0 | 0.0 | 3 |
| `TEMPORAL` | 0.2 | 0.1 | 0.2 | 0.5 | 5 |
| `RELATIONAL` | 0.2 | 0.2 | 0.5 | 0.1 | 10 |
| `CAUSAL` | 0.1 | 0.1 | 0.6 | 0.2 | 10 |
| `EXPLORATORY` | 0.5 | 0.2 | 0.2 | 0.1 | 10 |
| `UNKNOWN` | 0.4 | 0.2 | 0.2 | 0.2 | 5 |

**Weight semantics:** Weights control the contribution of each retrieval source to the final blended score. They do not need to sum to 1.0 (the BlendedRetriever normalizes implicitly through score combination). `top_k` is the suggested number of results to return.

---

## VectorRetriever Scoring

Module: `zettelforge.vector_retriever`

### Base Similarity

```python
score = cosine_similarity(query_vector, note_vector)
```

Where `cosine_similarity(a, b) = dot(a, b) / (norm(a) * norm(b))`.

Embedding model: `nomic-embed-text-v1.5-Q` (768 dimensions). Embeddings are generated in-process via fastembed (ONNX).

### Entity Boost

Applied when query entities overlap with note entities:

```python
boosted_score = base_score * (entity_boost ** overlap_count)
```

| Parameter | Config Key | Default |
|:----------|:-----------|:--------|
| `entity_boost` | `retrieval.entity_boost` | `2.5` |
| `exact_match_boost` | hardcoded | `1.0` |

Exact match boost is applied multiplicatively when a query entity string appears verbatim in the note's raw content.

### Similarity Threshold

```python
if score >= similarity_threshold:
    include_in_results()
```

| Parameter | Config Key | Default |
|:----------|:-----------|:--------|
| `similarity_threshold` | `retrieval.similarity_threshold` | `0.25` (config) / `0.15` (runtime override) |

The runtime constructor defaults to `0.15`, which takes precedence over the config default of `0.25`.

### Embedding Validation

Vectors are validated before scoring. Invalid embeddings are regenerated from content.

| Check | Condition | Action |
|:------|:----------|:-------|
| Null vector | `vector is None` | Regenerate |
| Wrong dimensions | `len(vector) != 768` | Regenerate |
| All zeros | `all(v == 0.0 for v in vector)` | Regenerate |
| Low variance | `np.var(vector) < 0.001` | Regenerate |

### LanceDB vs. In-Memory

| Mode | Trigger | Score Calculation |
|:-----|:--------|:------------------|
| LanceDB | `use_lancedb=True` and LanceDB available | `similarity = 1.0 - distance` (LanceDB returns L2 distance) |
| In-memory | LanceDB unavailable or `use_lancedb=False` | Direct cosine similarity |

---

## GraphRetriever Scoring

Module: `zettelforge.graph_retriever`

### BFS Traversal

Starting from each query entity, BFS traverses the knowledge graph up to `max_depth` hops.

```python
max_depth = retrieval.max_graph_depth  # default: 2
```

### Score Formula

```python
score = 1.0 / (1.0 + hop_distance)
```

| Hops | Score |
|:-----|:------|
| 0 | 1.000 |
| 1 | 0.500 |
| 2 | 0.333 |
| 3 | 0.250 |

When multiple paths reach the same note, the path with the highest score (fewest hops) wins.

### ScoredResult

```python
@dataclass
class ScoredResult:
    note_id: str
    score: float
    hops: int
    path: List[str]  # e.g., ["actor:APT28", "tool:Mimikatz", "note:note_20240315_..."]
```

---

## BlendedRetriever Merge Algorithm

Module: `zettelforge.blended_retriever`

### Input

| Source | Type | Content |
|:-------|:-----|:--------|
| `vector_results` | `List[MemoryNote]` | Ranked notes from VectorRetriever |
| `graph_results` | `List[ScoredResult]` | Scored notes from GraphRetriever |
| `policy` | `Dict[str, float]` | Intent-based weight dictionary |

### Algorithm

```
1. For each vector result at position i:
     position_score = 1.0 / (1.0 + i)
     blended_score = position_score * policy["vector"]
     Add to scores dict: {note_id: (blended_score, note)}

2. For each graph result:
     graph_score = result.score * policy["graph"]
     If note_id already in scores dict:
       scores[note_id] = (existing_score + graph_score, existing_note)
     Else:
       Lookup note via note_lookup(note_id)
       If found: scores[note_id] = (graph_score, note)

3. Sort all entries by blended_score descending.

4. Return top k notes.
```

**Key behavior:** Notes found by both vector and graph retrieval receive additive scores from both sources. This "both-source bonus" means notes that are both semantically similar and graph-proximate rank highest.

### Blend Method Signature

```python
class BlendedRetriever:
    def blend(
        self,
        vector_results: List[MemoryNote],
        graph_results: List[ScoredResult],
        policy: Dict[str, float],
        note_lookup: Callable[[str], Optional[MemoryNote]],
        k: int = 10,
    ) -> List[MemoryNote]
```

| Parameter | Type | Description |
|:----------|:-----|:------------|
| `vector_results` | `List[MemoryNote]` | Pre-ranked vector search results. |
| `graph_results` | `List[ScoredResult]` | Graph traversal results with scores. |
| `policy` | `Dict[str, float]` | Must contain `vector` and `graph` keys. |
| `note_lookup` | `Callable[[str], Optional[MemoryNote]]` | Function to resolve note ID to MemoryNote. |
| `k` | `int` | Maximum results to return. |

---

## Full Retrieval Pipeline

```
Query
  |
  v
IntentClassifier.classify(query)
  |
  +--> QueryIntent + metadata
  |
  v
IntentClassifier.get_traversal_policy(intent)
  |
  +--> policy weights dict
  |
  v
[Parallel]
  |
  +--> VectorRetriever.retrieve(query, domain, k)
  |      cosine similarity + entity boost + link expansion
  |
  +--> GraphRetriever.retrieve_note_ids(query_entities, max_depth)
  |      BFS from resolved entities, score = 1/(1+hops)
  |
  v
BlendedRetriever.blend(vector_results, graph_results, policy, note_lookup, k)
  |
  +--> Additive score merge, sort descending, top-k
  |
  v
Filter superseded notes (if exclude_superseded=True)
  |
  v
Increment access counts
  |
  v
List[MemoryNote]
```

---

## LLM Quick Reference

ZettelForge's retrieval pipeline classifies query intent, then routes through parallel vector and graph retrievers before blending results with intent-specific policy weights.

**Intent classification** uses a two-tier approach: keyword matching first (counting hits against predefined keyword lists per intent), with LLM fallback for ambiguous queries (score < 2). Six intent types exist: FACTUAL (entity lookup), TEMPORAL (time-based), RELATIONAL (graph traversal), CAUSAL (cause-effect), EXPLORATORY (broad context), and UNKNOWN (fallback).

**Policy weights** control retriever contribution per intent. FACTUAL queries weight entity_index at 0.7 and vector at 0.3 with top_k=3 for precise lookups. RELATIONAL and CAUSAL queries weight graph at 0.5--0.6 for relationship traversal with top_k=10. EXPLORATORY queries weight vector at 0.5 for broad semantic search. TEMPORAL queries weight the temporal channel at 0.5.

**VectorRetriever** computes cosine similarity between the query embedding and note embeddings (nomic-embed-text-v2-moe, 768 dims). Scores are boosted multiplicatively by `entity_boost^overlap_count` (default 2.5x per overlapping entity). Notes below the similarity threshold (0.15 runtime default) are excluded. LanceDB is preferred; in-memory cosine similarity is the fallback.

**GraphRetriever** runs BFS from resolved query entities through the knowledge graph. Score formula: `1/(1+hops)`, so direct connections score 1.0, one-hop neighbors score 0.5, two-hop neighbors score 0.333. Max depth is configurable (default 2).

**BlendedRetriever** merges both result sets. Vector results are scored by reciprocal rank (`1/(1+position)`) multiplied by the vector policy weight. Graph results use their BFS score multiplied by the graph policy weight. Notes found by both sources get additive scores, creating a "both-source bonus" that promotes notes that are both semantically similar and graph-proximate. Final results are sorted by blended score and truncated to top-k.
