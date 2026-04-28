---
title: "MemoryManager API Reference"
description: "Complete API surface for the MemoryManager class and MemoryNote schema. All public methods, parameters, return types, and usage examples."
diataxis_type: "reference"
audience: "Senior CTI Practitioner"
tags:
  - api
  - memory-manager
  - memorynote
  - schema
  - python
last_updated: "2026-04-09"
version: "2.0.0"
---

# MemoryManager API Reference

Module: `zettelforge.memory_manager`

```python
from zettelforge.memory_manager import MemoryManager, get_memory_manager
```

## Constructor

```python
class MemoryManager:
    def __init__(
        self,
        jsonl_path: Optional[str] = None,
        lance_path: Optional[str] = None
    ) -> None
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `jsonl_path` | `Optional[str]` | `None` | Path to JSONL note store. Falls back to `~/.amem/notes.jsonl`. |
| `lance_path` | `Optional[str]` | `None` | Path to LanceDB directory. Falls back to `~/.amem/lance/`. |

Instantiates internal components: `MemoryStore`, `NoteConstructor`, `EntityIndexer`, `VectorRetriever`, `GovernanceValidator`, `AliasResolver`.

---

## Write Methods

### `remember`

```python
def remember(
    self,
    content: str,
    source_type: str = "conversation",
    source_ref: str = "",
    domain: str = "general",
    evolve: bool = False,
    sync: bool = False
) -> Tuple[MemoryNote, str]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `content` | `str` | *(required)* | Raw text to store as a memory note. |
| `source_type` | `str` | `"conversation"` | Origin type. Values: `conversation`, `task_output`, `ingestion`, `observation`, `mcp`, `report`. |
| `source_ref` | `str` | `""` | Source identifier (e.g., `subagent:task_id`, `conversation:session_id`). |
| `domain` | `str` | `"general"` | Memory domain. Values: `general`, `cti`, `incident`, `threat_intel`, `project`, `personal`, `research`. |
| `evolve` | `bool` | `False` | Enable memory evolution. When `True`, uses the two-phase Mem0-style pipeline: LLM extracts facts, compares each against existing notes, and decides ADD/UPDATE/DELETE/NOOP. Slower but prevents duplicate/stale knowledge. The MCP server and web API default to `evolve=True`. |
| `sync` | `bool` | `False` | When `False` (default), causal enrichment is deferred to a background worker and the call returns in ~45ms (fast path). When `True`, the call blocks until background enrichment completes. Use `sync=True` in tests or batch pipelines where you need enrichment to be visible before the next read. |

**Returns:** `Tuple[MemoryNote, str]` -- the note and status. Status is one of: `"created"` (direct store or ADD), `"updated"` (existing note superseded by refinement), `"corrected"` (existing note superseded by contradiction), `"noop"` (content already captured).

**Side effects:** Runs governance validation, entity extraction with alias resolution, supersession check, and knowledge graph update (including causal triple extraction for CTI domains). With `evolve=True`, additionally runs LLM fact extraction and update decisions.

**Raises:** `GovernanceViolationError` if governance validation fails.

```python
mm = MemoryManager()

# Direct store (fast, no LLM evolution)
note, status = mm.remember(
    "APT28 deployed X-Agent via spearphishing targeting NATO members",
    source_type="report",
    source_ref="https://example.com/report-123",
    domain="cti"
)

# With evolution (LLM compares against existing notes)
note, status = mm.remember(
    "APT28 stopped using X-Agent, switched to HeadLace backdoor",
    domain="cti",
    evolve=True,  # X-Agent note gets superseded
)
# status == "updated" — old note marked superseded
```

### `remember_with_extraction`

```python
def remember_with_extraction(
    self,
    content: str,
    source_type: str = "conversation",
    source_ref: str = "",
    domain: str = "general",
    context: str = "",
    min_importance: int = 3,
    max_facts: int = 5
) -> List[Tuple[Optional[MemoryNote], str]]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `content` | `str` | *(required)* | Raw text to process through the two-phase pipeline. |
| `source_type` | `str` | `"conversation"` | Origin type. |
| `source_ref` | `str` | `""` | Source identifier. |
| `domain` | `str` | `"general"` | Memory domain. |
| `context` | `str` | `""` | Rolling summary for disambiguation during extraction. |
| `min_importance` | `int` | `3` | Facts scored below this threshold are discarded. Range: 1--10. |
| `max_facts` | `int` | `5` | Maximum facts to extract per call. |

**Returns:** `List[Tuple[Optional[MemoryNote], str]]` -- list of `(note_or_None, status)` tuples. Status values: `"added"`, `"updated"`, `"corrected"`, `"noop"`.

**Pipeline:**
1. Phase 1 (Extraction): LLM distills content into scored candidate facts via `FactExtractor`.
2. Phase 2 (Update): Each fact is compared to existing notes; LLM decides `ADD`, `UPDATE`, `DELETE`, or `NOOP` via `MemoryUpdater`.

```python
results = mm.remember_with_extraction(
    content="New report: Volt Typhoon uses LOLBins to maintain persistence in US critical infrastructure.",
    domain="cti",
    min_importance=5,
    max_facts=3
)
for note, status in results:
    print(f"{status}: {note.id if note else 'skipped'}")
```

### `remember_report`

```python
def remember_report(
    self,
    content: str,
    source_url: str = "",
    published_date: str = "",
    domain: str = "cti",
    min_importance: int = 3,
    max_facts: int = 10,
    chunk_size: int = 3000
) -> List[Tuple[Optional[MemoryNote], str]]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `content` | `str` | *(required)* | Full report text. Chunked automatically if longer than `chunk_size`. |
| `source_url` | `str` | `""` | URL of the report source. |
| `published_date` | `str` | `""` | Publication date in ISO 8601 format. Injected as temporal context. |
| `domain` | `str` | `"cti"` | Memory domain. |
| `min_importance` | `int` | `3` | Importance threshold for extracted facts. |
| `max_facts` | `int` | `10` | Maximum facts per chunk. |
| `chunk_size` | `int` | `3000` | Maximum characters per chunk before splitting on sentence boundaries. |

**Returns:** `List[Tuple[Optional[MemoryNote], str]]` -- aggregated results across all chunks.

**Chunking:** Splits on sentence boundaries (`. `) when content exceeds `chunk_size`. Each chunk is processed independently through `remember_with_extraction`. Source refs are suffixed with `:chunk:N`.

```python
results = mm.remember_report(
    content=long_report_text,
    source_url="https://secureworks.com/research/volt-typhoon-2024",
    published_date="2024-12-15",
    domain="cti"
)
print(f"Extracted {len(results)} facts from report")
```

---

## Read Methods

### `recall`

```python
def recall(
    self,
    query: str,
    domain: Optional[str] = None,
    k: int = 10,
    include_links: bool = True,
    exclude_superseded: bool = True
) -> List[MemoryNote]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `query` | `str` | *(required)* | Natural language query. |
| `domain` | `Optional[str]` | `None` | Filter results to this domain. `None` searches all domains. |
| `k` | `int` | `10` | Maximum number of results to return. |
| `include_links` | `bool` | `True` | Expand results to include directly linked notes. |
| `exclude_superseded` | `bool` | `True` | Filter out notes that have been superseded by newer notes. |

**Returns:** `List[MemoryNote]` -- ranked by blended score (vector similarity + graph proximity).

**Retrieval pipeline:**
1. Intent classification (keyword + LLM fallback).
2. Entity extraction and alias resolution from query.
3. Vector retrieval via LanceDB (fallback: in-memory cosine similarity).
4. Graph retrieval via BFS from query entities.
5. Blended ranking using intent-based policy weights.
6. Superseded note filtering.
7. Access count increment on returned notes.

```python
notes = mm.recall("What tools does APT28 use?", domain="cti", k=5)
for note in notes:
    print(f"{note.id}: {note.semantic.context}")
```

### `recall_entity`

```python
def recall_entity(
    self,
    entity_type: str,
    entity_value: str,
    k: int = 5
) -> List[MemoryNote]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `entity_type` | `str` | *(required)* | Entity type. Values: `cve`, `actor`, `tool`, `campaign`, `sector`, `asset`. |
| `entity_value` | `str` | *(required)* | Entity value (case-insensitive lookup). |
| `k` | `int` | `5` | Maximum results. |

**Returns:** `List[MemoryNote]` -- notes indexed against this entity.

### `recall_cve`

```python
def recall_cve(self, cve_id: str, k: int = 5) -> List[MemoryNote]
```

Convenience wrapper. Calls `recall_entity('cve', cve_id.upper(), k)`.

### `recall_actor`

```python
def recall_actor(self, actor_name: str, k: int = 5) -> List[MemoryNote]
```

Convenience wrapper. Calls `recall_entity('actor', actor_name.lower(), k)`.

### `recall_tool`

```python
def recall_tool(self, tool_name: str, k: int = 5) -> List[MemoryNote]
```

Convenience wrapper. Calls `recall_entity('tool', tool_name.lower(), k)`.

### `get_context`

```python
def get_context(
    self,
    query: str,
    domain: Optional[str] = None,
    k: int = 10,
    token_budget: int = 4000
) -> str
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `query` | `str` | *(required)* | Natural language query. |
| `domain` | `Optional[str]` | `None` | Domain filter. |
| `k` | `int` | `10` | Maximum notes to retrieve. |
| `token_budget` | `int` | `4000` | Approximate token limit for output. Truncates at `token_budget * 4` characters. |

**Returns:** `str` -- formatted Markdown context block for agent prompt injection. Returns `"No relevant memories found."` if no results.

**Output format:**
```
## Relevant Memories (N notes)

### [1] note_20240315_143022_abc1 (confidence: 0.95, 2024-03-15)
Context: One-sentence summary
Content: First 300 characters...
Related: note_id_1, note_id_2
```

---

## Graph Methods

### `get_entity_relationships`

```python
def get_entity_relationships(
    self,
    entity_type: str,
    entity_value: str
) -> List[Dict]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `entity_type` | `str` | *(required)* | Entity type (e.g., `actor`, `tool`, `cve`). |
| `entity_value` | `str` | *(required)* | Entity value. Alias-resolved before lookup. |

**Returns:** `List[Dict]` -- direct neighbors from the knowledge graph.

### `traverse_graph`

```python
def traverse_graph(
    self,
    start_type: str,
    start_value: str,
    max_depth: int = 2
) -> List[Dict]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `start_type` | `str` | *(required)* | Starting entity type. |
| `start_value` | `str` | *(required)* | Starting entity value. Alias-resolved before traversal. |
| `max_depth` | `int` | `2` | Maximum BFS hops. |

**Returns:** `List[Dict]` -- all reachable nodes within `max_depth` hops.

---

## Synthesis Methods

### `synthesize`

```python
def synthesize(
    self,
    query: str,
    format: str = "direct_answer",
    k: int = 10,
    tier_filter: List[str] = None
) -> Dict[str, Any]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `query` | `str` | *(required)* | The question to answer. |
| `format` | `str` | `"direct_answer"` | Output format. Values: `direct_answer`, `synthesized_brief`, `timeline_analysis`, `relationship_map`. |
| `k` | `int` | `10` | Number of notes to retrieve for context. |
| `tier_filter` | `List[str]` | `None` | Filter by epistemic tier. Values: `["A"]`, `["A", "B"]`, `["A", "B", "C"]`. `None` uses config default. |

**Returns:** `Dict[str, Any]` -- synthesis result with keys for the synthesis output, metadata, and source notes.

```python
result = mm.synthesize(
    "What do we know about APT28?",
    format="synthesized_brief",
    tier_filter=["A", "B"]
)
print(result["synthesis"]["summary"])
```

### `validate_synthesis`

```python
def validate_synthesis(self, response: Dict) -> Tuple[bool, List[str]]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `response` | `Dict` | *(required)* | Synthesis response from `synthesize()`. |

**Returns:** `Tuple[bool, List[str]]` -- `(is_valid, list_of_error_strings)`.

### `check_synthesis_quality`

```python
def check_synthesis_quality(self, response: Dict) -> Dict
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `response` | `Dict` | *(required)* | Synthesis response from `synthesize()`. |

**Returns:** `Dict` -- quality metrics including `score` (0.0--1.0) and `grade`.

---

## Utility Methods

### `get_stats`

```python
def get_stats(self) -> Dict
```

**Returns:** `Dict` with keys:

| Key | Type | Description |
|:----|:-----|:------------|
| `notes_created` | `int` | Notes created in this session. |
| `retrievals` | `int` | Number of `recall()` calls. |
| `entity_index_hits` | `int` | Number of `recall_entity()` calls. |
| `total_notes` | `int` | Total notes in the store. |
| `entity_index` | `Dict` | Entity index statistics from `EntityIndexer`. |

### `mark_note_superseded`

```python
def mark_note_superseded(
    self,
    note_id: str,
    superseded_by_id: str
) -> bool
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `note_id` | `str` | *(required)* | ID of the note to mark as superseded. |
| `superseded_by_id` | `str` | *(required)* | ID of the newer note that supersedes it. |

**Returns:** `bool` -- `True` if successful, `False` if either note ID is not found.

**Side effects:** Updates both notes' link fields, rewrites to store, and adds a `SUPERSEDES` temporal edge to the knowledge graph.

### `snapshot`

```python
def snapshot(self) -> str
```

**Returns:** `str` -- file path of the exported JSONL snapshot. Written to `~/.amem/snapshots/notes_YYYYMMDD_HHMMSS.jsonl`.

---

## Global Accessor

```python
def get_memory_manager() -> MemoryManager
```

Returns the singleton `MemoryManager` instance. Creates one with default paths on first call.

---

## MemoryNote Schema

Module: `zettelforge.note_schema`

```python
from zettelforge.note_schema import MemoryNote
```

`MemoryNote` is a Pydantic `BaseModel` with the following structure:

### Top-Level Fields

| Field | Type | Default | Description |
|:------|:-----|:--------|:------------|
| `id` | `str` | *(required)* | Format: `note_YYYYMMDD_HHMMSS_xxxx`. |
| `version` | `int` | `1` | Schema version, incremented on evolution. |
| `created_at` | `str` | *(required)* | ISO 8601 timestamp. |
| `updated_at` | `str` | *(required)* | ISO 8601 timestamp. |
| `evolved_from` | `Optional[str]` | `None` | ID of the note this was evolved from. |
| `evolved_by` | `List[str]` | `[]` | IDs of notes that evolved from this note. |
| `content` | `Content` | *(required)* | Raw content and source metadata. |
| `semantic` | `Semantic` | *(required)* | LLM-generated semantic enrichment. |
| `embedding` | `Embedding` | *(required)* | Embedding vector and metadata. |
| `links` | `Links` | `Links()` | Conceptual links to other notes. |
| `metadata` | `Metadata` | `Metadata()` | Lifecycle and access metadata. |

### Content

```python
class Content(BaseModel):
    raw: str
    source_type: str   # conversation | task_output | ingestion | observation
    source_ref: str     # subagent:task_id or conversation:session_id
```

### Semantic

```python
class Semantic(BaseModel):
    context: str                                      # One-sentence contextual summary
    keywords: List[str] = Field(max_length=7)         # Up to 7 keywords
    tags: List[str] = Field(max_length=5)             # Up to 5 tags
    entities: List[str] = Field(default_factory=list)  # Extracted entity strings
```

### Embedding

```python
class Embedding(BaseModel):
    model: str = "nomic-embed-text-v2-moe"
    vector: List[float] = []
    dimensions: int = 768
    input_hash: str = ""   # SHA256 of concatenated text fields
```

### Links

```python
class Links(BaseModel):
    related: List[str] = []             # IDs of related notes
    superseded_by: Optional[str] = None  # ID of newer note that replaces this one
    supersedes: List[str] = []          # IDs of older notes this one replaces
    causal_chain: List[str] = []        # Ordered list of causally linked note IDs
```

### Metadata

```python
class Metadata(BaseModel):
    access_count: int = 0
    last_accessed: Optional[str] = None      # ISO 8601 timestamp
    evolution_count: int = 0
    confidence: float = 1.0                  # Decays on evolution (floor: 0.95 per step)
    ttl: Optional[int] = None                # Time-to-live in days
    domain: str = "general"                  # general | cti | incident | threat_intel | project | personal | research
    tier: str = "B"                          # A (authoritative) | B (operational) | C (support)
    importance: int = 5                      # 1-10 scale
```

### Instance Methods

| Method | Signature | Description |
|:-------|:----------|:------------|
| `increment_access` | `() -> None` | Increments `access_count`, sets `last_accessed` to now. |
| `increment_evolution` | `(evolved_by_note_id: str) -> None` | Increments `evolution_count`, appends to `evolved_by`, caps confidence at 0.95. |
| `should_flag_for_review` | `() -> bool` | Returns `True` if `confidence < 0.5` or `evolution_count > 5`. |

---

## LLM Quick Reference

MemoryManager is the primary agent interface for ZettelForge's agentic memory system. It provides three categories of operations: write, read, and synthesis.

**Write path:** `remember()` is the unified entry point. With `evolve=False` (default in Python), it stores a note with entity extraction, alias resolution, supersession checking, and knowledge graph update. With `evolve=True` (default in MCP/web API), it additionally runs the two-phase Mem0-style pipeline: LLM extraction of salient facts followed by per-fact ADD/UPDATE/DELETE/NOOP decisions against existing memory. By default (`sync=False`), causal enrichment is deferred to a background worker and the call returns in ~45ms; pass `sync=True` to block until enrichment completes. `remember_with_extraction()` is the underlying method for programmatic use. `remember_report()` extends this to long-form content by chunking on sentence boundaries before extraction.

**Read path:** `recall()` is the primary retrieval method. It classifies query intent (FACTUAL, TEMPORAL, RELATIONAL, CAUSAL, EXPLORATORY), then blends vector similarity and graph traversal results using intent-specific policy weights. Superseded notes are filtered by default. `recall_entity()`, `recall_cve()`, `recall_actor()`, and `recall_tool()` provide fast entity-indexed lookups that bypass vector search. `get_context()` formats retrieved notes as Markdown for prompt injection with a configurable token budget.

**Graph path:** `get_entity_relationships()` returns direct neighbors for an entity. `traverse_graph()` performs BFS up to `max_depth` hops. Both resolve aliases before lookup.

**Synthesis path:** `synthesize()` generates RAG answers in four formats: `direct_answer`, `synthesized_brief`, `timeline_analysis`, and `relationship_map`. Results can be validated with `validate_synthesis()` and scored with `check_synthesis_quality()`. Tier filtering controls which epistemic quality levels of notes feed into synthesis.

**MemoryNote schema:** Notes have five sub-models: Content (raw text + provenance), Semantic (LLM-generated context, keywords, tags, entities), Embedding (768-dim nomic-embed-text-v2-moe vector), Links (related, superseded_by, supersedes, causal_chain), and Metadata (access tracking, confidence decay, TTL, domain, tier, importance). Notes are flagged for review when confidence drops below 0.5 or evolution count exceeds 5.

**Singleton access:** Call `get_memory_manager()` to get the global instance. Configuration is loaded from `config.yaml` or `config.default.yaml` with environment variable overrides.
