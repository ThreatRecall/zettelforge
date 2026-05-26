"""Security regression tests for CCCS YARA metadata validation."""

from zettelforge.yara.cccs_metadata import validate_metadata


def _strict_meta(**overrides: str) -> dict[str, str]:
    meta = {
        "id": "validuuidstring01",
        "fingerprint": "a" * 64,
        "version": "1.0",
        "modified": "2024-01-01",
        "status": "RELEASED",
        "sharing": "TLP:WHITE",
        "source": "CCCS",
        "author": "analyst@CCCS",
        "description": "fixture",
        "category": "TECHNIQUE",
    }
    meta.update(overrides)
    return meta


def test_cccs_value_regexes_reject_multiline_injection() -> None:
    result = validate_metadata(
        _strict_meta(sharing="TLP:WHITE\nid: hostile_id"),
        tier="strict",
    )

    assert result.accepted is False
    assert any("sharing" in error for error in result.errors)


def test_cccs_value_regexes_reject_surrounding_whitespace() -> None:
    result = validate_metadata(_strict_meta(status=" RELEASED "), tier="strict")

    assert result.accepted is False
    assert any("status" in error for error in result.errors)


def test_cccs_author_rejects_shell_metacharacters() -> None:
    result = validate_metadata(_strict_meta(author='analyst@CCCS"; rm -rf / #'), tier="strict")

    assert result.accepted is False
    assert any("author" in error for error in result.errors)


def test_cccs_author_rejects_newline_suffix() -> None:
    result = validate_metadata(_strict_meta(author="analyst@CCCS\n"), tier="strict")

    assert result.accepted is False
    assert any("author" in error for error in result.errors)
