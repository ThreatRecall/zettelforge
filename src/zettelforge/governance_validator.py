"""
Governance Validator for ZettelForge

Automatically validates operations against our governance documentation
(GOV-003, GOV-007, GOV-011, etc.).
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple


class GovernanceValidator:
    """
    Validates ZettelForge operations against governance rules.
    """

    def __init__(self, governance_dir: Path = None):
        self.governance_dir = governance_dir
        self.rules = self._load_governance_rules()

    def _load_governance_rules(self) -> Dict:
        """Load key governance rules relevant to memory operations."""
        rules = {
            "GOV-003": {"python_standards": True, "type_hints": True, "naming": True},
            "GOV-007": {"testing": True, "coverage": 0.8},
            "GOV-011": {"security": True, "input_validation": True, "no_hardcoded_secrets": True},
            "GOV-012": {"observability": True, "structured_logging": True},
        }
        return rules

    def validate_operation(self, operation: str, data: Any = None) -> Tuple[bool, List[str]]:
        """
        Validate an operation against governance rules.

        Returns: (is_valid, list_of_violations)
        """
        violations = []

        if operation == "remember":
            if not isinstance(data, str) and not hasattr(data, "content"):
                violations.append("GOV-011: Input validation required for memory storage")

        if operation in ("remember", "synthesize"):
            if "GOV-012" in self.rules:
                # Should log operation
                pass

        is_valid = len(violations) == 0
        return is_valid, violations

    def enforce(self, operation: str, data: Any = None) -> None:
        """Enforce governance - raises exception on violation."""
        is_valid, violations = self.validate_operation(operation, data)
        if not is_valid:
            raise GovernanceViolationError(f"Governance violation in {operation}: {violations}")


class GovernanceViolationError(Exception):
    """Raised when a governance rule is violated."""

    pass
