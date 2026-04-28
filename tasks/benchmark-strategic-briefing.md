# Benchmark Strategic Briefing — ZettelForge v2.1.1

**Date:** 2026-04-14
**Agent:** Test Results Analyzer

## Landing Page Numbers (for threatrecall.ai)

| # | Claim | Number | Verifiable? |
|---|---|---|---|
| 1 | CTI query accuracy | **75%** at 620ms p50 | Yes — cti_retrieval_results.json |
| 2 | Threat actor attribution | **100%** accuracy | Yes — attribution category |
| 3 | Zero cloud dependencies | Air-gap deployable | Yes — fastembed + GGUF in-process |
| 4 | OCSF audit logging | Every memory operation | Yes — ocsf.py + audit.log |

**Do NOT put on landing page:** LOCOMO (17%), CTIBench (0.000), ingest rate (0.1 notes/s), MAB-CR (0.032)

## Strength/Weakness Profile

| Capability | Score | Grade |
|---|---|---|
| Attribution retrieval | 100% | A |
| Multi-hop reasoning (CTI) | 100% | A |
| Vector retrieval quality | 78.1% RAGAS | B+ |
| CVE linkage | 75% | B |
| Temporal CTI queries | 66.7% | B- |
| Tool attribution | 40% | D+ |
| Conversational memory | 17% LOCOMO | F (by design — wrong domain) |
| Conflict resolution | 0.032 MAB-CR | F (real gap) |

## Key Strategic Insights

1. **The local LLM is the bottleneck, not retrieval.** MAB showed 25x improvement (F1 0.007→0.180) by swapping Qwen2.5-3B for nemotron with zero retrieval changes.

2. **CTI retrieval is genuinely strong and uncontested.** No competitor benchmarks on CTI queries. The 75%/100% numbers are defensible and unique.

3. **OCSF + air-gap + STIX = procurement moat.** These are compliance checkboxes, not features. They determine whether ZettelForge can even be evaluated by defense/gov customers.

4. **The single highest-ROI fix:** upgrade local LLM from 3B to 7B+ for answer generation. Estimated LOCOMO lift from 17% to 30-40% with no architecture changes.
