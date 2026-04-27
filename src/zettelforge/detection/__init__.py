"""
ZettelForge Detection Rules — shared supertype + explainer + consumers.

Phase 3: DetectionRule supertype + RuleExplanation + explain() shipped;
DetectionMatchConsumer protocol frozen (implementations deferred to v1.1).
See phase-1c-detection-rule-architecture.md.
"""

from zettelforge.detection.base import DetectionRule
from zettelforge.detection.consumers import (
    ALL_CONSUMERS,
    DetectionMatchConsumer,
    RuleMatchEvent,
)
from zettelforge.detection.explainer import RuleExplanation, explain

__all__ = [
    "ALL_CONSUMERS",
    "DetectionMatchConsumer",
    "DetectionRule",
    "RuleExplanation",
    "RuleMatchEvent",
    "explain",
]
