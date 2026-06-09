"""
ZettelForge OSINT layer (RFC-016 / RFC-0001).

Importing the package merges the OSINT entity / edge types into the global
ontology and imports each collector subpackage so collectors register with
``TRANSFORM_REGISTRY`` at module load time.

Phase 1 (Infrastructure) ships functional collectors (DNS, WHOIS, crt.sh)
plus the passive BGP collector. Phase 1.5 adds the OSINT executor and
resolver wiring; active port scanning remains gated behind explicit
operator opt-in. Later collectors stay as graceful stubs until their
respective phases land.

Public surface:

- ``OSINT_ENTITY_TYPES`` / ``OSINT_RELATION_TYPES`` / ``ONTOLOGY`` -- additive
  ontology declarations.
- ``TRANSFORM_REGISTRY`` -- the singleton registry.
- ``CollectorTuple`` -- collector return-row shape.
- ``TransformMetadata`` / ``TransformRegistry`` -- types for adding new
  collectors.
- ``add_resolved`` / ``canonicalise_value`` / ``resolve`` -- entity
  resolver helpers.
- ``run_osint_collection`` / ``collect_osint`` -- the passive ingest API.
"""

from zettelforge.osint.entity_resolver import (
    add_resolved,
    canonicalise_organization,
    canonicalise_value,
    register_alias,
    resolve,
)
from zettelforge.osint.executor import (
    SUPPORTED_SEED_TYPES,
    OSINTCollectionResult,
    OSINTExecutionError,
    PersistedOSINTTuple,
    collect_osint,
    run_osint_collection,
)
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
# Idempotent -- safe under repeated imports (pytest, REPL re-imports, etc.).
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
    "SUPPORTED_SEED_TYPES",
    "TRANSFORM_REGISTRY",
    "CollectorFn",
    "CollectorTuple",
    "OSINTCollectionResult",
    "OSINTExecutionError",
    "PersistedOSINTTuple",
    "TransformMetadata",
    "TransformRegistry",
    "add_resolved",
    "canonicalise_organization",
    "canonicalise_value",
    "canonicalize_asn",
    "canonicalize_cidr",
    "canonicalize_domain",
    "canonicalize_ipv6",
    "canonicalize_mx",
    "canonicalize_port",
    "canonicalize_url",
    "canonicalize_web_title",
    "collect_osint",
    "get_transform_registry",
    "merge_into_global_ontology",
    "register_alias",
    "resolve",
    "run_osint_collection",
]
