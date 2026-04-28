"""
ZettelForge: Agentic Memory System

A production-grade memory system for AI agents with:
- Vector semantic search
- Knowledge graph relationships
- Entity extraction and indexing
- RAG-as-answer synthesis
- Intent-based query routing

Community edition (MIT):
    >>> from zettelforge import MemoryManager
    >>> mm = MemoryManager()
    >>> mm.remember("Important information")
    >>> results = mm.recall("query")
    >>> synthesis = mm.synthesize("What do we know?")

Enterprise edition (ThreatRecall by Threatengram) adds:
    - STIX 2.1 TypeDB ontology
    - Blended retrieval (vector + graph)
    - OpenCTI integration
    - Sigma rule generation
    - Advanced synthesis formats
    - Multi-tenant auth
    See https://threatengram.com/enterprise
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

__version__ = "2.1.1"
__all__ = [
    # Edition
    "Edition",
    "get_edition",
    "is_enterprise",
    "is_community",
    "edition_name",
    "EditionError",
    # Core
    "MemoryManager",
    "get_memory_manager",
    "MemoryNote",
    "VectorRetriever",
    "SynthesisGenerator",
    "get_synthesis_generator",
    "SynthesisValidator",
    "get_synthesis_validator",
    # Knowledge Graph
    "KnowledgeGraph",
    "get_knowledge_graph",
    # Retrieval
    "GraphRetriever",
    "ScoredResult",
    "BlendedRetriever",
    # Ontology
    "TypedEntityStore",
    "OntologyValidator",
    "get_ontology_store",
    "get_ontology_validator",
    "ENTITY_TYPES",
    "RELATION_TYPES",
    # Intent Classification
    "IntentClassifier",
    "get_intent_classifier",
    "QueryIntent",
    # Note Constructor
    "NoteConstructor",
    # Two-Phase Pipeline
    "FactExtractor",
    "ExtractedFact",
    "MemoryUpdater",
    "UpdateOperation",
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
