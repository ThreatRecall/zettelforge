"""
Sigma → entity/relation mapping.

Translates a parsed, validated Sigma rule dict into a ``SigmaRule``
dataclass instance plus a list of relation dicts describing edges to
ontology entities (``AttackPattern``, ``Vulnerability``, ``SigmaTag``,
``LogSource``, ...).

Relation shape (dict, not tuple — matches the KG-edge style used by
``sqlite_backend.add_kg_edge`` and the test skeletons which read
``r.get("rel")``)::

    {
        "from_type": "SigmaRule",
        "from_value": "<rule_id uuid>",
        "rel":       "detects",
        "to_type":   "AttackPattern",
        "to_value":  "T1059",
        "properties": {...},   # optional
    }
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import yaml

from zettelforge.detection.base import DetectionRule
from zettelforge.sigma.tags import resolve_sigma_tag


@dataclass
class SigmaRule(DetectionRule):
    """``DetectionRule`` specialisation for Sigma format.

    Adds Phase 1b Sigma-specific fields on top of the shared contract.
    """

    logsource_product: str | None = None
    logsource_service: str | None = None
    logsource_category: str | None = None
    rule_level: str | None = None  # raw Sigma ``level`` before enum mapping
    rule_status: str | None = None  # raw Sigma ``status`` before enum mapping
    sigma_format_version: str | None = None
    detection_body: str | None = None
    rule_type: str = "detection"  # detection | correlation | filter
    fields: list[str] = field(default_factory=list)
    falsepositives: list[str] = field(default_factory=list)


# ── Public API ───────────────────────────────────────────────────────────────


def from_rule_dict(rule_dict: dict[str, Any]) -> tuple[SigmaRule, list[dict[str, Any]]]:
    """Convert a parsed Sigma rule dict to ``(SigmaRule, relations)``.

    Emits relation dicts for:
    - ``applies_to``    → ``LogSource`` (one per product/service/category present)
    - ``tagged_with``   → ``SigmaTag`` (every raw tag is persisted)
    - ``detects``       → ``AttackPattern`` (``attack.t*`` technique tags)
    - ``references_cve``→ ``Vulnerability`` (``cve.*`` tags)
    - ``attributed_to`` → ``IntrusionSet``/``Malware`` (``attack.g*`` / ``attack.s*``)
    - ``superseded_by`` / ``related_to`` → ``SigmaRule`` (``related:`` field)
    """
    rule_id = _extract_rule_id(rule_dict)
    rule_type = _infer_rule_type(rule_dict)
    logsource = rule_dict.get("logsource") or {}
    detection_block = rule_dict.get("detection") or rule_dict.get("correlation")

    entity = SigmaRule(
        rule_id=rule_id,
        title=str(rule_dict.get("title", "")),
        source_format="sigma",
        content_sha256=_hash_rule(rule_dict),
        description=rule_dict.get("description"),
        author=rule_dict.get("author"),
        date=rule_dict.get("date"),
        modified=rule_dict.get("modified"),
        references=list(rule_dict.get("references") or []),
        tags=list(rule_dict.get("tags") or []),
        level=rule_dict.get("level"),
        status=rule_dict.get("status"),
        license=rule_dict.get("license"),
        logsource_product=logsource.get("product"),
        logsource_service=logsource.get("service"),
        logsource_category=logsource.get("category"),
        rule_level=rule_dict.get("level"),
        rule_status=rule_dict.get("status"),
        detection_body=(
            yaml.safe_dump(detection_block, sort_keys=False) if detection_block else None
        ),
        rule_type=rule_type,
        fields=list(rule_dict.get("fields") or []),
        falsepositives=list(rule_dict.get("falsepositives") or []),
    )

    relations: list[dict[str, Any]] = []
    relations.extend(_logsource_relations(entity))
    relations.extend(_tag_relations(entity))
    relations.extend(_related_relations(entity, rule_dict.get("related") or []))

    return entity, relations


# Alias matching the name used in the Phase 3 task brief.
rule_to_entities = from_rule_dict


# ── Helpers ──────────────────────────────────────────────────────────────────


def _extract_rule_id(rule_dict: dict[str, Any]) -> str:
    """Extract the rule UUID. Fall back to a content hash if absent.

    Phase 1c STOP #1: preserve the raw upstream UUID, do not namespace.
    """
    rid = rule_dict.get("id")
    if isinstance(rid, str) and rid.strip():
        return rid.strip()
    # Rules without an id (fixture 1 in our set) still need a stable id
    # so ingest can dedupe. Use content hash prefix — deterministic and
    # safe; the ontology only requires *some* unique string.
    return "sigma_" + _hash_rule(rule_dict)[:16]


def _infer_rule_type(rule_dict: dict[str, Any]) -> str:
    if "correlation" in rule_dict:
        return "correlation"
    if "filter" in rule_dict:
        return "filter"
    return "detection"


def _hash_rule(rule_dict: dict[str, Any]) -> str:
    """Stable SHA-256 of the canonical YAML form. Deterministic dedupe key."""
    canonical = yaml.safe_dump(rule_dict, sort_keys=True, default_flow_style=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _logsource_relations(entity: SigmaRule) -> list[dict[str, Any]]:
    """Emit one ``applies_to`` edge per populated logsource facet."""
    out: list[dict[str, Any]] = []
    for facet, value in (
        ("product", entity.logsource_product),
        ("service", entity.logsource_service),
        ("category", entity.logsource_category),
    ):
        if value:
            out.append(
                {
                    "from_type": "SigmaRule",
                    "from_value": entity.rule_id,
                    "rel": "applies_to",
                    "to_type": "LogSource",
                    "to_value": f"{facet}:{value}",
                    "properties": {"facet": facet, "value": value},
                }
            )
    return out


def _tag_relations(entity: SigmaRule) -> list[dict[str, Any]]:
    """For every Sigma tag, emit ``tagged_with`` → ``SigmaTag`` AND — if the
    namespace resolves — an upgrade edge (``detects`` / ``references_cve`` /
    ``attributed_to``)."""
    out: list[dict[str, Any]] = []
    for raw in entity.tags:
        if not isinstance(raw, str) or not raw:
            continue

        # Always keep the raw SigmaTag edge for lossless provenance.
        ns, _, name = raw.partition(".")
        out.append(
            {
                "from_type": "SigmaRule",
                "from_value": entity.rule_id,
                "rel": "tagged_with",
                "to_type": "SigmaTag",
                "to_value": raw,
                "properties": {"namespace": ns, "name": name},
            }
        )

        resolved = resolve_sigma_tag(raw)
        if resolved is None:
            continue
        target_type, target_value = resolved

        if target_type == "AttackPattern":
            out.append(
                {
                    "from_type": "SigmaRule",
                    "from_value": entity.rule_id,
                    "rel": "detects",
                    "to_type": "AttackPattern",
                    "to_value": target_value,
                    "properties": {"source": "sigma_tag", "raw_tag": raw},
                }
            )
        elif target_type == "Vulnerability":
            out.append(
                {
                    "from_type": "SigmaRule",
                    "from_value": entity.rule_id,
                    "rel": "references_cve",
                    "to_type": "Vulnerability",
                    "to_value": target_value,
                    "properties": {"source": "sigma_tag", "raw_tag": raw},
                }
            )
        elif target_type in ("IntrusionSet", "Malware"):
            out.append(
                {
                    "from_type": "SigmaRule",
                    "from_value": entity.rule_id,
                    "rel": "attributed_to",
                    "to_type": target_type,
                    "to_value": target_value,
                    "properties": {"source": "sigma_tag", "raw_tag": raw},
                }
            )
    return out


def _related_relations(entity: SigmaRule, related: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``related:`` block maps to ``superseded_by`` (obsolete) or ``related_to``."""
    out: list[dict[str, Any]] = []
    for item in related:
        if not isinstance(item, dict):
            continue
        other_id = item.get("id")
        rel_type = str(item.get("type") or "").lower()
        if not isinstance(other_id, str) or not other_id:
            continue
        edge_rel = "superseded_by" if rel_type == "obsolete" else "related_to"
        out.append(
            {
                "from_type": "SigmaRule",
                "from_value": entity.rule_id,
                "rel": edge_rel,
                "to_type": "SigmaRule",
                "to_value": other_id,
                "properties": {"sigma_related_type": rel_type},
            }
        )
    return out
