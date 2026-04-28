"""
ZettelForge Edition Detection

Determines whether the running instance is Community (open-source, MIT)
or Enterprise (commercial, BSL-1.1 licensed by Threatengram).

Enterprise is activated by EITHER:
  - A valid THREATENGRAM_LICENSE_KEY environment variable
  - The presence of an installed zettelforge-enterprise package

Community edition is a fully-featured agentic memory system:
  - Two-phase extraction pipeline (LLM fact extraction + ADD/UPDATE/DELETE)
  - Blended retrieval (vector + knowledge graph)
  - Cross-encoder reranking
  - Intent-adaptive query routing
  - Causal triple extraction
  - LLM-powered entity extraction (10 types)
  - JSONL knowledge graph with relationships
  - Direct-answer RAG synthesis
  - MCP server integration
  - Single-tenant operation

Enterprise adds scale, analyst workflows, integrations, and operations:
  - STIX 2.1 TypeDB ontology with inference rules (replaces JSONL graph)
  - Temporal knowledge graph queries (timeline, changes-since)
  - Multi-hop graph traversal (BFS)
  - Advanced RAG synthesis (synthesized_brief, timeline, relationship_map)
  - Report ingestion with auto-chunking
  - TypeDB-backed alias resolution
  - OpenCTI platform integration
  - Sigma rule generation
  - Proactive context injection
  - Multi-tenant OAuth/JWT authentication
  - Priority support from Threatengram
"""

import enum
import functools
import os
from typing import Optional


class Edition(enum.Enum):
    COMMUNITY = "community"
    ENTERPRISE = "enterprise"


_edition: Optional[Edition] = None


def get_edition() -> Edition:
    """Detect and cache the active edition."""
    global _edition
    if _edition is not None:
        return _edition

    # Check 1: License key in environment
    license_key = os.environ.get("THREATENGRAM_LICENSE_KEY", "").strip()
    if license_key:
        if _validate_license_key(license_key):
            _edition = Edition.ENTERPRISE
            return _edition

    # Check 2: Enterprise package installed
    try:
        from zettelforge.enterprise import is_licensed  # noqa: F401

        if is_licensed():
            _edition = Edition.ENTERPRISE
            return _edition
    except ImportError:
        pass

    _edition = Edition.COMMUNITY
    return _edition


def is_enterprise() -> bool:
    """Return True if running Enterprise edition."""
    return get_edition() == Edition.ENTERPRISE


def is_community() -> bool:
    """Return True if running Community edition."""
    return get_edition() == Edition.COMMUNITY


def edition_name() -> str:
    """Human-readable edition name for display."""
    if is_enterprise():
        return "ThreatRecall Enterprise by Threatengram"
    return "ZettelForge Community"


def _validate_license_key(key: str) -> bool:
    """Validate a Threatengram license key.

    Format: TG-XXXX-XXXX-XXXX-XXXX (20 hex chars after prefix).
    In production this would call a license server or check a
    cryptographic signature. For now, validate format only.
    """
    if not key.startswith("TG-"):
        return False
    parts = key.split("-")
    if len(parts) != 5:
        return False
    hex_part = "".join(parts[1:])
    if len(hex_part) != 16:
        return False
    try:
        int(hex_part, 16)
        return True
    except ValueError:
        return False


def require_enterprise(feature_name: str):
    """Decorator that gates a function behind Enterprise edition.

    When called in Community edition, raises EditionError with a
    clear message about upgrading.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not is_enterprise():
                raise EditionError(
                    f"'{feature_name}' requires ThreatRecall Enterprise. "
                    f"Set THREATENGRAM_LICENSE_KEY or visit https://threatengram.com/enterprise"
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def enterprise_fallback(feature_name: str, fallback_return=None):
    """Decorator that silently falls back in Community edition.

    Returns fallback_return instead of raising. Logs a one-time notice.
    """
    _warned = set()

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not is_enterprise():
                if feature_name not in _warned:
                    import logging

                    logging.getLogger("zettelforge.edition").info(
                        "[Community] %s requires Enterprise edition — using fallback. "
                        "https://threatengram.com/enterprise",
                        feature_name,
                    )
                    _warned.add(feature_name)
                return fallback_return
            return func(*args, **kwargs)

        return wrapper

    return decorator


class EditionError(Exception):
    """Raised when an Enterprise feature is used in Community edition."""

    pass


def reset_edition():
    """Reset cached edition (for testing)."""
    global _edition
    _edition = None
