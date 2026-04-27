"""
Shared JSON extraction from LLM output.

Handles markdown code fences, surrounding prose, and malformed responses.
All structured-output call sites delegate here instead of inline regex+json.loads.
"""

import json
import logging
import re

_logger = logging.getLogger("zettelforge.json_parse")

_parse_stats = {"success": 0, "failure": 0}


def extract_json(raw: str | None, expect: str = "object") -> dict | list | None:
    """Extract JSON from LLM output, handling code fences and surrounding text.

    Args:
        raw: Raw LLM output string (may contain code fences, prose, etc). None is safe.
        expect: "object" to find {...}, "array" to find [...].

    Returns:
        Parsed dict/list, or None if extraction failed.
    """
    if not raw or not isinstance(raw, str) or not raw.strip():
        _parse_stats["failure"] += 1
        return None

    text = _strip_code_fences(raw)

    # Try to find JSON in the text
    if expect == "array":
        match = re.search(r"\[.*\]", text, re.DOTALL)
    else:
        # Greedy match first to capture nested objects; fallback to non-greedy
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match is None:
            match = re.search(r"\{.*?\}", text, re.DOTALL)

    if match is None:
        _parse_stats["failure"] += 1
        return None

    try:
        result = json.loads(match.group(0))
        if expect == "array" and not isinstance(result, list):
            _parse_stats["failure"] += 1
            return None
        if expect == "object" and not isinstance(result, dict):
            _parse_stats["failure"] += 1
            return None
        _parse_stats["success"] += 1
        return result
    except (json.JSONDecodeError, ValueError):
        _parse_stats["failure"] += 1
        return None


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    # Handle ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return text.strip()


def get_parse_stats() -> dict:
    """Return parse success/failure counters."""
    return dict(_parse_stats)


def reset_parse_stats() -> None:
    """Reset counters (for testing)."""
    _parse_stats["success"] = 0
    _parse_stats["failure"] = 0
