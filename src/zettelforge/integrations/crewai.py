"""
ZettelForge × CrewAI Integration

Provides CrewAI-compatible tools that wrap ZettelForge's MemoryManager so
CrewAI agents can persist and recall CTI knowledge across runs. Designed as
a drop-in alternative to CrewAI's existing Mem0 memory tools for crews
focused on cyber threat intelligence.

Three tools are exposed:

* ``ZettelForgeRecallTool`` — blended vector + graph search across stored
  notes. Returns formatted text suitable for an agent's tool result channel.
* ``ZettelForgeRememberTool`` — persist a finding back to memory. Auto-extracts
  CVEs, threat actors, ATT&CK techniques, and IOCs.
* ``ZettelForgeSynthesizeTool`` — LLM-synthesized answer over retrieved memory.

Usage:
    >>> from crewai import Agent
    >>> from zettelforge import MemoryManager
    >>> from zettelforge.integrations.crewai import (
    ...     ZettelForgeRecallTool, ZettelForgeRememberTool, ZettelForgeSynthesizeTool,
    ... )
    >>>
    >>> mm = MemoryManager()
    >>> recall = ZettelForgeRecallTool(memory_manager=mm, k=5)
    >>> remember = ZettelForgeRememberTool(memory_manager=mm)
    >>> synthesize = ZettelForgeSynthesizeTool(memory_manager=mm)
    >>>
    >>> analyst = Agent(
    ...     role="CTI analyst",
    ...     goal="Investigate threat-actor activity using prior intel",
    ...     backstory="Senior analyst with access to the team's knowledge base.",
    ...     tools=[recall, remember, synthesize],
    ... )

Install: ``pip install zettelforge[crewai]``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from zettelforge.memory_manager import MemoryManager

# CrewAI is an optional dependency. We import lazily so a stock
# ``import zettelforge.integrations`` never fails on a host without crewai
# installed. Tool classes are only constructed when the user explicitly opts in
# via ``pip install zettelforge[crewai]`` and imports this module.
try:
    from crewai.tools import BaseTool
except ImportError as exc:  # pragma: no cover — exercised only on missing dep
    raise ImportError(
        "ZettelForge x CrewAI integration requires the 'crewai' package. "
        "Install it with: pip install zettelforge[crewai]"
    ) from exc

if TYPE_CHECKING:
    from zettelforge.note_schema import MemoryNote


# ── Tool argument schemas ─────────────────────────────────────────────────────


class _RecallInput(BaseModel):
    """Arguments for ZettelForgeRecallTool."""

    query: str = Field(
        ...,
        description=(
            "Natural-language query describing what to search for. Examples: "
            '"APT28 lateral movement techniques", "CVE-2024-3094 backdoor", '
            '"ransomware groups active in 2025". Entity names, CVE IDs, and '
            "ATT&CK technique IDs are recognized automatically."
        ),
    )


class _RememberInput(BaseModel):
    """Arguments for ZettelForgeRememberTool."""

    content: str = Field(
        ...,
        description=(
            "The finding, observation, or analyst note to persist. Should be a "
            "complete statement, not a fragment. CVEs, threat actors, IOCs, "
            "and ATT&CK techniques are auto-extracted into the knowledge graph."
        ),
    )
    source_ref: str = Field(
        default="",
        description=(
            "Optional identifier for the source document or origin (e.g. an "
            "incident ticket ID, a report URL, or an analyst handle). Used by "
            "auditors and humans to trace provenance."
        ),
    )


class _SynthesizeInput(BaseModel):
    """Arguments for ZettelForgeSynthesizeTool."""

    query: str = Field(
        ...,
        description=(
            "Natural-language question to answer using prior CTI memory. The "
            "tool will retrieve relevant notes, then have the LLM synthesize a "
            "coherent answer with citations."
        ),
    )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _format_recall_result(notes: list[MemoryNote], query: str) -> str:
    """Render a list of MemoryNote into a string suitable for an agent.

    Each note becomes a numbered block with id, tier, confidence, source ref,
    domain, key entities, and the first ~500 chars of content. The format is
    optimized to be concise but information-dense for the agent's downstream
    reasoning, not for human reading.
    """
    if not notes:
        return f"No matching notes found for query: {query!r}"

    lines: list[str] = [f"Found {len(notes)} note(s) for query: {query!r}", ""]
    for idx, note in enumerate(notes, start=1):
        entities = ", ".join(note.semantic.entities[:8]) if note.semantic.entities else "(none)"
        source_ref = note.content.source_ref or "(unspecified)"
        body = note.content.raw[:500].rstrip()
        if len(note.content.raw) > 500:
            body += "..."
        lines.append(
            f"[{idx}] id={note.id} tier={note.metadata.tier} "
            f"confidence={note.metadata.confidence} domain={note.metadata.domain}"
        )
        lines.append(f"    source: {source_ref}")
        lines.append(f"    entities: {entities}")
        lines.append(f"    content: {body}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_synthesis_result(result: dict[str, Any]) -> str:
    """Render a synthesize() dict into agent-readable text.

    ``MemoryManager.synthesize()`` returns a wrapper dict shaped like::

        {"query": ..., "format": ..., "synthesis": <inner>, "metadata": ...,
         "sources": [<note source dicts>]}

    The actual answer payload lives in ``result["synthesis"]`` and its shape
    varies by format:

    * ``direct_answer``: ``{"answer", "confidence", "sources"}``
    * ``synthesized_brief``: ``{"summary", "themes", "confidence"}``
    * ``timeline_analysis``: ``{"timeline", "confidence"}``
    * ``relationship_map``: ``{"entities", "relationships"}``

    For backward compatibility (and to keep this formatter useful if a caller
    hands us a flatter result shape) we also look up the same keys directly on
    the outer dict.
    """
    inner = result.get("synthesis") if isinstance(result.get("synthesis"), dict) else {}

    def _pick(key: str) -> Any:
        # Inner shape wins; fall through to outer for callers that pass the
        # flat synthesis payload directly.
        return inner.get(key) if inner.get(key) is not None else result.get(key)

    answer: Any = _pick("answer") or _pick("summary")

    # relationship_map carries both entities and relationships — both
    # contribute to the structured payload the agent reasons over. Combine
    # them into one dict so neither is silently dropped.
    if answer is None:
        entities = _pick("entities")
        relationships = _pick("relationships")
        if entities is not None or relationships is not None:
            answer = {"entities": entities, "relationships": relationships}

    if answer is None:
        answer = _pick("timeline")

    if answer is None:
        answer = "(synthesis returned no answer)"

    if isinstance(answer, (list, dict)):
        # Coerce structured formats (timeline, relationship_map, brief themes)
        # to JSON so the agent can parse downstream rather than dropping
        # structure to str().
        import json

        answer = json.dumps(answer, indent=2, default=str)

    # Sources: the wrapper exposes a top-level list of source-note dicts
    # populated by SynthesisGenerator. direct_answer's inner sources is just
    # a list of citation strings — surface it only as a fallback.
    sources = result.get("sources") or inner.get("sources") or []
    source_lines: list[str] = []
    for src in sources[:10]:
        if isinstance(src, dict):
            sid = src.get("id") or src.get("note_id") or ""
            tier = src.get("tier", "")
            source_lines.append(f"  - {sid} (tier={tier})")
        else:
            source_lines.append(f"  - {src}")

    # Confidence lives inside the synthesis payload for every format that
    # reports it; only fall back to top-level for legacy callers.
    confidence = (
        inner.get("confidence") if inner.get("confidence") is not None else result.get("confidence")
    )
    parts = [str(answer).rstrip()]
    if confidence is not None:
        parts.append(f"confidence: {confidence}")
    if source_lines:
        parts.append("sources:")
        parts.extend(source_lines)
    return "\n".join(parts)


# ── Tools ──────────────────────────────────────────────────────────────────────


class ZettelForgeRecallTool(BaseTool):
    """CrewAI tool wrapping ZettelForge's blended recall.

    Use this when an agent needs to look up prior CTI investigations, threat-
    actor profiles, CVE context, ATT&CK technique observations, or any past
    notes relevant to its current task.

    Args:
        memory_manager: A ZettelForge MemoryManager instance.
        k: Maximum number of notes to return per call (default 10).
        domain: Optional domain filter (e.g. "security_ops").
    """

    name: str = "zettelforge_recall"
    description: str = (
        "Search ZettelForge memory for prior CTI investigations, threat actors, "
        "CVEs, ATT&CK techniques, and IOCs. Use this tool whenever you need "
        "historical context from past analyst work, prior incidents, or to "
        "check whether an indicator has been seen before. Returns up to k notes "
        "ranked by blended vector and graph relevance."
    )
    args_schema: type[BaseModel] = _RecallInput

    model_config = ConfigDict(arbitrary_types_allowed=True)

    memory_manager: MemoryManager = Field(exclude=True)
    k: int = 10
    domain: str | None = None

    def _run(self, query: str) -> str:
        notes = self.memory_manager.recall(
            query=query,
            domain=self.domain,
            k=self.k,
        )
        return _format_recall_result(notes, query)


class ZettelForgeRememberTool(BaseTool):
    """CrewAI tool that persists a finding back to ZettelForge memory.

    Use this to record findings that future agent runs and human analysts
    should be able to recall. The system auto-extracts CVEs, threat actors,
    ATT&CK techniques, and IOCs into the knowledge graph.

    Args:
        memory_manager: A ZettelForge MemoryManager instance.
        domain: Domain to tag stored notes with (default "cti").
        source_type: source_type tag for stored notes (default "crewai_agent").
        evolve: Whether to run the Mem0-style two-phase evolution pipeline
            (LLM extracts facts and decides ADD/UPDATE/DELETE/NOOP). Default
            False, matching MemoryManager.remember default. Setting True is
            slower but produces a tighter, deduplicated knowledge graph.
    """

    name: str = "zettelforge_remember"
    description: str = (
        "Store a new note in ZettelForge memory. Use this whenever you discover "
        "a finding, observe an IOC, identify attribution evidence, or produce "
        "any CTI-relevant context that should outlive the current agent run. "
        "Returns the note id and a short list of auto-extracted entities. "
        "Do NOT call this for transient reasoning steps or scratch work."
    )
    args_schema: type[BaseModel] = _RememberInput

    model_config = ConfigDict(arbitrary_types_allowed=True)

    memory_manager: MemoryManager = Field(exclude=True)
    domain: str = "cti"
    source_type: str = "crewai_agent"
    evolve: bool = False

    def _run(self, content: str, source_ref: str = "") -> str:
        note, status = self.memory_manager.remember(
            content=content,
            source_type=self.source_type,
            source_ref=source_ref,
            domain=self.domain,
            evolve=self.evolve,
        )
        entities = note.semantic.entities[:8]
        entity_summary = ", ".join(entities) if entities else "(none)"
        return (
            f"Stored note id={note.id} status={status} "
            f"tier={note.metadata.tier} entities={entity_summary}"
        )


class ZettelForgeSynthesizeTool(BaseTool):
    """CrewAI tool that returns an LLM-synthesized answer over memory.

    Use for questions that need a coherent narrative across many notes
    rather than a list of raw matches. Slower than recall (one LLM call per
    invocation) so reserve it for the agent's final-answer phase, not for
    every intermediate lookup.

    Args:
        memory_manager: A ZettelForge MemoryManager instance.
        k: Notes to retrieve as synthesis context (default 10).
        format: Output format. ``direct_answer`` works in community edition;
            ``synthesized_brief``, ``timeline_analysis``, and
            ``relationship_map`` require the enterprise extension and fall
            back to ``direct_answer`` automatically when unavailable.
        tier_filter: Restrict synthesis context to specific tiers
            (e.g. ``["A", "B"]``).
    """

    name: str = "zettelforge_synthesize"
    description: str = (
        "Generate an LLM-synthesized answer over ZettelForge memory. Use this "
        "for questions that need a coherent narrative across multiple notes "
        '(e.g. "summarize what we know about APT28 in 2025"). Returns a '
        "synthesized answer plus source note ids you can cite back to the "
        "user. Slower than zettelforge_recall (one LLM call per invocation), "
        "so prefer recall for intermediate lookups and reserve synthesize "
        "for final-answer composition."
    )
    args_schema: type[BaseModel] = _SynthesizeInput

    model_config = ConfigDict(arbitrary_types_allowed=True)

    memory_manager: MemoryManager = Field(exclude=True)
    k: int = 10
    format: str = "direct_answer"
    tier_filter: list[str] | None = None

    def _run(self, query: str) -> str:
        result = self.memory_manager.synthesize(
            query=query,
            format=self.format,
            k=self.k,
            tier_filter=self.tier_filter,
        )
        return _format_synthesis_result(result)


__all__ = [
    "ZettelForgeRecallTool",
    "ZettelForgeRememberTool",
    "ZettelForgeSynthesizeTool",
]
