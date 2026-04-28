"""
ZettelForge OSINT layer (RFC-016 / RFC-0001).

Importing the package merges the OSINT entity / edge types into the global
ontology and imports each collector subpackage so collectors register with
``TRANSFORM_REGISTRY`` at module load time.

Phase 1 (Infrastructure) ships functional collectors (DNS, WHOIS, crt.sh)
plus stubs for BGP and port scanning. Phases 2-5 ship as graceful stubs:
each collector registers its metadata so callers can discover it, and
returns ``[]`` until the underlying API integration lands.

Public surface:

- ``OSINT_ENTITY_TYPES`` / ``OSINT_RELATION_TYPES`` / ``ONTOLOGY`` — additive
  ontology declarations.
- ``TRANSFORM_REGISTRY`` — the singleton registry.
- ``CollectorTuple`` — collector return-row shape.
- ``TransformMetadata`` / ``TransformRegistry`` — types for adding new
  collectors.
- ``Investigation`` / ``EntityResolver`` — Phase 4 / Phase 1.5 utilities
  (re-exported from their modules).
"""

from zettelforge.osint.ontology import (
    ONTOLOGY,
    OSINT_ENTITY_TYPES,
    OSINT_RELATION_TYPES,
    canonicalize_asn,
    canonicalize_cidr,
    canonicalize_domain,
    canonicalize_ipv6,
    canonicalize_mx,
    canonicalize_port,
    canonicalize_url,
    canonicalize_web_title,
    merge_into_global_ontology,
)
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorFn,
    CollectorTuple,
    TransformMetadata,
    TransformRegistry,
    get_transform_registry,
)

# Merge OSINT types into the global ontology before any collector runs.
# Idempotent — safe under repeated imports (pytest, REPL re-imports, etc.).
merge_into_global_ontology()

# Trigger collector self-registration. Each subpackage's __init__ imports
# the collector modules under it, and each module calls
# ``TRANSFORM_REGISTRY.register(...)`` at import time.
from zettelforge.osint.collectors import breach as _breach  # noqa: F401
from zettelforge.osint.collectors import infrastructure as _infrastructure  # noqa: F401
from zettelforge.osint.collectors import people as _people  # noqa: F401
from zettelforge.osint.collectors import social as _social  # noqa: F401
from zettelforge.osint.collectors import tech as _tech  # noqa: F401

__all__ = [
    "ONTOLOGY",
    "OSINT_ENTITY_TYPES",
    "OSINT_RELATION_TYPES",
    "TRANSFORM_REGISTRY",
    "CollectorFn",
    "CollectorTuple",
    "TransformMetadata",
    "TransformRegistry",
    "canonicalize_asn",
    "canonicalize_cidr",
    "canonicalize_domain",
    "canonicalize_ipv6",
    "canonicalize_mx",
    "canonicalize_port",
    "canonicalize_url",
    "canonicalize_web_title",
    "get_transform_registry",
    "merge_into_global_ontology",
]
