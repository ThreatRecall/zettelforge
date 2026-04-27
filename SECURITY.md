# Security Policy

## Reporting a Vulnerability

This is a solo-maintainer project. For security-related issues:
- Open a GitHub Security Advisory in the repository
- Tag with `security` label
- Expect acknowledgement within 48 hours

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest release | ✅ |
| master branch | ✅ (CI gates) |
| older releases | ❌ |

## Supply Chain Security

This project implements:
- SHA-pinned GitHub Actions (all third-party actions pinned by commit SHA)
- PyPI trusted publishing (OIDC, no long-lived tokens)
- pip-audit on every CI run (HIGH/CRITICAL must pass)
- Dependabot for weekly dependency updates
- Snyk SAST scanning on every push/PR

## Known Security Architecture

See [THREAT_MODEL.md](docs/THREAT_MODEL.md) for the complete STRIDE threat model.

### Data at Rest

- Notes, the knowledge graph, and the entity index are stored in a local SQLite database (WAL mode) under the configured data directory. No encryption at rest is applied by ZettelForge itself -- encrypt the filesystem or volume at the OS level for sensitive deployments.
- LanceDB vector index files live alongside the SQLite database and carry the same recommendation.

### PII Protection

- As of v2.5.0 (RFC-013), optional PII detection via Microsoft Presidio scans content before `remember()` storage. Three modes: log (discovery), redact (compliance), block (strict). Disabled by default. Requires `pip install zettelforge[pii]` to activate.
- Raw PII text is never written to structured logs. Only entity type and detection score are recorded.

### LLM Provider Security

- Four providers: `local` (in-process, no network), `ollama` (localhost HTTP), `litellm` (cloud APIs), `mock` (testing). Each is configurable via `llm.provider` in config.yaml.
- `local` provider is fully offline. `ollama` runs on localhost only. `litellm` makes outbound HTTPS calls to configured cloud APIs.
- API keys use `${ENV_VAR}` resolution -- never committed to YAML. Redacted from all log output via `LLMConfig.__repr__`.
- Provider timeout is configurable (default 60s). LiteLLM provider supports configurable retry count.

### Injection Defenses

- As of v2.1.1, all LanceDB query expressions are parameterized. String-interpolated queries were present in v2.1.0 and earlier (see CVE advisory, if issued, or CHANGELOG v2.1.1 P0-3).

### File Locking

- As of v2.1.1, all JSONL and entity index write paths use `fcntl.flock()` exclusive locks to prevent concurrent-write corruption.

### Audit Logging

- All security-relevant operations emit OCSF v1.3 structured events via `structlog`. Authorization decisions, API activity, and file activity are auditable in any SIEM that ingests JSON logs.

### Air-Gap Deployments

- ZettelForge supports fully offline operation (fastembed ONNX + llama-cpp-python). No telemetry or external calls are made in this configuration.

## Disclosure Policy

ZettelForge follows a coordinated disclosure model:

1. Reporter submits vulnerability privately via email.
2. We acknowledge within 48 hours and begin assessment.
3. We develop and test a fix on a private branch.
4. We notify the reporter when a fix is ready and agree on a disclosure date.
5. We release the fix and publish a security advisory simultaneously.
6. We credit the reporter in the advisory (unless they opt out).

We ask reporters to give us a reasonable time to fix issues before public disclosure. We will not take legal action against good-faith security researchers who follow this policy.
