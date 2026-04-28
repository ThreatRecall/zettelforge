---
title: "Epistemic Tiers and Confidence"
description: "ThreatRecall's model for tracking intelligence quality and confidence decay"
diataxis_type: explanation
audience: "Senior CTI Practitioner"
tags: [confidence, epistemic, tiers, quality, intelligence-lifecycle]
last_updated: "2026-04-09"
version: "2.0.0"
---

# Epistemic Tiers and Confidence

Not all intelligence is created equal. A verified CISA advisory carries more weight than an anonymous forum post, which carries more weight than an LLM's speculation. ThreatRecall tracks this through two complementary mechanisms: epistemic tiers and confidence scores.

## Epistemic Tiers (A / B / C)

Every note and entity in ThreatRecall carries a `tier` classification:

| Tier | Label | Meaning | Typical Sources |
|:-----|:------|:--------|:----------------|
| **A** | Authoritative | Verified, high-confidence intelligence from trusted sources | CISA advisories, MITRE ATT&CK, vendor-confirmed CVEs, court documents |
| **B** | Operational | Working knowledge with moderate confidence, useful for day-to-day analysis | Threat reports from CrowdStrike/Mandiant, internal incident notes, peer-reviewed analysis |
| **C** | Support | Low-confidence, inferred, or speculative intelligence | LLM-extracted relationships, unverified forum posts, automated correlations, causal triples |

Tiers are assigned at ingestion time:
- Notes ingested via `remember()` default to tier **B**
- LLM-extracted facts from the two-phase pipeline inherit tier **B** from the source note
- Causal triples extracted by the `NoteConstructor` are tier **C** (LLM inference, not human-verified)
- Analysts can promote notes to tier **A** by modifying `note.metadata.tier`

## Confidence Scores (0.0 - 1.0)

Every note, entity, and relationship carries a `confidence` score:

- **1.0**: Certain (e.g., CVE-2024-3094 exists — it's in the NVD)
- **0.85**: High confidence (e.g., "APT28 uses Cobalt Strike" — multiple corroborating reports)
- **0.5**: Moderate (e.g., "Campaign may be attributed to Lazarus Group" — single source)
- **0.1**: Low (e.g., "Possible connection between Volt Typhoon and infrastructure X" — speculative)

### Confidence on Relations

In TypeDB, confidence is an attribute on every STIX relationship:

```
(user: APT28, used: Cobalt Strike) isa uses, has confidence 0.85
(source: Lazarus Group, target: crypto exchanges) isa targets, has confidence 0.6
```

This means the `BlendedRetriever` can weight results not just by relevance but by reliability. A high-confidence, direct relationship ranks above a low-confidence, inferred one.

### Confidence Decay

ThreatRecall's `MemoryNote` tracks `evolution_count` — how many times a note has been superseded or evolved. Each evolution event reduces confidence:

```python
def increment_evolution(self, evolved_by_note_id: str):
    self.metadata.evolution_count += 1
    self.evolved_by.append(evolved_by_note_id)
    self.metadata.confidence = min(self.metadata.confidence, 0.95)
```

A note that has been superseded 5+ times triggers `should_flag_for_review()`, signaling that this piece of intelligence has been revised frequently and may warrant human review.

## How Tiers Affect Retrieval and Synthesis

The `synthesize()` method accepts a `tier_filter` parameter:

```python
# Only use authoritative and operational sources
result = mm.synthesize("APT28 capabilities", tier_filter=["A", "B"])

# Include speculative/inferred intelligence
result = mm.synthesize("APT28 capabilities", tier_filter=["A", "B", "C"])

# Strict mode: authoritative only
result = mm.synthesize("APT28 capabilities", tier_filter=["A"])
```

The default filter is `["A", "B"]` — operational quality. This means LLM-extracted causal triples (tier C) are excluded from synthesis by default unless explicitly requested.

## The Diamond Model Connection

CTI practitioners will recognize ThreatRecall's confidence model as complementary to the Diamond Model of Intrusion Analysis. Where the Diamond Model describes relationships between adversary, capability, infrastructure, and victim, ThreatRecall's epistemic tiers address the meta-question: how much do we trust each relationship?

A Diamond Model analysis might state "Adversary X uses Capability Y targeting Victim Z." ThreatRecall stores this as three typed relationships, each with independent confidence scores and temporal validity. The adversary-capability link might be confidence 0.9 (observed in multiple incidents), while the adversary-victim link might be confidence 0.4 (single report, unconfirmed).

## LLM Quick Reference

ThreatRecall uses a two-layer quality model. Epistemic tiers (A/B/C) classify intelligence by source reliability: A=authoritative (CISA, MITRE, vendor-confirmed), B=operational (threat reports, incident notes, default for remember()), C=support (LLM-extracted causal triples, unverified correlations). Confidence scores (0.0-1.0) provide continuous quality measurement on every note, entity, and TypeDB relationship — a uses relation between APT28 and Cobalt Strike might carry confidence 0.85 while a speculative attribution carries 0.3. Confidence decays on evolution: each time a note is superseded, confidence caps at 0.95 and evolution_count increments; notes with evolution_count >= 5 trigger should_flag_for_review(). The synthesize() method accepts tier_filter (default ["A", "B"]) controlling which quality tiers contribute to RAG answers — tier C is excluded by default, meaning LLM-extracted inferences don't appear in synthesis unless explicitly requested. The BlendedRetriever can weight results by confidence in addition to relevance, ensuring high-confidence direct relationships rank above low-confidence inferred ones. Configuration: default tier for new notes is B (Metadata.tier default), configurable per note. Confidence on TypeDB relations is a double attribute constrained to 0.0-1.0 in the STIX schema.
