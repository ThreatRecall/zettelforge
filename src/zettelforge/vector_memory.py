#!/usr/bin/env python3
"""
vector_memory.py — Cross-session semantic memory using LanceDB + Nomic embeddings

Stores memory entries as vectors for semantic search across ALL sessions.
No external API calls. Everything local.

Usage:
    from zettelforge.vector_memory import VectorMemory
    vm = VectorMemory()
    vm.init()                                    # Init DB
    vm.add('something worth remembering', tags=['decision'])
    results = vm.search('what did we decide about x?')  # Returns top-k matches
"""

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from zettelforge.log import get_logger

_logger = get_logger("zettelforge.vector_memory")


def _sanitize_filter_value(value: str) -> str:
    """Sanitize a value for use in LanceDB WHERE clauses.
    Only allows alphanumeric, hyphen, underscore, dot, colon, and forward slash.
    """
    if not re.match(r"^[a-zA-Z0-9_\-\.:/]+$", value):
        raise ValueError(f"Invalid filter value: {value!r}")
    return value


# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q"
DEFAULT_EMBEDDING_PROVIDER = "fastembed"  # "fastembed" or "ollama"
DEFAULT_EMBEDDING_URL = "http://127.0.0.1:11434"


def get_embedding_provider() -> str:
    """Get embedding provider from environment or default."""
    return os.environ.get("ZETTELFORGE_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER)


def get_embedding_model() -> str:
    """Get embedding model from environment or default."""
    return os.environ.get("AMEM_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def get_embedding_url() -> str:
    """Get embedding server URL (only used when provider=ollama)."""
    return os.environ.get("AMEM_EMBEDDING_URL", DEFAULT_EMBEDDING_URL)


# ── fastembed singleton ──────────────────────────────────────────────────────

_embed_model = None
_embed_lock = threading.Lock()


def _get_embed_model():
    """Get or create the fastembed TextEmbedding model (singleton)."""
    global _embed_model
    if _embed_model is None:
        with _embed_lock:
            if _embed_model is None:
                from fastembed import TextEmbedding

                _embed_model = TextEmbedding(get_embedding_model())
    return _embed_model


def preload_embedding_model() -> None:
    """Force the embedding model to load synchronously.

    [RFC-009 Phase 0.5 / task #39] Without this, the model lazy-loads on the
    first ``get_embedding()`` call, which on Vigil added ~800ms of
    ``construct`` phase time to the first ``remember()`` after process start.
    Calling this once at ``MemoryManager.__init__`` moves the cost off the
    user-visible path. Idempotent; the underlying singleton check is unchanged.
    No-op when the configured provider is not fastembed. Failures are logged
    and swallowed — preload is best-effort, not a hard dependency.
    """
    if get_embedding_provider() != "fastembed":
        return
    try:
        _get_embed_model()
    except Exception:
        _logger.warning("fastembed_preload_failed", exc_info=True)


# ── Embedding ────────────────────────────────────────────────────────────────


def get_embedding(text: str, model: str | None = None) -> list[float]:
    """Generate embedding. Uses fastembed (in-process) by default, ollama/HTTP as fallback."""
    provider = get_embedding_provider()

    if provider == "fastembed":
        try:
            m = _get_embed_model()
            results = list(m.embed([text]))
            return results[0].tolist()
        except Exception:
            _logger.warning("fastembed_embedding_failed", exc_info=True)

    # HTTP fallback (Ollama or llama.cpp)
    try:
        import requests

        url = get_embedding_url()
        model = model or get_embedding_model()
        resp = requests.post(
            f"{url}/v1/embeddings",
            json={"input": text, "model": model},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        embedding = data["data"][0]["embedding"]
        if embedding and len(embedding) > 0:
            return embedding
    except Exception:
        _logger.warning("http_embedding_failed", exc_info=True)

    # Last resort: deterministic mock embedding (non-cryptographic).
    h = int(hashlib.md5(text.encode(), usedforsecurity=False).hexdigest(), 16)
    import random

    random.seed(h)
    from zettelforge.config import get_config

    dim = get_config().embedding.dimensions
    return [random.random() for _ in range(dim)]  # noqa: S311


def get_embedding_batch(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Batch embed. Native batch with fastembed, sequential with ollama."""
    provider = get_embedding_provider()

    if provider == "fastembed":
        try:
            m = _get_embed_model()
            results = list(m.embed(texts))
            return [r.tolist() for r in results]
        except Exception:
            _logger.error("embedding_init_failed", exc_info=True)

    return [get_embedding(text, model) for text in texts]


# ── LanceDB Schema ───────────────────────────────────────────────────────────


def _build_schema():
    import pyarrow as pa

    from zettelforge.config import get_config

    return pa.schema(
        [
            ("id", pa.string()),
            ("text", pa.string()),
            ("embedding", pa.list_(pa.float32(), get_config().embedding.dimensions)),
            ("content_hash", pa.string()),
            ("timestamp", pa.string()),
            ("source", pa.string()),
            ("session_key", pa.string()),
            ("tags", pa.list_(pa.string())),
            ("metadata", pa.string()),
        ]
    )


# ── VectorMemory ──────────────────────────────────────────────────────────────


class VectorMemory:
    """
    Local cross-session semantic memory store.
    Stores entries in LanceDB with Nomic embeddings.
    """

    def __init__(self, db_path: str | None = None):
        from zettelforge.memory_store import get_default_data_dir

        if db_path is None:
            db_path = get_default_data_dir() / "vector_memory.lance"
        self.db_path = Path(db_path)
        self.db = None
        self.table = None
        self.embedding_model = get_embedding_model()
        self._embedding_cache: dict[str, list[float]] = {}

    def init(self):
        """Connect to or create the LanceDB database."""
        import lancedb

        self.db = lancedb.connect(str(self.db_path))
        self._ensure_table()

    def _ensure_table(self):
        """Create table if it doesn't exist."""
        if "memories" not in self.db.list_tables():
            self.db.create_table("memories", schema=_build_schema())
        self.table = self.db.open_table("memories")

    def _content_hash(self, text: str) -> str:
        """Stable hash of text content for dedup."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]

    def _chunk_text(self, text: str, max_tokens: int = 512, overlap: int = 128) -> list[str]:
        """
        Simple token-aware text chunker.
        Splits on sentence boundaries, groups up to max_tokens.
        """
        max_chars = max_tokens * 4
        overlap_chars = overlap * 4

        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks, current = [], ""

        for sent in sentences:
            if len(current) + len(sent) < max_chars:
                current += " " + sent
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = current[-overlap_chars:].strip() + " " + sent

        if current.strip():
            chunks.append(current.strip())

        return [c for c in chunks if len(c) > 50]

    def add(
        self,
        text: str,
        tags: list[str] | None = None,
        session_key: str = "default",
        source: str = "session",
        metadata: dict | None = None,
        chunk: bool = True,
        overwrite: bool = False,
    ) -> list[str]:
        """
        Add a memory entry. Returns list of chunk IDs added.
        """
        if self.table is None:
            self.init()

        tags = tags or []
        content_hash = self._content_hash(text)
        timestamp = datetime.now().isoformat()

        # Check dedup
        if not overwrite:
            existing = self.table.search().where(f"content_hash = '{content_hash}'").to_list()
            if existing:
                return []

        chunks = self._chunk_text(text) if chunk and len(text) > 2000 else [text]

        ids = []
        for chunk_text in chunks:
            chunk_hash = self._content_hash(chunk_text)
            chunk_id = str(uuid.uuid4())

            # Embed (with simple cache)
            if chunk_hash not in self._embedding_cache:
                self._embedding_cache[chunk_hash] = get_embedding(chunk_text)
            embedding = self._embedding_cache[chunk_hash]

            row = {
                "id": chunk_id,
                "text": chunk_text,
                "embedding": embedding,
                "content_hash": chunk_hash,
                "timestamp": timestamp,
                "source": source,
                "session_key": session_key,
                "tags": tags,
                "metadata": json.dumps(metadata or {}),
            }
            self.table.add([row])
            ids.append(chunk_id)

        return ids

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_filter: str | None = None,
        session_filter: str | None = None,
    ) -> list[dict]:
        """
        Semantic search across all memory entries.
        """
        if self.table is None:
            self.init()

        query_emb = get_embedding(query)

        # Build where clause filters
        where_clauses = []
        if source_filter:
            where_clauses.append(f"source = '{_sanitize_filter_value(source_filter)}'")
        if session_filter:
            where_clauses.append(f"session_key = '{_sanitize_filter_value(session_filter)}'")

        search = self.table.search(query_emb, vector_column_name="embedding")
        if where_clauses:
            search = search.where(" AND ".join(where_clauses))

        results = search.limit(top_k).to_list()

        return [
            {
                "id": r["id"],
                "text": r["text"],
                "source": r["source"],
                "session_key": r["session_key"],
                "tags": r.get("tags", []),
                "timestamp": r["timestamp"],
                "score": r.get("_score", 0),
            }
            for r in results
        ]

    def get_recent(self, session_key: str | None = None, limit: int = 20) -> list[dict]:
        """Get most recent memory entries."""
        if self.table is None:
            self.init()

        q = self.table.search().order_by("timestamp", descending=True).limit(limit)
        if session_key:
            q = q.where(f"session_key = '{_sanitize_filter_value(session_key)}'")

        return q.to_list()

    def delete(self, content_hash: str | None = None, entry_id: str | None = None):
        """Delete by content_hash or entry ID."""
        if self.table is None:
            self.init()

        if content_hash:
            self.table.delete(f"content_hash = '{_sanitize_filter_value(content_hash)}'")
        elif entry_id:
            self.table.delete(f"id = '{_sanitize_filter_value(entry_id)}'")

    def count(self) -> int:
        """Total entry count."""
        if self.table is None:
            self.init()
        return len(self.table.to_list())

    def stats(self) -> dict:
        """Return memory store statistics."""
        if self.table is None:
            self.init()

        all_entries = self.table.to_list()
        sources = {}
        for e in all_entries:
            s = e.get("source", "unknown")
            sources[s] = sources.get(s, 0) + 1

        return {
            "total_entries": len(all_entries),
            "by_source": sources,
            "db_path": str(self.db_path),
            "embedding_model": self.embedding_model,
        }


# ── CLI for testing ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cross-session vector memory")
    parser.add_argument("--init", action="store_true", help="Init the database")
    parser.add_argument("--stats", action="store_true", help="Show stats")
    parser.add_argument("--search", type=str, help="Search query")
    parser.add_argument("--add", type=str, help="Add a memory entry")
    args = parser.parse_args()

    vm = VectorMemory()

    if args.init:
        vm.init()
        print(f"Initialized at {vm.db_path}")

    if args.stats:
        print(json.dumps(vm.stats(), indent=2))

    if args.search:
        results = vm.search(args.search, top_k=5)
        for r in results:
            print(f"\n[{r['source']} | score:{r['score']:.3f}]")
            print(r["text"][:300])

    if args.add:
        ids = vm.add(args.add, source="cli", session_key="cli-test")
        print(f"Added {len(ids)} chunk(s)")
