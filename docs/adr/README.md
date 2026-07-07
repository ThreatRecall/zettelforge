# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for ZettelForge. ADRs document significant architecture decisions: the context in which they were made, the decision itself, and its consequences. They explain *why* things are built the way they are, so contributors and users can understand trade-offs without digging through commit history.

## Format

Each ADR follows [Michael Nygard's template](https://adr.github.io/):

- **Title** — Short noun phrase describing the decision
- **Date** — When the decision was recorded
- **Status** — Proposed, Accepted, Deprecated, or Superseded
- **Context** — The forces at play and the problem being solved
- **Decision** — What we chose to do
- **Consequences** — The resulting trade-offs, both positive and negative

ADRs are numbered sequentially (`0001`, `0002`, ...) and are immutable once accepted. If a decision changes, write a new ADR that supersedes the old one rather than editing it.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](0001-jsonl-for-community-storage.md) | JSONL for community storage | Accepted |
| [ADR-002](0002-blended-retrieval-vector-plus-graph.md) | Blended retrieval (vector + graph) | Accepted |
| [ADR-003](0003-in-process-llm-llama-cpp-python.md) | In-process LLM (llama-cpp-python) | Accepted |
| [ADR-004](0004-stix-2.1-entity-types.md) | STIX 2.1 entity types | Accepted |

## References

- [ADR format overview](https://adr.github.io/)
- [Example ADR collection](https://github.com/joelparkerhenderson/architecture-decision-record)
