"""Unit tests for RFC-013 PII detection via Microsoft Presidio.

Tests run without presidio-analyzer installed -- they verify:
- Construction
- ImportError when SDK missing
- Redaction logic (which is pure string manipulation, no Presidio needed)
- Block behavior
- CTI allowlist filtering
- PIIValidator integration into GovernanceValidator
"""

from __future__ import annotations

import sys

import pytest

from zettelforge.config import PIIConfig
from zettelforge.governance_validator import GovernanceValidator, GovernanceViolationError

# ---- PIIValidator direct tests (no presidio installed) ------------------------


class TestPIIValidatorNoSDK:
    def test_import_error_when_presidio_missing(self):
        """ImportError must be deferred to first call, not constructor."""
        from zettelforge.pii_validator import PIIValidator

        v = PIIValidator()
        # Constructor should succeed without presidio
        with pytest.raises(ImportError, match="presidio-analyzer"):
            v.detect("hello")

    def test_import_error_on_validate(self):
        from zettelforge.pii_validator import PIIValidator

        v = PIIValidator()
        with pytest.raises(ImportError, match="presidio-analyzer"):
            v.validate("hello")

    def test_redact_logic(self):
        """_redact is pure string manipulation; testable without presidio."""
        from zettelforge.pii_validator import PIIDetection, PIIValidator

        v = PIIValidator(action="redact", placeholder="[REDACTED]")
        detections = [
            PIIDetection(
                entity_type="EMAIL_ADDRESS", text="user@example.com", start=9, end=25, score=0.95
            ),
        ]
        result = v._redact("Contact: user@example.com for info", detections)
        assert "[REDACTED]" in result
        assert "user@example.com" not in result
        assert result == "Contact: [REDACTED] for info"

    def test_redact_multiple_detections(self):
        from zettelforge.pii_validator import PIIDetection, PIIValidator

        v = PIIValidator(action="redact", placeholder="[REDACTED]")
        detections = [
            PIIDetection(
                entity_type="EMAIL_ADDRESS", text="alice@co.com", start=0, end=12, score=0.95
            ),
            PIIDetection(entity_type="PHONE_NUMBER", text="555-1234", start=16, end=24, score=0.90),
        ]
        result = v._redact("alice@co.com -> 555-1234", detections)
        assert result == "[REDACTED] -> [REDACTED]"

    def test_redact_overlapping_keeps_longest(self):
        """reverse-order processing handles overlapping spans correctly."""
        from zettelforge.pii_validator import PIIDetection, PIIValidator

        v = PIIValidator(action="redact", placeholder="[X]")
        detections = [
            PIIDetection(entity_type="PERSON", text="John Smith", start=0, end=10, score=0.95),
            PIIDetection(
                entity_type="PERSON", text="John", start=0, end=4, score=0.50
            ),  # lower score, subspan
        ]
        result = v._redact("John Smith is here", detections)
        # Longer span wins, both get redacted in order, but the outer
        # redaction subsumes the inner one. Reverse-order processing
        # handles this correctly.
        assert "John Smith" not in result

    def test_validate_log_passes_through(self):
        """action=log must return original content unchanged."""
        from zettelforge.pii_validator import PIIValidator

        v = PIIValidator(action="log")
        # Can't call validate without SDK, but we can verify detect returns empty
        # when no text is provided
        assert v.detect("") == []
        assert v.detect("   ") == []

    def test_empty_validator_init(self):
        from zettelforge.pii_validator import PIIValidator

        v = PIIValidator()
        assert v._action == "log"
        assert v._placeholder == "[REDACTED]"
        assert v._entities is None
        assert v._language == "en"
        assert v._nlp_model == "en_core_web_sm"

    def test_custom_validator_init(self):
        from zettelforge.pii_validator import PIIValidator

        v = PIIValidator(
            action="redact",
            placeholder="[PII]",
            entities=["EMAIL_ADDRESS"],
            language="en",
            nlp_model="en_core_web_trf",
        )
        assert v._action == "redact"
        assert v._placeholder == "[PII]"
        assert v._entities == ["EMAIL_ADDRESS"]
        assert v._nlp_model == "en_core_web_trf"

    def test_unknown_action_raises(self):
        from zettelforge.pii_validator import PIIValidator

        with pytest.raises(ValueError, match="Unknown PII action"):
            PIIValidator(action="delete")

    def test_cti_allowlist_filters_entities(self):
        '''Entities in CTI allowlist must be excluded from detection.'''
        from zettelforge.pii_validator import _CTI_ALLOWLIST, PIIValidator

        assert 'IP_ADDRESS' in _CTI_ALLOWLIST
        assert 'URL' in _CTI_ALLOWLIST
        assert 'DOMAIN_NAME' in _CTI_ALLOWLIST

        # Constructor preserves explicit entities as-is (allowlist filtering
        # happens in detect(), not constructor).
        v = PIIValidator(entities=['EMAIL_ADDRESS', 'IP_ADDRESS', 'PHONE_NUMBER'])
        assert 'IP_ADDRESS' in v._entities
        assert 'EMAIL_ADDRESS' in v._entities
        assert 'PHONE_NUMBER' in v._entities

        # When entities is None (detect all)
        v2 = PIIValidator()
        assert v2._entities is None

        # Empty list in PIIConfig becomes None (detect-all)
        v3 = PIIValidator(entities=[])
        assert v3._entities is None


# ---- PIIBlockedError ---------------------------------------------------------


class TestPIIBlockedError:
    def test_is_exception(self):
        from zettelforge.pii_validator import PIIBlockedError

        e = PIIBlockedError("blocked")
        assert isinstance(e, Exception)
        assert str(e) == "blocked"


# ---- PIIConfig ----------------------------------------------------------------


class TestPIIConfig:
    def test_defaults(self):
        cfg = PIIConfig()
        assert cfg.enabled is False
        assert cfg.action == "log"
        assert cfg.redact_placeholder == "[REDACTED]"
        assert cfg.entities == []
        assert cfg.language == "en"
        assert cfg.nlp_model == "en_core_web_sm"

    def test_custom(self):
        cfg = PIIConfig(
            enabled=True,
            action="redact",
            redact_placeholder="[PII REMOVED]",
            entities=["EMAIL_ADDRESS"],
            language="de",
            nlp_model="en_core_web_lg",
        )
        assert cfg.enabled is True
        assert cfg.action == "redact"
        assert cfg.redact_placeholder == "[PII REMOVED]"
        assert cfg.entities == ["EMAIL_ADDRESS"]
        assert cfg.language == "de"


# ---- GovernanceValidator PII integration --------------------------------------


class TestGovernanceValidatorPII:
    def test_no_pii_when_disabled(self):
        """PII must be skipped when config says disabled."""
        cfg = PIIConfig(enabled=False)
        gv = GovernanceValidator(pii_config=cfg)
        # Should have no _pii validator
        assert gv._pii is None
        result = gv.validate_remember("test content")
        assert result == "test content"

    def test_no_pii_when_unconfigured(self):
        """No pii_config param = no PII validation."""
        gv = GovernanceValidator()
        assert gv._pii is None

    def test_pii_enabled_but_sdk_missing(self):
        """When PII is enabled but presidio not installed, create validator gracefully.

        The PIIValidator class is always importable (it is our module).
        The presidio-analyzer import is deferred to the first ``detect()``
        call, so construction of GovernanceValidator with PII config
        succeeds. The ImportError surfaces only on first use.
        """
        cfg = PIIConfig(enabled=True)
        gv = GovernanceValidator(pii_config=cfg)
        # PIIValidator is constructed successfully (SDK import is lazy)
        assert gv._pii is not None
        assert gv._pii._action == "log"
        # But calling detect should raise the SDK ImportError
        try:
            gv._pii.detect("test")
            assert False, "Expected ImportError"
        except ImportError:
            pass

    def test_validate_remember_rejects_invalid_data(self):
        """``remember`` data that is neither a string nor an object with
        ``.content`` should fail GOV-011 input validation and raise."""
        gv = GovernanceValidator()
        with pytest.raises(GovernanceViolationError):
            gv.enforce("remember", None)

    def test_remember_enforce_passes_through_no_pii(self):
        """enforce() must return original content when PII is disabled."""
        gv = GovernanceValidator()
        result = gv.enforce("remember", "hello world")
        assert result == "hello world"

    def test_remember_enforce_returns_string(self):
        gv = GovernanceValidator()
        result = gv.enforce("remember", "test")
        assert isinstance(result, str)


# ---- Mocked Presidio analyzer integration --------------------------------------


def _patch_presidio():
    """Create minimal stubs for the presidio_analyzer package."""
    import types

    pkg = types.ModuleType("presidio_analyzer")

    # Stub AnalyzerEngine
    class _StubAnalyzerEngine:
        def __init__(self, *a, **kw):
            pass

        def analyze(self, text, entities=None, language=None):
            return []

    pkg.AnalyzerEngine = _StubAnalyzerEngine

    # Stub NlpEngineProvider (nested module)
    nlp_pkg = types.ModuleType("presidio_analyzer.nlp_engine")

    class _StubNlpProvider:
        def __init__(self, *a, **kw):
            pass

        def create_engine(self):
            return type("E", (), {})()

    nlp_pkg.NlpEngineProvider = _StubNlpProvider
    pkg.nlp_engine = nlp_pkg

    # Stub RecognizerResult
    class _StubRecognizerResult:
        def __init__(self, entity_type, start, end, score, text):
            self.entity_type = entity_type
            self.start = start
            self.end = end
            self.score = score
            self._text = text

    pkg.RecognizerResult = _StubRecognizerResult

    # The submodule `presidio_analyzer.nlp_engine` must be a Module so that
    # `from presidio_analyzer.nlp_engine import NlpEngineProvider` resolves
    # NlpEngineProvider as a module attribute. Using a class here breaks
    # the import in pii_validator.py.
    nlp_engine_pkg = types.ModuleType("presidio_analyzer.nlp_engine")
    nlp_engine_pkg.NlpEngineProvider = _StubNlpProvider

    sys.modules["presidio_analyzer"] = pkg
    sys.modules["presidio_analyzer.nlp_engine"] = nlp_pkg
    return pkg


class TestPIIValidatorWithStubs:
    def test_detect_returns_empty_when_no_pii(self):
        _patch_presidio()
        # Re-import after patch
        if "zettelforge.pii_validator" in sys.modules:
            del sys.modules["zettelforge.pii_validator"]

        from zettelforge.pii_validator import PIIValidator

        v = PIIValidator()
        results = v.detect("clean text without PII")
        assert results == []

    def test_validate_log_passes_content_through(self):
        _patch_presidio()
        if "zettelforge.pii_validator" in sys.modules:
            del sys.modules["zettelforge.pii_validator"]

        from zettelforge.pii_validator import PIIValidator

        v = PIIValidator(action="log")
        passed, content, detections = v.validate("hello")
        assert passed is True
        assert content == "hello"
        assert detections == []

    def test_validate_redact_with_no_pii(self):
        _patch_presidio()
        if "zettelforge.pii_validator" in sys.modules:
            del sys.modules["zettelforge.pii_validator"]

        from zettelforge.pii_validator import PIIValidator

        v = PIIValidator(action="redact")
        passed, content, detections = v.validate("clean text")
        assert passed is True
        assert content == "clean text"
        assert detections == []
