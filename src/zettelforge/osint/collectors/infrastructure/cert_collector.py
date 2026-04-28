"""
Certificate Transparency collector — Phase 1 (RFC-016 §5).

Queries crt.sh for certificates matching a domain and emits SAN domains as
``DomainName`` entities linked to the input domain via the existing
``related_to`` edge.

Phase boundary: ``CertificateSubject`` and ``SSLPoint`` entity types and
their richer edges (``has_certificate``, ``terminates_tls``) are Phase 3.
Phase 1 only enumerates SAN domains.
"""

from __future__ import annotations

from typing import Any

import httpx

from zettelforge.log import get_logger
from zettelforge.osint.ontology import canonicalize_domain
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.cert")

CRTSH_URL = "https://crt.sh/"
DEFAULT_TIMEOUT = 10.0
MAX_CERTS = 200


def _fetch_crtsh(domain: str, timeout: float) -> list[dict[str, Any]]:
    """Query crt.sh JSON API. Returns the parsed list of cert records.

    Empty list on any HTTP / parse error — failure is logged and absorbed.
    """
    params = {"q": domain, "output": "json"}
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(CRTSH_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        _logger.warning("cert_collector_http_error", domain=domain, error=str(exc))
        return []
    except ValueError as exc:  # JSON decode error
        _logger.warning("cert_collector_json_error", domain=domain, error=str(exc))
        return []
    if not isinstance(payload, list):
        _logger.warning("cert_collector_unexpected_shape", domain=domain)
        return []
    return payload[:MAX_CERTS]


def _extract_san_domains(record: dict[str, Any], input_domain: str) -> set[str]:
    """Pull SAN-style domains from a crt.sh record.

    crt.sh records include ``name_value`` which is a newline-delimited list
    of SAN entries. Wildcard entries (``*.example.com``) are stripped to the
    parent domain.
    """
    raw = record.get("name_value")
    if not isinstance(raw, str):
        return set()
    domains: set[str] = set()
    for entry in raw.split("\n"):
        candidate = entry.strip().lstrip("*.").rstrip(".")
        if not candidate:
            continue
        normalized = canonicalize_domain(candidate)
        if not normalized or normalized == input_domain:
            continue
        domains.add(normalized)
    return domains


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Enumerate SAN domains for an input domain via crt.sh.

    Returns ``[]`` for non-DomainName inputs or when the upstream query
    fails. Output is deduplicated across the cert set.
    """
    if input_entity_type != "DomainName":
        return []

    domain = canonicalize_domain(input_value)
    if not domain:
        return []

    records = _fetch_crtsh(domain, DEFAULT_TIMEOUT)
    seen: set[str] = set()
    out: list[CollectorTuple] = []
    for record in records:
        for san in _extract_san_domains(record, domain):
            if san in seen:
                continue
            seen.add(san)
            out.append(
                CollectorTuple(
                    output_entity_type="DomainName",
                    output_value=san,
                    edge_type="related_to",
                    from_entity_type="DomainName",
                    to_entity_type="DomainName",
                    output_props={"value": san},
                    edge_props={"source": "crt.sh"},
                )
            )
    return out


_METADATA = TransformMetadata(
    name="cert_collector",
    description="crt.sh certificate transparency: enumerate SAN domains for a domain.",
    input_types=("DomainName",),
    output_types=(("DomainName", "related_to"),),
    api_dependencies=("crt.sh",),
    rate_limit=None,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
