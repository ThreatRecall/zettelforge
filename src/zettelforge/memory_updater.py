"""
Memory Updater - Phase 2 of Mem0-style two-phase pipeline.

Compares new facts against existing notes and decides:
ADD (new), UPDATE (refine), DELETE (contradict), or NOOP (duplicate).
"""

import json
import re
from enum import Enum
from typing import List, Optional, Tuple

from zettelforge.log import get_logger
from zettelforge.note_schema import MemoryNote

_logger = get_logger("zettelforge.memory_updater")


class UpdateOperation(Enum):
    ADD = "ADD"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    NOOP = "NOOP"


class MemoryUpdater:
    def __init__(self, memory_manager, model: str = "qwen2.5:3b", top_s: int = 3):
        self.mm = memory_manager
        self.model = model
        self.top_s = top_s

    def find_similar(self, fact_text: str, domain: Optional[str] = None) -> List[MemoryNote]:
        return self.mm.retriever.retrieve(
            query=fact_text, domain=domain, k=self.top_s, include_links=False
        )

    def decide(self, fact_text: str, similar_notes: List[MemoryNote]) -> UpdateOperation:
        if not similar_notes:
            return UpdateOperation.ADD

        prompt = self._build_decision_prompt(fact_text, similar_notes)

        try:
            from zettelforge.llm_client import generate

            raw = generate(prompt, max_tokens=150, temperature=0.1)
            return self._parse_operation_response(raw)
        except Exception:
            _logger.warning("llm_update_decision_failed_defaulting_add", exc_info=True)
            return UpdateOperation.ADD

    def apply(
        self,
        operation: UpdateOperation,
        fact_text: str,
        importance: int,
        source_ref: str,
        similar_notes: List[MemoryNote],
        domain: str = "cti",
    ) -> Tuple[Optional[MemoryNote], str]:
        if operation == UpdateOperation.NOOP:
            return None, "noop"

        if operation == UpdateOperation.ADD:
            note, _ = self.mm.remember(
                fact_text, source_type="extraction", source_ref=source_ref, domain=domain
            )
            note.metadata.importance = importance
            self.mm.store._rewrite_note(note)
            return note, "added"

        if operation == UpdateOperation.UPDATE:
            note, _ = self.mm.remember(
                fact_text, source_type="extraction", source_ref=source_ref, domain=domain
            )
            note.metadata.importance = importance
            self.mm.store._rewrite_note(note)
            if similar_notes:
                self.mm.mark_note_superseded(similar_notes[0].id, note.id)
            return note, "updated"

        if operation == UpdateOperation.DELETE:
            note, _ = self.mm.remember(
                fact_text, source_type="correction", source_ref=source_ref, domain=domain
            )
            note.metadata.importance = importance
            self.mm.store._rewrite_note(note)
            if similar_notes:
                self.mm.mark_note_superseded(similar_notes[0].id, note.id)
            return note, "corrected"

        return None, "unknown"

    def _build_decision_prompt(self, fact_text: str, similar_notes: List[MemoryNote]) -> str:
        existing = "\n".join(f"- [{n.id}] {n.content.raw[:200]}" for n in similar_notes)
        return f"""Compare this new fact against existing memory entries.
Decide one operation: ADD, UPDATE, DELETE, or NOOP.

- ADD: fact is genuinely new, no similar entry covers it
- UPDATE: fact refines or corrects an existing entry
- DELETE: fact contradicts an existing entry (the old one is wrong/stale)
- NOOP: fact is already captured, nothing changed

New fact: {fact_text}

Existing entries:
{existing}

Respond with JSON: {{"operation": "ADD|UPDATE|DELETE|NOOP", "reason": "brief explanation"}}
JSON:"""

    def _parse_operation_response(self, raw: str) -> UpdateOperation:
        if not raw:
            return UpdateOperation.ADD

        if raw.startswith("```"):
            parts = raw.split("```")
            for part in parts:
                stripped = part.strip()
                if stripped.startswith("json"):
                    stripped = stripped[4:].strip()
                if stripped.startswith("{"):
                    raw = stripped
                    break

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return UpdateOperation.ADD

        try:
            parsed = json.loads(match.group(0))
            op_str = parsed.get("operation", "ADD").upper()
            return UpdateOperation(op_str)
        except (json.JSONDecodeError, ValueError):
            return UpdateOperation.ADD
