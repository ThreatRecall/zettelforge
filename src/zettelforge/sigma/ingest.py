"""
Sigma ingest — high-level Python API.

``ingest_rule`` orchestrates the pipeline:

1. Parse & validate YAML against the vendored SigmaHQ schema.
2. Build a ``SigmaRule`` entity + relation list.
3. Construct the memory-note content (YAML body + summary).
4. Persist the note via ``MemoryManager.remember``.
5. Write the relations into the backend KG via ``store.add_kg_edge``.

The LLM rule explainer is NOT invoked here — that's Stream C's concern and
runs asynchronously off an enrichment queue.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from zettelforge.sigma.entities import SigmaRule, from_rule_dict
from zettelforge.sigma.parser import (
    SigmaParseError,
    SigmaValidationError,
    parse_file,
    parse_yaml,
)

_log = logging.getLogger(__name__)

# What the caller may pass as ``rule`` — a parsed dict, a raw YAML string, or
# a Path to a .yml/.yaml file.
RuleSource = dict | str | Path


def ingest_rule(
    rule: RuleSource,
    mm: Any,
    *,
    domain: str = "detection",
    source_ref: str | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    """Ingest a single Sigma rule.

    Args:
        rule: Parsed dict, raw YAML string, or ``Path`` to a ``.yml`` file.
        mm: A :class:`zettelforge.memory_manager.MemoryManager` instance.
        domain: Memory domain for the note (default ``"detection"``).
        source_ref: Override ``source_ref`` on the note (defaults to the
            rule id for dict/str input, or the file path for Path input).

    Returns:
        ``(note, relations)`` — the :class:`MemoryNote` persisted and the
        list of emitted relation dicts.

    Raises:
        SigmaParseError: YAML could not be parsed.
        SigmaValidationError: rule failed JSON-schema validation.
        ValueError: ``mm`` was ``None`` — caller must pass a real manager
            so rules are not silently dropped. Matches YARA parity.
    """
    if mm is None:
        raise ValueError("ingest_rule requires a MemoryManager instance")

    rule_dict, _default_ref = _coerce(rule)
    entity, relations = from_rule_dict(rule_dict)

    # CR-W2: adopt the format-prefixed + content-hash-scoped source_ref that
    # YARA already uses. Idempotency is handled by the same ``source_ref``
    # lookup pattern, so re-ingesting an unchanged rule returns the original
    # note instead of creating a duplicate.
    effective_source_ref = source_ref or f"sigma:{entity.rule_id}:{entity.content_sha256[:12]}"

    store = getattr(mm, "store", None)
    if store is not None and hasattr(store, "get_note_by_source_ref"):
        existing = store.get_note_by_source_ref(effective_source_ref)
        if existing is not None:
            return existing, relations

    content = _build_content(rule_dict, entity)
    note, _status = mm.remember(
        content=content,
        source_type="sigma_rule",
        source_ref=effective_source_ref,
        domain=domain,
        sync=True,
    )

    _persist_relations(mm, relations, note_id=note.id)
    return note, relations


def ingest_rules_dir(
    path: str | Path,
    mm: Any,
    *,
    glob: str = "**/*.yml",
    domain: str = "detection",
) -> tuple[int, int]:
    """Walk a directory, ingesting every matching Sigma rule.

    Returns ``(ingested, skipped)`` — the skip count covers per-file parse
    or validation errors, which are logged but do not abort the walk.
    """
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"sigma rules directory not found: {root}")

    ingested = 0
    skipped = 0
    root_resolved = root.resolve()
    # Accept both .yml and .yaml; de-duplicate in case the glob overlaps.
    candidates = sorted({*root.glob(glob), *root.glob(glob.replace(".yml", ".yaml"))})
    for fpath in candidates:
        if not fpath.is_file():
            continue
        # SEC-3: refuse to follow symlinks or paths that resolve outside the
        # root. Prevents a malicious rule tree from luring ingest into
        # /etc/passwd or any other file on disk.
        if fpath.is_symlink():
            _log.warning(
                "ingest_skipped_symlink path=%s resolved_target=%s",
                fpath,
                fpath.resolve(strict=False),
            )
            skipped += 1
            continue
        try:
            resolved = fpath.resolve(strict=False)
        except OSError:
            skipped += 1
            continue
        if root_resolved not in resolved.parents and resolved != root_resolved:
            _log.warning(
                "ingest_skipped_symlink path=%s resolved_target=%s",
                fpath,
                resolved,
            )
            skipped += 1
            continue
        try:
            ingest_rule(fpath, mm, domain=domain)
            ingested += 1
        except (SigmaParseError, SigmaValidationError) as exc:
            _log.warning("sigma_ingest_skip path=%s reason=%s", fpath, exc)
            skipped += 1
        except Exception as exc:  # pragma: no cover — defensive
            _log.warning("sigma_ingest_error path=%s reason=%s", fpath, exc)
            skipped += 1
    return ingested, skipped


# ── Internals ────────────────────────────────────────────────────────────────


def _coerce(rule: RuleSource) -> tuple[dict[str, Any], str | None]:
    """Turn the caller's input into ``(parsed_dict, default_source_ref)``."""
    if isinstance(rule, dict):
        return rule, None
    if isinstance(rule, Path):
        return parse_file(rule), str(rule)
    if isinstance(rule, str):
        # Disambiguate: does it look like a path on disk?
        maybe_path = Path(rule)
        if len(rule) < 4096 and "\n" not in rule and maybe_path.is_file():
            return parse_file(maybe_path), str(maybe_path)
        return parse_yaml(rule), None
    raise TypeError(f"unsupported rule source: {type(rule).__name__}")


def _build_content(rule_dict: dict[str, Any], entity: SigmaRule) -> str:
    """Note body = full YAML + blank line + one-line summary.

    The YAML body is what vector/keyword search will hit; the summary is
    the operator-facing gist.
    """
    body = yaml.safe_dump(rule_dict, sort_keys=False, default_flow_style=False)
    logsource = []
    if entity.logsource_product:
        logsource.append(f"product={entity.logsource_product}")
    if entity.logsource_service:
        logsource.append(f"service={entity.logsource_service}")
    if entity.logsource_category:
        logsource.append(f"category={entity.logsource_category}")
    summary = (
        f"[sigma] {entity.title or '(untitled)'} "
        f"level={entity.rule_level or 'n/a'} "
        f"status={entity.rule_status or 'n/a'} "
        f"logsource=[{','.join(logsource) or 'n/a'}]"
    )
    return f"{body.rstrip()}\n\n{summary}\n"


def _persist_relations(mm: Any, relations: list[dict[str, Any]], note_id: str) -> None:
    """Write each relation dict into the KG via the storage backend."""
    store = getattr(mm, "store", None)
    if store is None or not hasattr(store, "add_kg_edge"):
        return  # Caller passed something that isn't a MemoryManager — no-op.
    for rel in relations:
        props = dict(rel.get("properties") or {})
        # Tag these edges so Stream C can distinguish them from causal
        # edges (edge_type='causal') and heuristic edges (edge_type='heuristic').
        props.setdefault("edge_type", "detection")
        props.setdefault("source", "sigma_ingest")
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
            _log.warning(
                "sigma_edge_persist_failed from=%s rel=%s to=%s",
                rel.get("from_value"),
                rel.get("rel"),
                rel.get("to_value"),
                exc_info=True,
            )


if __name__ == "__main__":  # pragma: no cover
    # Delegate to the CLI — `python -m zettelforge.sigma.ingest <path>`.
    import sys

    from zettelforge.sigma.cli import main

    sys.exit(main(sys.argv[1:]))
