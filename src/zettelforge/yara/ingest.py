"""
YARA ingest — high-level Python API.

Orchestrates the per-rule pipeline:

    parse  →  CCCS metadata validate  →  entity extraction  →  MemoryManager.remember

A single ``.yar`` file may contain multiple rules. We create one note per
rule so downstream retrieval can hit at rule granularity.

Idempotency: we look up existing notes by ``source_ref`` (which is the
rule id + content hash) before calling ``remember`` a second time. This
matches what ZettelForge already does for OpenCTI sync.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zettelforge.yara.entities import YaraRule, rule_to_entities
from zettelforge.yara.parser import parse_file, parse_yara

if TYPE_CHECKING:  # pragma: no cover
    from zettelforge.memory_manager import MemoryManager
    from zettelforge.note_schema import MemoryNote

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Note formatting
# ---------------------------------------------------------------------------


def _build_note_content(
    entity: YaraRule,
    rule_dict: dict[str, Any],
    source_path: str | None = None,
) -> str:
    """Construct the note body: raw rule text + blank line + summary."""
    raw = rule_dict.get("raw_rule") or ""
    summary_bits: list[str] = [f"YARA rule: {entity.rule_name}"]
    if entity.category:
        summary_bits.append(f"category={entity.category}")
    if entity.technique_tag:
        summary_bits.append(f"technique={entity.technique_tag}")
    mitre_from_relations = [
        (r.get("properties") or {}).get("technique_id")
        for r in rule_dict.get("_relations", [])
        if r.get("rel") == "detects"
    ]
    if mitre_from_relations:
        summary_bits.append("mitre_att=" + ",".join(filter(None, mitre_from_relations)))
    if entity.author:
        summary_bits.append(f"author={entity.author}")
    summary_bits.append(f"cccs_tier={entity.extra.get('cccs_compliant')}")
    if source_path:
        summary_bits.append(f"source_path={source_path}")
    summary = "  |  ".join(summary_bits)

    body = raw.strip() if raw else (entity.rule_name or "")
    return f"{body}\n\n{summary}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ingest_rule(
    rule_source: str | Path | dict[str, Any],
    mm: MemoryManager | None = None,
    *,
    domain: str = "detection",
    tier: str = "warn",
) -> tuple[MemoryNote | None, list[dict[str, Any]]]:
    """Ingest a single YARA rule (file, text, or pre-parsed dict).

    Args:
        rule_source: Path to ``.yar`` file, raw YARA source text, or a
            single pre-parsed plyara dict. When a file contains multiple
            rules, only the first is ingested here — use
            :func:`ingest_rules_dir` or pass a directory to batch.
        mm: :class:`~zettelforge.memory_manager.MemoryManager` instance.
            Required; ``None`` raises ``ValueError`` so callers don't
            silently lose rules.
        domain: Memory domain for the note. Default ``"detection"``.
        tier: CCCS validation tier. ``"warn"`` (default), ``"strict"``,
            or ``"non_cccs"``.

    Returns:
        ``(note, relations)``. ``note`` is ``None`` only when CCCS
        strict-tier validation rejected the rule.
    """
    if mm is None:
        raise ValueError("ingest_rule requires a MemoryManager instance")

    rules = _normalize_source(rule_source)
    if not rules:
        return None, []

    rule_dict = rules[0]
    note, relations, _is_new = _ingest_single(rule_dict, mm, domain=domain, tier=tier)
    return note, relations


def ingest_rules_dir(
    path: str | Path,
    mm: MemoryManager | None = None,
    *,
    glob: str = "**/*.yar",
    tier: str = "warn",
    domain: str = "detection",
) -> dict[str, Any]:
    """Walk a directory tree and ingest every YARA rule file.

    Returns:
        ``{"ingested": int, "skipped": int, "errors": list[str]}``
    """
    if mm is None:
        raise ValueError("ingest_rules_dir requires a MemoryManager instance")

    root = Path(path)
    if not root.exists():
        return {"ingested": 0, "skipped": 0, "errors": [f"path does not exist: {path}"]}

    ingested = 0
    skipped = 0
    errors: list[str] = []

    # Support both .yar and .yara via caller-supplied glob, plus a default
    # extra sweep for .yara if caller used the default glob.
    globs = [glob]
    if glob == "**/*.yar":
        globs.append("**/*.yara")

    root_resolved = root.resolve()
    seen: set[Path] = set()
    for pattern in globs:
        for yar_path in sorted(root.glob(pattern)):
            if yar_path in seen or not yar_path.is_file():
                continue
            seen.add(yar_path)
            # SEC-3: never follow symlinks and never read files whose real
            # path escapes the rules directory — refuses the "point at
            # /etc/passwd via symlink" trick.
            if yar_path.is_symlink():
                _LOG.warning(
                    "ingest_skipped_symlink path=%s resolved_target=%s",
                    yar_path,
                    yar_path.resolve(strict=False),
                )
                skipped += 1
                continue
            try:
                resolved = yar_path.resolve(strict=False)
            except OSError:
                skipped += 1
                continue
            if root_resolved not in resolved.parents and resolved != root_resolved:
                _LOG.warning(
                    "ingest_skipped_symlink path=%s resolved_target=%s",
                    yar_path,
                    resolved,
                )
                skipped += 1
                continue
            try:
                rules = parse_file(yar_path)
            except Exception as exc:  # pragma: no cover — defensive
                errors.append(f"{yar_path}: parse failed ({exc})")
                skipped += 1
                continue

            for rule_dict in rules:
                try:
                    note, _rel, is_new = _ingest_single(
                        rule_dict,
                        mm,
                        domain=domain,
                        tier=tier,
                        source_path=str(yar_path),
                    )
                except Exception as exc:  # pragma: no cover — defensive
                    errors.append(f"{yar_path}:{rule_dict.get('rule_name')}: {exc}")
                    skipped += 1
                    continue
                if note is None:
                    # Strict-tier rejection or other hard skip.
                    skipped += 1
                elif is_new:
                    ingested += 1
                else:
                    # Already present (idempotent hit).
                    skipped += 1

    return {"ingested": ingested, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _normalize_source(src: str | Path | dict[str, Any]) -> list[dict[str, Any]]:
    """Turn any of (Path, raw text, parsed dict) into a list of rule dicts."""
    if isinstance(src, dict):
        # Pre-parsed. Make sure we have our normalized shape.
        if "meta" not in src and "metadata" in src:
            from zettelforge.yara.parser import _flatten_metadata  # local import

            src = {**src, "meta": _flatten_metadata(src.get("metadata"))}
        return [src]

    if isinstance(src, Path):
        return parse_file(src)

    text = str(src)
    if "\n" not in text and Path(text).expanduser().exists():
        return parse_file(Path(text).expanduser())
    return parse_yara(text)


def _ingest_single(
    rule_dict: dict[str, Any],
    mm: MemoryManager,
    *,
    domain: str,
    tier: str,
    source_path: str | None = None,
) -> tuple[MemoryNote | None, list[dict[str, Any]], bool]:
    """Ingest one rule. Returns ``(note_or_None, relations, is_new)``.

    ``is_new`` is ``False`` when the rule was already present and we hit
    the idempotent shortcut; ``True`` on first-time ingest.
    """
    entity, relations = rule_to_entities(rule_dict, tier=tier)

    if tier == "strict" and entity.extra.get("cccs_compliant") != "strict":
        _LOG.info(
            "skipping rule %s: CCCS strict validation failed (errors=%s)",
            entity.rule_name,
            entity.extra.get("cccs_errors"),
        )
        return None, relations, False

    # Attach relations so _build_note_content can summarise MITRE refs.
    rule_dict_for_content = dict(rule_dict)
    rule_dict_for_content["_relations"] = relations

    source_ref = f"yara:{entity.rule_id}:{entity.content_sha256[:12]}"

    # Idempotency — the exact same rule body is only stored once.
    existing = mm.store.get_note_by_source_ref(source_ref)
    if existing is not None:
        return existing, relations, False

    content = _build_note_content(entity, rule_dict_for_content, source_path=source_path)
    note, _status = mm.remember(
        content=content,
        source_type="yara",
        source_ref=source_ref,
        domain=domain,
        sync=True,
    )

    # CR-B1: persist every relation as a KG edge keyed on the YaraRule's
    # ``entity.rule_id`` / note id. Mirrors ``sigma/ingest._persist_relations``.
    _persist_relations(mm, relations, note_id=note.id)

    # source_path, cccs_tier, mitre refs are recorded inside the note body
    # (see _build_note_content) and on the returned entity/relations. The
    # Metadata schema doesn't expose an extras bucket yet, so we avoid
    # mutating it here — Phase 4 can add a typed metadata extension if
    # downstream consumers need keyed access without re-parsing.
    return note, relations, True


def _persist_relations(mm: MemoryManager, relations: list[dict[str, Any]], *, note_id: str) -> None:
    """Write each canonical-shape relation into the KG via the storage backend.

    Mirrors ``zettelforge.sigma.ingest._persist_relations``: same defensive
    guards, same ``edge_type='detection'`` / ``source='yara_ingest'``
    tagging so the enrichment worker can distinguish them from causal or
    heuristic edges.
    """
    store = getattr(mm, "store", None)
    if store is None or not hasattr(store, "add_kg_edge"):
        return
    for rel in relations:
        props = dict(rel.get("properties") or {})
        props.setdefault("edge_type", "detection")
        props.setdefault("source", "yara_ingest")
        try:
            store.add_kg_edge(
                from_type=rel["from_type"],
                from_value=rel["from_value"],
                to_type=rel["to_type"],
                to_value=rel["to_value"],
                relationship=rel["rel"],
                note_id=note_id,
                properties=props,
            )
        except Exception:  # pragma: no cover — defensive
            _LOG.warning(
                "yara_edge_persist_failed from=%s rel=%s to=%s",
                rel.get("from_value"),
                rel.get("rel"),
                rel.get("to_value"),
                exc_info=True,
            )


__all__ = ["ingest_rule", "ingest_rules_dir"]


if __name__ == "__main__":
    # Delegate to the YARA CLI so ``python -m zettelforge.yara.ingest`` works.
    import sys

    from zettelforge.yara.cli import main as _cli_main

    sys.exit(_cli_main(sys.argv[1:]))
