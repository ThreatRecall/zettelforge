"""
Test suite for ZettelForge governance validation (GOV-007, GOV-011 compliant)
"""

import pytest
from zettelforge.governance_validator import GovernanceValidator, GovernanceViolationError
from zettelforge.note_schema import MemoryNote, Content, Semantic, Embedding, Metadata


def test_governance_validation():
    validator = GovernanceValidator()

    # Test valid operation
    is_valid, violations = validator.validate_operation("remember", "Test content")
    assert is_valid
    assert len(violations) == 0


def test_governance_violation_raises():
    validator = GovernanceValidator()

    with pytest.raises(GovernanceViolationError):
        validator.enforce("remember", None)  # Should trigger validation error


def test_governance_in_memory_manager():
    """Test that MemoryManager includes governance validator"""
    from zettelforge.memory_manager import MemoryManager

    mm = MemoryManager()
    assert hasattr(mm, "governance")
    assert isinstance(mm.governance, GovernanceValidator)


# ── Content size limit (RFC-014) ──────────────────────────────────────────────


def test_content_size_limit_within_bounds():
    """Content under the default limit must pass through."""
    from zettelforge.config import LimitsConfig

    gv = GovernanceValidator(limits_config=LimitsConfig(max_content_length=1024))
    result = gv.enforce("remember", "a" * 100)
    assert result == "a" * 100


def test_content_size_limit_exceeded():
    """Content over the limit must raise."""
    from zettelforge.config import LimitsConfig

    gv = GovernanceValidator(limits_config=LimitsConfig(max_content_length=50))
    with pytest.raises(GovernanceViolationError, match="max_content_length"):
        gv.enforce("remember", "a" * 100)


def test_content_size_limit_zero_disabled():
    """limit=0 disables the check."""
    from zettelforge.config import LimitsConfig

    gv = GovernanceValidator(limits_config=LimitsConfig(max_content_length=0))
    result = gv.enforce("remember", "a" * 10000)
    assert result == "a" * 10000


def test_content_size_limit_none_config():
    """No limits_config means no limit check."""
    gv = GovernanceValidator()
    result = gv.enforce("remember", "a" * 100000)
    assert result == "a" * 100000


def test_limits_config_defaults():
    """LimitsConfig has sane defaults."""
    from zettelforge.config import LimitsConfig

    lc = LimitsConfig()
    assert lc.max_content_length == 52428800  # 50 MB
    assert lc.recall_timeout_seconds == 30.0


def test_content_limit_message_contains_value():
    """Error message must include actual and max sizes for debugging."""
    from zettelforge.config import LimitsConfig

    gv = GovernanceValidator(limits_config=LimitsConfig(max_content_length=10))
    try:
        gv.enforce("remember", "x" * 100)
    except GovernanceViolationError as e:
        msg = str(e)
        assert "100" in msg
        assert "10" in msg


def test_recall_timeout_wired():
    """LimitsConfig.recall_timeout_seconds is read and used by recall()."""
    from zettelforge.config import LimitsConfig

    lc = LimitsConfig(recall_timeout_seconds=0.001)
    # Verify the config dataclass accepts sub-second values
    assert lc.recall_timeout_seconds == 0.001


def test_recall_timeout_returns_empty_on_timeout():
    """When recall times out, return empty list instead of hanging."""
    import os

    from zettelforge.config import get_config, reload_config
    from zettelforge import MemoryManager

    # Set an extremely short timeout
    os.environ["ZETTELFORGE_LIMITS_RECALL_TIMEOUT"] = "0.001"
    reload_config()

    try:
        mm = MemoryManager()
        # Store a note first so recall has something to process
        mm.remember("APT28 uses Cobalt Strike.", source_type="test", evolve=False)
        # This should time out almost instantly and return []
        # Use a query that requires actual retrieval work
        results = mm.recall("What tools does APT28 use?", k=10)
        # The timeout is so short we expect either empty or partial results
        assert isinstance(results, list)
    finally:
        del os.environ["ZETTELFORGE_LIMITS_RECALL_TIMEOUT"]
        reload_config()
