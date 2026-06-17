# Design philosophy: dual-hemisphere CTI memory

This document explains why ZettelForge is built the way it is. The architecture
is modeled on the brain by deliberate decision, and that decision is grounded in
published cognitive-science and threat-intelligence research. Contributors
working on storage, retrieval, the knowledge graph, or ingestion should treat the
principles here as design doctrine and cite the relevant layer when justifying a
change. The binding form of this commitment lives in `GOVERNANCE.md`.

## In one paragraph

ZettelForge separates precise, rule-bound recall from associative, exploratory
reasoning, the way the brain separates them. A symbolic "left hemisphere" (a
typed, STIX-aligned knowledge graph with schema enforcement and rule-based
inference) is the authority of record: precise, constraint-checked, explainable.
An associative "right hemisphere" (blended vector and graph retrieval with
GraphRAG-style synthesis) explores and proposes. Both rest on a shared,
evidence-grounded, time-stamped data model: atomic facts connected by directed,
time-stamped, pairwise associations, where time and provenance are first-class
primitives. Every retrieved answer carries provenance and markings.

## The research foundation

Three independent lines of work converge on this design. We adopt the
convergence, not any single paper.

### Layer 0: the Cognitive Data Model (the data-modeling basis)

Pieris (2025, arXiv:2503.20041) argues that the brain organizes knowledge with a
logical data model independent of its anatomy, with three properties we adopt:

- Atomic things: knowledge is built from granular concepts expressible in words
  (an actor, a CVE, an IOC), not compound rows with hidden structure.
- Directed pairwise associations: concepts connect two at a time, in a
  member-to-owner direction; a thing plays one role per association.
- First-class time: every thing carries a continuously updating time attribute,
  and every association records the moment it formed plus a reference to what it
  connected.

CTI knowledge is intrinsically a time-stamped graph of atomic facts:
infrastructure churns, confidence decays, actors reappear, indicators expire. A
model where time and directed association are primitives is the correct substrate
for a memory of evidence-backed claims.

### Layer 1: the dual-hemisphere architecture (the system shape)

Cortical semantic cognition pairs sequential, rule-based association with flexible
integration through a deep semantic hub with sparse connections (Jackson, Rogers
and Ralph, 2019, Nature Human Behaviour; Nowinski, 2021). Translated to
architecture:

- Left hemisphere: a typed CTI ontology layer. STIX-aligned classes and
  relations, schema enforcement, datatypes for timestamps, confidence and
  markings, and rule-based inference for risk propagation, alias deduplication,
  and indirect relationships. Grounded in ontology-based CTI work (Riesco and
  Villagra, 2019; Merah and Kenaza, 2021) and CTI knowledge-graph construction
  (CSKG4APT, Ren et al. 2023; LLM-TIKG, Hu et al. 2024; ATT&CK-to-CVE, Rahman et
  al. 2025).
- Right hemisphere: an agentic GraphRAG layer over a property graph, where a
  pipeline decomposes a question, runs hybrid subgraph and vector search,
  aggregates evidence paths, and synthesizes a grounded answer, with newly
  derived facts written back into the graph. Grounded in the GraphRAG three-stage
  formalism (Peng et al. 2024) and agentic-RAG surveys (Singh et al. 2025;
  Nguyen et al. 2025; Liu et al. 2025).

Reported benefits from this literature, which we treat as motivation until
reproduced on our own benchmarks: hybrid graph plus text retrieval improves
multi-hop QA by up to 35 percent over vector-only RAG (Hamzic et al. 2026; Yu et
al. 2025), and structure-aware, schema-constrained retrieval reduces unsupported
statements substantially (Bussari et al. 2026).

### Layer 2: engineering principles (how to build it well)

From the agent-memory and CTI-standards literature (A-MEM, Mem0, GraphRAG; STIX
2.1, MITRE ATT&CK, FIRST TLP, OpenCTI), the build standard is:

1. A claim-and-evidence model: immutable evidence (raw artifacts, spans, hashes,
   collector, markings, trust) separated from extracted, deduplicated,
   time-bounded claims, linked by an explicit claim-to-evidence relation.
2. Hybrid dense plus sparse retrieval by default, with reranking applied after
   filtering on markings, provenance, and time.
3. First-class temporal and provenance tracking: validity windows, "as of"
   queries, and supersession are queryable primitives, not metadata filters.
4. Native markings and dissemination control (TLP, marking restriction) at the
   memory-object level, not only at the API perimeter.
5. Ingestion treated as a threat surface: source trust scoring, content
   sanitization before extraction, and provenance enforcement (OWASP GenAI Top
   10).
6. A CTI-specific benchmark suite (CTIBench, CTI-REALM, LoCoMo, RAGAS,
   ATT&CK-aligned and provenance regressions) with provenance completeness and
   marking-leakage rate as first-class metrics.

## How ZettelForge embodies this

The design above is not aspirational; the core is implemented:

- Left hemisphere: the typed knowledge graph with a STIX 2.1 ontology (TypeDB
  extension) and seeded alias resolution; the default SQLite backend stores
  notes, graph nodes, graph edges, and the entity index with foreign keys and
  WAL mode.
- Right hemisphere: the `BlendedRetriever` fuses vector similarity (LanceDB,
  768-dim, in-process fastembed) with graph traversal, weighted by an
  `IntentClassifier` that routes each query (factual, temporal, relational,
  causal, exploratory); a cross-encoder reranks results, and synthesis runs as
  RAG-as-Answer with quality validation.
- Shared data model: the `MemoryNote` schema separates raw content, semantic
  annotations, and operational metadata (source, tier, confidence, time);
  enrichment runs causal-triple extraction and A-Mem-style neighbor refinement.
- Time and provenance: timestamps, recency weighting, causal triples, and
  epistemic tiers are present; promoting full claim-level validity windows and
  "as of" recall to first-class primitives is the leading open increment.

The honest gaps the research names, in priority order: a first-class claim layer
(claim and evidence separated, with supersession and validity windows), temporal
"as of" recall and confidence decay as primitives, and a CTI benchmark harness
that turns the cited literature figures into measured numbers for this codebase.

## Doctrine for contributors

1. Default to the dual-hemisphere split: precise, schema-checked, standards-aligned
   work belongs in the symbolic layer; exploratory, multi-hop synthesis belongs in
   the associative layer. Do not blur them.
2. Treat time and provenance as primitives, not metadata. New artifacts carry
   source, markings, confidence, and time validity; recall results carry
   provenance.
3. The symbolic layer is the authority of record. The associative layer explores
   and proposes; it writes back only through validated paths.
4. Ingestion is untrusted. Sanitize or isolate external content before any model
   call.
5. Benchmark before claiming. External literature figures are motivation; report
   measured numbers from this codebase as fact.

## References

Cognitive and architectural foundation:
- Pieris, D. (2025). Toward a Cognitive Data Model: Exploring a Mind-Inspired Approach to Database Design. arXiv:2503.20041.
- Jackson, R., Rogers, T., and Ralph, M. L. L. (2019). Reverse-Engineering the Cortical Architecture for Controlled Semantic Cognition. Nature Human Behaviour, 5, 774-786.
- Nowinski, W. (2021). Towards an Architecture of a Multi-purpose, User-Extendable Reference Human Brain Atlas. Neuroinformatics, 20, 405-426.

GraphRAG and agentic retrieval:
- Peng, B., et al. (2024). Graph Retrieval-Augmented Generation: A Survey. ACM TOIS, 44.
- Han, H., et al. (2024). Retrieval-Augmented Generation with Graphs (GraphRAG). arXiv:2501.00309.
- Singh, A., et al. (2025). Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG. arXiv:2501.09136.
- Nguyen, T., et al. (2025). MA-RAG: Multi-Agent Retrieval-Augmented Generation via Collaborative Chain-of-Thought Reasoning. arXiv:2505.20096.
- Liu, P., et al. (2025). HM-RAG: Hierarchical Multi-Agent Multimodal Retrieval Augmented Generation. ACM MM 2025.
- Yu, C., et al. (2025). GraphRAG-R1: Graph Retrieval-Augmented Generation with Process-Constrained RL. ACM Web Conference 2026.

CTI knowledge graphs, reasoning, and evaluation:
- Hamzic, D., et al. (2026). Beyond RAG for Cyber Threat Intelligence: A Systematic Evaluation of Graph-Based and Agentic Retrieval.
- Bussari, S., et al. (2026). RAGSec: Retrieval-Augmented Generation for Cybersecurity Threat Intelligence in Enterprise Networks. IEEE ICAIC 2026.
- Yang, X., et al. (2026). CTI-Thinker: an LLM-driven system for CTI knowledge graph construction and attack reasoning. Cybersecurity, 9.
- Hu, Y., et al. (2024). LLM-TIKG: Threat intelligence knowledge graph construction using LLMs. Computers and Security, 145.
- Ren, Y., et al. (2023). CSKG4APT: A Cybersecurity Knowledge Graph for APT Organization Attribution. IEEE TKDE, 35.
- Rahman, M., et al. (2025). ATT&CK-to-CVE: A Large-Scale Automated Knowledge Graph for Threat Intelligence. IEEE ICDMW 2025.
- Riesco, R., and Villagra, V. (2019). Leveraging cyber threat intelligence for a dynamic risk framework. International Journal of Information Security, 18, 715-739.
- Merah, Y., and Kenaza, T. (2021). Proactive Ontology-based Cyber Threat Intelligence Analytic. ICRAMI 2021.
- Bratsas, C., et al. (2024). Knowledge Graphs and Semantic Web Tools in Cyber Threat Intelligence: A Systematic Literature Review. J. Cybersecurity and Privacy, 4.

Standards and security: STIX 2.1 (OASIS), MITRE ATT&CK, FIRST TLP 2.0, OpenCTI, OWASP GenAI/LLM Top 10. Agent-memory systems: A-MEM, Mem0, H-Mem, GraphRAG, LoCoMo, CTIBench, CTI-REALM, RAGAS.
