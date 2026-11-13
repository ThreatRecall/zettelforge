"""
Username -> SocialAccount collector — AGE-120 (RFC-016 §5).

Enumerates the social platforms a username (``Alias``) is present on and
emits a ``SocialAccount`` per hit, linked to the input alias via the
``has_account`` edge.

Temporarily disabled: Maigret 0.6.6 constrains SoupSieve to vulnerable
versions (CVE-2026-126190). The collector stays registered for API
compatibility but performs no imports or network work, even if an older
installation still contains Maigret. It returns no records and emits a
structured warning. Re-enable only after upstream supports patched dependencies
and the complete dependency audit passes.
"""

from __future__ import annotations

from typing import Any

from zettelforge.log import get_logger
from zettelforge.osint.ontology import canonicalize_alias, canonicalize_social_account
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.maigret")

# Cap emitted accounts so a noisy username (maigret checks 3000+ sites) cannot
# flood the graph in one collection.
MAX_ACCOUNTS = 200


def _search_username(username: str) -> list[dict[str, Any]]:
    """Fail closed until Maigret supports patched SoupSieve releases."""
    _logger.warning("maigret_collector_disabled", advisory="CVE-2026-126190")
    return []


def _rows_to_tuples(username: str, rows: list[dict[str, Any]]) -> list[CollectorTuple]:
    """Map ``{platform, url}`` rows to ``has_account`` CollectorTuples."""
    out: list[CollectorTuple] = []
    seen: set[str] = set()
    for row in rows[:MAX_ACCOUNTS]:
        platform = str(row.get("platform", "")).strip()
        if not platform:
            continue
        account_id = canonicalize_social_account(username, platform)
        if account_id in seen:
            continue
        seen.add(account_id)
        props: dict[str, Any] = {
            "id": account_id,
            "username": username,
            "platform": platform,
        }
        url = str(row.get("url", "")).strip()
        if url:
            props["profile_url"] = url
        out.append(
            CollectorTuple(
                output_entity_type="SocialAccount",
                output_value=account_id,
                edge_type="has_account",
                from_entity_type="Alias",
                to_entity_type="SocialAccount",
                output_props=props,
                edge_props={},
            )
        )
    return out


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Enumerate SocialAccounts for an Alias (username). Returns [] otherwise."""
    if input_entity_type != "Alias":
        return []
    username = canonicalize_alias(input_value)
    if not username:
        return []
    return _rows_to_tuples(username, _search_username(username))


_METADATA = TransformMetadata(
    name="maigret_collector",
    description="Disabled: Maigret username search awaits a fix for CVE-2026-126190.",
    input_types=("Alias",),
    output_types=(("SocialAccount", "has_account"),),
    api_dependencies=("maigret",),
    rate_limit=None,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
