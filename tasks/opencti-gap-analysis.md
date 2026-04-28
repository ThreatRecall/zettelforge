# OpenCTI vs ZettelForge Data Architecture Gap Analysis

**Date:** 2026-04-14
**Agent:** Data Engineer
**Live OpenCTI:** 114K relationships, 140K indicators, 73K observables, 31K CVEs, 1K ATT&CK patterns

## Critical Finding

ZettelForge cannot represent 99% of the data in the live OpenCTI instance. The dominant workload is IOC indicators (140K) and STIX Cyber Observables (73K hashes, domains, IPs) — none of which have entity types, extractors, or storage in ZettelForge.

## Entity Coverage

| Category | OpenCTI Has | ZettelForge Can Represent | Gap |
|---|---|---|---|
| SDOs (domain objects) | 18 types | 7 types (partial) | 11 missing |
| SCOs (observables) | 12+ types | 0 types | All missing |
| SROs (relationships) | 15+ types | 6 types (TypeDB only) | 9+ missing |

### Biggest Gaps by Analyst Impact

| Gap | OpenCTI Count | Impact |
|---|---|---|
| **Indicators (IOCs)** | 140,060 | Cannot store, extract, or query ANY indicators |
| **Observables (hashes, IPs, domains)** | 73,071 | Cannot store file hashes, IP addresses, domain names |
| **Attack Patterns (ATT&CK)** | 1,094 | No entity type, no extractor, no KG node |
| **Infrastructure (C2 servers)** | 629 | Completely absent |
| **Intrusion Set vs Threat Actor** | 31 vs 13 | Collapsed into single "actor" type — misattribution risk |
| **TLP markings** | On every object | No TLP field — compliance exposure on sync |
| **STIX patterns** | On all indicators | No parser, no storage field |

### What ZettelForge CAN Represent

| Entity | Status |
|---|---|
| Threat actors (partial — hardcoded regex) | Works for ~6 known actors |
| Malware (partial — 7 hardcoded names) | Works for known malware |
| CVEs | Works well — regex reliable |
| Campaigns | Works — "Operation X" regex |
| Reports (as notes) | Works but loses metadata |
| Basic relationships (uses, targets) | TypeDB backend only |

## Priority Fixes

| # | Fix | Impact | Effort |
|---|---|---|---|
| 1 | Add IOC extractors (MD5, SHA256, IPv4, domain, URL regex) | Covers 99% of IOC corpus | 1 day |
| 2 | Add AttackPattern entity + T-code extractor | 1,094 techniques queryable | 0.5 day |
| 3 | Rebuild sync client (relationships, SCOs, dedup) | Prevents duplicate notes, enables full sync | 3 days |
| 4 | Split IntrusionSet from ThreatActor | Prevents misattribution | 0.5 day |
| 5 | Add TLP + STIX confidence to Metadata | Compliance requirement | 0.5 day |
| 6 | Expand Vulnerability fields (CVSS v3/v4, EPSS, CISA KEV) | Analyst prioritization | 0.5 day |
