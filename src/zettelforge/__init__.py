"""
ZettelForge: Agentic Memory System

A production-grade memory system for AI agents with:
- Vector semantic search
- Knowledge graph relationships
- Entity extraction and indexing
- RAG-as-answer synthesis
- Intent-based query routing

Usage:
    >>> from zettelforge import MemoryManager
    >>> mm = MemoryManager()
    >>> mm.remember("Important information")
    >>> results = mm.recall("query")
    >>> synthesis = mm.synthesize("What do we know?")

Optional extensions (e.g. zettelforge-enterprise) add:
    - STIX 2.1 TypeDB ontology
    - Deeper graph traversal
    - Extended synthesis formats
    - OpenCTI integration
"""

from zettelforge.blended_retriever import BlendedRetriever
from zettelforge.edition import (
    Edition,
    EditionError,
    edition_name,
    get_edition,
    is_community,
    is_enterprise,
)
from zettelforge.fact_extractor import ExtractedFact, FactExtractor
from zettelforge.graph_retriever import GraphRetriever, ScoredResult
from zettelforge.intent_classifier import IntentClassifier, QueryIntent, get_intent_classifier
from zettelforge.knowledge_graph import KnowledgeGraph, get_knowledge_graph
from zettelforge.memory_manager import MemoryManager, get_memory_manager
from zettelforge.memory_updater import MemoryUpdater, UpdateOperation
from zettelforge.note_constructor import NoteConstructor
from zettelforge.note_schema import MemoryNote
from zettelforge.ontology import (
    ENTITY_TYPES,
    RELATION_TYPES,
    OntologyValidator,
    TypedEntityStore,
    get_ontology_store,
    get_ontology_validator,
)
from zettelforge.synthesis_generator import SynthesisGenerator, get_synthesis_generator
from zettelforge.synthesis_validator import SynthesisValidator, get_synthesis_validator
from zettelforge.vector_retriever import VectorRetriever

# Note on the ontology module above: ENTITY_TYPES and RELATION_TYPES are
# reference tables consumers use directly. TypedEntityStore / OntologyValidator
# are a parallel store not wired into MemoryManager as of v2.2.0 — they remain
# importable for advanced use but are not part of the advertised public API
# and are therefore excluded from __all__ below.

__version__ = "2.6.2"
__all__ = [
    # Ontology reference tables (TypedEntityStore / OntologyValidator are
    # importable from zettelforge.ontology but are not part of the public API
    # — see the module comment above for details).
    "ENTITY_TYPES",
    "RELATION_TYPES",
    "BlendedRetriever",
    # Edition
    "Edition",
    "EditionError",
    "ExtractedFact",
    # Two-Phase Pipeline
    "FactExtractor",
    # Retrieval
    "GraphRetriever",
    # Intent Classification
    "IntentClassifier",
    # Knowledge Graph
    "KnowledgeGraph",
    # Core
    "MemoryManager",
    "MemoryNote",
    "MemoryUpdater",
    # Note Constructor
    "NoteConstructor",
    "QueryIntent",
    "ScoredResult",
    "SynthesisGenerator",
    "SynthesisValidator",
    "UpdateOperation",
    "VectorRetriever",
    "edition_name",
    "get_edition",
    "get_intent_classifier",
    "get_knowledge_graph",
    "get_memory_manager",
    "get_synthesis_generator",
    "get_synthesis_validator",
    "is_community",
    "is_enterprise",
]

# ── Enterprise-only imports (conditional) ───────────────────────────────────
# These require the separate zettelforge-enterprise package.
# pip install zettelforge-enterprise

if is_enterprise():
    try:
        from zettelforge_enterprise import (
            get_context_injector as _get_ctx_inj,
        )
        from zettelforge_enterprise import (
            get_cti_connector as _get_cti_conn,
        )
        from zettelforge_enterprise import (
            get_sigma_generator as _get_sigma_gen,
        )
        from zettelforge_enterprise import (
            get_typedb_client,
        )

        __all__ += [
            "get_typedb_client",
        ]
    except ImportError:
        pass  # Enterprise package not installed
