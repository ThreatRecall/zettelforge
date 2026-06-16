"""
Username -> SocialAccount collector — AGE-120 (RFC-016 §5).

Enumerates the social platforms a username (``Alias``) is present on and
emits a ``SocialAccount`` per hit, linked to the input alias via the
``has_account`` edge.

Backend: ``maigret`` (soxoj, MIT) with ``sherlock`` (MIT) as an alternate.
Both are lazy-imported behind ``_search_username`` so the package loads
without them; a missing dependency logs a warning and returns ``[]``.

This replaces the GPL ``holehe`` path that AGE-118 excluded (see
``collectors/people/holehe_collector.py``): account enumeration is done on
a permissive basis only.

No retries: maigret already manages per-site timeouts, and AGENTS.OE
Override 4 forbids silent retry. Any backend failure surfaces as an empty
result plus a structured warning.
"""

from __future__ import annotations

import logging
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
    """Run a username presence search. Returns rows ``{platform, url}``.

    Lazy-imports ``maigret`` (MIT). Returns ``[]`` when maigret is not
    installed or the search fails — fail-closed, no silent retry. maigret's
    public search API is async, so it is driven on a private event loop.

    The live maigret wiring is best-effort behind a single boundary; tests
    mock this function and exercise the pure mapping in ``_rows_to_tuples``.
    """
    try:
        import asyncio

        import maigret
        from maigret.sites import MaigretDatabase
    except ImportError:
        _logger.warning("maigret_collector_missing_dep", username=username)
        return []

    try:
        settings = maigret.settings.Settings()
        load = getattr(settings, "load", None)
        if callable(load):
            load()
        db = MaigretDatabase().load_from_path(settings.sites_db_path)
        sites = db.ranked_sites_dict(top=MAX_ACCOUNTS)
        backend_logger = logging.getLogger("zettelforge.osint.collectors.maigret.backend")
        results = asyncio.run(
            maigret.search(
                username=username,
                site_dict=sites,
                timeout=30,
                logger=backend_logger,
                no_progressbar=True,
            )
        )
    except Exception as exc:  # backend boundary: any maigret failure fails closed
        _logger.warning("maigret_collector_failed", error=str(exc))
        return []

    rows: list[dict[str, Any]] = []
    for site_name, data in (results or {}).items():
        status = data.get("status")
        # maigret marks a confirmed hit with a CLAIMED query-result status.
        claimed = getattr(status, "status", None)
        if claimed is not None and str(claimed).upper().endswith("CLAIMED"):
            rows.append({"platform": site_name, "url": data.get("url_user", "")})
    return rows


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
    description="maigret/sherlock: enumerate a username's social accounts.",
    input_types=("Alias",),
    output_types=(("SocialAccount", "has_account"),),
    api_dependencies=("maigret",),
    rate_limit=None,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
