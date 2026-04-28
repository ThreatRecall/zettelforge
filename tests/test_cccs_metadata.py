"""Tests for cccs_metadata regex security (SEC-6, SEC-7).

Covers every regex defined in cccs_metadata.py:

- _AUTHOR_REGEX (SEC-7: tightened from permissive to safe chars only)
- _regex_match with fullmatch instead of search (SEC-6: multiline injection)
- All anchored single-value regexes (version, date, uuid, fingerprint, mitre_att)
- Three-tier validation end-to-end with malicious inputs
"""

from zettelforge.yara.cccs_metadata import (
    _AUTHOR_REGEX,
    _VERSION_REGEX,
    _DATE_REGEX,
    _UUID_REGEX,
    _FINGERPRINT_REGEX,
    _MITRE_ATT_REGEX,
    _regex_match,
    _STATUS_REGEXES,
    _SHARING_REGEXES,
    _CATEGORY_REGEXES,
    _MALWARE_TYPE_REGEXES,
    _ACTOR_TYPE_REGEXES,
    _HASH_REGEXES,
    validate_metadata,
)


# ---------------------------------------------------------------------------
# SEC-7: _AUTHOR_REGEX tightened
# ---------------------------------------------------------------------------


class TestAuthorRegex:
    """_AUTHOR_REGEX must accept real CCCS authors and reject injection."""

    POSITIVE = [
        "jdoe@CCCS",
        "analyst@ORG",
        "CCCS",
        "ORG_NAME",
        "user+tag@ORG",
        "first.last@ORG",
        "double--dash",
        "underscore_name",
        "abc123@XYZ",
        "dot.dot@A",
    ]

    NEGATIVE = [
        "",  # empty
        " ",  # space only
        "spaces in name",  # spaces
        "newline\ninjected",  # multiline injection
        "<script>alert(1)</script>",  # HTML injection
        "evil()",  # parens
        "pipe|here",  # pipe
        "backtick`here",  # backtick
        "colon:here",  # colon
        "semicolon;here",  # semicolon
        "quote'here",  # single quote
        'quote"here',  # double quote
        "slash/here",  # forward slash
        "back\\here",  # backslash
        "b@d!",  # exclamation
        "dollar$ign",  # dollar sign
        "percent%",  # percent
        "caret^here",  # caret
        "star*here",  # asterisk
        "parens()here",  # parens again
        "[bracket",  # bracket
        "{brace",  # brace
        "\x00null",  # null byte
        "\t",  # tab
        "line1\r\nline2",  # CRLF
    ]

    def test_accepts_valid_authors(self) -> None:
        for val in self.POSITIVE:
            assert _AUTHOR_REGEX.match(val), f"Author should accept: {val!r}"

    def test_rejects_injection(self) -> None:
        for val in self.NEGATIVE:
            assert not _AUTHOR_REGEX.match(val), f"Author should reject: {val!r}"


# ---------------------------------------------------------------------------
# SEC-6: _regex_match uses fullmatch, not search
# ---------------------------------------------------------------------------


class TestRegexMatchFullmatch:
    """_regex_match must use fullmatch to prevent multiline bypass."""

    def test_valid_tlp_clear_matches(self) -> None:
        assert _regex_match("TLP:CLEAR", _SHARING_REGEXES)

    def test_valid_tlp_white_matches(self) -> None:
        assert _regex_match("TLP:WHITE", _SHARING_REGEXES)

    def test_multiline_injection_rejected(self) -> None:
        """SEC-6: 'TLP:WHITE\\nid: hostile_id' must NOT match."""
        assert not _regex_match("TLP:WHITE\nid: hostile_id", _SHARING_REGEXES)

    def test_multiline_tlp_green_rejected(self) -> None:
        assert not _regex_match("TLP:GREEN\nextra:stuff", _SHARING_REGEXES)

    def test_status_exact_match(self) -> None:
        assert _regex_match("RELEASED", _STATUS_REGEXES)

    def test_status_multiline_rejected(self) -> None:
        assert not _regex_match("RELEASED\nmalicious", _STATUS_REGEXES)

    def test_category_exact_match(self) -> None:
        assert _regex_match("MALWARE", _CATEGORY_REGEXES)

    def test_category_multiline_rejected(self) -> None:
        assert not _regex_match("INFO\nhack", _CATEGORY_REGEXES)

    def test_non_string_returns_false(self) -> None:
        assert not _regex_match(123, _SHARING_REGEXES)
        assert not _regex_match(None, _SHARING_REGEXES)  # type: ignore[arg-type]
        assert not _regex_match([], _SHARING_REGEXES)


# ---------------------------------------------------------------------------
# Anchored single-value regexes — each has ^...$ and rejects extra content
# ---------------------------------------------------------------------------


class TestVersionRegex:
    POSITIVE = ["1.0", "0.1", "999.999", "2.3"]
    NEGATIVE = ["", "1", "1.0.0", "1.", ".1", "a.b", "1.0\n"]

    def test_positive(self) -> None:
        for v in self.POSITIVE:
            assert _VERSION_REGEX.match(v), f"Version should accept: {v!r}"

    def test_negative(self) -> None:
        for v in self.NEGATIVE:
            assert not _VERSION_REGEX.match(v), f"Version should reject: {v!r}"


class TestDateRegex:
    POSITIVE = ["2024-01-15", "1999-12-31", "2025-06-01"]
    NEGATIVE = ["", "2024-1-1", "2024/01/15", "Jan 15 2024", "2024-01-15\n"]

    def test_positive(self) -> None:
        for v in self.POSITIVE:
            assert _DATE_REGEX.match(v), f"Date should accept: {v!r}"

    def test_negative(self) -> None:
        for v in self.NEGATIVE:
            assert not _DATE_REGEX.match(v), f"Date should reject: {v!r}"


class TestUuidRegex:
    POSITIVE = [
        "abc123def4567890",
        "a" * 16,
        "Z" * 32,
        "0" * 20,
    ]
    NEGATIVE = [
        "", "a" * 15, "abc", "UUID:abc123", "abc123def4567890\n",
    ]

    def test_positive(self) -> None:
        for v in self.POSITIVE:
            assert _UUID_REGEX.match(v), f"UUID should accept: {v!r}"

    def test_negative(self) -> None:
        for v in self.NEGATIVE:
            assert not _UUID_REGEX.match(v), f"UUID should reject: {v!r}"


class TestFingerprintRegex:
    POSITIVE = [
        "a" * 40,
        "f" * 40,
        "0" * 64,
        "ABCDEF0123456789" * 4,  # 64 chars
    ]
    NEGATIVE = [
        "",
        "a" * 39,
        "a" * 65,
        "z" * 40,
        "g" * 40,
        "X" * 64,
        "abc\n",
    ]

    def test_positive(self) -> None:
        for v in self.POSITIVE:
            assert _FINGERPRINT_REGEX.match(v), f"Fingerprint should accept: {v!r}"

    def test_negative(self) -> None:
        for v in self.NEGATIVE:
            assert not _FINGERPRINT_REGEX.match(v), f"Fingerprint should reject: {v!r}"


class TestMitreAttRegex:
    POSITIVE = [
        "T1218",
        "T1218.001",
        "TA0001",
        "M1045",
        "G0001",
        "S0027",
        "T0000.999",
    ]
    NEGATIVE = [
        "",
        "X1234",
        "T123",
        "T12345",
        "T1234.",
        "T1234.00",
        "T1234.1234",
        "T1218\n",
        "t1218",
    ]

    def test_positive(self) -> None:
        for v in self.POSITIVE:
            assert _MITRE_ATT_REGEX.match(v), f"MITRE should accept: {v!r}"

    def test_negative(self) -> None:
        for v in self.NEGATIVE:
            assert not _MITRE_ATT_REGEX.match(v), f"MITRE should reject: {v!r}"


# ---------------------------------------------------------------------------
# End-to-end validate_metadata with malicious inputs (SEC-6 + SEC-7)
# ---------------------------------------------------------------------------


def _valid_meta(**overrides: str) -> dict[str, str]:
    """Build a minimal valid CCCS meta dict, overridable."""
    base = {
        "author": "jdoe@CCCS",
        "status": "RELEASED",
        "sharing": "TLP:CLEAR",
        "source": "CCCS",
        "description": "Test rule",
        "category": "INFO",
    }
    base.update(overrides)
    return base


class TestValidateMetadataSecurity:
    """Validate_metadata must reject injection and malicious values."""

    def test_valid_rule_accepted_in_warn(self) -> None:
        result = validate_metadata(_valid_meta())
        assert result.accepted is True

    def test_valid_rule_accepted_in_strict(self) -> None:
        meta = _valid_meta()
        # strict requires auto-gen fields too
        meta["id"] = "abcdef1234567890"
        meta["fingerprint"] = "a" * 40
        meta["version"] = "1.0"
        meta["modified"] = "2024-01-01"
        result = validate_metadata(meta, tier="strict")
        assert result.accepted is True, f"errors: {result.errors}"

    def test_multiline_sharing_rejected_strict(self) -> None:
        """SEC-6: multiline injection in sharing field."""
        meta = _valid_meta(sharing="TLP:CLEAR\nid: hostile_id")
        result = validate_metadata(meta, tier="strict")
        assert result.accepted is False
        assert any("sharing" in e for e in result.errors)

    def test_multiline_sharing_warn_level(self) -> None:
        """SEC-6: even in warn tier, bad sharing is a warning."""
        meta = _valid_meta(sharing="TLP:CLEAR\nid: hostile_id")
        result = validate_metadata(meta, tier="warn")
        assert result.accepted is True  # warn tier accepts
        assert any("sharing" in w for w in result.warnings)

    def test_multiline_status_rejected_strict(self) -> None:
        meta = _valid_meta(status="RELEASED\nmalicious")
        result = validate_metadata(meta, tier="strict")
        assert result.accepted is False
        assert any("status" in e for e in result.errors)

    def test_multiline_category_rejected_strict(self) -> None:
        meta = _valid_meta(category="INFO\nhack")
        result = validate_metadata(meta, tier="strict")
        assert result.accepted is False
        assert any("category" in e for e in result.errors)

    def test_malicious_author_rejected_strict(self) -> None:
        """SEC-7: HTML/script injection in author field."""
        meta = _valid_meta(author="<script>alert('xss')</script>")
        result = validate_metadata(meta, tier="strict")
        assert result.accepted is False
        assert any("author" in e for e in result.errors)

    def test_malicious_author_warn_level(self) -> None:
        meta = _valid_meta(author="<script>alert('xss')</script>")
        result = validate_metadata(meta, tier="warn")
        assert result.accepted is True
        assert any("author" in w for w in result.warnings)

    def test_author_with_newline_rejected(self) -> None:
        meta = _valid_meta(author="analyst@CCCS\nmalicious")
        result = validate_metadata(meta, tier="strict")
        assert result.accepted is False
        assert any("author" in e for e in result.errors)

    def test_author_with_spaces_rejected(self) -> None:
        meta = _valid_meta(author="john doe@CCCS")
        result = validate_metadata(meta, tier="strict")
        assert result.accepted is False
        assert any("author" in e for e in result.errors)
