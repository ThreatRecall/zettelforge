"""PII detection and redaction using Microsoft Presidio (RFC-013).

Optional integration with ``GovernanceValidator``. When enabled via config,
scans content for PII before ``remember()`` operations and applies the
configured action (``log``, ``redact``, or ``block``).

This module is NOT imported at package init time. It is loaded lazily by
``GovernanceValidator`` only when ``governance.pii.enabled = true`` in
config. The core package never hard-depends on ``presidio-analyzer`` or
``spacy``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from zettelforge.log import get_logger

_logger = get_logger("zettelforge.pii")


# PII entity types that are legitimate CTI indicators and should NOT be
# redacted by default. Users can override by specifying explicit entities.
_CTI_ALLOWLIST = frozenset(
    {
        "IP_ADDRESS",  # IOC -- threat data, not PII
        "URL",  # IOC -- threat data, not PII
        "DOMAIN_NAME",  # IOC -- threat data, not PII
    }
)


@dataclass
class PIIDetection:
    """A single PII detection result."""

    entity_type: str
    text: str
    start: int
    end: int
    score: float


class PIIValidator:
    """Validates content for PII using Microsoft Presidio.

    Three actions:
        ``log`` (default) -- detect and warn, pass content through unchanged.
        ``redact`` -- replace detected PII with placeholders.
        ``block`` -- raise :class:`PIIBlockedError` if ANY PII is detected.

    Thread-safe. Lazily loads Presidio + spaCy model on first call.
    The model downloads automatically (matching fastembed download pattern).
    """

    def __init__(
        self,
        action: str = "log",
        placeholder: str = "[REDACTED]",
        entities: list[str] | None = None,
        language: str = "en",
        nlp_model: str = "en_core_web_sm",
    ) -> None:
        if action not in ("log", "redact", "block"):
            raise ValueError(f"Unknown PII action: {action!r}")
        self._action = action
        self._placeholder = placeholder
        # Presidio semantics: entities=[] means "detect none", entities=None
        # means "detect all supported types". The PIIConfig default is []
        # (meaning "all"), so convert empty list to None here.
        self._entities: list[str] | None = entities if entities else None
        self._language = language
        self._nlp_model = nlp_model
        self._analyzer: object = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        """Lazy-load Presidio analyzer (downloads spaCy model on first call)."""
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

    def detect(self, text: str) -> list[PIIDetection]:
        """Analyze text and return detected PII entities.

        Results are sorted by start position. Overlapping spans are
        resolved: the longest span wins when one fully contains another;
        otherwise the highest-score entity wins per exact position.
        """
        if not text or not text.strip():
            return []
        self._ensure_loaded()

        # Apply CTI allowlist at detect time: when entities=None (detect
        # all), exclude allowlisted types from results. When user explicitly
        # provides entities, honour that list exactly.
        passed_to_analyzer = self._entities

        results = self._analyzer.analyze(
            text=text,
            entities=passed_to_analyzer,
            language=self._language,
        )

        # Resolve overlapping spans: longest span wins when one contains
        # another (the longer span is more precise for redaction). For
        # equal-length spans, highest score wins.
        raw: list[PIIDetection] = []
        for r in results:
            # Filter CTI allowlist at detect time when in detect-all mode
            if self._entities is None and r.entity_type in _CTI_ALLOWLIST:
                continue
            raw.append(
                PIIDetection(
                    entity_type=r.entity_type,
                    text=text[r.start : r.end],
                    start=r.start,
                    end=r.end,
                    score=r.score,
                )
            )

        # Span resolution: sort by length desc, then score desc.
        # Take each non-overlapping span greedily.
        raw.sort(key=lambda d: (d.end - d.start, d.score), reverse=True)

        selected: list[PIIDetection] = []
        for d in raw:
            # Check if this span overlaps any already-selected span
            overlaps = False
            for s in selected:
                if d.start < s.end and d.end > s.start:
                    overlaps = True
                    break
            if not overlaps:
                selected.append(d)

        return sorted(selected, key=lambda d: d.start)

    def validate(self, content: str) -> tuple[bool, str, list[PIIDetection]]:
        """Validate content for PII.

        Args:
            content: Text to validate.

        Returns:
            Tuple of (passed, processed_content, detections).
            ``passed`` is True when action is not ``block`` or no PII found.
            ``processed_content`` is the original content (for ``log`` /
            ``block``) or redacted content (for ``redact``).
        """
        detections = self.detect(content)
        if not detections:
            return True, content, []

        _logger.warning(
            "pii_detected",
            count=len(detections),
            action=self._action,
            # Log entity types and scores only -- never log the actual
            # detected text to avoid PII leakage into structured logs.
            entities=[{"type": d.entity_type, "score": round(d.score, 2)} for d in detections],
        )

        if self._action == "redact":
            return True, self._redact(content, detections), detections

        if self._action == "block":
            types = ", ".join(sorted(set(d.entity_type for d in detections)))
            raise PIIBlockedError(
                f"Content blocked by PII validation: {len(detections)} "
                f"detections of types [{types}]. "
                f"Set governance.pii.action=log or governance.pii.action=redact "
                f"to allow storage."
            )

        # action == "log": warn only, pass through unchanged
        return True, content, detections

    def _redact(self, text: str, detections: list[PIIDetection]) -> str:
        """Replace detected PII spans with placeholders (reverse-order safe)."""
        result = list(text)
        for d in reversed(detections):
            result[d.start : d.end] = self._placeholder
        return "".join(result)


class PIIBlockedError(Exception):
    """Raised when content is blocked by PII validation (action=block)."""
