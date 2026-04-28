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
    assert hasattr(mm, 'governance')
    assert isinstance(mm.governance, GovernanceValidator)
