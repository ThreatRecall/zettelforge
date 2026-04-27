"""
ZettelForge × LangChain Integration

Provides a LangChain-compatible retriever that wraps ZettelForge's
MemoryManager.recall() method, allowing ZettelForge to be used as a
retriever in any LangChain RAG pipeline.

Usage:
    >>> from langchain_core.runnables import RunnableConfig
    >>> from zettelforge import MemoryManager
    >>> from zettelforge.integrations.langchain_retriever import ZettelForgeRetriever
    >>>
    >>> mm = MemoryManager()
    >>> mm.remember("APT28 uses spear-phishing with credential-harvesting links")
    >>> retriever = ZettelForgeRetriever(memory_manager=mm, k=5)
    >>> docs = retriever.invoke("What techniques does APT28 use?")
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from zettelforge.memory_manager import MemoryManager


class ZettelForgeRetriever(BaseRetriever):
    """LangChain retriever wrapping ZettelForge's blended recall.

    Converts ZettelForge MemoryNotes into LangChain Documents with
    rich metadata (source, tier, confidence, keywords, tags, entities).

    Args:
        memory_manager: A ZettelForge MemoryManager instance.
        k: Number of results to return (default 10).
        domain: Optional domain filter (e.g. "security_ops").
        include_links: Whether to include graph-linked notes (default True).
        exclude_superseded: Whether to filter superseded notes (default True).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    memory_manager: MemoryManager = Field(exclude=True)
    k: int = 10
    domain: str | None = None
    include_links: bool = True
    exclude_superseded: bool = True

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        """Retrieve documents from ZettelForge memory.

        Calls MemoryManager.recall() and converts each MemoryNote
        into a LangChain Document with page_content and metadata.
        """
        notes = self.memory_manager.recall(
            query=query,
            domain=self.domain,
            k=self.k,
            include_links=self.include_links,
            exclude_superseded=self.exclude_superseded,
        )

        documents: list[Document] = []
        for note in notes:
            metadata: dict[str, Any] = {
                "note_id": note.id,
                "source_type": note.content.source_type,
                "source_ref": note.content.source_ref,
                "context": note.semantic.context,
                "keywords": note.semantic.keywords,
                "tags": note.semantic.tags,
                "entities": note.semantic.entities,
                "domain": note.metadata.domain,
                "tier": note.metadata.tier,
                "confidence": note.metadata.confidence,
                "importance": note.metadata.importance,
                "created_at": note.created_at,
                "updated_at": note.updated_at,
            }
            # Include CVE metadata if present
            if note.metadata.vuln is not None:
                metadata["cvss_v3_score"] = note.metadata.vuln.cvss_v3_score
                metadata["cisa_kev"] = note.metadata.vuln.cisa_kev

            documents.append(
                Document(
                    page_content=note.content.raw,
                    metadata=metadata,
                )
            )

        return documents
