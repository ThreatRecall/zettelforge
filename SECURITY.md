# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues by email to:

**security@zettelforge.dev**

Include in your report:
- A description of the vulnerability and its potential impact
- Steps to reproduce the issue or a proof-of-concept
- The affected version(s)
- Any suggested mitigations you have identified

### Response SLA

| Stage | Target |
|---|---|
| Acknowledgement | Within 48 hours of receipt |
| Initial assessment (severity + scope) | Within 5 business days |
| Fix or mitigation available | Within 30 days for Critical/High, 90 days for Medium/Low |
| Public disclosure | Coordinated with reporter after fix is available |

If you have not received a response within 48 hours, follow up at the
same address with "SECURITY FOLLOW-UP" in the subject line.

We follow responsible disclosure: we will coordinate public disclosure
timing with you and credit you in the advisory unless you prefer to
remain anonymous.

---

## Supported Versions

Security fixes are applied to the current release and, where feasible,
backported to the prior minor release.

| Version | Supported |
|---|---|
| 2.1.x (current) | Yes — active security support |
| 2.0.x | Critical fixes only, for 60 days after 2.1.0 release |
| < 2.0 | No — upgrade required |

---

## Security Scope

### In Scope

The following components are covered by this policy:

- **Memory pipeline** — `remember()`, `recall()`, `synthesize()`, and
  the two-phase extraction pipeline
- **Storage layer** — JSONL notes store, LanceDB vector index, entity
  index, knowledge graph JSONL
- **MCP server** — all tool handlers exposed to Claude Code and other
  MCP clients
- **REST API** — all FastAPI endpoints in `src/zettelforge/server.py`
  and the ThreatRecall web UI
- **Authentication** — JWT/OAuth handling, `THREATENGRAM_LICENSE_KEY`
  validation, edition gating
- **Governance** — `GovernanceValidator`, OCSF audit event emission,
  `structlog` configuration
- **Configuration** — layered config resolution (env vars, YAML,
  defaults), secrets handling
- **Enterprise features** — TypeDB integration, multi-tenant auth,
  OpenCTI sync

### Out of Scope

- Issues in third-party dependencies (report these upstream; we will
  upgrade promptly if a dependency is affected)
- Vulnerabilities requiring physical access to the host machine
- Social engineering attacks
- Issues in documentation only (no code path affected)
- The LOCOMO benchmark tooling in `benchmarks/`

---

## Known Security Architecture

### Data at Rest

- Notes are stored as JSONL on local disk. No encryption at rest is
  applied by ZettelForge itself — encrypt the filesystem or volume at
  the OS level for sensitive deployments.
- LanceDB vector index files are stored in the configured data directory
  and carry the same recommendation.

### Injection Defenses

- As of v2.1.1, all LanceDB query expressions are parameterized.
  String-interpolated queries were present in v2.1.0 and earlier
  (see CVE advisory, if issued, or CHANGELOG v2.1.1 P0-3).

### File Locking

- As of v2.1.1, all JSONL and entity index write paths use
  `fcntl.flock()` exclusive locks to prevent concurrent-write corruption.

### Audit Logging

- All security-relevant operations emit OCSF v1.3 structured events via
  `structlog`. Authorization decisions, API activity, and file activity
  are auditable in any SIEM that ingests JSON logs.

### Air-Gap Deployments

- ZettelForge supports fully offline operation (fastembed ONNX +
  llama-cpp-python). No telemetry or external calls are made in this
  configuration.

---

## Disclosure Policy

ZettelForge follows a coordinated disclosure model:

1. Reporter submits vulnerability privately via email.
2. We acknowledge within 48 hours and begin assessment.
3. We develop and test a fix on a private branch.
4. We notify the reporter when a fix is ready and agree on a disclosure date.
5. We release the fix and publish a security advisory simultaneously.
6. We credit the reporter in the advisory (unless they opt out).

We ask reporters to give us a reasonable time to fix issues before
public disclosure. We will not take legal action against good-faith
security researchers who follow this policy.
