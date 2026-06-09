---
title: "Passive OSINT Enrichment"
description: "Run the RFC-016 OSINT executor, persist collector output into the knowledge graph, and keep active scanning gated behind explicit opt-in."
diataxis_type: "how-to"
audience: "Python developers and CTI operators using ZettelForge"
tags: [osint, enrichment, knowledge-graph, dns, whois, bgp, passive-recon]
last_updated: "2026-06-08"
version: "2.7.0"
---

# Passive OSINT Enrichment

ZettelForge ships a passive OSINT executor that runs registered collectors, validates each tuple against the ontology, canonicalizes entity values, and persists nodes and edges into the knowledge graph.

## Install

Install the OSINT extra when you need DNS, WHOIS, or IP/ASN enrichment:

```bash
pip install "zettelforge[osint]"
```

The base package already includes `httpx`, so passive BGPView lookups work with the standard install. The OSINT extra adds `dnspython`, `python-whois`, and `ipwhois` for the DNS and WHOIS collectors.

## Run a passive enrichment

```python
from zettelforge.osint import run_osint_collection

result = run_osint_collection("DomainName", "Example.COM.")
print(result.canonical_input_value)  # example.com
print(result.persisted_count)
print(result.error_count)
```

The executor accepts these seed types: `DomainName`, `IPv4Address`, `IPv6Address`, `ASNumber`, and `Netblock`.

Common passive flows:

- `DomainName` seeds drive DNS, WHOIS, and certificate transparency collectors.
- `IPv4Address` and `IPv6Address` seeds drive WHOIS enrichment.
- `ASNumber` seeds drive passive BGP prefix lookups.

## Dry-run or narrow scope

Pass `persist=False` to validate collector output without writing to the knowledge graph:

```python
from zettelforge.osint import run_osint_collection

result = run_osint_collection("ASNumber", "AS15169", persist=False)
```

Use `collector_names=(...)` when you want to run only specific collectors from the registry.

## Safety controls

Active port scanning stays disabled unless the operator explicitly enables it:

```bash
export ZETTELFORGE_OSINT_ACTIVE_SCAN=1
```

Without that flag, the port scanner returns an empty result and no probe is sent. Keep that flag unset unless you own the target network or have explicit authorization to scan it.

## What gets persisted

The executor writes canonical entity values to the graph, so duplicate spellings collapse onto the same nodes. For example, `AS15169` and `15169` resolve to the same canonical ASN node, and alternate domain spellings register as aliases for the same canonical domain node.

Errors are collected per collector or tuple. A single failing collector does not abort the run.
