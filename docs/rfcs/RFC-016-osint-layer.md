# RFC-016: ZettelForge OSINT Layer

## Status (2026-06-08)

**Phase 1 (Infrastructure): functional. Phase 1.5: executor, resolver wiring, and passive BGP lookup shipped. Phases 2-5 remain declared/stubbed.**
Branch: `rfc/osint-layer-scaffold` (PR #147 amended).

What ships:

- **Ontology** — Phase 1-5 entity and edge declarations, all using the
  ``from_types`` / ``to_types`` shape that ``OntologyValidator`` actually
  validates against. Auto-merged into the global ``ENTITY_TYPES`` /
  ``RELATION_TYPES`` at import time.
- **Phase 1 collectors (functional)** — ``dns_collector`` (A/AAAA/NS/MX),
  ``whois_collector`` (domain + IP RDAP), ``cert_collector`` (crt.sh), plus
  the passive ``bgp_collector`` for ASN prefix lookups. All sync, all mocked
  in tests, no network at test time.
- **Phase 1.5 executor + resolver wiring** — ``run_osint_collection`` drives
  registry discovery, ontology validation, canonicalization, and KG
  persistence through ``entity_resolver`` and ``KnowledgeGraph``.
  ``port_scanner`` remains gated behind ``ZETTELFORGE_OSINT_ACTIVE_SCAN``;
  later Phase 2-4 collectors still register as stubs until their API
  integrations land.
- **Tests** — Focused mocked coverage for entity validation, edge
  validation, canonicalization, executor ingest, and passive BGP lookup.
- **Investigation / EntityResolver** — Phase 4 / 1.5 utility scaffolds.

Three deviations from the literal text of this RFC are tracked in
`SCOPING_DOC.md` §0 and reproduced here:

1. **Single `kg_nodes` / `kg_edges` storage** instead of per-type SQLite
   tables (RFC §3 line 19). Reuses the existing `KnowledgeGraph` API; no
   schema migration. Validation happens at the ontology layer
   (`OntologyValidator`), not at the table level.
2. **No CLI surface in this PR** (RFC §10 lists `cli.py` modifications).
   Collectors are importable Python functions; agents and tests call them
   directly. The CLI lands with the workflow engine in Phase 4.
3. **Synchronous collector signatures** instead of `async def` (RFC §5).
   Matches the codebase's existing yara/sigma pipelines (zero `async def`
   today). The Phase 4 workflow engine is the natural place to introduce
   async; sync collectors can be wrapped via `asyncio.to_thread()` then.

## 1. Motivation
ZettelForge currently extracts entities (CVEs, threat actors, IOCs, techniques) from analyst notes and builds a STIX 2.1 knowledge graph. However, it lacks the ability to automatically enrich these entities with open‑source intelligence (OSINT) data—such as DNS records, WHOIS, certificate transparency, social‑media profiles, technology fingerprints, and breach data—that is essential for modern threat investigations.

This RFC defines a schema‑first, composable OSINT layer that plugs cleanly into the existing ZettelForge ontology and knowledge‑graph storage, enabling investigators to pivot from a single IOC to a full infrastructure map with minimal effort. It also introduces an **agent‑conducted investigation workflow system** so that any LLM agent can run structured, multi‑step investigations as first‑class KG operations.

## 2. Design Principles
- **Agent-native**: Each collector is an async Python function callable by an LLM agent (via the tool system), not just a REST endpoint. Investigation workflows are also callable tools an agent can invoke and drive to completion.
- **Schema-first**: New entity and edge types are declared in the ontology before any collector or workflow is written; the KG validates all incoming data. Every entity type corresponds to a table in the SQLite backend.
- **Composable**: Collectors are standalone functions that emit `(entity_type, entity_value, edge_type, from_entity, properties)` tuples; they can be chained or run in parallel.
- **Local-first**: No mandatory external API dependencies. Free/public sources (crt.sh, DNS, WHOIS, BGPView) are built in first; paid APIs (SecurityTrails, Hunter.io, BuiltWith, etc.) are optional extras.
- **Knowledge‑graph improvements**: The new entity/edge types, resolver, and workflow system directly extend the ZettelForge knowledge graph, enabling richer traversal, more precise retrieval, and agent‑driven investigation sessions.

## 3. New Entity Types

All new types extend the base `ENTITY_TYPES` dictionary in `src/zettelforge/osint/ontology.py`. Each type lists **required** and **optional** fields; unspecified properties are allowed but not validated.

Every entity type maps to a dedicated SQLite table.

### Phase 1 — Infrastructure
| Entity | Required | Optional |
|---|---|---|
| ASNumber | `number` (ASN integer) | `name`, `description`, `org` |
| Netblock | `cidr` (IPv4/IPv6 CIDR string) | `description`, `org`, `country` |
| MXRecord | `priority` (integer), `exchange` (domain) | `ttl` |
| NSRecord | `nsdname` (domain) | `ttl` |
| Port | `number` (1‑65535), `protocol` (`tcp`\|`udp`) | `service`, `banner` |
| Website | `url` (valid URL) | `title`, `status_code`, `server` |
| WebTitle | `title` (page title), `url` | `snippet` |

### Phase 2 — People & Communications
| Entity | Required | Optional |
|---|---|---|
| PhoneNumber | `e164` (international format) | `countrycode`, `citycode`, `areacode`, `lastnumbers`, `type` (mobile\|landline\|voip) |
| TwitterAffiliation | `handle` (without `@`) | `follower_count`, `following_count`, `verified`, `location`, `description` |
| Hashtag | `namespace` (platform, e.g., `twitter`), `name` (without `#`) | `post_count` |
| Alias | `value` (the alias/handle) | `platform`, `confidence` |
| NamechkResult | `platform` (service name), `username` | `available` (boolean), `url_if_taken` |

### Phase 3 — Technical Fingerprinting
| Entity | Required | Optional |
|---|---|---|
| BuiltWithTechnology | `technology` (name), `category` (e.g., `CMS`, `Framework`) | `version`, `confidence` |
| BuiltWithRelationship | `from_tech` (tech name), `to_tech` (tech name), `relationship_type` (`uses`\|`extends`\|`depends_on`) | `confidence` |
| CertificateSubject | `common_name` (CN), `organization` (O), `issuer` | `serial_number`, `not_before`, `not_after`, `sans` |
| SSLPoint | `ip` (IPv4/IPv6), `port` (1‑65535), `protocol` (`tls`\|`ssl`), `certificate_hash` (SHA‑256) | `cipher_suite`, `tls_version` |

### Phase 4 — Investigation Workflows
| Entity | Required | Optional |
|---|---|---|
| Investigation | `investigation_id` (UUID), `name`, `status` (`active`\|`completed`\|`abandoned`), `owner` | `description`, `classification` (e.g., `TLP:AMBER`), `created_at`, `updated_at`, `tags` |
| WorkflowDefinition | `workflow_id` (UUID), `name`, `version` | `description`, `steps` (JSON), `created_at` |
| WorkflowStep | `step_id` (UUID), `workflow_id` (FK), `name`, `order` (integer), `status` (`pending`\|`running`\|`completed`\|`failed`\|`skipped`) | `tool_name`, `input_template` (JSON), `condition`, `retry_count`, `max_retries`, `completed_at`, `result` |
| WorkflowEdge | `from_step_id` (FK), `to_step_id` (FK), `condition` | `label` (e.g., `on_success`, `on_failure`, `on_find`) |

## 4. New Edge Types
Edges are stored as `(from_entity_type, from_value, edge_type, to_entity_type, to_value, properties)`.

### Phase 1 edges
| Edge | From → To | Meaning |
|---|---|---|
| resolves_to | Domain → IPv4Address | DNS A/AAAA record |
| hosts | IPv4Address → Domain | Virtual hosting (reverse DNS or vhosts) |
| ns_for | Domain → NSRecord | Nameserver delegation |
| mx_for | Domain → MXRecord | Mail exchanger record |
| owned_by | Netblock → Organization | WHOIS registrant org |
| part_of_as | IPv4Address → ASNumber | BGP prefix → origin AS |
| delegated_to | NSRecord → IPv4Address | Nameserver host (glue or A record) |
| receives_mail_on | MXRecord → Domain | Inbound mail domain for the MX |
| listens_on | IPv4Address → Port | Service listening on IP:port |
| associated_with | IPv4Address → Netblock | IP belongs to CIDR block |

### Phase 2 edges
| Edge | From → To | Meaning |
|---|---|---|
| has_phone | Person → PhoneNumber | Person's phone number |
| affiliated_with | Person → Organization | Employment or membership |
| located_at | Person/Device → Location/GPS | Known physical location |
| has_handle | Person → Alias | Online handle/username |
| verified_on | Alias → Platform | Alias verified on given platform |
| uses_platform | Person → TwitterAffiliation | Person operates Twitter account |
| hashtags | Tweet → Hashtag | Hashtags used in tweet |
| mentions | Tweet → Person/Alias/URL | @mentions or URL links in tweet |

### Phase 3 edges
| Edge | From → To | Meaning |
|---|---|---|
| powered_by | Domain → BuiltWithTechnology | Detected technology on website |
| powered_by_relationship | BuiltWithTechnology → BuiltWithTechnology | Tech stack relationships (e.g., WordPress → PHP) |
| issued_cert | Organization → CertificateSubject | Org issued the certificate |
| terminates_tls | IPv4Address → SSLPoint | TLS endpoint on IP:port |
| has_certificate | Domain → CertificateSubject | Domain name in certificate SAN/CN |

### Phase 4 edges (Investigation Workflows)
| Edge | From → To | Meaning |
|---|---|---|
| contains | Investigation → any entity | Entity is part of this investigation |
| follows | Investigation → WorkflowDefinition | Investigation is an instance of a workflow template |
| executed_step | Investigation → WorkflowStep | Step was executed as part of this investigation |
| next_step | WorkflowStep → WorkflowStep | Sequencing edge between steps (conditional on result) |
| generated | WorkflowStep → any entity | Step output a KG entity |

## 5. Transform / Collector Architecture

Each collector is an `async def` function with a strict type signature:

```python
async def collect(
    input_entity: str,
    input_value: str,
) -> list[
    tuple[
        str,  # output_entity_type
        str,  # output_entity_value
        str,  # edge_type
        str,  # from_entity_type (same as input)
        str,  # to_entity_type
        dict, # properties on the output entity
        dict, # properties on the edge
    ]
]:
    ...
```

### Registry layout
```
src/
  zettelforge/
    osint/
      __init__.py
      ontology.py             # <-- new entity/edge types
      transform_registry.py   # <-- registers collectors
      collectors/
        __init__.py
        infrastructure/
          dns_collector.py       # A/AAAA, NS, MX, TXT, PTR
          whois_collector.py     # WHOIS lookup (ipwhois, python-whois)
          cert_collector.py      # crt.sh certificate transparency
          bgp_collector.py       # ASN, prefix, peer data (BGPView, Team Cymru)
          port_scanner.py        # nmap‑style service discovery (optional, local-only)
        people/
          hunter_collector.py    # Email → person/social (Hunter.io)
          holehe_collector.py    # Email → social accounts (holehe)
          namechk_collector.py   # Username → availability (namechk.com)
        tech/
          wappalyzer_collector.py# Tech stack (Wappalyzer database/API)
          builtwith_collector.py # BuiltWith lookup
```

Each collector registers itself in the registry with metadata:

```python
TRANSFORM_REGISTRY.register(
    name="dns_a",
    description="Resolve domain to IPv4/IPv6 addresses",
    input_types=["Domain"],
    output_types=[("IPv4Address", "resolves_to"), ("IPv6Address", "resolves_to")],
    api_dependencies=[],          # uses system resolvers / public DNS
    rate_limit=None,              # local/unbounded unless external API used
)
```

### Execution flow
1. Agent calls `zettelforge osint collect --input-type Domain --input-value example.com`.
2. Registry finds all collectors declaring `Domain` as input.
3. Each collector runs (with concurrency limit) and returns tuples.
4. Tuples are fed to the KG via `add_node()` / `add_edge()` with automatic deduplication.
5. The agent receives a summary of new entities/edges created.

## 6. Entity Resolution
Duplicate entities are merged using a canonical key:

- **Canonical key**: `(entity_type, normalized_value)`
  - `IPv4Address`: `"1.2.3.4"` (no leading zeros)
  - `Domain`: lowercased, stripped trailing dot
  - `PhoneNumber`: E.164 format (`+15551234567`)
  - `ASNumber`: `"AS12345"` or just integer `12345`
  - `Netblock`: CIDR string (`"192.168.0.0/24"`)

An **Alias index** maps alternate representations (e.g., `www.example.com` → `example.com`) to the canonical node ID.

**Merge strategy**:
- Properties: newest write wins (LWW)
- Edges: accumulate (union of edge sets)
- Timestamps: `updated_at` set to `max(existing, incoming)`

## 7. Agent-Conducted Investigation Workflows

### Overview
The investigation workflow system allows an LLM agent to run structured, multi‑step investigation sessions as first‑class knowledge‑graph operations. A workflow is defined once as a `WorkflowDefinition`, then instantiated as an `Investigation` that the agent drives forward step by step.

### Workflow Definition
A workflow is defined as an ordered list of steps. Each step specifies:
- `tool_name`: the collector or function to call (e.g., `dns_collector`, `whois_collector`)
- `input_template`: JSON dict mapping step input to a source entity in the investigation context (e.g., `{"domain": "$trigger.domain"}`)
- `condition`: optional JS‑like expression for conditional branching (e.g., `result.ip_count > 0`)
- `max_retries`: integer, defaults to 2
- `on_success`: step ID to jump to on success (default: next step)
- `on_failure`: step ID to jump to on failure (default: abort investigation)

Example `WorkflowDefinition`:
```json
{
  "workflow_id": "uuid-v4",
  "name": "Infrastructure Reconnaissance",
  "version": "1.0",
  "description": "Passive infrastructure enrichment from a domain seed",
  "steps": [
    {
      "step_id": "step-1",
      "name": "DNS Resolution",
      "order": 1,
      "tool_name": "dns_collector",
      "input_template": {"entity_type": "Domain", "value": "$trigger.value"},
      "max_retries": 2,
      "on_success": "step-2",
      "on_failure": null
    },
    {
      "step_id": "step-2",
      "name": "WHOIS Lookup",
      "order": 2,
      "tool_name": "whois_collector",
      "input_template": {"entity_type": "Domain", "value": "$trigger.value"},
      "condition": "result.has_whois",
      "max_retries": 2,
      "on_success": "step-3",
      "on_failure": "step-3"
    },
    {
      "step_id": "step-3",
      "name": "Certificate Transparency",
      "order": 3,
      "tool_name": "cert_collector",
      "input_template": {"entity_type": "Domain", "value": "$trigger.value"},
      "max_retries": 2,
      "on_success": null,
      "on_failure": null
    }
  ]
}
```

### Workflow Engine API (agent-callable tools)
```python
# Start a new investigation from a seed entity
zettelforge investigation create \
  --name "APT29 Infrastructure Hunt" \
  --seed-type Domain --seed-value evil.com \
  --workflow infrastructure-recon-v1

# List active investigations
zettelforge investigation list --status active

# Show current step and pending steps for an investigation
zettelforge investigation status --iid <uuid>

# Agent drives the next step (calls the tool, receives result, engine advances)
zettelforge investigation step --iid <uuid>

# Agent manually advances with a custom result (for reasoning agents)
zettelforge investigation advance --iid <uuid> --step-id <step-id> --result <json>

# Add a related entity to an active investigation
zettelforge investigation add --iid <uuid> --entity-type IPv4Address --value 1.2.3.4

# Complete and archive an investigation
zettelforge investigation close --iid <uuid> --outcome "attributed-to-apt29"

# Export investigation KG as JSON/CSV for reporting
zettelforge investigation export --iid <uuid> --format json
```

### Agent Workflow Session Example
```
Agent: "Start an infrastructure investigation on evil.com using the passive-recon workflow."
System: Investigation created (ID: inv-abc123), step 1/3 "DNS Resolution" is next.

Agent: "Run the next step."
System: DNS collector returned 3 IPs (1.2.3.4, 5.6.7.8, 9.10.11.12).
        Step 1 complete. Edge resolves_to added. Step 2 "WHOIS Lookup" is next.

Agent: "Run the next step."
System: WHOIS returned registrant org "Evil Corp". Step 2 complete.
        Step 3 "Certificate Transparency" is next.

Agent: "Run the next step."
System: crt.sh returned 5 certificates. Step 3 complete. Investigation complete.
        8 new entities, 7 new edges added to KG.

Agent: "Export the investigation graph."
System: Exported inv-abc123.json (42 entities, 67 edges).
```

### Workflow State Machine
Each `WorkflowStep` in an active `Investigation` follows this state machine:
```
pending → running → completed
                └→ failed → skipped (if max_retries exceeded)
                └→ skipped (if condition not met)
```

The engine persists step state after each transition. An agent can query the current state at any time and resume from wherever the investigation left off — even across sessions.

### Predefined Workflow Templates (shipped with ZettelForge)
1. `passive-recon` — DNS → WHOIS → Certificate Transparency (Phase 1 entities)
2. `phone-enrichment` — PhoneNumber → Namechk → Hunter.io → Alias resolution
3. `actor-infrastructure` — Given a threat actor, traverse related domains → IPs → ASNs → SSL certs
4. `ioc-triage` — Given any IOC, auto-classify type and run the appropriate collector chain

### Custom Workflow Registration
Analysts can register new workflow definitions via:
```python
from zettelforge.osint import register_workflow

register_workflow("my-workflow", {
    "name": "My Custom Workflow",
    "version": "1.0",
    "steps": [...]
})
```

## 8. Phases & Effort Estimates

| Phase | Goal | Weeks |
|---|---|---|
| **1 Infrastructure** | Add ASNumber, Netblock, MX, NS, Port, Website, WebTitle entities + Phase 1 edges. Implement DNS, WHOIS, crt.sh, BGPView collectors. | 3‑4 |
| **2 People & Comms** | Add PhoneNumber, TwitterAffiliation, Hashtag, Alias, NamechkResult entities + Phase 2 edges. Implement Hunter, holehe, namechk collectors. PhoneNumber extraction from reports works like any other entity type. | 2‑3 |
| **3 Technical** | Add BuiltWithTechnology, BuiltWithRelationship, CertificateSubject, SSLPoint entities + Phase 3 edges. Implement Wappalyzer, BuiltWith collectors. | 2‑3 |
| **4 Investigation Workflows** | Add Investigation, WorkflowDefinition, WorkflowStep, WorkflowEdge entities + Phase 4 edges. Build workflow engine, state machine, agent‑callable CLI tools, predefined templates, and export. | 3‑4 |
| **Total** |  | **≈11‑15 weeks** (can be delivered incrementally per phase) |

## 9. Backward Compatibility
- No existing entity or edge type is modified or removed.
- The OSINT layer lives under `src/zettelforge/osint/`; core KG and ontology imports remain unchanged.
- Phases can be enabled independently; e.g., run only Phase 1 for passive‑only enrichment.

## 10. File Changes

**New files**
```
src/zettelforge/osint/ontology.py
src/zettelforge/osint/transform_registry.py
src/zettelforge/osint/entity_resolver.py
src/zettelforge/osint/workflow_engine.py       # investigation workflow state machine
src/zettelforge/osint/workflow_templates.py    # predefined workflow definitions
src/zettelforge/osint/investigation.py         # Investigation session management
src/zettelforge/osint/collectors/__init__.py
src/zettelforge/osint/collectors/infrastructure/dns_collector.py
src/zettelforge/osint/collectors/infrastructure/whois_collector.py
src/zettelforge/osint/collectors/infrastructure/cert_collector.py
src/zettelforge/osint/collectors/infrastructure/bgp_collector.py
src/zettelforge/osint/collectors/infrastructure/port_scanner.py
src/zettelforge/osint/collectors/people/hunter_collector.py
src/zettelforge/osint/collectors/people/holehe_collector.py
src/zettelforge/osint/collectors/people/namechk_collector.py
src/zettelforge/osint/collectors/tech/wappalyzer_collector.py
src/zettelforge/osint/collectors/tech/builtwith_collector.py
tests/test_osint_entities.py
tests/test_osint_collectors.py
tests/test_workflow_engine.py
tests/test_investigation.py
docs/rfcs/RFC-016-osint-layer.md
```

**Modified files**
- `src/zettelforge/__init__.py` – expose `osint` subpackage
- `src/zettelforge/knowledge_graph.py` – optionally add helper for bulk ingest from collectors
- `src/zettelforge/cli.py` – add `investigation` command group

---
*End of RFC-016*