---
title: "Community vs Enterprise Editions"
description: "Feature matrix, activation methods, and edition detection API for ZettelForge Community (MIT) and ZettelForge Enterprise (proprietary)."
diataxis_type: "reference"
audience: "Senior CTI Practitioner, deployment engineers"
tags:
  - editions
  - community
  - enterprise
  - feature-gates
  - licensing
last_updated: "2026-04-27"
version: "2.6.0"
---

# Community vs Enterprise Editions

Module: `zettelforge.edition`, `zettelforge.extensions`

```python
from zettelforge.edition import (
    Edition,
    EditionError,
    is_enterprise,
    is_community,
    get_edition,
    edition_name,
    reset_edition,
)
```

---

## Edition Detection Mechanism

ZettelForge detects the active edition at runtime by checking whether the `zettelforge_enterprise` extension package is loaded. The detection flows through two layers:

1. **`zettelforge.extensions.load_extensions()`** -- attempts to import `zettelforge_enterprise`. On success, the `"enterprise"` extension is registered. Falls back to the legacy `THREATENGRAM_LICENSE_KEY` env var check.
2. **`zettelforge.edition`** -- thin wrappers over `has_extension("enterprise")` with an `Edition` enum and an `EditionError` exception.

The loader is idempotent: the first call caches the result for the lifetime of the process. Call `reset_edition()` only in test teardown to force re-evaluation.

---

## Feature Matrix

| Feature | Community | Enterprise | Notes |
|:--------|:---------:|:----------:|:------|
| Core storage (SQLite) | yes | yes | Default backend for notes, entities, KG |
| LanceDB vector store | yes | yes | Offline-first embedding storage |
| Entity extraction (regex) | yes | yes | CTI entities, IOCs, conversational types |
| Entity extraction (LLM NER) | yes | yes | Always-on via enrichment queue |
| Knowledge graph (JSONL) | yes | yes | In-memory with JSONL persistence |
| Alias resolution | yes | yes | TypeDB-backed with JSONL fallback |
| Memory evolution | yes | yes | LLM-based fact comparison |
| Synthesis generation | yes | yes | Direct answer, brief, timeline, relationship map |
| Web management interface | yes | yes | FastAPI + SPA on port 8088 |
| MCP server | yes | yes | Model Context Protocol endpoint |
| CLI tools | yes | yes | rebuild-index, compact-lance, migration scripts |
| Governance controls | yes | yes | Limits, PII detection (optional), tier filtering |
| **TypeDB backend** | -- | yes | Enterprise-grade graph database for KG edges |
| **OpenCTI integration** | -- | yes | Bidirectional sync of STIX entities |
| **Multi-tenant auth** | -- | yes | Role-based access for the web interface |
| **Telemetry aggregation** | -- | yes | Usage dashboards, performance metrics |
| **CCCS YARA validation** | -- | yes | Canadian Centre for Cyber Security metadata compliance |

---

## Activation

### Enterprise (via `zettelforge-enterprise` package)

Install the proprietary `zettelforge-enterprise` package (not on PyPI; contact the maintainer):

```python
# After installation, enterprise features are auto-detected
from zettelforge.edition import is_enterprise

print(is_enterprise())  # True
```

### Enterprise (legacy env var fallback)

For backward compatibility, the `THREATENGRAM_LICENSE_KEY` environment variable can activate enterprise mode without the package installed:

```bash
export THREATENGRAM_LICENSE_KEY="TG-1234-5678-9abc-def0"
```

The key must match the pattern `TG-XXXX-XXXX-XXXX-XXXX` (four hyphen-separated alphanumeric segments starting with "TG-").

### Community (default)

No action needed. All MIT-licensed features work out of the box:

```bash
pip install zettelforge
```

---

## Edition Detection API

```python
class Edition(enum.Enum):
    COMMUNITY = "community"
    ENTERPRISE = "enterprise"
```

| Function | Return Type | Description |
|:---------|:------------|:------------|
| `is_enterprise()` | `bool` | True if enterprise extensions are loaded (package or env var) |
| `is_community()` | `bool` | True if no enterprise extension is available |
| `get_edition()` | `Edition` | `Edition.ENTERPRISE` or `Edition.COMMUNITY` |
| `edition_name()` | `str` | `"ZettelForge + Extensions"` (enterprise) or `"ZettelForge"` (community) |
| `reset_edition()` | `None` | Clear cached edition state (test only) |

---

## Feature Gating in Code

### Soft gate (graceful degradation)

```python
if is_enterprise():
    # Use TypeDB for knowledge graph
    backend = TypeDBBackend(config)
else:
    # Fall back to SQLite
    backend = SQLiteBackend(config)
```

### Hard gate (raises EditionError)

```python
from zettelforge.edition import is_enterprise, EditionError

def sync_with_opencti():
    if not is_enterprise():
        raise EditionError("OpenCTI integration requires ZettelForge Enterprise")
    # ... sync logic ...
```

### Config-driven gating

The Configuration Reference documents Enterprise-only config sections:

- `typedb.*` -- TypeDB connection settings (ignored in Community)
- `opencti.*` -- OpenCTI URL, token, sync interval (ignored in Community)

These sections have no runtime effect in the Community edition. Values are accepted by the config parser but never consumed.

---

## Enterprise-Only Configuration

### TypeDB

```yaml
typedb:
  host: localhost
  port: 1729
  database: zettelforge
  username: ""      # Set via TYPEDB_USERNAME env var
  password: ""      # Set via TYPEDB_PASSWORD env var
```

Environment variable overrides: `TYPEDB_HOST`, `TYPEDB_PORT`, `TYPEDB_DATABASE`, `TYPEDB_USERNAME`, `TYPEDB_PASSWORD`.

### OpenCTI

```yaml
opencti:
  url: http://localhost:8080
  token: ""          # Set via OPENCTI_TOKEN env var
  sync_interval: 0   # Seconds between pulls; 0 = manual only
```

Supported entity types for pull/push: `attack_pattern`, `intrusion_set`, `threat_actor`, `malware`, `indicator`, `vulnerability`, `report`. See [Configure OpenCTI](../how-to/configure-opencti.md).

Environment variable overrides: `OPENCTI_URL`, `OPENCTI_TOKEN`, `OPENCTI_SYNC_INTERVAL`.

---

## License & Packaging

| Aspect | Community | Enterprise |
|:-------|:----------|:-----------|
| License | MIT | Proprietary |
| PyPI | `pip install zettelforge` | Private distribution only |
| Source | Public on GitHub (`rolandpg/zettelforge`) | Not public |
| Dependencies | Core only (sqlite, lancedb, fastembed, ollama) | Adds typedb-client, pycti, auth middleware |
| Support | GitHub Issues | Direct maintainer channel |

---

## Testing Edition Detection

```python
import os
from unittest.mock import patch
from zettelforge.extensions import reset_extensions
from zettelforge.edition import (
    Edition,
    is_enterprise,
    is_community,
    get_edition,
    edition_name,
    reset_edition,
)


def test_community_by_default():
    reset_extensions()
    with patch.dict("sys.modules", {"zettelforge_enterprise": None}):
        # Force re-load
        import zettelforge.extensions as ext_mod
        ext_mod._loaded = False
        ext_mod._extensions.clear()
        assert is_community() is True
        assert is_enterprise() is False


def test_enterprise_with_valid_key():
    os.environ["THREATENGRAM_LICENSE_KEY"] = "TG-1234-5678-9abc-def0"
    reset_extensions()
    assert is_enterprise() is True
    assert get_edition() == Edition.ENTERPRISE


def test_community_with_invalid_key():
    os.environ["THREATENGRAM_LICENSE_KEY"] = "invalid"
    reset_extensions()
    # Block the enterprise package import
    with patch.dict("sys.modules", {"zettelforge_enterprise": None}):
        assert is_enterprise() is False
        assert edition_name() == "ZettelForge"


def test_enterprise_name():
    os.environ["THREATENGRAM_LICENSE_KEY"] = "TG-9999-8888-7777-6666"
    reset_extensions()
    assert edition_name() == "ZettelForge + Extensions"
```

---

## Environment Variables Summary

| Variable | Affects | Edition |
|:---------|:--------|:--------|
| `THREATENGRAM_LICENSE_KEY` | Edition activation | Enterprise (legacy) |
| `TYPEDB_HOST`, `TYPEDB_PORT`, ... | TypeDB connection | Enterprise |
| `OPENCTI_URL`, `OPENCTI_TOKEN`, ... | OpenCTI sync | Enterprise |
| `ZETTELFORGE_BACKEND` | Backend selection (`sqlite` or `typedb`) | Both |

See the [Configuration Reference](configuration.md#environment-variables-summary) for the full list.
