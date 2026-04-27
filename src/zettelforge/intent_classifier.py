"""
Intent Classifier - Adaptive Query Routing (MAGMA-style)
A-MEM Agentic Memory Architecture V1.0

Query Intent Types:
- factual: "What CVE was used?" - Entity lookup, direct
- temporal: "What changed since X?" - Timeline queries
- relational: "Who uses what?" - Graph traversal
- exploratory: "Tell me about X" - Full recall + synthesis
- causal: "Why did X happen?" - Causal edge traversal

Task 3: Lightweight intent classifier to weight traversal policy
"""

from enum import Enum

from zettelforge.log import get_logger

_logger = get_logger("zettelforge.intent")


class QueryIntent(Enum):
    FACTUAL = "factual"  # Entity lookup (CVE, actor, tool)
    TEMPORAL = "temporal"  # Time-based queries
    RELATIONAL = "relational"  # Graph traversal (who uses what)
    EXPLORATORY = "exploratory"  # General exploration
    CAUSAL = "causal"  # Causal chains
    UNKNOWN = "unknown"


# Keywords for fast classification (zero-shot)
INTENT_KEYWORDS = {
    QueryIntent.FACTUAL: [
        "cve-",
        "cve ",
        "vulnerability",
        "exploit",
        "threat",
        "what is",
        "what was",
        "who is",
        "name",
        "identify",
    ],
    QueryIntent.TEMPORAL: [
        "when",
        "timeline",
        "since",
        "before",
        "after",
        "changed",
        "history",
        "previously",
        "earlier",
        "latest",
        "recent",
    ],
    QueryIntent.RELATIONAL: [
        "who uses",
        "who targets",
        "who conducts",
        "what tools does",
        "what malware does",
        "what technique",
        "what cve does",
        "used by",
        "attributed to",
        "related to",
        "connected to",
        "associated with",
        "linked to",
        "uses tool",
        "between",
        "relationship",
        "connection",
        "link",
        "which actor",
        "which group",
        "which apt",
        "what does",
    ],
    QueryIntent.CAUSAL: [
        "why",
        "because",
        "caused by",
        "enables",
        "leads to",
        "results in",
        "due to",
        "reason for",
    ],
    QueryIntent.EXPLORATORY: [
        "tell me about",
        "explain",
        "describe",
        "overview",
        "information on",
        "details about",
        "context",
        "summarize",
        "what do we know",
        "brief",
    ],
}


class IntentClassifier:
    """
    Lightweight intent classifier for query routing.
    Uses keyword matching + optional LLM for ambiguous cases.
    """

    def __init__(self, use_llm_fallback: bool = False):
        self.use_llm_fallback = use_llm_fallback
        self._llm_client = None

    def classify(self, query: str) -> tuple[QueryIntent, dict]:
        """
        Classify query intent.
        Returns (intent, metadata) where metadata includes confidence and reasoning.
        """
        query_lower = query.lower()

        # Fast keyword matching
        scores = {intent: 0 for intent in QueryIntent}

        for intent, keywords in INTENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in query_lower:
                    scores[intent] += 1

        # Get best intent
        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]

        # Confidence threshold: score >= 2 is high confidence.
        # score == 1 is accepted when the best intent is unambiguous
        # (no other intent also scored 1+), preventing EXPLORATORY fallback
        # for clear single-keyword matches like "what tools does APT28 use?".
        competing = sum(1 for intent, s in scores.items() if s > 0 and intent != best_intent)
        if best_score >= 2:
            confidence = min(1.0, best_score / 4)
            return best_intent, {"confidence": confidence, "method": "keyword", "scores": scores}
        if best_score == 1 and competing == 0:
            return best_intent, {
                "confidence": 0.6,
                "method": "keyword_unambiguous",
                "scores": scores,
            }

        # Low confidence - use LLM fallback
        if self.use_llm_fallback:
            return self._classify_llm(query)

        return QueryIntent.EXPLORATORY, {"confidence": 0.3, "method": "default", "scores": scores}

    def _classify_llm(self, query: str) -> tuple[QueryIntent, dict]:
        """Use LLM for ambiguous queries."""
        prompt = f"""Classify this query into one of these intents:
- factual: Entity lookup (CVE, actor, tool, malware)
- temporal: Time-based queries (when, since, history)
- relational: Graph traversal (who uses what, connections)
- exploratory: General exploration (tell me about)
- causal: Cause-effect (why, because)

Query: {query}

Respond with just the intent name (factual, temporal, relational, exploratory, or causal):"""

        try:
            from zettelforge.llm_client import generate

            intent_name = generate(prompt, max_tokens=20, temperature=0.1).lower()

            for intent in QueryIntent:
                if intent.value == intent_name:
                    return intent, {"confidence": 0.8, "method": "llm", "llm_response": intent_name}
        except Exception as e:
            _logger.warning("llm_classification_failed", error=str(e))

        return QueryIntent.EXPLORATORY, {"confidence": 0.5, "method": "llm_fallback", "scores": {}}

    def get_traversal_policy(self, intent: QueryIntent) -> dict:
        """
        Get traversal policy weights based on intent.
        Returns dict of (retriever_weight, graph_weight, temporal_weight)
        """
        policies = {
            QueryIntent.FACTUAL: {
                "vector": 0.3,
                "entity_index": 0.7,
                "graph": 0.2,
                "temporal": 0.0,
                "top_k": 3,
            },
            QueryIntent.TEMPORAL: {
                "vector": 0.2,
                "entity_index": 0.1,
                "graph": 0.2,
                "temporal": 0.5,
                "top_k": 5,
            },
            QueryIntent.RELATIONAL: {
                "vector": 0.2,
                "entity_index": 0.2,
                "graph": 0.5,
                "temporal": 0.1,
                "top_k": 10,
            },
            QueryIntent.CAUSAL: {
                "vector": 0.1,
                "entity_index": 0.1,
                "graph": 0.6,
                "temporal": 0.2,
                "top_k": 10,
            },
            QueryIntent.EXPLORATORY: {
                "vector": 0.5,
                "entity_index": 0.2,
                "graph": 0.2,
                "temporal": 0.1,
                "top_k": 10,
            },
            QueryIntent.UNKNOWN: {
                "vector": 0.4,
                "entity_index": 0.2,
                "graph": 0.2,
                "temporal": 0.2,
                "top_k": 5,
            },
        }

        return policies.get(intent, policies[QueryIntent.EXPLORATORY])


# Global instance
_classifier: IntentClassifier | None = None


def get_intent_classifier() -> IntentClassifier:
    """Get global intent classifier."""
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier
