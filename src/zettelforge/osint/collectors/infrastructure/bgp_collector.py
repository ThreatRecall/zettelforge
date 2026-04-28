"""
BGP collector — Phase 1.5 stub (RFC-016 §5).

Fetches ASN / netblock data from BGPView's public JSON API. Sync; matches
the rest of the codebase. Returns ``[]`` on any HTTP / parse failure or
when ``httpx`` is unavailable; the agent sees an empty result, never an
exception.

The Phase 1 PR ships this with the registration metadata and the live
BGPView call wired up but treated as best-effort. Hardening (retry / caching
/ rate-limit budget) lands with Phase 1.5.
"""

from __future__ import annotations

from typing import Any

from zettelforge.log import get_logger
from zettelforge.osint.ontology import canonicalize_asn, canonicalize_cidr
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.bgp")

BGPVIEW_BASE = "https://api.bgpview.io"
DEFAULT_TIMEOUT = 10.0


def _bgpview_get(path: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any] | None:
    """Issue a BGPView API GET; return parsed ``data``, or None on failure."""
    try:
        import httpx
    except ImportError:
        _logger.warning("bgp_collector_missing_httpx")
        return None
    url = f"{BGPVIEW_BASE}{path}"
    try:
        with httpx.Client(
            timeout=timeout, headers={"User-Agent": "ZettelForge-OSINT/1.0"}
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        _logger.warning("bgp_collector_http_error", path=path, error=str(exc))
        return None
    except ValueError as exc:
        _logger.warning("bgp_collector_json_error", path=path, error=str(exc))
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Look up an ASN's prefixes via BGPView and emit Netblock tuples.

    Returns ``[]`` on any failure or for non-ASNumber inputs.
    """
    if input_entity_type != "ASNumber":
        return []
    try:
        asn = canonicalize_asn(input_value)
    except ValueError:
        _logger.debug("bgp_invalid_asn", raw=input_value)
        return []

    data = _bgpview_get(f"/asn/{asn}")
    if not data:
        return []

    out: list[CollectorTuple] = []
    org = ""
    owner = data.get("owner")
    if isinstance(owner, dict):
        org_value = owner.get("name")
        if isinstance(org_value, str):
            org = org_value.strip()

    for prefix in data.get("prefixes", []) or []:
        if not isinstance(prefix, dict):
            continue
        cidr_raw = prefix.get("prefix")
        if not isinstance(cidr_raw, str):
            continue
        try:
            cidr = canonicalize_cidr(cidr_raw)
        except ValueError:
            continue
        props: dict[str, Any] = {"cidr": cidr}
        if org:
            props["org"] = org
        out.append(
            CollectorTuple(
                output_entity_type="Netblock",
                output_value=cidr,
                edge_type="part_of_as",
                from_entity_type="ASNumber",
                to_entity_type="Netblock",
                output_props=props,
                edge_props={},
            )
        )
    return out


_METADATA = TransformMetadata(
    name="bgp_collector",
    description="BGPView lookup: enumerate netblocks announced by an ASN.",
    input_types=("ASNumber",),
    output_types=(("Netblock", "part_of_as"),),
    api_dependencies=("bgpview",),
    rate_limit=1.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
