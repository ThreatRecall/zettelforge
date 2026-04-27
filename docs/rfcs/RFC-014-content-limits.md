# RFC-014: Content Size Limits and Recall Timeout for Denial of Service Mitigation

## Metadata

- **Author**: Patrick Roland
- **Status**: Draft
- **Created**: 2026-04-25
- **Last Updated**: 2026-04-25
- **Reviewers**: TBD
- **Related Tickets**: ZF-014
- **Related RFCs**: RFC-013 (PII Detection), RFD-001 (threat model)

## Summary

Add configurable content size limits to `remember()` and a configurable timeout to `recall()` to mitigate denial-of-service threats identified in THREAT_MODEL.md: D-01 (large content exhausting memory or blocking the enrichment queue) and D-03 (malicious queries triggering deep graph traversal). Introduce a new `limits` config section under `governance` with `max_content_length` and `recall_timeout_seconds` fields. Defaults preserve backward compatibility.

## Motivation

The THREAT_MODEL.md (THREAT-001, Section 2.5) identifies two denial-of-service vectors with no current mitigation:

**D-01 (Large Content, HIGH):** `remember()` accepts content of arbitrary length. A 100MB input would:
- Block the enrichment queue (maxsize=500 with no per-item size limit)
- Exhaust memory during embedding (fastembed loads the entire input)
- Block the `remember()` call for minutes during embedding
- Potentially crash the process on low-memory systems

**D-03 (Deep Graph Traversal, MEDIUM):** `recall()` with a crafted query could trigger deep BFS traversal in the knowledge graph, taking seconds to minutes to resolve. With `max_graph_depth: 2` this risk is limited, but no hard timeout exists.

Both are standard "defense in depth" controls per FedRAMP SI-10 (Information Input Validation) and SA-8 (Security Engineering Principles). The default values are generous enough to never affect legitimate use but provide a hard stop for abuse or accidents.

## Proposed Design

### Config Schema

New `limits` subsection under `governance`:

```yaml
governance:
  enabled: true
  min_content_length: 1
  limits:
    max_content_length: 52428800    # 50 MB default, 0 = unlimited
    recall_timeout_seconds: 30.0    # 30 seconds default, 0 = unlimited
  pii:
    enabled: false
```

The 50 MB default is chosen because:
- Largest real-world CTI report ingested is ~10 MB (NIST NVD feed, MITRE ATT&CK)
- Embedding 50 MB of text at ~7ms/768-dim chunk takes ~5 seconds
- Any legitimate use case below 50 MB is unaffected
- 0 = unlimited preserves backward compatibility for any edge case

### Dataclass Changes

```python
@dataclass
class LimitsConfig:
    """Operation limits for DoS mitigation (RFC-014).

    Values of 0 disable the limit (unlimited).
    """
    max_content_length: int = 52428800   # bytes, 50 MB
    recall_timeout_seconds: float = 30.0


@dataclass
class GovernanceConfig:
    enabled: bool = True
    min_content_length: int = 1
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    pii: PIIConfig = field(default_factory=PIIConfig)
```

### GovernanceValidator Changes

```python
# In validate_remember()
if self._limits.max_content_length > 0:
    if len(content) > self._limits.max_content_length:
        raise GovernanceViolationError(
            f"Content exceeds max_content_length "
            f"({len(content)} > {self._limits.max_content_length} bytes). "
            f"Increase governance.limits.max_content_length or reduce "
            f"input size."
        )
```

### recall() Timeout Integration

```python
# In MemoryManager.recall()
# Wrap the entire recall pipeline with a ThreadPoolExecutor timeout
timeout = get_config().governance.limits.recall_timeout_seconds
if timeout > 0:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(self._recall_inner, ...)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            log warning, return []
return self._recall_inner(...)
```

### Environment Variables

```python
if v := os.environ.get("ZETTELFORGE_LIMITS_MAX_CONTENT_LENGTH"):
    cfg.governance.limits.max_content_length = int(v)
if v := os.environ.get("ZETTELFORGE_LIMITS_RECALL_TIMEOUT"):
    cfg.governance.limits.recall_timeout_seconds = float(v)
```

### File Changes

| File | Change |
|------|--------|
| `src/zettelforge/config.py` | Add `LimitsConfig` dataclass; add `limits` to `GovernanceConfig`; env overrides |
| `src/zettelforge/governance_validator.py` | Add content length check in `validate_remember()` |
| `src/zettelforge/memory_manager.py` | Wire recall timeout into `recall()` / `BlendedRetriever` calls |
| `config.default.yaml` | Document `governance.limits` section |
| `tests/test_governance.py` | Add tests for content size limit |
| `docs/THREAT_MODEL.md` | Update D-01/D-03 to "mitigated" |
| `docs/rfcs/RFC-014-content-limits.md` | New RFC |

## Migration

**Existing users:** Zero config changes. `limits.max_content_length` defaults to 50 MB. `limits.recall_timeout_seconds` defaults to 30 seconds. Existing data is never re-validated — limits apply only to new `remember()` / `recall()` calls.

**Users who hit the limit:** Set `limits.max_content_length: 0` or `limits.recall_timeout_seconds: 0` in config to disable the limit.

## Alternatives Considered

**Alternative 1: Separate section instead of nested under governance.** A top-level `limits:` section was considered. Rejected because: the content size limit is conceptually a governance validation (input validation per GOV-011 / SI-10) and belongs with other governance controls. The recall timeout is a performance protection but benefits from colocation.

**Alternative 2: No limit, rely on OS-level ulimit.** Rejected because: embedded systems and containerized deployments may have high ulimits. A process-level crash is worse than a graceful GovernanceViolationError.

## Decision

**Decision**: [Pending review]
**Date**: [Pending]
**Decision Maker**: [Pending]
**Rationale**: [Pending]
