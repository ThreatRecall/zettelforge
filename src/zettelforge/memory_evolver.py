"""
Memory Evolution — A-Mem inspired neighbor refinement.

When a new note is created, finds top-k similar existing notes and
prompts the LLM to decide whether each neighbor should be updated
with new context from the incoming note.

Based on: A-Mem (arXiv:2502.12110, NeurIPS 2025)
"""

from typing import Any

from zettelforge.json_parse import extract_json
from zettelforge.llm_client import generate
from zettelforge.log import get_logger
from zettelforge.note_schema import MemoryNote
from zettelforge.vector_memory import get_embedding

EVOLUTION_PROMPT = """You are analyzing whether an existing memory note should be updated based on new information.

EXISTING NOTE:
{neighbor_content}

NEW INFORMATION:
{new_content}

Should the existing note be updated to incorporate the new information?

Rules:
- Only update if the new information adds meaningful context, corrects errors, or fills gaps
- Do NOT update if the new information is unrelated or redundant
- If updating, provide the COMPLETE updated note content (not just the changes)

Respond with JSON only:
{{"action": "evolve" or "keep", "reason": "brief explanation", "updated_content": "complete updated text if evolve, empty string if keep"}}"""


class MemoryEvolver:
    """Evolve existing notes by incorporating context from newly created notes.

    Implements the neighbor-refinement loop from A-Mem: for each new note,
    find top-k semantic neighbors, ask the LLM whether each neighbor should
    be updated, and apply the evolution with rollback capability.
    """

    def __init__(
        self,
        memory_manager: Any,
        k: int = 5,
        similarity_threshold: float = 0.3,
    ):
        self._mm = memory_manager
        self.k = k
        self.similarity_threshold = similarity_threshold
        self._logger = get_logger("zettelforge.evolution")

    # ── Candidate discovery ─────────────────────────────────────────────

    def find_evolution_candidates(self, note: MemoryNote) -> list[MemoryNote]:
        """Find top-k notes similar to *note* that might benefit from evolution.

        Uses the memory manager's recall path (vector + entity + reranking)
        to surface neighbors, then filters out the note itself and any notes
        already queued for evolution.
        """
        results = self._mm.recall(
            query=note.content.raw[:500],
            domain=note.metadata.domain,
            k=self.k + 1,  # +1 because the note itself may appear
            include_links=False,
            exclude_superseded=True,
        )

        candidates = [r for r in results if r.id != note.id]
        return candidates[: self.k]

    # ── LLM evaluation ──────────────────────────────────────────────────

    def evaluate_evolution(
        self,
        new_note: MemoryNote,
        neighbor: MemoryNote,
    ) -> dict | None:
        """Ask the LLM whether *neighbor* should be updated given *new_note*.

        Returns a dict with keys ``action``, ``reason``, ``updated_content``
        when the LLM responds with valid JSON, or ``None`` on parse failure
        (after one retry).
        """
        prompt = EVOLUTION_PROMPT.format(
            neighbor_content=neighbor.content.raw[:1000],
            new_content=new_note.content.raw[:1000],
        )

        # First attempt
        output = generate(prompt, max_tokens=2500, temperature=0.2, json_mode=True)
        result = extract_json(output, expect="object")

        # Single retry on parse failure (AD-2). Capture what the model
        # actually returned so we can diagnose schema/template mismatches
        # without re-running the test.
        if result is None:
            self._logger.warning(
                "evolution_parse_retry",
                neighbor_id=neighbor.id,
                new_note_id=new_note.id,
                raw_preview=(output or "")[:240],
                raw_chars=len(output or ""),
                prompt_preview=prompt[:240],
            )
            output = generate(prompt, max_tokens=2500, temperature=0.1, json_mode=True)
            result = extract_json(output, expect="object")

        if result is None:
            self._logger.warning(
                "evolution_parse_failed",
                neighbor_id=neighbor.id,
                new_note_id=new_note.id,
                raw_preview=(output or "")[:240],
                raw_chars=len(output or ""),
            )
            return None

        # Validate required fields
        action = result.get("action")
        if action not in ("evolve", "keep"):
            self._logger.warning(
                "evolution_invalid_action",
                neighbor_id=neighbor.id,
                action=action,
            )
            return None

        # Ensure updated_content exists for evolve actions
        if action == "evolve" and not result.get("updated_content"):
            self._logger.warning(
                "evolution_missing_content",
                neighbor_id=neighbor.id,
            )
            return None

        return result

    # ── Apply / rollback ────────────────────────────────────────────────

    def apply_evolution(
        self,
        neighbor: MemoryNote,
        updated_content: str,
        new_note_id: str,
    ) -> MemoryNote:
        """Apply evolution to a neighbor note.

        * Saves original content in ``content.previous_raw`` for rollback.
        * Replaces ``content.raw`` with the evolved text.
        * Re-generates the embedding vector (AD-5).
        * Calls ``increment_evolution()`` to bump count and decay confidence.
        * Persists via ``store._rewrite_note()``.
        """
        # Preserve original content for rollback (AD-3)
        neighbor.content.previous_raw = neighbor.content.raw
        neighbor.content.raw = updated_content

        # Re-embed with new content (AD-5)
        new_vector = get_embedding(updated_content[:1000])
        neighbor.embedding.vector = new_vector

        # Update metadata via schema helper
        neighbor.increment_evolution(evolved_by_note_id=new_note_id)

        # Persist
        self._mm.store._rewrite_note(neighbor)

        self._logger.info(
            "evolution_applied",
            neighbor_id=neighbor.id,
            new_note_id=new_note_id,
            evolution_count=neighbor.metadata.evolution_count,
        )

        return neighbor

    def rollback(self, note: MemoryNote) -> bool:
        """Rollback an evolution by restoring ``previous_raw`` content.

        Re-embeds the restored content and persists the change.
        Returns ``True`` on success, ``False`` if no previous content exists.
        """
        if not note.content.previous_raw:
            return False

        note.content.raw = note.content.previous_raw
        note.content.previous_raw = None

        # Undo metadata changes
        note.metadata.evolution_count = max(0, note.metadata.evolution_count - 1)

        # Re-embed with restored content
        note.embedding.vector = get_embedding(note.content.raw[:1000])

        # Persist
        self._mm.store._rewrite_note(note)

        self._logger.info("evolution_rolled_back", note_id=note.id)
        return True

    # ── Main entry point ────────────────────────────────────────────────

    def evolve_neighbors(self, new_note: MemoryNote) -> dict[str, Any]:
        """Find candidates and evolve neighbors of *new_note*.

        Returns a report dict::

            {
                "candidates_found": int,
                "evaluated": int,
                "evolved": int,
                "kept": int,
                "errors": int,
                "evolved_ids": [str],
            }
        """
        report: dict[str, Any] = {
            "candidates_found": 0,
            "evaluated": 0,
            "evolved": 0,
            "kept": 0,
            "errors": 0,
            "evolved_ids": [],
        }

        candidates = self.find_evolution_candidates(new_note)
        report["candidates_found"] = len(candidates)

        for neighbor in candidates:
            try:
                result = self.evaluate_evolution(new_note, neighbor)
                if result is None:
                    report["errors"] += 1
                    continue

                report["evaluated"] += 1

                if result["action"] == "evolve":
                    self.apply_evolution(
                        neighbor,
                        result["updated_content"],
                        new_note.id,
                    )
                    report["evolved"] += 1
                    report["evolved_ids"].append(neighbor.id)
                else:
                    report["kept"] += 1

            except Exception:
                self._logger.warning(
                    "evolution_neighbor_error",
                    neighbor_id=neighbor.id,
                    exc_info=True,
                )
                report["errors"] += 1

        self._logger.info(
            "evolution_complete",
            new_note_id=new_note.id,
            **{k: v for k, v in report.items() if k != "evolved_ids"},
        )

        return report
