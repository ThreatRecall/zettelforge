"""
CCCS YARA metadata validator — clean-room re-implementation.

Upstream ``validator_functions.py`` is NOT vendored (see
``src/zettelforge/yara/schemas/NOTICE.md``). We read the vendored
``CCCS_YARA.yml`` and ``CCCS_YARA_values.yml`` to derive which meta keys
are required and what regex/value set each one should match, then do the
matching locally with stdlib ``re``.

Three tiers (phase-1c architecture §1.5):

* ``strict``     — every ``optional: No`` field must be present and valid.
                   Any failure → accepted=False, errors populated.
* ``warn``       — same checks, but failures are recorded as warnings and
                   ``accepted`` stays True. Default tier.
* ``non_cccs``   — accept unconditionally, no checks performed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, NamedTuple

import yaml

Tier = Literal["strict", "warn", "non_cccs"]


class YaraValidationError(ValueError):
    """Raised when a YARA rule fails validation hard enough that callers
    should treat it as unacceptable (mirrors :class:`~zettelforge.sigma.
    parser.SigmaValidationError` — ``validate_metadata`` itself still
    returns a :class:`ValidationResult` so strict/warn/non_cccs callers
    can inspect the outcome without catching)."""


class ValidationResult(NamedTuple):
    """Outcome of :func:`validate_metadata`."""

    accepted: bool
    warnings: list[str]
    errors: list[str]


# ---------------------------------------------------------------------------
# Schema loading — eager at import time so failures surface fast.
# ---------------------------------------------------------------------------

_SCHEMA_DIR = Path(__file__).parent / "schemas"
_CCCS_YARA_PATH = _SCHEMA_DIR / "CCCS_YARA.yml"
_CCCS_VALUES_PATH = _SCHEMA_DIR / "CCCS_YARA_values.yml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


CCCS_YARA_SPEC: dict[str, Any] = _load_yaml(_CCCS_YARA_PATH)
CCCS_YARA_VALUES: dict[str, Any] = _load_yaml(_CCCS_VALUES_PATH)


def _allowed_regexes(value_name: str) -> list[re.Pattern[str]]:
    """Return compiled alternation regexes for a named value set."""
    entries = CCCS_YARA_VALUES.get(value_name, []) or []
    patterns: list[re.Pattern[str]] = []
    for entry in entries:
        if isinstance(entry, dict) and "value" in entry:
            patterns.append(re.compile(entry["value"]))
    return patterns


# Named value sets we care about. Compiled once at import time.
_STATUS_REGEXES = _allowed_regexes("rule_statuses")
_SHARING_REGEXES = _allowed_regexes("sharing_classifications")
_CATEGORY_REGEXES = _allowed_regexes("category_types")
_MALWARE_TYPE_REGEXES = _allowed_regexes("malware_types")
_ACTOR_TYPE_REGEXES = _allowed_regexes("actor_types")
_HASH_REGEXES = _allowed_regexes("hash_types")

# From CCCS_YARA.yml: author's own regexExpression.
_AUTHOR_REGEX = re.compile(r"^[a-zA-Z]+\@[A-Z]+$|^[A-Z\s._\-]+$|^.*$")
_VERSION_REGEX = re.compile(r"^\d+\.\d+$")
_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID_REGEX = re.compile(r"^[0-9A-Za-z]{16,}$")  # base62 UUID, generous lower bound.
_FINGERPRINT_REGEX = re.compile(r"^[a-fA-F0-9]{40,64}$")  # SHA-1 / SHA-256-ish.
_MITRE_ATT_REGEX = re.compile(r"^(TA|T|M|G|S)\d{4}(\.\d{3})?$")


# Fields whose ``optional: No`` makes them required under CCCS-strict.
# Derived from CCCS_YARA.yml; we walk the spec dynamically so changes to
# the vendored YAML don't need code edits.
def _required_fields() -> list[str]:
    """Walk the CCCS YAML and collect fields we treat as required.

    We fold two CCCS notions into one gate:

    * ``optional: No`` — hard-required (``status``, ``sharing``, ``source``,
      ``author``, ``description``, ``category``).
    * ``optional: Optional`` — upstream *auto-generates* missing values
      (``id``, ``fingerprint``, ``version``, ``modified``). ZettelForge's
      validator does not auto-generate; we therefore treat them as required
      in ``strict`` tier so callers can't accidentally drop provenance.
      See phase-1c architecture §1.5.

    PyYAML silently coerces unquoted ``No``/``Yes`` into ``False``/``True``.
    We accept both string and bool forms so the vendored spec is unchanged.
    """
    required: list[str] = []
    for key, spec in CCCS_YARA_SPEC.items():
        if not isinstance(spec, dict):
            continue
        raw = spec.get("optional", "")
        if raw is False:
            required.append(key)
            continue
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"no", "optional"}:
                required.append(key)
    return required


REQUIRED_FIELDS: list[str] = _required_fields()


# ---------------------------------------------------------------------------
# Per-field validators — clean-room implementations of CCCS validator names.
# ---------------------------------------------------------------------------


def _regex_match(value: Any, patterns: list[re.Pattern[str]]) -> bool:
    if not isinstance(value, str):
        return False
    return any(p.search(value) is not None for p in patterns)


def _validate_field(name: str, value: Any) -> str | None:
    """Return an error string if invalid, else None."""
    if value is None or value == "":
        return f"{name}: empty value"

    if name == "id":
        return None if _UUID_REGEX.match(str(value)) else f"id: not a valid base62 UUID ({value!r})"
    if name == "fingerprint":
        return (
            None
            if _FINGERPRINT_REGEX.match(str(value))
            else f"fingerprint: expected hex digest ({value!r})"
        )
    if name == "version":
        return None if _VERSION_REGEX.match(str(value)) else f"version: expected x.y ({value!r})"
    if name in {"date", "modified"}:
        return None if _DATE_REGEX.match(str(value)) else f"{name}: expected YYYY-MM-DD ({value!r})"
    if name == "status":
        return (
            None
            if _regex_match(value, _STATUS_REGEXES)
            else f"status: not in rule_statuses ({value!r})"
        )
    if name == "sharing":
        return (
            None
            if _regex_match(value, _SHARING_REGEXES)
            else f"sharing: not in sharing_classifications ({value!r})"
        )
    if name == "category":
        return (
            None
            if _regex_match(value, _CATEGORY_REGEXES)
            else f"category: not in category_types ({value!r})"
        )
    if name == "malware_type":
        return (
            None
            if _regex_match(value, _MALWARE_TYPE_REGEXES)
            else f"malware_type: not in malware_types ({value!r})"
        )
    if name == "actor_type":
        return (
            None
            if _regex_match(value, _ACTOR_TYPE_REGEXES)
            else f"actor_type: not in actor_types ({value!r})"
        )
    if name == "hash":
        return None if _regex_match(value, _HASH_REGEXES) else "hash: not a known hash length"
    if name == "mitre_att":
        return (
            None
            if _MITRE_ATT_REGEX.match(str(value))
            else f"mitre_att: expected T#### / G#### / S#### ({value!r})"
        )
    if name == "author":
        return None if _AUTHOR_REGEX.match(str(value)) else f"author: unexpected format ({value!r})"
    if name == "source":
        # CCCS spec: "uppercase" via valid_source (source organization name).
        # Accept any non-empty string; uppercase is convention, not hard rule.
        return None
    if name == "description":
        return None if str(value).strip() else "description: empty"

    return None  # Unknown fields pass through.


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def validate_metadata(rule_meta: dict[str, Any], tier: Tier = "warn") -> ValidationResult:
    """Validate a rule's meta block against the vendored CCCS schema.

    Args:
        rule_meta: Flattened meta dict, as produced by
            :func:`zettelforge.yara.parser.parse_yara`.
        tier: Validation strictness. Default ``"warn"``.

    Returns:
        :class:`ValidationResult`. For ``non_cccs`` tier, returns
        ``(True, [], [])`` unconditionally.
    """
    if tier == "non_cccs":
        return ValidationResult(accepted=True, warnings=[], errors=[])

    warnings: list[str] = []
    errors: list[str] = []

    for required in REQUIRED_FIELDS:
        if required not in rule_meta or rule_meta[required] in (None, ""):
            msg = f"missing required CCCS field: {required}"
            if tier == "strict":
                errors.append(msg)
            else:
                warnings.append(msg)

    # Validate any present field, whether required or optional.
    for name, value in rule_meta.items():
        problem = _validate_field(name, value)
        if problem is None:
            continue
        if tier == "strict" and name in REQUIRED_FIELDS:
            errors.append(problem)
        else:
            warnings.append(problem)

    accepted = tier == "warn" or len(errors) == 0
    return ValidationResult(accepted=accepted, warnings=warnings, errors=errors)


__all__ = [
    "CCCS_YARA_SPEC",
    "CCCS_YARA_VALUES",
    "REQUIRED_FIELDS",
    "Tier",
    "ValidationResult",
    "validate_metadata",
]
