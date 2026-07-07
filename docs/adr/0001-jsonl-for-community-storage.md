# ADR-001: JSONL for community storage

**Date:** 2026-07-02

**Status:** Accepted

## Context

ZettelForge's community edition needed a persistence layer for notes, knowledge graph nodes, and edges from day one. A relational database like SQLite offers transactions and indexed queries, but it adds schema migrations, binary files that are opaque to users, and more moving parts for a young project whose data model was still evolving rapidly.

## Decision

Use append-only JSONL (newline-delimited JSON) files as the community storage format — `kg_nodes.jsonl`, `kg_edges.jsonl`, and note stores — rather than adopting SQLite from day one.

## Consequences

**Pros:**

- Zero configuration: no schema setup, migrations, or database drivers required.
- Human-readable and grep-able — analysts can inspect and debug their memory store with standard text tools.
- Append-only writes are simple, crash-tolerant, and naturally preserve an audit trail.
- Trivially diffable and portable; files can be versioned, backed up, or shipped between hosts.
- The data model could evolve without lockstep schema migrations.

**Cons:**

- No indexed queries; the full file must be loaded and cached in memory.
- No transactional guarantees across multiple files.
- Performance degrades as stores grow large, which eventually motivated an optional SQLite backend and a JSONL-to-SQLite migration path (see `docs/how-to/migrate-jsonl-to-sqlite.md`).
- Concurrent writers must be coordinated at the application layer.
