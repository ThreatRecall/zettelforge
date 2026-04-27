---
title: "Configure PII Detection and Redaction"
description: "Set up Microsoft Presidio for PII detection in ZettelForge. Scan content for personally identifiable information before storage, with configurable log/redact/block policies."
diataxis_type: "how-to"
audience: "Compliance Officer, SOC Manager, FedRAMP Engineer"
tags: [pii, governance, compliance, presidio, privacy, fedramp, gdpr]
last_updated: "2026-04-25"
version: "2.5.0"
---

# Configure PII Detection and Redaction

ZettelForge uses [Microsoft Presidio](https://github.com/microsoft/presidio) (open-source, MIT license) to detect and optionally redact PII (Personally Identifiable Information) from content before it is stored in the vector database and knowledge graph.

PII detection is **disabled by default** with no new core dependencies. It is a fully optional feature -- `pip install zettelforge[pii]` activates it.

## Prerequisites

- ZettelForge installed
- `pip install zettelforge[pii]` to install presidio-analyzer, presidio-anonymizer, and spaCy
- About ~12-50 MB of disk space for the spaCy model (auto-downloads on first use)

## How It Works

Presidio runs **in-process** as a validation step inside `GovernanceValidator`, invoked before every `remember()` operation:

```
remember(content)
  -> GovernanceValidator.validate_remember(content)
    -> PIIValidator.validate(content)
      -> presidio-analyzer scans for 20+ PII types
    -> Returns (passed, processed_content, detections)
  -> Returns processed_content (possibly redacted)
-> MemoryStore.save(processed_content)
```

Three actions control what happens when PII is detected:

| Action | Behavior | Use Case |
|:-------|:---------|:---------|
| `log` | Detect, log a warning, pass content through unchanged | Discovery -- see what PII is in your pipeline |
| `redact` | Replace PII with `[REDACTED]` before storage | Compliance -- prevent PII persistence |
| `block` | Raise an exception, storage is cancelled | Strict environments -- no PII allowed through |

## Configuration

Add a `pii:` section under `governance:` in your `config.yaml`:

```yaml
governance:
  enabled: true
  pii:
    enabled: true       # enable PII detection
    action: log          # log | redact | block
    redact_placeholder: "[REDACTED]"
    entities: []         # empty = all PII types
    language: en
    nlp_model: en_core_web_sm
```

### Entity Filtering

The `entities` list lets you scope detection to specific PII types. When empty (default), all supported types are detected.

Common entity types:

| Entity | Example | Notes |
|:-------|:--------|:------|
| `EMAIL_ADDRESS` | `user@example.com` | Enables spam from phishing reports |
| `PHONE_NUMBER` | `(555) 123-4567` | |
| `PERSON` | `John Smith` | |
| `CREDIT_CARD` | `4111-1111-1111-1111` | |
| `SSN` | `123-45-6789` | |
| `CRYPTO` | `1A1zP1eP5QGefi2DMP` | Bitcoin addresses |
| `LOCATION` | `New York City` | |
| `ORGANIZATION` | `Microsoft Corp` | |

IP addresses, URLs, and domain names are **exempt from detection by default** -- these are legitimate CTI indicators (IOCs), not PII in the threat intelligence context. To include them, set `entities` explicitly:

```yaml
pii:
  enabled: true
  entities: ["IP_ADDRESS", "EMAIL_ADDRESS"]   # IPs will now be detected
```

## Example Configurations

### 1. Log-Only (Discovery Mode)

Use this first to understand what PII flows through your pipeline without changing any data:

```yaml
governance:
  pii:
    enabled: true
    action: log
```

Every PII detection is logged as a structured `pii_detected` log event with count, entity types, and scores. Content is stored unchanged.

### 2. Redact (Compliance Mode)

Automatically replace PII with placeholders before storage:

```yaml
governance:
  pii:
    enabled: true
    action: redact
    redact_placeholder: "[PII REMOVED]"
```

The redacted content is what gets stored and indexed. The original content with PII is never persisted.

### 3. Block (Strict Mode)

Reject any content containing PII entirely:

```yaml
governance:
  pii:
    enabled: true
    action: block
```

If PII is detected, `remember()` raises a `PIIBlockedError` and the operation is cancelled. The calling code receives the exception and can handle it (e.g., ask the user to retry without PII).

### 4. Targeted Detection (Only Emails and Phones)

Scope detection to specific entity types to reduce noise:

```yaml
governance:
  pii:
    enabled: true
    action: redact
    entities: ["EMAIL_ADDRESS", "PHONE_NUMBER"]
```

### 5. Complete Compliance Setup (FedRAMP-aligned)

```yaml
governance:
  enabled: true
  min_content_length: 1
  pii:
    enabled: true
    action: redact
    redact_placeholder: "[REDACTED]"
    entities: []
    language: en
    nlp_model: en_core_web_sm
```

## Environment Variables

| Variable | Maps To | Default |
|:---------|:--------|:--------|
| `ZETTELFORGE_PII_ENABLED` | `governance.pii.enabled` | `false` |
| `ZETTELFORGE_PII_ACTION` | `governance.pii.action` | `log` |

## spaCy Model Download

The spaCy NLP model downloads automatically on the first `remember()` call after PII is enabled. The download is a one-time cost:

| Model | Size | Speed | Notes |
|:------|:-----|:------|:------|
| `en_core_web_sm` | ~12 MB | Fast | Default. Good accuracy for standard PII |
| `en_core_web_md` | ~40 MB | Medium | Better person/location disambiguation |
| `en_core_web_lg` | ~560 MB | Slow | Best accuracy, word vectors |
| `en_core_web_trf` | ~400 MB | Slowest | Transformer-based, best for context |

To pre-download (recommended for air-gapped deployments):

```bash
python -m spacy download en_core_web_sm
```

## Verification

After configuration, test that PII detection is working:

```python
from zettelforge import MemoryManager

mm = MemoryManager()

# This should trigger a PII warning if action=log
note, status = mm.remember(
    "Contact analyst John Smith at john@example.com or 555-1234 for details."
)
```

With `action=log`, you will see a `pii_detected` structured log event.

With `action=redact`, the stored content will have PII replaced:

```python
print(note.content.raw)
# "Contact analyst [REDACTED] at [REDACTED] or [REDACTED] for details."
```

With `action=block`, `remember()` will raise `PIIBlockedError`.

## Performance Impact

- First call: ~2-3 seconds (spaCy model loading). Subsequent calls are fast.
- Detection latency: ~50-200ms per `remember()` depending on content length and model size.
- No network calls (all detection is local).
- No impact when `governance.pii.enabled: false` (disabled by default).

## Related

- [Configuration Reference](../reference/configuration.md) -- all `config.yaml` keys
- [Governance Controls](../reference/governance-controls.md) -- GOV-013 PII enforcement
- [Microsoft Presidio](https://github.com/microsoft/presidio) -- upstream project
- RFC-013: PII Detection and Redaction via Microsoft Presidio
