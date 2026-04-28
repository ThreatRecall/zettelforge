"""
Fact Extractor - Phase 1 of Mem0-style two-phase pipeline.

Extracts salient facts from raw content using LLM, with importance scoring.
Only the important facts proceed to storage, reducing redundancy and noise.
"""

import json
import re
from dataclasses import dataclass
from typing import List

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
    ) -> List[ExtractedFact]:
        prompt = self._build_prompt(content, context)

        try:
            from zettelforge.llm_client import generate

            raw_output = generate(prompt, max_tokens=400, temperature=0.1)
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

    def _parse_extraction_response(self, raw: str) -> List[ExtractedFact]:
        if not raw:
            return []

        # Strip markdown code fences
        if raw.startswith("```"):
            parts = raw.split("```")
            for part in parts:
                stripped = part.strip()
                if stripped.startswith("json"):
                    stripped = stripped[4:].strip()
                if stripped.startswith("["):
                    raw = stripped
                    break

        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []

        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
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
