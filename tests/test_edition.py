"""Tests for edition detection and feature gating."""
import os
import pytest

from zettelforge.edition import (
    Edition,
    EditionError,
    get_edition,
    is_enterprise,
    is_community,
    edition_name,
    reset_edition,
    _validate_license_key,
    require_enterprise,
    enterprise_fallback,
)


@pytest.fixture(autouse=True)
def _clean_edition():
    """Reset edition state before and after each test."""
    old_key = os.environ.pop("THREATENGRAM_LICENSE_KEY", None)
    reset_edition()
    yield
    if old_key is not None:
        os.environ["THREATENGRAM_LICENSE_KEY"] = old_key
    else:
        os.environ.pop("THREATENGRAM_LICENSE_KEY", None)
    reset_edition()


class TestLicenseKeyValidation:
    def test_valid_key(self):
        assert _validate_license_key("TG-1234-5678-9abc-def0") is True

    def test_valid_key_uppercase(self):
        assert _validate_license_key("TG-AAAA-BBBB-CCCC-DDDD") is True

    def test_invalid_prefix(self):
        assert _validate_license_key("XX-1234-5678-9abc-def0") is False

    def test_too_few_parts(self):
        assert _validate_license_key("TG-1234-5678") is False

    def test_too_many_parts(self):
        assert _validate_license_key("TG-1234-5678-9abc-def0-aaaa") is False

    def test_non_hex_chars(self):
        assert _validate_license_key("TG-xxxx-yyyy-zzzz-qqqq") is False

    def test_empty_string(self):
        assert _validate_license_key("") is False

    def test_no_prefix(self):
        assert _validate_license_key("1234-5678-9abc-def0") is False


class TestEditionDetection:
    def test_community_by_default(self):
        assert get_edition() == Edition.COMMUNITY
        assert is_community() is True
        assert is_enterprise() is False

    def test_enterprise_with_valid_key(self):
        os.environ["THREATENGRAM_LICENSE_KEY"] = "TG-1234-5678-9abc-def0"
        reset_edition()
        assert get_edition() == Edition.ENTERPRISE
        assert is_enterprise() is True
        assert is_community() is False

    def test_community_with_invalid_key(self):
        os.environ["THREATENGRAM_LICENSE_KEY"] = "bad-key"
        reset_edition()
        assert get_edition() == Edition.COMMUNITY

    def test_edition_is_cached(self):
        e1 = get_edition()
        e2 = get_edition()
        assert e1 is e2

    def test_reset_clears_cache(self):
        get_edition()  # cache it
        os.environ["THREATENGRAM_LICENSE_KEY"] = "TG-1234-5678-9abc-def0"
        assert is_community()  # still cached as community
        reset_edition()
        assert is_enterprise()  # now re-evaluated


class TestEditionName:
    def test_community_name(self):
        assert edition_name() == "ZettelForge Community"

    def test_enterprise_name(self):
        os.environ["THREATENGRAM_LICENSE_KEY"] = "TG-1234-5678-9abc-def0"
        reset_edition()
        assert edition_name() == "ThreatRecall Enterprise by Threatengram"


class TestRequireEnterprise:
    def test_raises_in_community(self):
        @require_enterprise("test feature")
        def gated_fn():
            return "ok"

        with pytest.raises(EditionError, match="test feature"):
            gated_fn()

    def test_passes_in_enterprise(self):
        os.environ["THREATENGRAM_LICENSE_KEY"] = "TG-1234-5678-9abc-def0"
        reset_edition()

        @require_enterprise("test feature")
        def gated_fn():
            return "ok"

        assert gated_fn() == "ok"


class TestEnterpriseFallback:
    def test_returns_fallback_in_community(self):
        @enterprise_fallback("test feature", fallback_return=[])
        def gated_fn():
            return ["real", "data"]

        assert gated_fn() == []

    def test_returns_real_in_enterprise(self):
        os.environ["THREATENGRAM_LICENSE_KEY"] = "TG-1234-5678-9abc-def0"
        reset_edition()

        @enterprise_fallback("test feature", fallback_return=[])
        def gated_fn():
            return ["real", "data"]

        assert gated_fn() == ["real", "data"]
