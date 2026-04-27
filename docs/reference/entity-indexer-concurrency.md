---
title: "Entity Indexer Concurrency Reference"
description: "Thread-safety guarantees, atomicity model, locking strategy, and crash resilience for the EntityIndexer. Documents RFC-001 Warnings 4, 5, and 6."
diataxis_type: "reference"
audience: "Senior CTI Practitioner, Python developers integrating with ZettelForge"
tags:
  - entity-indexer
  - concurrency
  - thread-safety
  - atomicity
  - locking
last_updated: "2026-04-27"
version: "2.6.0"
---

# Entity Indexer Concurrency Reference

Module: `zettelforge.entity_indexer`

```python
from zettelforge.entity_indexer import EntityIndexer, EntityExtractor
```

---

## Architecture Overview

The `EntityIndexer` maintains an in-memory index mapping entity values to note IDs, persisted to a JSON file on disk. The index is structured as:

```
entity_type -> entity_value -> set[note_id]
```

Example structure after indexing a note about APT28 using Cobalt Strike:

```python
{
    "actor": {"apt28": {"note_abc123"}},
    "tool": {"cobalt-strike": {"note_abc123"}},
    "cve": {},
    # ... 16 more entity type buckets (all 19 ENTITY_TYPES)
}
```

---

## Concurrency Guarantees

### Thread Safety

The indexer is **thread-safe under concurrent read and write**. All mutations (`add_note`, `remove_note`) and persistence (`save`, `load`, `_flush_sync`) are serialized through a single `threading.RLock`.

| Operation | Lock Scope | Safe Under |
|:----------|:-----------|:-----------|
| `add_note(note_id, entities)` | Full mutation + flush scheduling | Concurrent `add_note`, `remove_note`, `save` |
| `remove_note(note_id)` | Full mutation + flush scheduling | Concurrent `add_note`, `remove_note`, `save` |
| `save()` | Full serialize + file write | Concurrent `add_note`, `remove_note`, `_flush_sync` |
| `load()` | Full file read + index rebuild | Isolated (called once in `__init__`) |
| `get_note_ids(etype, evalue)` | **Not locked** (read-only dict access) | Safe under GIL; no mutation |
| `search_entities(query, limit)` | **Not locked** (read-only dict access) | Safe under GIL; no mutation |
| `stats()` | **Not locked** (read-only dict comprehension) | Safe under GIL; no mutation |
| `build()` | Sequential (no concurrent path) | Single-threaded rebuild only |
| `_flush_sync()` | Full dirty-check + save + clear | Concurrent `add_note`, `remove_note` |

**Why RLock?** `_schedule_flush()` is called from within `add_note()` and `remove_note()`, which already hold `_flush_lock`. A plain `threading.Lock` would deadlock on the timer-coordination acquisition inside `_schedule_flush`. RLock allows re-entrance by the same thread.

### Cross-Process Safety

File writes use `fcntl.flock` (advisory lock on the temp file) so two processes won't clobber each other's serialized index. The final write is `os.replace()` (atomic on POSIX).

---

## Locking Strategy

```
add_note() / remove_note()
  |
  +-- acquire _flush_lock (RLock)
  |     +-- mutate self.index dict
  |     +-- set self._dirty = True
  +-- release _flush_lock
  |
  +-- _schedule_flush()
        +-- acquire _flush_lock (re-entrant, no deadlock)
        |     +-- start Timer(5.0, _flush_sync) if not already running
        +-- release _flush_lock

_flush_sync() (called by Timer or atexit)
  |
  +-- acquire _flush_lock
  |     +-- if self._dirty:
  |     |     +-- self.save()      # snapshot + atomic rename
  |     |     +-- self._dirty = False
  +-- release _flush_lock

save()
  |
  +-- acquire _flush_lock
  |     +-- snapshot: dict comprehension over self.index
  +-- release _flush_lock
  |
  +-- write to temp file (flock LOCK_EX on fd)
  |     +-- json.dump(data, f)
  |     +-- os.fsync(f.fileno())
  |     +-- flock LOCK_UN
  +-- os.replace(tmp_path, index_path)   # atomic on POSIX
```

---

## Atomicity Model

### In-Process Atomicity

The `_flush_lock` (RLock) ensures that the dict comprehension in `save()` always sees a consistent snapshot of `self.index`:

```python
with self._flush_lock:
    data = {k: {kk: list(vv) for kk, vv in v.items()} for k, v in self.index.items()}
```

A concurrent `add_note()` cannot modify `self.index` while this comprehension is running because it would block on the same lock.

### Cross-Process Atomicity (File Write)

The `save()` method uses a write-temp-then-rename pattern:

1. Write to `tempfile.mkstemp(prefix=".entity_index.", dir=...)`
2. Acquire `fcntl.flock(f, LOCK_EX)` on the temp file fd
3. `json.dump(data, f)` then `os.fsync(f.fileno())`
4. Release `fcntl.flock(f, LOCK_UN)`
5. `os.replace(tmp_path, index_path)` -- atomic on POSIX

**Crash resilience**: If the process crashes between steps 3 and 5, the `index_path` remains intact (the old file is untouched). The temp file is cleaned up on next startup or left as a harmless orphan.

**No partial writes**: The old implementation truncated `index_path` before acquiring `flock`, leaving the file empty if a crash occurred mid-write. The current implementation never writes directly to the target path.

---

## Background Flush Timer

The indexer defers persistence to avoid thrashing on disk during burst writes:

```python
def _schedule_flush(self) -> None:
    with self._flush_lock:
        if self._flush_timer is None or not self._flush_timer.is_alive():
            self._flush_timer = threading.Timer(5.0, self._flush_sync)
            self._flush_timer.daemon = True
            self._flush_timer.start()
```

- Debounce window: **5 seconds** from the last mutation
- Timer is daemon: does not prevent process exit
- `atexit.register(_flush_sync)`: final flush on clean shutdown
- `build()` cancels any pending timer and saves synchronously before returning

---

## 19-Type Invariant

The indexer initializes with all 19 entity type buckets present as empty dicts:

```python
self.index: dict[str, dict[str, set[str]]] = {
    etype: {} for etype in EntityExtractor.ENTITY_TYPES
}
```

**Warning 5 (RFC-001)**: A previous implementation deleted the entity-type key when its value dict emptied (during `remove_note`). This broke the invariant that `self.index` always contains every key from `ENTITY_TYPES`. Code elsewhere (e.g., `add_note` re-checking `entity_type not in self.index`) relied on this invariant.

**Current behaviour**: `remove_note()` preserves empty parent type buckets. Only per-value sets are pruned:

```python
def remove_note(self, note_id: str) -> None:
    with self._flush_lock:
        for entity_type in list(self.index.keys()):
            for entity_value in list(self.index[entity_type].keys()):
                self.index[entity_type][entity_value].discard(note_id)
                if not self.index[entity_type][entity_value]:
                    del self.index[entity_type][entity_value]  # prune per-value set
            # Parent entity_type dict is NOT deleted even if empty
```

---

## EntityExtractor: Thread Safety

`EntityExtractor` is a **stateless regex + optional LLM** extractor. It holds no mutable state -- all methods take `text` as input and return a new dict:

- `extract_regex(text)` -- pure regex, no side effects
- `extract_llm(text)` -- calls LLM client, no shared state beyond the call
- `extract_all(text, use_llm)` -- orchestrates the above, returns merged dict

No locks needed. Safe to share a single `EntityExtractor` instance across threads.

---

## False Positive Filtering (Hash IOCs)

The `_filter_false_positive_hashes` method removes hex strings (MD5, SHA1, SHA256) that appear in code or VCS contexts:

```python
_CODE_CONTEXT_PATTERN = re.compile(r"""
    (?:
        [a-zA-Z_]\w*\s*=\s*["']?[a-fA-F0-9]{32,64}   # var = hash
      | \bcommit\s+[a-fA-F0-9]{7,40}\b                # git commit
      | \bmerge\s+[a-fA-F0-9]{7,40}\b                 # git merge
      | \btree\s+[a-fA-F0-9]{7,40}\b                  # git tree
      | \bparent\s+[a-fA-F0-9]{7,40}\b                # git parent
      | \bAuthor:\s                                    # git log header
      | ```                                            # code fence
      | \bdef\s+\w                                     # function definition
      | [a-zA-Z_]\w*\([^)]*[a-fA-F0-9]{32,64}         # function call with hash arg
    )
""", re.VERBOSE | re.IGNORECASE)
```

Strategy: scan each line of the input text. If the line matches `_CODE_CONTEXT_PATTERN`, every hex string (32-64 hex chars) on that line is excluded from hash results.

This is a regex-level filter, not a concurrency concern. It runs inside the caller's thread.

---

## Entity Types

The 19 recognized entity types fall into three categories:

### CTI Entities (regex fast-path)

| Type | Example | Pattern |
|:-----|:--------|:--------|
| `cve` | `CVE-2024-3094` | `CVE-\d{4}-\d{4,}` |
| `intrusion_set` | `APT28`, `UNC2452` | `(apt\|unc\|ta\|fin\|temp)\s*-?\s*\d+` |
| `actor` | `lazarus`, `sandworm`, `volt typhoon` | Named match list |
| `tool` | `cobalt strike`, `mimikatz` | Named match list |
| `campaign` | `Operation Midnight` | `operation \w+` |
| `attack_pattern` | `T1059`, `T1059.001` | `T\d{4}(\.\d{3})?` |

### IOCs / STIX Cyber Observables (regex fast-path)

| Type | Example |
|:-----|:--------|
| `ipv4` | `192.168.1.1` |
| `domain` | `evil.example.com` |
| `url` | `https://malware.example/payload` |
| `md5` | `d41d8cd98f00b204e9800998ecf8427e` |
| `sha1` | `a9993e364706816aba3e25717850c26c9cd0d89d` |
| `sha256` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `email` | `user@example.com` |

### Conversational Entities (LLM NER, optional)

| Type | Description |
|:-----|:------------|
| `person` | Named individuals (also regex-matched from dialogue format `Name: text`) |
| `location` | Cities, regions, countries |
| `organization` | Company, agency, group names |
| `event` | Named events |
| `activity` | Named activities |
| `temporal` | Time expressions |

---

## Testing Concurrency

The race-condition regression test (`test_entity_indexer_races.py`) exercises the three documented warnings:

### W-4: Atomic Save

```python
def test_save_uses_atomic_rename_pattern(self, indexer, monkeypatch):
    observed_replaces = []
    real_replace = os.replace
    def _spy(src, dst):
        observed_replaces.append((str(src), str(dst)))
        return real_replace(src, dst)
    monkeypatch.setattr("zettelforge.entity_indexer.os.replace", _spy)
    indexer.add_note("note_a", {"actor": ["APT28"]})
    indexer.save()
    assert any(str(indexer.index_path) == dst for _, dst in observed_replaces)
```

### W-5: 19-Type Invariant

```python
def test_remove_note_preserves_empty_type_bucket(self, indexer):
    assert set(indexer.index.keys()) == set(EntityExtractor.ENTITY_TYPES)
    indexer.add_note("note_a", {"actor": ["APT28"], "tool": ["Cobalt Strike"]})
    indexer.remove_note("note_a")
    assert "actor" in indexer.index       # bucket preserved
    assert indexer.index["actor"] == {}   # empty, but present
    assert set(indexer.index.keys()) == set(EntityExtractor.ENTITY_TYPES)
```

### W-6: Thread-Safe Save + Concurrent Add

```python
def test_save_during_concurrent_add_does_not_raise(self, indexer):
    errors = []
    stop = threading.Event()
    def writer():
        i = 0
        while not stop.is_set() and i < 500:
            indexer.add_note(f"note_{i}", {"actor": [f"APT{i % 5}"]})
            i += 1
    def saver():
        j = 0
        while not stop.is_set() and j < 50:
            indexer.save()
            j += 1
    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=saver)
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)
    stop.set()
    assert errors == []
```

---

## Key Class: EntityIndexer

| Method | Purpose | Thread-Safe | Locks |
|:-------|:--------|:-----------:|:------|
| `__init__(index_path)` | Load index from disk or create empty | No (constructor) | `_flush_lock` |
| `load()` | Load from JSON file | No (called once) | `_flush_lock` |
| `save()` | Persist index atomically | Yes | `_flush_lock` + `fcntl.flock` |
| `add_note(note_id, entities)` | Index entities for a note | Yes | `_flush_lock` |
| `remove_note(note_id)` | Remove note from all entity sets | Yes | `_flush_lock` |
| `get_note_ids(entity_type, entity_value)` | Lookup note IDs by entity | Yes (GIL) | None |
| `search_entities(query, limit)` | Prefix search across types | Yes (GIL) | None |
| `stats()` | Index statistics | Yes (GIL) | None |
| `build()` | Rebuild from all notes | No (sequential) | None |
| `_flush_sync()` | Background persistence | Yes | `_flush_lock` |

---

## Key Class: EntityExtractor

| Method | Purpose | Thread-Safe |
|:-------|:--------|:-----------:|
| `extract_regex(text)` | Regex-only extraction (CTI + IOC + dialogue names) | Yes (stateless) |
| `extract_llm(text)` | LLM NER for conversational entities | Yes (stateless) |
| `extract_all(text, use_llm)` | Combined regex + LLM extraction | Yes (stateless) |
| `_filter_false_positive_hashes(candidates, text)` | Remove hash IOCs in code context | Yes (stateless) |
