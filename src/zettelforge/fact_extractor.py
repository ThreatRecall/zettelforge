"""
Fact Extractor - Phase 1 of Mem0-style two-phase pipeline.

Extracts salient facts from raw content using LLM, with importance scoring.
Only the important facts proceed to storage, reducing redundancy and noise.
"""

from dataclasses import dataclass

from zettelforge.json_parse import extract_json
from zettelforge.log import get_logger

_logger = get_logger("zettelforge.fact_extractor")


@dataclass
class ExtractedFact:
    """A single extracted fact with importance score."""

    text: str
    importance: int = 5  # 1-10 scale


class FactExtractor:
    """Extract salient facts from content using LLM."""

    def __init__(
        self,
        model: str = "qwen2.5:3b",
        max_facts: int = 5,
    ):
        self.model = model
        self.max_facts = max_facts

    def extract(
        self,
        content: str,
        context: str = "",
    ) -> list[ExtractedFact]:
        prompt = self._build_prompt(content, context)

        try:
            from zettelforge.llm_client import generate

            # 2500-token budget for reasoning-model headroom (see v2.5.2
            # CHANGELOG; pre-fix 400 was exhausted by qwen3.5+ <think> tokens).
            raw_output = generate(prompt, max_tokens=2500, temperature=0.1)
            return self._parse_extraction_response(raw_output)
        except Exception:
            _logger.warning("llm_fact_extraction_failed", exc_info=True)
            return [ExtractedFact(text=content[:500], importance=5)]

    def _build_prompt(self, content: str, context: str) -> str:
        parts = [
            "Extract the most important facts from this text as a JSON array.",
            'Each item: {"fact": "concise statement", "importance": 1-10}',
            "Only include facts worth remembering long-term. Skip greetings and filler.",
        ]
        if context:
            parts.append(f"\nContext:\n{context}")
        parts.append(f"\nText:\n{content[:2000]}")
        parts.append("\nJSON:")
        return "\n".join(parts)

    def _parse_extraction_response(self, raw: str) -> list[ExtractedFact]:
        if not raw:
            # Was previously a silent return — empty completions vanished
            # entirely from the audit trail, undercounting LLM failures.
            _logger.warning(
                "parse_failed",
                schema="fact_extraction",
                reason="empty_completion",
                raw="",
            )
            return []

        parsed = extract_json(raw, expect="array")
        if parsed is None:
            _logger.warning(
                "parse_failed",
                schema="fact_extraction",
                reason="json_decode",
                raw=raw[:240],
                raw_chars=len(raw),
            )
            return []

        facts = []
        for item in parsed:
            if isinstance(item, dict):
                text = item.get("fact", "").strip()
                try:
                    importance = int(item.get("importance", 5))
                except (ValueError, TypeError):
                    importance = 5
                importance = max(1, min(10, importance))
                if text:
                    facts.append(ExtractedFact(text=text, importance=importance))

        facts.sort(key=lambda f: f.importance, reverse=True)
        return facts[: self.max_facts]
