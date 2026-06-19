# Governance

## Maintainer

ZettelForge is maintained by Patrick Roland (@rolandpg).

## Licensing Commitment

ZettelForge is MIT licensed. This will not change.

## Design Commitment: Brain-Inspired Memory Architecture

ZettelForge is modeled on the brain by deliberate decision, not metaphor. This
commitment is binding on the architecture and will not be quietly abandoned.

The memory engine is dual-hemisphere. A symbolic left hemisphere (a typed,
STIX/ATT&CK-aligned knowledge graph with schema enforcement and rule-based
inference) is the authority of record: precise, constraint-checked, and
explainable. An associative right hemisphere (blended vector and graph retrieval,
GraphRAG, and agentic synthesis) explores and proposes, and writes back into the
symbolic layer only through validated paths. The two layers stay distinct.

Underneath both, knowledge is represented as atomic facts connected by directed,
time-stamped, pairwise associations (the Cognitive Data Model, Pieris 2025). Time
and provenance are first-class primitives: every note and claim carries its
source, markings (TLP), confidence, and time validity, and every retrieval result
carries provenance. Ingested content is untrusted and is sanitized or isolated
before any model call. Quantitative quality or performance claims are reproduced
on the project's own CTI benchmark suite before being stated as fact.

Changes to storage, retrieval, the knowledge graph, or ingestion MUST preserve
this model, and design decisions SHOULD cite the relevant hemisphere or layer.
The full rationale and research basis are in
[docs/explanation/design-philosophy-dual-hemisphere.md](docs/explanation/design-philosophy-dual-hemisphere.md).

## Extension Boundary

The extension package (`zettelforge-enterprise`) provides features
that require external infrastructure (TypeDB, OpenCTI, multi-tenant
OAuth). The open source project will never be degraded to create
commercial incentive.

Rule: if a feature works with JSONL + local embeddings, it belongs
in this repo.

## Contributions

Community contributions are reviewed on their technical merits.
All contributions to this repository remain MIT licensed.
