"""Tests for zettelforge.yara.parser."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from zettelforge.yara.parser import parse_file, parse_text, parse_yara

FIXTURES = Path(__file__).parent / "fixtures" / "yara"


def test_parse_file_plain_yara() -> None:
    """Plain YARA rule with no CCCS meta parses and exposes rule_name."""
    rules = parse_file(FIXTURES / "malware_hash.yar")
    assert len(rules) == 1
    assert rules[0]["rule_name"] == "silent_banker"
    # plyara attaches rule-level tags at rule dict level.
    assert rules[0]["tags"] == ["banker"]


def test_parse_file_cccs_technique_rule_flattens_metadata() -> None:
    """CCCS-annotated rule flattens ``metadata`` list → ``meta`` dict."""
    rules = parse_file(FIXTURES / "technique_loader.yar")
    assert rules[0]["rule_name"] == "MemoryModule"
    meta = rules[0]["meta"]
    # Every key we care about is promoted from the list-of-dicts shape.
    assert meta["category"] == "TECHNIQUE"
    assert meta["mitre_att"] == "T1218"
    assert meta["sharing"] == "TLP:WHITE"
    assert meta["author"] == "analyst@CCCS"


def test_parse_file_webshell_promotes_parser_imports() -> None:
    """plyara attaches parser-level imports per-rule in our normalized shape.

    Known plyara quirk: when a rule's condition does NOT reference the
    import namespace (here ``pe``) plyara drops ``imports`` from that
    rule's dict. Our parser copies parser-level imports across every rule
    so downstream code doesn't have to care.
    """
    rules = parse_file(FIXTURES / "webshell.yar")
    assert rules[0]["rule_name"] == "SuspiciousWebShell"
    assert "pe" in rules[0].get("imports", [])
    assert sorted(rules[0]["tags"]) == ["php", "webshell"]


def test_parse_text_equivalent_to_parse_file() -> None:
    """parse_yara/parse_text produce the same rule_name from the same source."""
    src = (FIXTURES / "malware_hash.yar").read_text()
    rules_yara = parse_yara(src)
    rules_text = parse_text(src)
    assert rules_yara[0]["rule_name"] == rules_text[0]["rule_name"] == "silent_banker"


def test_parse_text_handles_multiple_rules_in_one_file() -> None:
    """Multi-rule text returns one dict per rule, each with its own raw_rule carve."""
    src = """
import "pe"

rule First {
    condition:
        pe.is_pe
}

rule Second {
    strings:
        $a = "beacon"
    condition:
        $a
}
"""
    rules = parse_yara(src)
    assert [r["rule_name"] for r in rules] == ["First", "Second"]
    # Each rule gets parser-level imports copied in.
    assert "pe" in rules[0]["imports"]
    assert "pe" in rules[1]["imports"]
    # raw_rule carved from source lines — non-empty for both.
    assert "rule First" in rules[0]["raw_rule"]
    assert "rule Second" in rules[1]["raw_rule"]


def test_parse_yara_cached_parser_is_safe_under_concurrency() -> None:
    """Concurrent parses must not clear shared plyara state mid-parse."""
    src = (FIXTURES / "webshell.yar").read_text()

    def parse_names() -> list[str]:
        return [rule["rule_name"] for rule in parse_yara(src)]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _i: parse_names(), range(12)))

    assert results == [["SuspiciousWebShell"]] * 12


def test_parse_text_raises_on_syntax_error() -> None:
    """Malformed YARA raises ValueError (not a silent empty list).

    plyara quirk: truncated rules like ``rule Foo { condition:`` silently
    return an empty list — only genuinely unparseable token streams raise.
    We pick one that does.
    """
    import pytest

    with pytest.raises(ValueError):
        parse_yara("NOT_A_YARA_RULE")


def test_parse_file_rejects_oversize_rule(tmp_path) -> None:
    """SEC-2: files over MAX_RULE_FILE_BYTES must raise before plyara runs."""
    import pytest

    from zettelforge.yara.parser import (
        MAX_RULE_FILE_BYTES,
        YaraParseError,
        parse_file,
    )

    big = tmp_path / "giant.yar"
    big.write_bytes(b"x" * (MAX_RULE_FILE_BYTES * 2))
    with pytest.raises(YaraParseError, match="too large"):
        parse_file(big)


def test_yara_public_api_exports_match_sigma_parity() -> None:
    """CR-W1: ``zettelforge.yara`` must expose the full Phase-3 surface."""
    import zettelforge.yara as yara_pkg

    for name in (
        "parse_file",
        "parse_yara",
        "validate_metadata",
        "rule_to_entities",
        "resolve_yara_tag",
        "ingest_rule",
        "ingest_rules_dir",
        "YaraRule",
        "YaraParseError",
        "YaraValidationError",
    ):
        assert hasattr(yara_pkg, name), f"zettelforge.yara missing {name!r}"
        assert name in yara_pkg.__all__, f"{name!r} not advertised in __all__"
