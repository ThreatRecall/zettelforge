# CTIBench ATE Low F1 Diagnosis

**Date:** 2026-04-14
**Current F1:** 0.036 (was 0.000 before ATT&CK cross-reference fix)

## Root Causes (4 compounding failures)

1. **Missing ATT&CK matrices (45% of ceiling):** Only enterprise-attack.json loaded. 56% of gold T-codes are Mobile/ICS techniques (T1398, T1404-T1646) — not in the database.
2. **Self-retrieval (severe):** CTI descriptions and technique notes share domain="cti". Query embeds at ~0.99 cosine with its own ingested note, so CTI descriptions outrank technique notes.
3. **k=10 too small:** After self-retrieval fills slots, only 3-5 technique notes reach the results.
4. **Query framing mismatch:** "What ATT&CK techniques..." wrapper pushes embedding into question-space, away from technique description-space.

## Fix Plan

| Fix | Expected F1 Lift | Effort |
|---|---|---|
| Add mobile-attack.json + ics-attack.json | +0.20-0.25 | 30 min |
| Isolate techniques in domain="attack_techniques" | +0.10-0.15 | 1 hour |
| Increase k to 20-30 | +0.05-0.08 | 5 min |
| Query with raw description (no wrapper) | +0.05-0.10 | 30 min |

**Projected F1 after all 4 fixes: 0.30-0.40**
**Ceiling for retrieval-only (no LLM reasoning): ~0.45**
**SOTA LLM generative baseline: 0.45-0.60**
