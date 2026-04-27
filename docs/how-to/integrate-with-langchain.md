---
title: "Integrate with LangChain"
description: "Use ZettelForge as a retriever in LangChain RAG pipelines, providing blended vector and graph search over CTI memory."
diataxis_type: "how-to"
audience: "Developers building LangChain RAG applications over CTI knowledge, security engineers extending LLM pipelines with ZettelForge memory"
tags: [langchain, rag, retriever, vector-search, graph-search, integration]
last_updated: "2026-04-27"
version: "2.7.0"
---

# Integrate with LangChain

Use ZettelForge as a LangChain-compatible retriever in any RAG pipeline. The
`ZettelForgeRetriever` wraps `MemoryManager.recall()` and converts ZettelForge
`MemoryNote` objects into LangChain `Document` objects with rich metadata.

## Prerequisites

- ZettelForge installed (`pip install zettelforge`)
- LangChain installed: `pip install langchain-core langchain-community`
- Embedding and LLM models available (download automatically on first use)

## Steps

### 1. Create a MemoryManager and seed it

```python
from zettelforge import MemoryManager

mm = MemoryManager()

# Seed with CTI-relevant memories
mm.remember(
    "APT28 (Fancy Bear) uses spear-phishing emails with credential-harvesting links. "
    "They have been observed using domains mimicking NATO and defense contractors.",
    domain="security_ops",
)
mm.remember(
    "CVE-2024-3094: XZ Utils backdoor in versions 5.6.0 and 5.6.1. "
    "CVSS score 10.0. Supply chain attack affecting SSH authentication.",
    domain="security_ops",
)
```

### 2. Create the retriever

```python
from zettelforge.integrations.langchain_retriever import ZettelForgeRetriever

retriever = ZettelForgeRetriever(
    memory_manager=mm,
    k=5,                     # Number of documents to return
)
```

### 3. Use the retriever directly

```python
docs = retriever.invoke("What techniques does APT28 use?")

for doc in docs:
    print(f"Note ID: {doc.metadata['note_id']}")
    print(f"Domain: {doc.metadata['domain']}")
    print(f"Content: {doc.page_content[:100]}...")
    print("---")
```

### 4. Use the retriever in a LangChain RAG chain

```python
from langchain.chains import RetrievalQA
from langchain_ollama import ChatOllama

llm = ChatOllama(model="qwen3.5:9b", temperature=0.1)

qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever=retriever,
)

answer = qa_chain.invoke("What is known about APT28's spear-phishing?")
print(answer["result"])
```

### 5. Configure retriever parameters

```python
# Filter by domain
retriever = ZettelForgeRetriever(
    memory_manager=mm,
    k=10,
    domain="security_ops",    # Only search notes in this domain
)

# Control graph-linked notes and superseded filtering
retriever = ZettelForgeRetriever(
    memory_manager=mm,
    k=10,
    include_links=True,       # Include graph-linked notes (default True)
    exclude_superseded=True,  # Exclude superseded notes (default True)
)
```

### 6. Use as part of a conversational RAG pipeline

```python
from langchain.memory import ConversationBufferMemory
from langchain.chains import ConversationalRetrievalChain

memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
)

conversational_chain = ConversationalRetrievalChain.from_llm(
    llm=llm,
    retriever=retriever,
    memory=memory,
)

result = conversational_chain.invoke({
    "question": "What CVEs were in the XZ Utils incident?"
})
print(result["answer"])
```

### 7. Understand the metadata fields

Each LangChain `Document` carries the following `metadata` dictionary:

| Field | Type | Description |
|:------|:-----|:------------|
| `note_id` | `str` | ZettelForge internal note ID |
| `source_type` | `str` | Source type (e.g., `report`, `conversation`, `sigma_rule`) |
| `source_ref` | `str` | Source reference string |
| `context` | `str` | Semantic context summary |
| `keywords` | `list[str]` | Extracted keywords |
| `tags` | `list[str]` | Semantic tags |
| `entities` | `list[str]` | Extracted entities |
| `domain` | `str` | Memory domain |
| `tier` | `str` | Epistemic tier (A, B, C) |
| `confidence` | `float` | Note confidence score |
| `importance` | `int` | Importance rating (1-10) |
| `created_at` | `str` | ISO 8601 creation timestamp |
| `updated_at` | `str` | ISO 8601 update timestamp |
| `cvss_v3_score` | `float \| None` | CVSS v3 score (CVE notes only) |
| `cisa_kev` | `bool \| None` | CISA KEV status (CVE notes only) |

### 8. Use with a custom prompt template

```python
from langchain.prompts import PromptTemplate

template = """
You are a CTI analyst reviewing intelligence from past investigations.
Use the following pieces of context to answer the question.
If you don't know the answer, say so — do not fabricate information.

Context:
{context}

Question: {question}

Answer with specific entities, techniques, and confidence levels where possible:
"""

prompt = PromptTemplate(
    template=template,
    input_variables=["context", "question"],
)

qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever=retriever,
    chain_type_kwargs={"prompt": prompt},
)
```

## LLM Quick Reference

**Task**: Integrate ZettelForge memory as a LangChain retriever.

**Class**: `ZettelForgeRetriever` from `zettelforge.integrations.langchain_retriever`

**Constructor parameters**:
- `memory_manager: MemoryManager` — required ZettelForge instance
- `k: int = 10` — number of documents to return
- `domain: str | None = None` — filter by memory domain
- `include_links: bool = True` — include graph-linked notes
- `exclude_superseded: bool = True` — exclude superseded notes

**Returns**: `list[Document]` where each `Document.page_content` is the raw
note content and `Document.metadata` contains all ZettelForge metadata fields.

**Blended search**: The retriever uses `MemoryManager.recall()` which performs
blended vector similarity search and knowledge graph traversal, then ranks
results by combined relevance.

**CVE metadata**: Notes with vulnerability data include `cvss_v3_score` and
`cisa_kev` in metadata fields automatically.

**Standard LangChain**: Implements `BaseRetriever` from `langchain_core` so it
works with `RetrievalQA`, `ConversationalRetrievalChain`, `create_retrieval_chain`,
and any other LangChain API that accepts a retriever.

**Serialization**: The retriever uses Pydantic `ConfigDict(arbitrary_types_allowed=True)`
so the `MemoryManager` field is accepted as an arbitrary type without validation
errors.
