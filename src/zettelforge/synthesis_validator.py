"""
Synthesis Validator — Phase 7 Response Validation
A-MEM Agentic Memory Architecture V1.0
"""

import threading


class SynthesisValidator:
    """Validates synthesis responses against quality thresholds."""

    def __init__(
        self,
        min_confidence: float = 0.3,
        min_sources: int = 1,
        max_sources: int = 20,
        max_summary_length: int = 500,
        max_answer_length: int = 200,
    ):
        self.min_confidence = min_confidence
        self.min_sources = min_sources
        self.max_sources = max_sources
        self.max_summary_length = max_summary_length
        self.max_answer_length = max_answer_length

    def validate_response(self, response: dict) -> tuple[bool, list[str]]:
        """Validate a complete synthesis response."""
        errors = []
        synthesis = response.get("synthesis", {})
        sources = response.get("sources", [])

        # Validate synthesis
        if "confidence" in synthesis:
            conf = synthesis["confidence"]
            if not isinstance(conf, (int, float)):
                errors.append("confidence must be a number")
            elif conf < self.min_confidence:
                errors.append(f"confidence below threshold: {conf} < {self.min_confidence}")

        # Validate sources
        if len(sources) < self.min_sources:
            errors.append(f"sources count below minimum: {len(sources)} < {self.min_sources}")
        if len(sources) > self.max_sources:
            errors.append(f"sources count exceeds maximum: {len(sources)} > {self.max_sources}")

        return len(errors) == 0, errors

    def check_quality_score(self, response: dict) -> dict:
        """Compute a quality score for a response."""
        synthesis = response.get("synthesis", {})
        sources = response.get("sources", [])

        confidence = synthesis.get("confidence", 0)
        confidence_score = min(1.0, confidence / 0.7)
        source_score = min(1.0, len(sources) / 5)

        completeness = 1.0
        if "answer" not in synthesis and "summary" not in synthesis:
            completeness = 0.0

        score = confidence_score * 0.4 + source_score * 0.3 + completeness * 0.3

        return {
            "score": round(score, 3),
            "components": {
                "confidence": round(confidence_score, 3),
                "sources": round(source_score, 3),
                "completeness": round(completeness, 3),
            },
            "quality": "EXCELLENT" if score >= 0.8 else "GOOD" if score >= 0.5 else "NEEDS_WORK",
        }


_validator: SynthesisValidator | None = None
_validator_lock = threading.Lock()


def get_synthesis_validator() -> SynthesisValidator:
    global _validator
    if _validator is None:
        with _validator_lock:
            if _validator is None:
                _validator = SynthesisValidator()
    return _validator
