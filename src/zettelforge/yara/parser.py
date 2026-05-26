"""
YARA rule parser — plyara wrapper.

Phase 3: wraps ``plyara.Plyara`` and normalises the output to a stable
shape we can rely on downstream.

Notes on plyara 2.2.x output (observed, verified against fixtures):
    * ``metadata`` is a *list of single-key dicts*, not a flat mapping.
    * Rule-level tags appear under ``tags`` on each rule dict (absent
      entirely when the rule has no tags).
    * Imports are attached to a rule dict only when that rule's condition
      references the import namespace. Parser-level imports live on
      ``Plyara.imports`` (a set). We copy them onto every rule so
      downstream code can rely on a per-rule ``imports`` list.
    * ``rule_name``, ``condition_terms``, ``raw_meta``/``raw_strings``/
      ``raw_condition`` are always present.

The parser preserves plyara's original keys and adds:
    * ``meta``: dict flattened from ``metadata`` (last-write-wins for dup
      keys; CCCS rules are expected to have unique keys).
    * ``imports``: list copied from parser-level ``Plyara.imports`` if the
      rule dict lacks one.
    * ``raw_rule``: the substring of the source file that produced this
      rule, carved by ``start_line``/``stop_line``. Useful for persisting
      rule text back into a note.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import plyara

#: Hard cap on the size of a single YARA rule file. Rules are text, typically
#: a few KB; a 1 MB ceiling catches runaway payloads without blocking normal
#: multi-rule files.
MAX_RULE_FILE_BYTES = 1_048_576  # 1 MB
_PARSER_LOCK = threading.Lock()
_PARSER: plyara.Plyara | None = None


class YaraParseError(ValueError):
    """Raised when a YARA rule file cannot be parsed or is otherwise rejected
    before it reaches :mod:`plyara` (I/O error, oversize, etc.)."""


def _flatten_metadata(metadata: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Collapse plyara's list-of-single-key dicts into a flat mapping."""
    if not metadata:
        return {}
    flat: dict[str, Any] = {}
    for entry in metadata:
        if not isinstance(entry, dict):
            continue
        for key, value in entry.items():
            flat[key] = value
    return flat


def _carve_raw_rule(source_lines: list[str], rule: dict[str, Any]) -> str:
    """Extract the raw source text for a rule using plyara line markers."""
    start = rule.get("start_line")
    stop = rule.get("stop_line")
    if not start or not stop or start < 1:
        return ""
    # plyara lines are 1-indexed and inclusive.
    return "\n".join(source_lines[start - 1 : stop])


def _get_parser() -> plyara.Plyara:
    global _PARSER
    if _PARSER is None:
        _PARSER = plyara.Plyara()
    return _PARSER


def parse_yara(text: str) -> list[dict[str, Any]]:
    """Parse YARA source text into a list of normalized rule dicts.

    A single .yar file may contain multiple rules; one dict per rule.
    """
    with _PARSER_LOCK:
        parser = _get_parser()
        parser.clear()
        try:
            rules: list[dict[str, Any]] = list(parser.parse_string(text))
            parser_imports = sorted(getattr(parser, "imports", set()) or [])
        except Exception as exc:  # plyara raises generic Exception on syntax errors
            raise ValueError(f"plyara parse error: {exc}") from exc
        finally:
            parser.clear()

    source_lines = text.splitlines()

    for rule in rules:
        rule["meta"] = _flatten_metadata(rule.get("metadata"))
        # Promote parser-level imports when the rule dict lacks its own.
        if not rule.get("imports") and parser_imports:
            rule["imports"] = list(parser_imports)
        rule.setdefault("tags", [])
        rule["raw_rule"] = _carve_raw_rule(source_lines, rule)

    return rules


def parse_file(path: str | Path) -> list[dict[str, Any]]:
    """Parse a .yar/.yara file into a list of normalized rule dicts."""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError as exc:
        raise YaraParseError(f"cannot stat {p}: {exc}") from exc
    if size > MAX_RULE_FILE_BYTES:
        raise YaraParseError(f"rule file too large ({size} bytes, max {MAX_RULE_FILE_BYTES}): {p}")
    text = p.read_text(encoding="utf-8")
    return parse_yara(text)


# Legacy alias expected by existing Phase 2 scaffolding.
def parse_text(yara_text: str) -> list[dict[str, Any]]:
    """Alias for :func:`parse_yara`. Retained for scaffold compatibility."""
    return parse_yara(yara_text)
