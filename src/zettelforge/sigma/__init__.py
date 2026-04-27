"""
ZettelForge Sigma ingest module.

Phase 3 implementation. See phase-1c-detection-rule-architecture.md §1.4
and phase-1b-sigma-architecture.md for the design rationale.
"""

from zettelforge.sigma.entities import SigmaRule, from_rule_dict, rule_to_entities
from zettelforge.sigma.ingest import ingest_rule, ingest_rules_dir
from zettelforge.sigma.parser import (
    SigmaParseError,
    SigmaValidationError,
    parse_file,
    parse_yaml,
    validate,
)
from zettelforge.sigma.tags import resolve_sigma_tag

__all__ = [
    "SigmaParseError",
    "SigmaRule",
    "SigmaValidationError",
    "from_rule_dict",
    "ingest_rule",
    "ingest_rules_dir",
    "parse_file",
    "parse_yaml",
    "resolve_sigma_tag",
    "rule_to_entities",
    "validate",
]
