# RFC-013: PII Detection and Redaction via Microsoft Presidio

## Metadata

- **Author**: Patrick Roland
- **Status**: Draft
- **Created**: 2026-04-25
- **Last Updated**: 2026-04-25
- **Reviewers**: TBD
- **Related Tickets**: ZF-013
- **Related RFCs**: RFC-002 (Universal LLM Provider), RFC-011 (Local LLM Backend), RFC-012 (LiteLLM Provider)

## Summary

Integrate Microsoft Presidio into ZettelForge for PII (Personally Identifiable Information) detection and redaction. Presidio runs as a governance check before `remember()` operations, scanning content for sensitive data (names, emails, phone numbers, IP addresses, credit cards, SSNs, and more) and applying configurable policies: log, redact, or block. The integration is scoped to the text ingestion path -- `remember()`, `remember_with_extraction()`, and `remember_report()` -- and is disabled by default with no new core dependencies.

## Motivation

ZettelForge stores threat intelligence content from analyst notes, reports, and agent exchanges. CTI workflows frequently handle data that may contain PII:

- **Email addresses** and **IP addresses** from phishing reports and IOC collections
- **Person names** in attribution analysis and journalist interviews
- **Phone numbers** and **physical addresses** in incident response reports
- **Organization names** that may identify individuals in small companies
- **Internal hostnames** and **network identifiers** that could be PII in some jurisdictions

Without PII detection, ZettelForge can silently store sensitive data in the vector database and knowledge graph, creating compliance liabilities under GDPR (Article 17 right to erasure), CCPA, and FedRAMP-required data minimization (SA-8, AC-6, AU-2).

Presidio is the standard open-source PII detection SDK from Microsoft (MIT license, 7k+ GitHub stars, FedRAMP-aligned documentation). It provides:

- **Pre-built recognizers** for 30+ PII types (PERSON, EMAIL_ADDRESS, PHONE_NUMBER, etc.) with regex + NLP (spaCy/transformers) scoring
- **Context-aware detection** -- "John called" vs "John Doe residence" -- using NLP entity recognition
- **Anonymization operators** -- redact, replace, hash, encrypt, mask
- **Pluggable recognizers** -- custom CTI-specific recognizers (e.g., internal hostname patterns, project codenames that resemble person names)
- **No external API calls** -- all detection runs locally via spaCy models (~50MB)

### Who benefits

- **SOC analysts** storing incident response notes with potential victim PII
- **CTI teams** ingesting public and private threat reports that may contain personal data
- **Compliance officers** requiring data minimization and right-to-erasure for threat intelligence stores
- **FedRAMP/IL5 deployments** that mandate PII scanning before database writes

## Proposed Design

### Architecture

Presidio integrates as a validation step in the governance layer, running before content is written to storage:

```
                +-------------------+
                | User calls        |
                | remember(content) |
                +--------+----------+
                         |
                         v
                +--------+----------+
                | GovernanceValidator|
                |   .validate()      |
                +--------+----------+
                         |
                         v
                +--------+----------+     +------------------+
                | PIIValidator      |---->| presidio-analyzer |
                | (NEW, configurable|     |   .analyze()      |
                |  log/redact/block)|     +------------------+
                +--------+----------+           |
                         |                      v
                         |              +------------------+
                         |              | Result: list of   |
                         |              | detected PII      |
                         |              | entities          |
                         |              +------------------+
                         v
                +--------+----------+
                | Action dispatch:  |
                | - log: warn only  |
                | - redact: replace |
                | - block: raise    |
                +--------+----------+
                         |
                         v
                +--------+----------+
                | MemoryStore.save() |
                +-------------------+
```

Key design: Presidio runs **in-process** via its Python SDK. No server process or external API required. The spaCy model (`en_core_web_sm`, ~12MB with word vectors, ~50MB with transformer) downloads on first use, same pattern as fastembed models.

### Configuration

New `governance.pii` section in `config.yaml`:

```yaml
governance:
  enabled: true
  min_content_length: 1
  pii:
    enabled: false                    # disabled by default; no new deps
    action: log                       # log | redact | block
    redact_placeholder: "[REDACTED]"  # replacement text when action=redact
    entities: []                      # empty = all supported entities
    # Example: only detect emails and phone numbers
    # entities: ["EMAIL_ADDRESS", "PHONE_NUMBER"]
    language: en                      # spaCy model language
    nlp_model: en_core_web_sm         # spaCy model size (sm, md, lg, trf)
```

Example configs:

```yaml
# Log-only (discover what PII is flowing through)
governance:
  pii:
    enabled: true
    action: log

# Redact all PII before storage
governance:
  pii:
    enabled: true
    action: redact
    redact_placeholder: "[PII REMOVED]"

# Block storage entirely if PII detected (strict)
governance:
  pii:
    enabled: true
    action: block

# Only redact emails and phone numbers; allow names through
governance:
  pii:
    enabled: true
    action: redact
    entities: ["EMAIL_ADDRESS", "PHONE_NUMBER"]

# Complete compliance setup for FedRAMP
governance:
  enabled: true
  min_content_length: 1
  pii:
    enabled: true
    action: redact
    redact_placeholder: "[REDACTED: {entity_type}]"
```

### Dataclass Changes

```python
# src/zettelforge/config.py

@dataclass
class PIIConfig:
    """Presidio PII detection settings (RFC-013)."""
    enabled: bool = False
    action: str = "log"               # "log", "redact", "block"
    redact_placeholder: str = "[REDACTED]"
    entities: List[str] = field(default_factory=list)  # empty = all
    language: str = "en"
    nlp_model: str = "en_core_web_sm"


@dataclass
class GovernanceConfig:
    enabled: bool = True
    min_content_length: int = 1
    pii: PIIConfig = field(default_factory=PIIConfig)  # NEW
```

### PIIValidator Design

```python
# src/zettelforge/pii_validator.py

"""PII detection and redaction using Microsoft Presidio (RFC-013)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from zettelforge.log import get_logger

_logger = get_logger("zettelforge.pii")

# Default placeholder per entity type
_DEFAULT_PLACEHOLDER = "[REDACTED]"

# Entity types we explicitly NEVER redact in CTI context
# (these are threat intelligence identifiers, not PII)
_CTI_ALLOWLIST = frozenset({
    "IP_ADDRESS",          # IOC — IPs are threat data, not PII
    "URL",                 # IOC — URLs are threat data
})


@dataclass
class PIIDetection:
    """A single PII detection result."""
    entity_type: str
    text: str
    start: int
    end: int
    score: float


class PIIValidator:
    """Validates content for PII using Presidio.

    Three modes of operation:
    - ``log``: detect and log PII, pass content through unchanged
    - ``redact``: replace detected PII with placeholders before returning
    - ``block``: raise ``PIIBlockedError`` if ANY PII is detected

    Thread-safe singleton per model. Models download on first use
    (matching fastembed download pattern).
    """

    def __init__(
        self,
        action: str = "log",
        placeholder: str = _DEFAULT_PLACEHOLDER,
        entities: Optional[List[str]] = None,
        language: str = "en",
        nlp_model: str = "en_core_web_sm",
    ) -> None:
        if action not in ("log", "redact", "block"):
            raise ValueError(f"Unknown PII action: {action!r}")
        self._action = action
        self._placeholder = placeholder
        self._entities = (
            [e for e in entities if e not in _CTI_ALLOWLIST]
            if entities else None
        )
        self._language = language
        self._nlp_model = nlp_model
        self._analyzer: object = None
        self._anonymizer: object = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        """Lazy-load Presidio analyzer and download spaCy model if needed."""
        if self._analyzer is not None:
            return
        with self._lock:
            if self._analyzer is not None:
                return
            try:
                from presidio_analyzer import AnalyzerEngine
                from presidio_analyzer.nlp_engine import NlpEngineProvider
            except ImportError as exc:
                raise ImportError(
                    "PII validation requires presidio-analyzer. "
                    "Install with: pip install zettelforge[pii]"
                ) from exc

            configuration = {
                "nlp_engine_name": "spacy",
                "models": [
                    {"lang_code": self._language, "model_name": self._nlp_model},
                ],
            }
            provider = NlpEngineProvider(nlp_configuration=configuration)
            nlp_engine = provider.create_engine()
            self._analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine,
                supported_languages=[self._language],
            )
            _logger.debug(
                "pii_analyzer_loaded",
                model=self._nlp_model,
                language=self._language,
            )

    def detect(self, text: str) -> List[PIIDetection]:
        """Analyze text and return detected PII entities.

        Returns list of ``PIIDetection`` objects sorted by start position,
        deduplicated by position (highest-score entity per position wins).
        """
        if not text or not text.strip():
            return []
        self._ensure_loaded()
        results = self._analyzer.analyze(
            text=text,
            entities=self._entities,
            language=self._language,
        )
        # Deduplicate: for overlapping spans, keep the highest score
        span_map: Dict[Tuple[int, int], PIIDetection] = {}
        for r in results:
            key = (r.start, r.end)
            existing = span_map.get(key)
            if existing is None or r.score > existing.score:
                span_map[key] = PIIDetection(
                    entity_type=r.entity_type,
                    text=text[r.start:r.end],
                    start=r.start,
                    end=r.end,
                    score=r.score,
                )
        return sorted(span_map.values(), key=lambda d: d.start)

    def validate(
        self, content: str
    ) -> Tuple[bool, str, List[PIIDetection]]:
        """Validate content for PII.

        Args:
            content: Text to validate.

        Returns:
            Tuple of (passed, processed_content, detections).
            ``passed`` is True if no PII was detected or action is not "block".
            ``processed_content`` is the original content (for action="log"
            or action="block") or redacted content (for action="redact").
        """
        detections = self.detect(content)
        if not detections:
            return True, content, []

        # Log detections regardless of action
        _logger.warning(
            "pii_detected",
            count=len(detections),
            action=self._action,
            entities=[
                {"type": d.entity_type, "text": d.text, "score": round(d.score, 2)}
                for d in detections
            ],
        )

        if self._action == "redact":
            redacted = self._redact(content, detections)
            return True, redacted, detections

        if self._action == "block":
            types = ", ".join(sorted(set(d.entity_type for d in detections)))
            raise PIIBlockedError(
                f"Content blocked by PII validation: {len(detections)} "
                f"detections of types [{types}]. "
                f"Set governance.pii.action=log or governance.pii.action=redact "
                f"to allow storage."
            )

        # action == "log": pass through
        return True, content, detections

    def _redact(self, text: str, detections: List[PIIDetection]) -> str:
        """Redact detected PII (process in reverse to preserve positions)."""
        # Build replacement map: entity_type -> placeholder
        # This allows entity-type-specific messages if configured
        result = list(text)
        for d in reversed(detections):
            result[d.start:d.end] = self._placeholder
        return "".join(result)


class PIIBlockedError(Exception):
    """Raised when content is blocked by PII validation."""
```

### Integration into GovernanceValidator

```python
# Modified: src/zettelforge/governance_validator.py

def __init__(self, governance_dir: Path = None, pii_config: Optional[PIIConfig] = None):
    self.governance_dir = governance_dir
    self.rules = self._load_governance_rules()
    self._pii = None
    if pii_config and pii_config.enabled:
        try:
            from zettelforge.pii_validator import PIIValidator
            self._pii = PIIValidator(
                action=pii_config.action,
                placeholder=pii_config.redact_placeholder,
                entities=pii_config.entities,
                language=pii_config.language,
                nlp_model=pii_config.nlp_model,
            )
        except ImportError:
            _logger.warning("pii_validator_unavailable")


def validate_remember(self, content: str) -> str:
    """Validate content for remember(). Returns (possibly redacted) content."""
    if self._pii:
        passed, processed, detections = self._pii.validate(content)
        if not passed:
            raise GovernanceViolationError(
                f"PII validation blocked content: {len(detections)} detections"
            )
        return processed
    return content
```

### Presidio Recognizers

Presidio ships with these built-in recognizers. Only those NOT in `_CTI_ALLOWLIST` are activated by default:

| PII Entity Type | Example | Default? | Notes |
|:----------------|:--------|:---------|:------|
| PERSON | John Smith | yes | |
| EMAIL_ADDRESS | user@example.com | yes | |
| PHONE_NUMBER | (555) 123-4567 | yes | |
| CREDIT_CARD | 4111-1111-1111-1111 | yes | |
| SSN | 123-45-6789 | yes | |
| CRYPTO | 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa | yes | Bitcoin addresses |
| DATE_TIME | April 25, 2026 | yes | |
| LOCATION | New York City | yes | |
| ORGANIZATION | Microsoft Corp | yes | |
| IP_ADDRESS | 10.0.0.1 | **explicitly allowed** | CTI IOC data |
| URL | https://evil.com | **explicitly allowed** | CTI IOC data |

The `_CTI_ALLOWLIST` protects IP_ADDRESS and URL from redaction since those are common CTI indicators, not PII in the CTI context.

### Package Extras

```toml
# pyproject.toml addition

[project.optional-dependencies]
# PII detection via Microsoft Presidio (RFC-013)
pii = [
    "presidio-analyzer>=2.2.0",
    "presidio-anonymizer>=2.2.0",
    "spacy>=3.5.0",
]
```

### Env Override

```python
# In _apply_env():
if v := os.environ.get("ZETTELFORGE_PII_ENABLED"):
    cfg.governance.pii.enabled = v.lower() in ("true", "1", "yes")
if v := os.environ.get("ZETTELFORGE_PII_ACTION"):
    cfg.governance.pii.action = v
```

### File Changes

| File | Change |
|------|--------|
| `src/zettelforge/pii_validator.py` | **Create** -- PIIValidator, PIIDetection, PIIBlockedError |
| `src/zettelforge/config.py` | Add `PIIConfig` dataclass; add `pii` field to `GovernanceConfig`; add env overrides |
| `src/zettelforge/governance_validator.py` | Integrate PIIValidator into `validate_remember()` |
| `src/zettelforge/memory_manager.py` | Call governance with returned (possibly redacted) content |
| `pyproject.toml` | Add `pii` optional dependency extra |
| `config.default.yaml` | Document `governance.pii` section |
| `docs/reference/configuration.md` | Document PII settings |
| `docs/reference/governance-controls.md` | Update with PII governance controls |
| `docs/how-to/configure-pii.md` | **Create** -- PII setup guide |
| `tests/test_pii_validator.py` | **Create** -- unit tests |
| `tests/test_governance_pii.py` | **Create** -- integration tests |

## Implementation Plan

### Phase 1: Core PIIValidator + Integration (v2.5.0)

1. Create `src/zettelforge/pii_validator.py` with PIIValidator, PIIDetection, PIIBlockedError.
2. Add `PIIConfig` dataclass to `config.py`.
3. Add `pii` field to `GovernanceConfig`.
4. Integrate PIIValidator into `GovernanceValidator.validate_remember()`.
5. Wire `governance.validate_remember()` into `memory_manager.remember()` so redacted content is what gets stored.
6. Add `pii` optional extra to `pyproject.toml`.
7. Add env overrides in `_apply_env()`.
8. Write unit tests: detection, redaction, blocking, CTI allowlist, no-PII passthrough.

### Phase 2: Documentation + CTI Custom Recognizers (v2.5.0)

1. Create `docs/how-to/configure-pii.md`.
2. Update `config.default.yaml` with examples.
3. Update `docs/reference/configuration.md`.
4. Update `docs/reference/governance-controls.md`.
5. (Optional) Add custom Presidio recognizer for CTI-specific patterns (project codenames, internal hostname formats).

## Rollout Strategy

**Phase 1** (v2.5.0): Disabled by default (`governance.pii.enabled: false`). Zero impact on existing installations. `pip install zettelforge[pii]` to enable. spaCy model downloads on first detection (~12-50MB depending on model size).

**Rollback:** Set `governance.pii.enabled: false` (or remove from config). No data impact -- redacted content is the only persistent effect.

**Observability:** Every PII detection logs structured event `pii_detected` with count, action, and entity type summary. Redactions and blocks leave audit trail.

## Alternatives Considered

**Alternative 1: Cloud-based PII detection (AWS Comprehend, Azure AI Content Safety).** Rejected because: (a) requires network access and API keys; (b) sends content to third-party servers, which may violate data sovereignty requirements; (c) adds per-operation cost; (d) incompatible with air-gapped deployments.

**Alternative 2: Regex-only PII detection.** Rejected because: (a) high false-positive rate for person names and organizations; (b) no context awareness ("Paris" = location vs "Paris Hilton" = person); (c) Presidio already includes regex patterns with NLP context scoring, so building it ourselves is wasted effort.

**Alternative 3: Post-storage PII scanning (async).** Rejected because: (a) PII may be stored before the async scanner runs, violating right-to-erasure principles; (b) vector database compaction after removal is expensive; (c) synchronous pre-storage validation is the simpler, safer pattern.

**Alternative 4: Require presidio-analyzer as a core dependency.** Rejected because: (a) adds ~50MB of spaCy model download for users who don't need PII detection; (b) follows the optional-extra pattern established by `local`, `local-onnx`, and `litellm`.

## Open Questions

1. **Should IP_ADDRESS be in the CTI allowlist by default?** Yes -- IPs are threat intelligence indicators, not PII in the CTI context. Users who need IP redaction can override `entities` to include `IP_ADDRESS`.

2. **Should the spaCy model be pinned or auto-download?** Auto-download on first use, matching the fastembed pattern. The download is a one-time cost (~12MB for `en_core_web_sm`).

3. **Should Presidio's `score` threshold be configurable?** Presidio returns scores (0.0-1.0). The default threshold is 0.5. This can be exposed via config in a follow-up if false positives are an issue.

4. **Should we add custom CTI recognizers?** In scope for Phase 2. Common CTI patterns like "UNC1234", "APT28", or "CVE-2025-12345" could be falsely detected as PII by generic models. Custom recognizers to explicitly allow these would reduce false positives.

5. **What about images?** Presidio Image Redactor is out of scope for v1. ZettelForge does not currently store images. If image support is added, image PII redaction will need its own RFC.

## Decision

**Decision**: [Pending review]
**Date**: [Pending]
**Decision Maker**: [Pending]
**Rationale**: [Pending]
