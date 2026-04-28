"""
Example: ingest a MISP JSON export into ZettelForge.

MISP (Malware Information Sharing Platform) is the most widely used threat
intelligence sharing platform. This script reads a MISP JSON export file and
ingests each event into ZettelForge as structured memory notes.

Usage::

    pip install zettelforge
    python examples/ingest_misp.py path/to/misp_export.json

The script expects a standard MISP JSON export format (as produced by the MISP
REST API ``/events`` endpoint or the UI export).  The top-level JSON structure
is::

    {
        "response": [
            {
                "Event": {
                    "uuid": "...",
                    "info": "Event title / description",
                    "analysis": "0",
                    "threat_level_id": "1",
                    "Tag": [{"name": "tlp:amber"}, ...],
                    "Attribute": [
                        {
                            "type": "ip-src",
                            "value": "1.2.3.4",
                            "category": "Network activity",
                            "Tag": [{"name": "osint:source=\"somewhere\""}, ...]
                        },
                        ...
                    ]
                }
            }
        ]
    }

Attribute types mapped to ZettelForge entity types:

    =====================  =============  =====================
    MISP type              ZF entity      Category (example)
    =====================  =============  =====================
    ip-src, ip-dst         ipv4           Network activity
    domain, hostname       domain         Network activity
    url                    url            Network activity
    email, email-src,
      email-dst            email          Payload delivery
    md5                    md5            Payload delivery
    sha1                   sha1           Payload delivery
    filename|md5          md5            Artifacts dropped
    filename|sha1         sha1           Artifacts dropped
    filename|sha256       sha256         Artifacts dropped

Sample MISP JSON data for testing::

    {
      "response": [
        {
          "Event": {
            "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "info": "Suspicious activity related to APT28 infrastructure",
            "analysis": "2",
            "threat_level_id": "2",
            "date": "2025-04-01",
            "Tag": [
              {"name": "tlp:amber"},
              {"name": "osint:source-type=\"dark-web\""}
            ],
            "Attribute": [
              {
                "type": "ip-src",
                "value": "185.220.101.1",
                "category": "Network activity",
                "Tag": []
              },
              {
                "type": "domain",
                "value": "malicious-evil-domain.xyz",
                "category": "Network activity",
                "Tag": [{"name": "osint:confidence=\"high\""}]
              },
              {
                "type": "url",
                "value": "https://malicious-evil-domain.xyz/beacon",
                "category": "Network activity",
                "Tag": []
              },
              {
                "type": "md5",
                "value": "d41d8cd98f00b204e9800998ecf8427e",
                "category": "Payload delivery",
                "Tag": []
              },
              {
                "type": "email-src",
                "value": "phisher@evil-domain.xyz",
                "category": "Payload delivery",
                "Tag": []
              }
            ]
          }
        }
      ]
    }

Save the above as ``examples/sample_misp_event.json`` to run a quick test.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from typing import Any


# ── MISP-to-ZettelForge entity type mapping ─────────────────────────────────

MISP_ATTRIBUTE_TO_ENTITY: dict[str, str] = {
    # Network layer
    "ip-src": "ipv4",
    "ip-dst": "ipv4",
    "domain": "domain",
    "hostname": "domain",
    "url": "url",
    # Email
    "email": "email",
    "email-src": "email",
    "email-dst": "email",
    # Hashes (exact match on simple hash types)
    "md5": "md5",
    "sha1": "sha1",
    "sha256": "sha256",
    # Composite hash types: filename|md5, filename|sha1, filename|sha256
    # Handled separately below because the value is a pipe-delimited pair.
}

# Composite attribute types where value is "filename|hash"
COMPOSITE_HASH_TYPES: dict[str, str] = {
    "filename|md5": "md5",
    "filename|sha1": "sha1",
    "filename|sha256": "sha256",
}

# Regex to validate hex hash strings before emitting as entities
_HEX32 = re.compile(r"^[a-fA-F0-9]{32}$")
_HEX40 = re.compile(r"^[a-fA-F0-9]{40}$")
_HEX64 = re.compile(r"^[a-fA-F0-9]{64}$")

_HASH_VALIDATORS: dict[str, re.Pattern] = {
    "md5": _HEX32,
    "sha1": _HEX40,
    "sha256": _HEX64,
}


def _validate_hash(hash_type: str, value: str) -> bool:
    """Return True if *value* matches the expected hex pattern for *hash_type*."""
    validator = _HASH_VALIDATORS.get(hash_type)
    if validator is None:
        return True  # unknown hash type, let it through
    return bool(validator.match(value))


_THREAT_LEVEL_LABELS: dict[str, str] = {
    "1": "high",
    "2": "medium",
    "3": "low",
    "4": "undefined",
}

_ANALYSIS_LABELS: dict[str, str] = {
    "0": "initial",
    "1": "ongoing",
    "2": "completed",
}


# ── Helper functions ─────────────────────────────────────────────────────────


def _safe_str(val: Any, default: str = "") -> str:
    """Coerce *val* to str, returning *default* on failure."""
    if val is None:
        return default
    try:
        return str(val)
    except (ValueError, TypeError):
        return default


def _extract_tags(event_or_attr: dict[str, Any]) -> list[str]:
    """Extract tag names from a MISP Event or Attribute dict."""
    tags_raw = event_or_attr.get("Tag") or event_or_attr.get("tag") or []
    names: list[str] = []
    for t in tags_raw:
        if isinstance(t, dict):
            name = t.get("name") or t.get("Name") or ""
            if name:
                names.append(name)
        elif isinstance(t, str):
            names.append(t)
    return names


def _build_event_note_content(
    event: dict[str, Any],
    attributes: list[dict[str, Any]],
    entity_counts: Counter,
) -> str:
    """Build the human-readable content string for a ``remember()`` call."""
    info = _safe_str(event.get("info", ""))
    uuid = _safe_str(event.get("uuid", ""))
    tl_id = _safe_str(event.get("threat_level_id", "4"))
    analysis = _safe_str(event.get("analysis", "0"))
    date = _safe_str(event.get("date", ""))

    threat_label = _THREAT_LEVEL_LABELS.get(tl_id, tl_id)
    analysis_label = _ANALYSIS_LABELS.get(analysis, analysis)

    lines: list[str] = []
    lines.append(f"Event: {info}")
    lines.append(f"UUID: {uuid}")
    if date:
        lines.append(f"Date: {date}")
    lines.append(f"Threat Level: {threat_label} (id={tl_id})")
    lines.append(f"Analysis: {analysis_label} (id={analysis})")

    # Event-level tags
    event_tags = _extract_tags(event)
    if event_tags:
        lines.append(f"Tags: {', '.join(sorted(event_tags))}")

    # Attributes
    lines.append("")
    lines.append("Attributes:")
    for attr in attributes:
        atype = _safe_str(attr.get("type", ""))
        avalue = _safe_str(attr.get("value", ""))
        acat = _safe_str(attr.get("category", ""))
        attr_tags = _extract_tags(attr)
        tag_str = f" [{', '.join(attr_tags)}]" if attr_tags else ""
        lines.append(f"  [{acat}] {atype}: {avalue}{tag_str}")

    return "\n".join(lines)


def _extract_entity_type(attr_type: str, attr_value: str) -> str | None:
    """
    Map a MISP attribute type and value to a ZettelForge entity type.
    Returns None if the attribute does not map to a known entity type.
    """
    # Check composite hash types first (filename|md5 etc.)
    if attr_type in COMPOSITE_HASH_TYPES:
        hash_type = COMPOSITE_HASH_TYPES[attr_type]
        parts = attr_value.split("|", 1)
        hash_val = parts[1].strip() if len(parts) == 2 else parts[0].strip()
        if _validate_hash(hash_type, hash_val):
            return hash_type
        return None

    # Direct mapping
    entity_type = MISP_ATTRIBUTE_TO_ENTITY.get(attr_type)
    if entity_type is None:
        return None

    # Validate hash values
    if entity_type in _HASH_VALIDATORS and not _validate_hash(entity_type, attr_value):
        return None

    return entity_type


def _parse_misp_event(event_wrapper: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the Event dict from a response item, or return None on failure."""
    if not isinstance(event_wrapper, dict):
        return None
    event = event_wrapper.get("Event") or event_wrapper
    if not isinstance(event, dict):
        return None
    # We need at least a uuid or info to consider this a valid event
    if not event.get("uuid") and not event.get("info"):
        return None
    return event


# ── Main ingest logic ───────────────────────────────────────────────────────


def ingest_misp_file(filepath: str) -> int:
    """
    Read a MISP JSON export file and ingest all events into ZettelForge.

    Returns 0 on success, 1 on failure.
    """
    # Defer import so the script can be imported without zettelforge installed
    # (useful for docstring / unit-test scenarios)
    try:
        from zettelforge import MemoryManager
    except ImportError:
        print(
            "This example requires the 'zettelforge' package. "
            "Install with: pip install zettelforge",
            file=sys.stderr,
        )
        return 1

    # ── Load MISP JSON ──────────────────────────────────────────────────
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: file not found: {filepath}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON in {filepath}: {exc}", file=sys.stderr)
        return 1

    # ── Parse response items ────────────────────────────────────────────
    raw_events: list[Any] = data.get("response") or data.get("Event") or []
    if isinstance(raw_events, dict):
        # Single event (not wrapped in a list)
        raw_events = [raw_events]

    if not raw_events:
        print("WARNING: no events found in JSON data (expected 'response' key)", file=sys.stderr)
        return 1

    # ── Initialize ZettelForge ──────────────────────────────────────────
    mm = MemoryManager()

    total_events = 0
    total_entities = 0
    total_attributes = 0
    total_skipped = 0
    entity_type_counter: Counter = Counter()

    for raw_item in raw_events:
        event = _parse_misp_event(raw_item)
        if event is None:
            total_skipped += 1
            continue

        uuid = _safe_str(event.get("uuid", "")) or f"no-uuid-{total_skipped}"
        info = _safe_str(event.get("info", "")) or "(no info)"

        # Extract attributes
        attributes: list[dict[str, Any]] = event.get("Attribute") or event.get("attribute") or []
        if not isinstance(attributes, list):
            attributes = []

        # Map each attribute to a ZettelForge entity, collecting unique entities
        entities: dict[str, set[str]] = {}
        for attr in attributes:
            if not isinstance(attr, dict):
                continue
            total_attributes += 1
            atype = _safe_str(attr.get("type", ""))
            avalue = _safe_str(attr.get("value", ""))
            if not atype or not avalue:
                continue

            entity_type = _extract_entity_type(atype, avalue)
            if entity_type is None:
                continue

            if entity_type not in entities:
                entities[entity_type] = set()
            entities[entity_type].add(avalue)
            entity_type_counter[entity_type] += 1
            total_entities += 1

        # Extract event tags
        event_tags = _extract_tags(event)
        tag_str = ", ".join(sorted(event_tags)) if event_tags else "none"

        # Build threat-level summary
        tl_id = _safe_str(event.get("threat_level_id", "4"))
        threat_label = _THREAT_LEVEL_LABELS.get(tl_id, tl_id)

        # Build the content string to store in ZettelForge
        content = _build_event_note_content(event, attributes, entity_type_counter)

        # ── Ingest into ZettelForge ─────────────────────────────────────
        # Construct a human-readable summary prefixed with entity info so
        # the LLM/vector index can retrieve by IOC later.
        entity_summary_parts = []
        for etype, evalues in sorted(entities.items()):
            entity_summary_parts.append(f"{etype}: {', '.join(sorted(evalues))}")

        entity_summary = "; ".join(entity_summary_parts)
        ingest_content = (
            f"[MISP Event] {info}\n"
            f"UUID: {uuid}\n"
            f"Threat Level: {threat_label}\n"
            f"Tags: {tag_str}\n"
            f"Entities: {entity_summary}\n\n"
            f"{content}"
        )

        try:
            mm.remember(
                content=ingest_content,
                source_type="misp",
                source_ref=uuid,
                domain="cti",
            )
            total_events += 1
        except Exception as exc:
            print(
                f"WARNING: failed to ingest event {uuid} ({info[:60]}...): {exc}",
                file=sys.stderr,
            )
            total_skipped += 1
            continue

    # ── Summary ──────────────────────────────────────────────────────────
    stats = mm.get_stats()
    total_notes = stats.get("total_notes", 0)

    print("=" * 60)
    print("MISP INGEST SUMMARY")
    print("=" * 60)
    print(f"  File:                 {filepath}")
    print(f"  Events processed:     {total_events}")
    print(f"  Events skipped:       {total_skipped}")
    print(f"  Attributes scanned:   {total_attributes}")
    print(f"  Entities extracted:   {total_entities}")
    print(f"  ZettelForge notes:    {total_notes}")
    if entity_type_counter:
        print(f"  Entity type breakdown:")
        for etype, count in entity_type_counter.most_common():
            print(f"    {etype}: {count}")
    print("=" * 60)

    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest a MISP JSON export into ZettelForge memory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python examples/ingest_misp.py examples/sample_misp_event.json\n\n"
            "The MISP export file should contain a top-level 'response' key with\n"
            "an array of event objects, as produced by the MISP REST API."
        ),
    )
    parser.add_argument(
        "filepath",
        type=str,
        help="Path to a MISP JSON export file",
    )
    args = parser.parse_args()
    return ingest_misp_file(args.filepath)


if __name__ == "__main__":
    sys.exit(main())
