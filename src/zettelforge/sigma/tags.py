"""
Sigma tag resolver — namespaced tags → typed entity references.

Sigma tag spec (§tags appendix of sigma-rules-specification):
- ``attack.t1059``, ``attack.t1059.001`` → MITRE ATT&CK technique
- ``attack.g0007``                       → MITRE ATT&CK group (intrusion set)
- ``attack.s0154``                       → MITRE ATT&CK software (malware/tool)
- ``cve.2024.3094`` / ``cve.2021-44228`` → CVE reference
- ``tlp.amber``                          → TLP marking (metadata only, not entity)
- ``detection.*``                        → detection-meta tag (metadata only)

Everything else returns ``None`` — the caller still persists the raw
``SigmaTag`` entity but doesn't upgrade it to a typed cross-reference.
"""

from __future__ import annotations

import re

# attack.g\d+ / attack.s\d+  → IntrusionSet / Malware (not emitted as
# techniques). Only technique tags (T + digits, optionally .digits) become
# AttackPatterns.
_ATTACK_TECHNIQUE_RE = re.compile(r"^t\d+(\.\d+)?$", re.IGNORECASE)
_ATTACK_GROUP_RE = re.compile(r"^g\d+$", re.IGNORECASE)
_ATTACK_SOFTWARE_RE = re.compile(r"^s\d+$", re.IGNORECASE)


def _normalize_cve(suffix: str) -> str | None:
    """Normalize a Sigma CVE suffix (``2021-44228`` or ``2021.44228``) to
    canonical ``CVE-YYYY-NNNN`` form. Returns ``None`` if it doesn't match."""
    # Sigma writes cve.2024.3094 (dots) per the spec, but many rules in
    # the wild use cve.2024-3094. Accept both.
    parts = re.split(r"[.-]", suffix, maxsplit=1)
    if len(parts) != 2:
        return None
    year, num = parts
    if not (year.isdigit() and len(year) == 4 and num.replace("-", "").isdigit()):
        return None
    return f"CVE-{year}-{num}"


def resolve_sigma_tag(tag: str) -> tuple[str, str] | None:
    """Resolve a Sigma tag to a typed entity reference.

    Returns ``(entity_type, entity_value)`` for tags that upgrade to a
    typed reference, or ``None`` for tags that are metadata-only
    (``tlp.*``, ``detection.*``) or unrecognised namespaces.

    Ontology entity types returned:
    - ``AttackPattern`` for ``attack.t*`` (technique + sub-technique)
    - ``IntrusionSet`` for ``attack.g*``
    - ``Malware`` for ``attack.s*``
    - ``Vulnerability`` for ``cve.*``
    """
    if not isinstance(tag, str) or "." not in tag:
        return None

    namespace, _, suffix = tag.partition(".")
    namespace = namespace.lower()
    suffix = suffix.strip()

    if namespace == "attack":
        # Sub-namespace via suffix: t####, g####, s####, or tactic name.
        first = suffix.split(".", 1)[0].lower()
        if _ATTACK_TECHNIQUE_RE.match(suffix):
            # Canonical ATT&CK form is uppercase T-number.
            return ("AttackPattern", suffix.upper())
        if _ATTACK_GROUP_RE.match(first):
            return ("IntrusionSet", first.upper())
        if _ATTACK_SOFTWARE_RE.match(first):
            return ("Malware", first.upper())
        # tactic names ("initial-access", "execution", ...) aren't
        # first-class entities in the ontology; leave as raw SigmaTag.
        return None

    if namespace == "cve":
        canon = _normalize_cve(suffix)
        if canon:
            return ("Vulnerability", canon)
        return None

    if namespace in {"tlp", "detection"}:
        return None

    return None
