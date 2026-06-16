"""Prompt-injection and retrieval-poisoning guardrails.

The guard is intentionally dependency-free and deterministic. It blocks explicit
attempts to override system/developer instructions, rewrite roles, call tools, or
exfiltrate hidden prompts/secrets before untrusted CTI reaches LLM prompts,
embeddings, or synthesis context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptInjectionFinding:
    """A matched guard pattern."""

    code: str


class PromptInjectionError(ValueError):
    """Raised when untrusted text contains hostile prompt instructions."""

    def __init__(self, field: str, code: str) -> None:
        super().__init__(f"Prompt-injection pattern detected in {field}: {code}")
        self.field = field
        self.code = code


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|bypass|override)\b.{0,80}"
            r"(?:\b(previous|prior|above|earlier|system|developer|safety)\b.{0,80})?"
            r"\b(all\s+)?(instructions?|directives?|rules?|prompts?|messages?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "role_rewrite",
        re.compile(
            r"\b(you are now|you should now be|you must now be)\b"
            r"|\b(you\s+)?act as\s+(my|an?|the)\s+"
            r"(assistant|system|developer|admin|root|jailbreak|dan)\b"
            r"|\bpretend to be\s+(my|an?|the)?\s*"
            r"(assistant|system|developer|admin|root|jailbreak|dan)\b"
            r"|\b(developer mode|jailbreak|dan mode)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "secret_exfiltration",
        re.compile(
            r"(?:^|[.!?,;:]\s*|\b(?:please|kindly)\s+)"
            r"\b(reveal|print|dump|show|exfiltrate|leak|return)\b.{0,80}"
            r"\b(system prompt|developer message|hidden instructions?|api keys?|tokens?|"
            r"secrets?|credentials?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "tool_or_network_command",
        re.compile(
            r"(?:^|[.!?,;:]\s*|\b(?:please|kindly)\s+)"
            r"\b(call|invoke|use|run|execute)\b.{0,80}"
            r"\b(tool|function|shell tool|bash|curl|wget|http request|webhook)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "prompt_boundary_marker",
        re.compile(
            r"\b(begin|end)\s+(system|developer|assistant|tool)\s+"
            r"(prompt|message|instructions?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "memory_poisoning_intent",
        re.compile(
            r"\b(store|remember|save)\b.{0,80}\b(this|the following)\b.{0,80}"
            r"\b(as|as a)\b.{0,40}\b(system|developer|highest priority)\b"
            r".{0,40}\b(instruction|rule|memory)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
)


def _normalize(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def inspect_prompt_injection(value: object) -> PromptInjectionFinding | None:
    """Return a finding when text contains an explicit hostile instruction."""

    text = _normalize(value)
    if not text:
        return None
    for code, pattern in _PATTERNS:
        if pattern.search(text):
            return PromptInjectionFinding(code=code)
    return None


def assert_no_prompt_injection(value: object, *, field: str = "input") -> str:
    """Raise ``PromptInjectionError`` if ``value`` is unsafe."""

    finding = inspect_prompt_injection(value)
    if finding is not None:
        raise PromptInjectionError(field, finding.code)
    return str(value)
