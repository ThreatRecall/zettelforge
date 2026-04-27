"""
LLM-generated rule explainer — the v1 killer feature.

See phase-1c-detection-rule-architecture.md §3.

The explainer is invoked synchronously by direct callers of ``explain()``.
In v1 the Sigma/YARA ``ingest.py`` modules do NOT enqueue ``explain_rule``
jobs — wiring the explainer into the async enrichment worker is a v1.1
task. Today, callers that want rule explanations must call ``explain()``
themselves after ingest completes.

Invariants:
- Pure-ish function. Only persistent state is the in-process rate-limiter
  bucket (module-level dict). No files, no databases.
- Never raises for recoverable conditions (LLM offline, invalid JSON,
  rate-limit). Returns a ``RuleExplanation`` with ``confidence=0.0`` and
  a diagnostic summary so callers can render something safe.
- Hard-caps ``rule_body`` at 8192 chars before calling the LLM to limit
  prompt-injection blast radius and token cost.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from zettelforge import llm_client
from zettelforge.json_parse import extract_json
from zettelforge.log import get_logger

if TYPE_CHECKING:
    from zettelforge.detection.base import DetectionRule


_logger = get_logger("zettelforge.detection.explainer")


# ── Constants ────────────────────────────────────────────────────────────────

#: Hard cap on rule_body passed to the LLM (chars). Guards against prompt
#: injection and runaway token cost. Longer bodies are truncated.
MAX_RULE_BODY_CHARS = 8192

#: Cost-envelope knob: max explanations per minute per process. Callers
#: (bulk ingest) should check ``rate_limit_ok()`` before enqueuing, but the
#: explainer also enforces it internally as a belt-and-suspenders measure.
EXPLAIN_MAX_CALLS_PER_MINUTE = 60

#: Schema version of the RuleExplanation dict. Bump if the shape changes.
SCHEMA_VERSION = "1.0"

_SYSTEM_PROMPT = (
    "You are a senior detection engineer. You receive one detection rule "
    "(Sigma YAML or YARA) and produce a structured explanation for SOC analysts. "
    "Be precise. Cite specific strings/fields the rule uses. Do not speculate "
    "beyond the rule text unless you flag the inference. Output valid JSON only."
)


# ── Dataclass ────────────────────────────────────────────────────────────────


@dataclass
class RuleExplanation:
    """Structured explanation emitted by the LLM explainer.

    See phase-1c §3a for schema rationale.
    """

    summary: str
    mechanism: str = ""
    threat_model: str = ""
    false_positive_patterns: list[str] = field(default_factory=list)
    related_techniques: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model: str = ""
    generated_at: str = ""
    schema_version: str = SCHEMA_VERSION


# ── Rate limiter (in-process, token-bucket-ish) ──────────────────────────────

# Map of start-of-minute-epoch -> call count. Single dict, O(1) cleanup.
_rate_bucket: dict[int, int] = {}


def _current_minute() -> int:
    return int(time.time() // 60)


def rate_limit_ok() -> bool:
    """Return True iff a new explain call fits under the per-minute cap.

    Does NOT increment the counter — callers should call ``_consume_token``
    on the actual attempt. Kept separate so ingest paths can gate enqueue
    without polluting the bucket.
    """
    cap = _effective_rpm()
    now = _current_minute()
    # Drop stale minutes; only the current bucket matters.
    for minute in list(_rate_bucket):
        if minute < now:
            del _rate_bucket[minute]
    return _rate_bucket.get(now, 0) < cap


def _consume_token() -> bool:
    """Atomically check and increment the rate-limiter bucket. Returns True
    if the call was permitted, False if capped."""
    if not rate_limit_ok():
        return False
    now = _current_minute()
    _rate_bucket[now] = _rate_bucket.get(now, 0) + 1
    return True


def _effective_rpm() -> int:
    """Honour ``ZETTELFORGE_EXPLAIN_RPM`` env override; fall back to default."""
    raw = os.environ.get("ZETTELFORGE_EXPLAIN_RPM")
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return EXPLAIN_MAX_CALLS_PER_MINUTE


def _reset_rate_limiter() -> None:
    """Test-only hook. Clears the rate-limiter bucket."""
    _rate_bucket.clear()


# ── Public API ───────────────────────────────────────────────────────────────


def explain(
    rule: DetectionRule,
    *,
    rule_body: str,
    provider: str | None = None,
) -> RuleExplanation:
    """Generate a semantic explanation of a detection rule.

    Args:
        rule: The parsed ``DetectionRule`` (or subclass).
        rule_body: Raw rule text (Sigma YAML or YARA source). Truncated
            to ``MAX_RULE_BODY_CHARS`` before being sent to the LLM.
        provider: Override provider name (primarily for testing). When
            ``None``, the configured provider is used via
            ``llm_client.get_llm_provider()``.

    Returns:
        A ``RuleExplanation``. Never raises for recoverable failures;
        on LLM error, parse failure, or rate-limit, returns an
        explanation with ``confidence=0.0`` and a diagnostic ``summary``.
    """
    start = time.monotonic()
    provider_name = provider or llm_client.get_llm_provider()
    is_mock = provider_name == "mock"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Mock provider — return canned deterministic response so CI tests
    # don't depend on fake-JSON parsing from the MockProvider's "mock response".
    if is_mock:
        _logger.info(
            "rule_explained",
            rule_id=rule.rule_id,
            rule_format=rule.source_format,
            ms_elapsed=round((time.monotonic() - start) * 1000, 2),
            confidence=0.0,
            mock_provider=True,
        )
        return RuleExplanation(
            summary="mock provider — no real explanation",
            mechanism="",
            threat_model="",
            false_positive_patterns=[],
            related_techniques=[],
            confidence=0.0,
            model=f"mock:{provider_name}",
            generated_at=now_iso,
            schema_version=SCHEMA_VERSION,
        )

    # Rate limit — callers are supposed to check rate_limit_ok() before
    # enqueuing, but we double-gate here in case a bad caller bypasses it.
    if not _consume_token():
        _logger.warning(
            "rule_explain_rate_limited",
            rule_id=rule.rule_id,
            rule_format=rule.source_format,
            rpm_cap=_effective_rpm(),
        )
        return RuleExplanation(
            summary="explanation unavailable: rate limited",
            confidence=0.0,
            model=provider_name,
            generated_at=now_iso,
            schema_version=SCHEMA_VERSION,
        )

    # Truncate body (prompt-injection + cost guard).
    body = rule_body or ""
    if len(body) > MAX_RULE_BODY_CHARS:
        body = body[:MAX_RULE_BODY_CHARS] + "... [truncated]"
    # Neutralise any attempt in the untrusted body to close the delimiter
    # and emit its own instructions.
    body = body.replace("</rule_source>", "</rule_source_ESCAPED>")

    prompt = f'{rule.explain_prompt()}\n\n<rule_source untrusted="true">\n{body}\n</rule_source>\n'

    try:
        raw = llm_client.generate(
            prompt,
            max_tokens=800,
            temperature=0.1,
            system=_SYSTEM_PROMPT,
            json_mode=True,
        )
    except Exception as exc:
        _logger.warning(
            "rule_explain_llm_error",
            rule_id=rule.rule_id,
            rule_format=rule.source_format,
            error=repr(exc),
        )
        return RuleExplanation(
            summary=f"explanation unavailable: llm error ({type(exc).__name__})",
            confidence=0.0,
            model=provider_name,
            generated_at=now_iso,
            schema_version=SCHEMA_VERSION,
        )

    # Keep the verbatim LLM output in a transient local only. Not persisted
    # on the returned dataclass (SEC-4): rule bodies are untrusted input and
    # we don't want LLM output round-tripping back to storage.
    _raw_for_debug = raw if os.environ.get("ZETTELFORGE_LOG_LEVEL") == "DEBUG" else ""

    if not raw:
        _logger.warning(
            "rule_explain_empty_response",
            rule_id=rule.rule_id,
            rule_format=rule.source_format,
        )
        return RuleExplanation(
            summary="explanation unavailable: empty response",
            confidence=0.0,
            model=provider_name,
            generated_at=now_iso,
            schema_version=SCHEMA_VERSION,
        )

    parsed = extract_json(raw, expect="object")
    if parsed is None:
        _logger.warning(
            "rule_explain_parse_failure",
            rule_id=rule.rule_id,
            rule_format=rule.source_format,
            raw_snippet=_raw_for_debug[:500],
        )
        return RuleExplanation(
            summary="explanation unavailable: invalid json",
            confidence=0.0,
            model=provider_name,
            generated_at=now_iso,
            schema_version=SCHEMA_VERSION,
        )

    explanation = _from_llm_dict(parsed, provider_name, now_iso)
    _logger.info(
        "rule_explained",
        rule_id=rule.rule_id,
        rule_format=rule.source_format,
        ms_elapsed=round((time.monotonic() - start) * 1000, 2),
        confidence=explanation.confidence,
        mock_provider=False,
    )
    return explanation


def _from_llm_dict(
    parsed: dict,
    provider_name: str,
    generated_at: str,
) -> RuleExplanation:
    """Coerce an LLM-JSON dict into a RuleExplanation with defensive defaults."""

    def _as_str(v: object) -> str:
        return v if isinstance(v, str) else ""

    def _as_str_list(v: object) -> list[str]:
        if isinstance(v, list):
            return [x for x in v if isinstance(x, str)]
        return []

    def _as_float(v: object) -> float:
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        # Clamp to [0, 1].
        return max(0.0, min(1.0, f))

    return RuleExplanation(
        summary=_as_str(parsed.get("summary")) or "explanation unavailable: missing summary",
        mechanism=_as_str(parsed.get("mechanism")),
        threat_model=_as_str(parsed.get("threat_model")),
        false_positive_patterns=_as_str_list(parsed.get("false_positive_patterns")),
        related_techniques=_as_str_list(parsed.get("related_techniques")),
        confidence=_as_float(parsed.get("confidence")),
        model=provider_name,
        generated_at=generated_at,
        schema_version=SCHEMA_VERSION,
    )
