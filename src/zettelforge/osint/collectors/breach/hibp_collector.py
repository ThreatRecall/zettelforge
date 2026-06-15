"""
HaveIBeenPwned collector — AGE-120 (RFC-016 §5).

Looks up breach exposure for an ``EmailAddress`` via the native HIBP v3 REST
API and emits one ``Breach`` per hit, linked to the email via the
``appeared_in_breach`` edge.

This is the native REST path mandated by AGE-118: the LGPL ``hibpwned``
wrapper is excluded (see ``THIRD_PARTY/THIRD_PARTY_NOTICES.md``).

Key handling
------------
The API key is read from ``HIBP_API_KEY`` at call time and passed only in
the ``hibp-api-key`` request header. It is never logged. Without the key the
collector fails closed and returns ``[]``.

No retries: AGENTS.OE Override 4 forbids silent retry. HTTP 404 means "no
breaches" (empty list); every other failure logs a warning and returns ``[]``.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

from zettelforge.log import get_logger
from zettelforge.osint.ontology import canonicalize_email
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.hibp")

API_KEY_ENV = "HIBP_API_KEY"
API_BASE = "https://haveibeenpwned.com/api/v3/breachedaccount"
# HIBP rejects requests without a descriptive User-Agent.
USER_AGENT = "ZettelForge-OSINT"
DEFAULT_TIMEOUT = 15.0


def _fetch_breaches(email: str, api_key: str) -> list[dict[str, Any]]:
    """Call HIBP v3 breachedaccount. Returns the parsed breach list.

    404 -> ``[]`` (account clean). The API key travels only in the header and
    is never logged. Any HTTP / parse error logs a warning and returns ``[]``.
    """
    url = f"{API_BASE}/{quote(email)}"
    headers = {"hibp-api-key": api_key, "User-Agent": USER_AGENT}
    params = {"truncateResponse": "false"}
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            response = client.get(url, headers=headers, params=params)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        _logger.warning("hibp_collector_http_error", email=email, error=str(exc))
        return []
    except ValueError as exc:  # JSON decode error
        _logger.warning("hibp_collector_json_error", email=email, error=str(exc))
        return []
    if not isinstance(payload, list):
        _logger.warning("hibp_collector_unexpected_shape", email=email)
        return []
    return [item for item in payload if isinstance(item, dict)]


def _breach_props(record: dict[str, Any]) -> dict[str, Any] | None:
    """Map a HIBP breach record to ``Breach`` entity properties.

    Returns ``None`` if the record has no ``Name`` (the required field).
    """
    name = record.get("Name")
    if not isinstance(name, str) or not name.strip():
        return None
    props: dict[str, Any] = {"name": name.strip()}
    for src, dst in (
        ("Title", "title"),
        ("Domain", "domain"),
        ("BreachDate", "breach_date"),
        ("AddedDate", "added_date"),
        ("Description", "description"),
    ):
        value = record.get(src)
        if isinstance(value, str) and value.strip():
            props[dst] = value.strip()
    pwn_count = record.get("PwnCount")
    if isinstance(pwn_count, int):
        props["pwn_count"] = pwn_count
    if isinstance(record.get("IsVerified"), bool):
        props["is_verified"] = record["IsVerified"]
    data_classes = record.get("DataClasses")
    if isinstance(data_classes, list):
        props["data_classes"] = [str(d) for d in data_classes]
    return props


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Enumerate breaches for an EmailAddress via HIBP. Fail-closed without key."""
    if input_entity_type != "EmailAddress":
        return []
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        _logger.debug("hibp_collector_no_api_key", env=API_KEY_ENV)
        return []

    email = canonicalize_email(input_value)
    if not email:
        return []

    out: list[CollectorTuple] = []
    seen: set[str] = set()
    for record in _fetch_breaches(email, api_key):
        props = _breach_props(record)
        if props is None:
            continue
        name = props["name"]
        if name in seen:
            continue
        seen.add(name)
        out.append(
            CollectorTuple(
                output_entity_type="Breach",
                output_value=name,
                edge_type="appeared_in_breach",
                from_entity_type="EmailAddress",
                to_entity_type="Breach",
                output_props=props,
                edge_props={},
            )
        )
    return out


_METADATA = TransformMetadata(
    name="hibp_collector",
    description="HaveIBeenPwned: enumerate breach exposures for an email.",
    input_types=("EmailAddress",),
    output_types=(("Breach", "appeared_in_breach"),),
    api_dependencies=("haveibeenpwned.com",),
    rate_limit=2.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
