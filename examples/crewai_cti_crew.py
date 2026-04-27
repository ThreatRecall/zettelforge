"""Example: a small CrewAI crew that uses ZettelForge as its CTI memory.

Run with::

    pip install zettelforge[crewai]
    python examples/crewai_cti_crew.py

The crew has two agents:

* A retrieval analyst whose only job is to pull prior intel from ZettelForge
  using the recall tool, and persist the new task framing as a note.
* A synthesizer whose job is to compose the final analyst-facing answer
  using the synthesize tool.

The script seeds memory with three notes so you can see the recall path
return real content even on a freshly-installed system. Replace the seed
data with a real ingest path (MISP feed, MITRE ATT&CK, your incident
backlog) for production use.

This example deliberately does NOT call out to a remote LLM by default. If
your CrewAI install is wired to OpenAI / Anthropic, the agents will use
that backend; otherwise they will fall back to whatever LLM your local
CrewAI configuration points to. ZettelForge's own LLM (used by recall and
synthesize internally) is configured via ``zettelforge.config``, not by
CrewAI.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    try:
        from crewai import Agent, Crew, Task
    except ImportError:
        print(
            "This example requires the 'crewai' package. "
            "Install with: pip install zettelforge[crewai]",
            file=sys.stderr,
        )
        return 1

    from zettelforge import MemoryManager
    from zettelforge.integrations.crewai import (
        ZettelForgeRecallTool,
        ZettelForgeRememberTool,
        ZettelForgeSynthesizeTool,
    )

    mm = MemoryManager()

    # Seed a few notes so the demo isn't talking to an empty memory. Skip
    # seeding if the data dir already has notes (avoids piling up duplicates
    # on repeated runs).
    if mm.get_stats().get("total_notes", 0) == 0:
        mm.remember(
            "APT28 (Fancy Bear, STRONTIUM, Sofacy) is a Russian state-sponsored "
            "threat actor. Known for spear-phishing campaigns targeting NATO, "
            "defense contractors, and political organizations using credential-"
            "harvesting links and OAuth abuse.",
            domain="cti",
            source_type="seed",
            source_ref="examples/crewai_cti_crew.py",
        )
        mm.remember(
            "CVE-2024-3094 is the XZ Utils backdoor present in versions 5.6.0 "
            "and 5.6.1. CVSS v3 base score 10.0. Supply-chain attack that "
            "compromises sshd authentication on affected Linux distributions.",
            domain="cti",
            source_type="seed",
            source_ref="examples/crewai_cti_crew.py",
        )
        mm.remember(
            "Lazarus Group (DPRK-aligned) was observed in 2025-Q1 deploying a "
            "novel macOS payload via fake recruiter LinkedIn outreach. Initial "
            "access vector: signed but malicious .pkg installers.",
            domain="cti",
            source_type="seed",
            source_ref="examples/crewai_cti_crew.py",
        )

    recall = ZettelForgeRecallTool(memory_manager=mm, k=5)
    remember = ZettelForgeRememberTool(memory_manager=mm)
    synthesize = ZettelForgeSynthesizeTool(memory_manager=mm, k=8)

    retrieval_analyst = Agent(
        role="CTI retrieval analyst",
        goal=(
            "Pull all prior intel relevant to the investigation question and "
            "persist the question itself as a note for future audits."
        ),
        backstory=(
            "Junior analyst whose strength is exhaustive recall. Cites note ids "
            "verbatim and never invents context."
        ),
        tools=[recall, remember],
        allow_delegation=False,
        verbose=True,
    )

    senior_analyst = Agent(
        role="Senior CTI analyst",
        goal=(
            "Synthesize a clear, sourced answer for the team using only the "
            "memory ZettelForge surfaces. If the synthesis is empty, say so."
        ),
        backstory=(
            "10 years SOC and threat intel. Refuses to speculate beyond what "
            "the cited notes support. Answers in plain English."
        ),
        tools=[synthesize, recall],
        allow_delegation=False,
        verbose=True,
    )

    question = os.environ.get(
        "QUESTION",
        "What do we know about APT28 spear-phishing tradecraft and which CVEs "
        "have we seen them weaponize?",
    )

    pull_task = Task(
        description=(
            f"Investigate this question: {question!r}. First call "
            "zettelforge_recall to surface all relevant notes. Then call "
            "zettelforge_remember to persist the question as a tracked "
            "investigation. Return the recalled notes verbatim for the senior "
            "analyst to consume."
        ),
        expected_output="A structured list of all relevant note ids and their content.",
        agent=retrieval_analyst,
    )

    answer_task = Task(
        description=(
            f"Using the prior memory the retrieval analyst surfaced, answer: "
            f"{question!r}. Use zettelforge_synthesize for the main composition. "
            "Cite note ids inline. If memory is insufficient, say so explicitly."
        ),
        expected_output="A short, cited answer suitable for an analyst Slack channel.",
        agent=senior_analyst,
        context=[pull_task],
    )

    crew = Crew(
        agents=[retrieval_analyst, senior_analyst],
        tasks=[pull_task, answer_task],
        verbose=True,
    )

    result = crew.kickoff()
    print("\n" + "=" * 72)
    print("CREW FINAL ANSWER")
    print("=" * 72)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
