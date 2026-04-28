# RFC-016 Phase 1 Scoping Document

**Branch**: `feature/rfc-016-osint-layer`
**Status**: Decisions resolved. Implementation in progress.
**Author**: Claude Code, 2026-04-28
**Scope**: Phase 1 (Infrastructure) only. Phases 2-4 deferred.

---

## 0. Resolved decisions

The original draft of this doc raised three open questions in §2 (storage model, CLI location, async vs sync). The owner has resolved all three:

| # | Question | Decision | Source |
|---|---|---|---|
| 1 | Per-type SQLite tables or single `kg_nodes`? | **Single `kg_nodes`** (Option A). Reuse existing `KnowledgeGraph.add_node()` / `add_edge()` API. No SQLite migration. | Owner instruction: "Keep the single kg_nodes/kg_edges table approach already in the codebase. Do NOT use per-type tables." |
| 2 | Where does the CLI live? | **No CLI in Phase 1.** Collectors are importable Python functions under `src/zettelforge/osint/`. Agent invokes them via direct import. A CLI can be added in a follow-up if/when needed. | Owner instruction: "Do NOT add a CLI layer unless the codebase already has one." (The codebase has per-subpackage CLIs for sigma/yara, but no top-level cli.py and the task list does not include a new CLI file.) |
| 3 | Async or sync collector signatures? | **Sync.** The codebase has zero `async def` / `import asyncio` usage today. Sync matches existing yara/sigma pipelines and keeps tests deterministic. Async migration path is documented as a Phase 4 (workflow engine) concern. | Owner instruction: "Match whatever the codebase uses. If existing collectors/codebase is sync, use sync for Phase 1 with a documented async migration note." |

These three decisions deviate from the literal text of RFC-016 §3, §5, and §10. The deviations are tracked in the RFC status block (see §6 below).

---

## 1. What Phase 1 actually delivers

Per RFC-016 §3 and §4, Phase 1 covers the Infrastructure tier:

- **7 new entity types**: `ASNumber`, `Netblock`, `MXRecord`, `NSRecord`, `Port`, `Website`, `WebTitle`
- **1 supporting entity type**: `IPv6Address` (parity with existing `IPv4Address`)
- **10 new edge types**: `resolves_to`, `hosts`, `ns_for`, `mx_for`, `owned_by`, `part_of_as`, `delegated_to`, `receives_mail_on`, `listens_on`, `associated_with`
- **3 collectors**: `dns_collector`, `whois_collector`, `cert_collector`
- **1 transform registry** with `register()` / `find_by_input()` / `get()` / `list_all()`
- **2 test files**: entity validation + canonicalization, collector smoke tests with mocks

Phase 1 does NOT include: BGPView collector, port scanner, entity resolver, workflow engine, investigation sessions, CLI command. Those are listed in §10 of the RFC and are out of scope here.

---

## 2. How RFC-016 lines up against the existing codebase

### Single `kg_nodes` / `kg_edges` is canonical

`src/zettelforge/sqlite_backend.py:83-110` defines exactly two graph tables:

- `kg_nodes(node_id, entity_type, entity_value, properties JSON, created_at, updated_at)`
- `kg_edges(edge_id, from_node_id, to_node_id, relationship, edge_type, properties JSON, ...)`

`src/zettelforge/knowledge_graph.py` exposes the JSONL-shape API. Both backends are interchangeable through the same node/edge interface. Per-type-field validation is handled at the ontology layer (`OntologyValidator.validate_entity()`), not at the table level. OSINT additions therefore only touch:

- `ENTITY_TYPES` and `RELATION_TYPES` reference dicts in `src/zettelforge/ontology.py` (or a parallel dict that gets merged)
- New collector modules under `src/zettelforge/osint/`

No DDL changes. No schema migration.

### No top-level `cli.py` exists

`src/zettelforge/sigma/cli.py` and `src/zettelforge/yara/cli.py` are per-module entry points invoked via `python -m zettelforge.<module>.cli`. There is no `src/zettelforge/cli.py`, and `src/zettelforge/__main__.py` only routes to `demo` and `version`. Per the owner's task instructions, Phase 1 ships **without** a CLI surface; agents and tests import collectors directly.

### Codebase is fully synchronous

`grep -rE "async def|import asyncio" src/zettelforge` returns zero matches. Phase 1 collectors will follow this convention.

---

## 3. Phase 1 entity → schema mapping

New types live in `src/zettelforge/osint/ontology.py` as a parallel dict `OSINT_ENTITY_TYPES`. A merge helper (`merge_into_global_ontology()`) is called at import time from `osint/__init__.py` so the global `ENTITY_TYPES` validator picks them up. This keeps OSINT additions isolated and reversible.

`entity_value` (canonical KG key) is required for every node. For multi-field entities, we synthesize the canonical value from the most-identifying field; the rest live in `properties`. This matches how `Vulnerability` (cve_id) and `IPv4Address` (value) are handled today.

| Entity | `entity_value` (canonical) | `required` props | `optional` props | Notes |
|---|---|---|---|---|
| `ASNumber` | integer ASN as string (e.g., `"15169"`) | `number` | `name`, `description`, `org` | Strip leading `AS` if present. Validated as positive integer. |
| `Netblock` | CIDR (e.g., `"8.8.8.0/24"`) | `cidr` | `description`, `org`, `country` | IPv4 + IPv6. Canonicalized via `ipaddress.ip_network`. |
| `MXRecord` | `f"{priority} {exchange}"` (e.g., `"10 mail.example.com"`) | `priority`, `exchange` | `ttl` | Composite mirrors DNS zone-file syntax. Exchange lowercased, no trailing dot. |
| `NSRecord` | `nsdname` (lowercased domain, no trailing dot) | `nsdname` | `ttl` | NS records are unique per name. |
| `Port` | `f"{number}/{protocol}"` (e.g., `"443/tcp"`) | `number`, `protocol` | `service`, `banner` | Protocol enum: `tcp` or `udp`. Number 1-65535. |
| `Website` | normalized URL (e.g., `"https://example.com/"`) | `url` | `title`, `status_code`, `server` | Trailing slash for root path. Lowercase scheme + host. |
| `WebTitle` | `f"{url}::{title}"` truncated to 256 chars | `title`, `url` | `snippet` | Composite to keep `(WebTitle, value)` unique per URL+title pair. |
| `IPv6Address` | RFC 5952 compressed form (e.g., `"2001:db8::1"`) | `value` | `belongs_to_ref`, `resolves_to_refs` | Symmetric with existing `IPv4Address`. |

**Validation**: Each entry uses the existing `ENTITY_TYPES` schema (`required` / `optional` / `properties` keys). The `OntologyValidator.validate_entity()` method already enforces required fields. Enum-style validation for `Port.protocol` uses the existing `enum_properties` mechanism in the validator.

### Edge mapping

New edges added to `OSINT_RELATION_TYPES` in `osint/ontology.py`, then merged into the global `RELATION_TYPES` at import.

| Edge | from_types | to_types | Cardinality |
|---|---|---|---|
| `resolves_to` | `DomainName` | `IPv4Address`, `IPv6Address` | many_to_many |
| `hosts` | `IPv4Address` | `DomainName` | many_to_many |
| `ns_for` | `DomainName` | `NSRecord` | many_to_many |
| `mx_for` | `DomainName` | `MXRecord` | many_to_many |
| `owned_by` | `Netblock`, `DomainName` | `Organization` | many_to_one |
| `part_of_as` | `IPv4Address`, `IPv6Address`, `Netblock` | `ASNumber` | many_to_one |
| `delegated_to` | `NSRecord` | `IPv4Address`, `IPv6Address` | many_to_many |
| `receives_mail_on` | `MXRecord` | `DomainName` | many_to_many |
| `listens_on` | `IPv4Address`, `IPv6Address` | `Port` | many_to_many |
| `associated_with` | `IPv4Address`, `IPv6Address` | `Netblock` | many_to_one |

**Reused existing types**: `IPv4Address`, `DomainName`, `EmailAddress`, `Organization` (defined in `src/zettelforge/ontology.py:205-228`). We do not redefine them. `IPv6Address` is the only addition to the core ontology file.

---

## 4. Collector specs

All Phase 1 collectors share a single signature:

```python
def collect(
    input_entity_type: str,
    input_value: str,
) -> list[CollectorTuple]
```

Where `CollectorTuple` is a `NamedTuple` defined once in `transform_registry.py` with fields:

```
(output_entity_type, output_value, edge_type, from_entity_type, to_entity_type, output_props, edge_props)
```

This matches the RFC §5 tuple shape and gives readable named-field access in collector bodies.

### 4.1 `dns_collector.py` — anchor implementation

**Inputs accepted**: `DomainName` only in Phase 1.

**Behavior**:
1. Use `dns.resolver.Resolver` (from `dnspython`) with a configurable timeout (default 5s, single retry).
2. Query A, AAAA, NS, MX records. TXT skipped in Phase 1 (no entity type for it yet).
3. Emit one tuple per record:
   - A → `(IPv4Address, ip, "resolves_to", DomainName, IPv4Address, {}, {ttl})`
   - AAAA → `(IPv6Address, ip, "resolves_to", DomainName, IPv6Address, {}, {ttl})`
   - NS → `(NSRecord, nsdname, "ns_for", DomainName, NSRecord, {ttl}, {})`
   - MX → `(MXRecord, "{priority} {exchange}", "mx_for", DomainName, MXRecord, {priority, exchange, ttl}, {})`
4. NXDOMAIN, NoAnswer, Timeout return empty list (no exception). Other network errors propagate.

**Dependencies**: `dnspython` (already importable in this environment). Listed under a new `[project.optional-dependencies] osint = [...]` group in `pyproject.toml` (deferred — not strictly required for tests since they mock the resolver).

**Test strategy**: Mock `dns.resolver.Resolver.resolve()` with `unittest.mock` to return fixed records. No real DNS calls in tests.

### 4.2 `whois_collector.py`

**Inputs accepted**: `DomainName`, `IPv4Address`.

**Behavior**:
- For domains: `python-whois` → emit `Organization` (registrant), edge `owned_by` from input domain to Organization.
- For IPs: `ipwhois` → emit `Netblock` (CIDR from prefix), `Organization` (registrant), `ASNumber` (origin AS). Edges: `associated_with` (IP→Netblock), `owned_by` (Netblock→Org), `part_of_as` (IP→ASNumber).
- Failures (rate-limited, parse error, library missing) return empty list and log a warning. No retries in Phase 1.

**Dependencies**: `python-whois`, `ipwhois`. Both are NOT installed in this environment. The collector handles `ImportError` gracefully (logs + returns []), so the module loads fine without them. Tests inject fake whois/ipwhois objects to drive the parser branches.

### 4.3 `cert_collector.py`

**Inputs accepted**: `DomainName`.

**Behavior**:
1. Query crt.sh JSON API: `https://crt.sh/?q=<domain>&output=json`.
2. Use `httpx.Client` (already a core dep) with 10s timeout.
3. For each unique cert, emit:
   - SAN domains as `DomainName` entities — edge `related_to` from input domain (we don't have `has_certificate` until Phase 3, so use the existing generic `related_to`).
4. Limit to 200 most recent certs to bound output.

**Phase boundary**: `CertificateSubject` and `SSLPoint` are Phase 3 entities. Phase 1's cert collector only enumerates SAN domains and emits domain-to-domain `related_to` edges. The full cert subject record waits for Phase 3.

---

## 5. Transform registry

`src/zettelforge/osint/transform_registry.py` exposes a global `TRANSFORM_REGISTRY` singleton.

```python
@dataclass(frozen=True)
class TransformMetadata:
    name: str
    description: str
    input_types: tuple[str, ...]
    output_types: tuple[tuple[str, str], ...]   # (entity_type, edge_type)
    api_dependencies: tuple[str, ...]
    rate_limit: float | None                    # calls per second; None = unbounded


class TransformRegistry:
    def register(self, metadata, fn) -> None: ...
    def find_by_input(self, input_type: str) -> list[tuple[TransformMetadata, Callable]]: ...
    def get(self, name: str) -> tuple[TransformMetadata, Callable]: ...
    def list_all(self) -> list[TransformMetadata]: ...
```

Collectors register themselves at import time. Re-registering the same name is a no-op (idempotent), which keeps repeated test imports safe.

---

## 6. File-by-file change list

### New files

| File | Purpose | LoC est. |
|---|---|---|
| `src/zettelforge/osint/__init__.py` | Re-export public API; trigger collector module imports for self-registration; merge OSINT ontology into global. | 40 |
| `src/zettelforge/osint/ontology.py` | `OSINT_ENTITY_TYPES` (8 types incl. IPv6Address), `OSINT_RELATION_TYPES` (10 edges), canonicalization helpers, merge functions. | 220 |
| `src/zettelforge/osint/transform_registry.py` | `TransformMetadata`, `TransformRegistry`, `CollectorTuple` NamedTuple, global singleton. | 110 |
| `src/zettelforge/osint/collectors/__init__.py` | Empty marker. | 1 |
| `src/zettelforge/osint/collectors/infrastructure/__init__.py` | Imports each collector module to trigger registration. | 8 |
| `src/zettelforge/osint/collectors/infrastructure/dns_collector.py` | DNS A/AAAA/NS/MX collector, sync, dnspython. | 160 |
| `src/zettelforge/osint/collectors/infrastructure/whois_collector.py` | Domain + IP WHOIS, ASN extraction. Graceful import failures. | 180 |
| `src/zettelforge/osint/collectors/infrastructure/cert_collector.py` | crt.sh SAN enumeration. | 110 |
| `tests/test_osint_entities.py` | Entity validation, edge constraint validation, value canonicalization, ontology merge. | 220 |
| `tests/test_osint_collectors.py` | Mocked DNS/WHOIS/crt.sh collectors, registry dispatch. | 240 |

**Total new code**: ~1,290 LoC across 10 files.

### Modified files

| File | Change | Risk |
|---|---|---|
| `src/zettelforge/__init__.py` | Add `from zettelforge import osint` (side-effect import to trigger registration). Optionally export `osint` symbol in `__all__`. | Low. Additive. |
| `src/zettelforge/ontology.py` | Add `IPv6Address` entry to `ENTITY_TYPES`. Symmetric to existing `IPv4Address`. | Low. New type, no removal. |
| `docs/rfcs/RFC-016-osint-layer.md` | Add a status header marking Phase 1 as "In Progress (started 2026-04-28)". Document the 3 deviations from RFC literal text (single kg_nodes table, no Phase 1 CLI, sync collectors). | Low. Doc-only. |

**No changes** to `knowledge_graph.py`, `sqlite_backend.py`, `entity_indexer.py`, `memory_manager.py`, `__main__.py`, or `pyproject.toml` in Phase 1. Optional dependency declarations and CLI wiring are deferred until they are needed.

---

## 7. Effort estimate

| Step | Effort | Notes |
|---|---|---|
| `osint/ontology.py` + `IPv6Address` | 1.5 hr | Schema-only, no I/O |
| `transform_registry.py` | 1 hr | Pure Python |
| `dns_collector.py` + tests | 3 hr | Anchor collector, mocked tests |
| `whois_collector.py` + tests | 3 hr | Two libraries, two code paths, both graceful on `ImportError` |
| `cert_collector.py` + tests | 2 hr | Single HTTP call, easy mocks |
| `__init__.py`, RFC doc updates | 1 hr | |
| Buffer for review feedback | 2 hr | |
| **Total** | **≈13 hr (1.5-2 working days)** | Well under the RFC's 3-4 week Phase 1 budget. |

The RFC's 3-4 week estimate covers BGPView + port scanner + entity resolver + a CLI surface. None of those are in Phase 1 as scoped here. They slot into a Phase 1.5.

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Real DNS calls in CI | All tests mock `dns.resolver.Resolver`. No network-touching tests in the default suite. |
| Optional whois deps unavailable | Collectors guard imports with `try/except ImportError`, log a warning, return empty list. Tests inject fakes for both branches. |
| WHOIS rate limits | No retries in Phase 1. Single attempt. Failure → empty list + warning. |
| crt.sh JSON shape changes | Defensive parsing: `.get()` everywhere, type-check before use. Cap output at 200 records. |
| Edge validator rejects new edge types | New edges added to `OSINT_RELATION_TYPES` and merged at import. Verified by `tests/test_osint_entities.py`. |
| Async expectation in workflow engine (Phase 4) | Sync collectors can be wrapped with `asyncio.to_thread()` later. Documented in the RFC deviation note. |
| 709-test baseline regression | Run full suite after each new file. Halt on red. |

---

## 9. Acceptance criteria for "Phase 1 done"

1. `OSINT_ENTITY_TYPES` defines all 7 Phase 1 entity types (+ `IPv6Address`); each round-trips through `OntologyValidator.validate_entity()`.
2. `OSINT_RELATION_TYPES` defines all 10 Phase 1 edges; each round-trips through `OntologyValidator.validate_relation()`.
3. `dns_collector.collect("DomainName", "example.com")` returns ≥1 tuple in mocked tests; tuples shape-conform to `CollectorTuple`.
4. `whois_collector` and `cert_collector` smoke-test against mocked responses, including the missing-library branch.
5. The transform registry returns the right collector(s) for `DomainName` / `IPv4Address` inputs.
6. All 709 pre-existing tests still pass.
7. New tests added: ≥20 in `test_osint_entities.py`, ≥15 in `test_osint_collectors.py`. Both run in <5s on standard hardware (no network).
8. No ruff or mypy regressions in `src/zettelforge/osint/`.
9. RFC-016 status block updated; deviations documented.

---

## 10. Out of scope (deferred to Phase 1.5 / later phases)

- BGPView collector (RFC §5)
- nmap-style port scanner (RFC §5)
- `entity_resolver.py` with E.164 normalization, alias index (RFC §6) — Phase 1 uses naive canonical-value matching via existing `kg_nodes` UNIQUE constraint.
- Async collectors and the workflow engine (RFC §7) — Phase 4.
- Bulk-ingest helper on `KnowledgeGraph` — only if profiling reveals it's needed.
- LLM agent tool integration (MCP wiring) — deferred until at least one workflow exists.
- CLI / `__main__.py` wiring — deferred to a follow-up.
- Container packaging — RFC §10 already defers to vNext per `docs/03-TechStack.md`.

---

*End of SCOPING_DOC.md*
