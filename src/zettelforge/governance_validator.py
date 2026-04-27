"""
Governance Validator for ZettelForge

Automatically validates operations against our governance documentation
(GOV-003, GOV-007, GOV-011, GOV-012, and GOV-013 for PII).

PII validation via Microsoft Presidio is optional -- disabled by default,
no new core dependencies. Requires ``pip install zettelforge[pii]`` and
``governance.pii.enabled: true`` in config.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from zettelforge.log import get_logger

if TYPE_CHECKING:
    from zettelforge.config import LimitsConfig, PIIConfig

_logger = get_logger("zettelforge.governance")


class GovernanceValidator:
    """
    Validates ZettelForge operations against governance rules.

    When ``pii_config`` is provided and enabled, PIIValidator is loaded
    lazily (soft dependency on presidio-analyzer). The core package never
    hard-depends on it.
    """

    def __init__(
        self,
        governance_dir: Path | None = None,
        pii_config: PIIConfig | None = None,
        limits_config: LimitsConfig | None = None,
    ):
        self.governance_dir = governance_dir
        self.rules = self._load_governance_rules()
        self._pii = None
        # RFC-014: operation limits (DoS mitigation)
        self._limits = limits_config

        # RFC-013: Optional PII validator. If the config says enabled but
        # presidio-analyzer is not installed, log a warning and continue --
        # no core functionality breaks.
        if pii_config and pii_config.enabled:
            try:
                from zettelforge.pii_validator import PIIValidator

                self._pii = PIIValidator(
                    action=pii_config.action,
                    placeholder=pii_config.redact_placeholder,
                    entities=pii_config.entities,
                    language=pii_config.language,
                    nlp_model=pii_config.nlp_model,
                )
                _logger.info("pii_validator_loaded", action=pii_config.action)
            except ImportError:
                _logger.warning(
                    "pii_validator_unavailable",
                    hint="Install with: pip install zettelforge[pii]",
                )

    def _load_governance_rules(self) -> dict:
        """Load key governance rules relevant to memory operations."""
        rules = {
            "GOV-003": {"python_standards": True, "type_hints": True, "naming": True},
            "GOV-007": {"testing": True, "coverage": 0.8},
            "GOV-011": {
                "security": True,
                "input_validation": True,
                "no_hardcoded_secrets": True,
            },
            "GOV-012": {"observability": True, "structured_logging": True},
        }
        return rules

    def validate_operation(self, operation: str, data: Any = None) -> tuple[bool, list[str]]:
        """
        Validate an operation against governance rules.

        Returns: (is_valid, list_of_violations)
        """
        violations = []

        if operation == "remember":
            if not isinstance(data, str) and not hasattr(data, "content"):
                violations.append("GOV-011: Input validation required for memory storage")

            if "GOV-012" in self.rules:
                pass  # Should log operation (placeholder)

        is_valid = len(violations) == 0
        return is_valid, violations

    def validate_remember(self, content: str) -> str:
        """Validate content for remember().

        Runs governance rules and optional PII detection.
        If PII is configured with action=redact, returns redacted content.
        If PII is configured with action=block and PII found, raises.

        Returns:
            Content safe to store (possibly redacted).
        """
        # Base governance validation
        is_valid, violations = self.validate_operation("remember", content)
        if not is_valid:
            raise GovernanceViolationError(f"Governance violation in remember: {violations}")

        # RFC-014: Content size limit (DoS mitigation)
        if (
            self._limits is not None
            and self._limits.max_content_length > 0
            and len(content) > self._limits.max_content_length
        ):
            raise GovernanceViolationError(
                f"Content exceeds max_content_length "
                f"({len(content)} > {self._limits.max_content_length} bytes). "
                f"Increase governance.limits.max_content_length or "
                f"reduce input size."
            )

        # RFC-013: Optional PII validation
        if self._pii is not None:
            try:
                passed, processed, detections = self._pii.validate(content)
            except ImportError:
                # presidio-analyzer not installed -- skip PII gracefully
                _logger.warning(
                    "pii_validation_skipped",
                    hint="Install with: pip install zettelforge[pii]",
                )
                return content
            except GovernanceViolationError:
                raise
            except Exception as exc:
                # PIIBlockedError and any other non-recoverable PII error
                # is converted to GovernanceViolationError so the caller
                # (memory_manager._remember_inner) catches it via its
                # existing except GovernanceViolationError handler.
                raise GovernanceViolationError(f"PII validation failed: {exc}") from exc
            if not passed:
                raise GovernanceViolationError(
                    f"PII validation blocked content: {len(detections)} detections"
                )
            if detections:
                _logger.info(
                    "pii_validation_applied",
                    action=self._pii._action,
                    count=len(detections),
                )
            return processed

        return content

    def enforce(self, operation: str, data: Any = None) -> str:
        """Enforce governance.

        For ``remember`` operations, returns (possibly redacted) content.
        For other operations, returns the original data.
        Raises GovernanceViolationError on violations.
        """
        # Always run the structural validation first so callers that pass
        # invalid data (e.g. ``None``) get a GovernanceViolationError, not a
        # silently-returned ``None`` or a ``TypeError`` deeper in the pipeline.
        is_valid, violations = self.validate_operation(operation, data)
        if not is_valid:
            raise GovernanceViolationError(f"Governance violation in {operation}: {violations}")

        if operation == "remember" and isinstance(data, str):
            return self.validate_remember(data)
        return data if isinstance(data, str) else ""


class GovernanceViolationError(Exception):
    """Raised when a governance rule is violated."""

    pass
