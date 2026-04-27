---
title: "Maintain LanceDB Indexes"
description: "Periodically compact LanceDB tables, clean up old version chains, and manage index health to prevent performance degradation on write-heavy workloads."
diataxis_type: "how-to"
audience: "Platform engineers maintaining ZettelForge deployments with high write volumes"
tags: [lancedb, maintenance, compaction, version-cleanup, performance]
last_updated: "2026-04-27"
version: "2.6.2"
---

# Maintain LanceDB Indexes

On write-heavy shards, the dominant cost of `MemoryStore._index_in_lance()` is LanceDB walking an unbounded version chain on each insert. `cleanup_old_versions()` collapses this chain to restore insert performance.

## Prerequisites

- ZettelForge installed (`pip install zettelforge`)
- LanceDB backend configured (see [Configure LanceDB](configure-lancedb.md))
- Write-heavy usage patterns (high volume of `remember()` calls)

## How Version Chains Grow

Each write to a LanceDB table creates a new version. Over time, the version chain grows linearly with write volume. LanceDB must walk this chain to resolve the latest state on each write. On tables with tens of thousands of versions, insert latency degrades significantly.

## Steps

### 1. Run maintenance via the CLI

```python
from zettelforge.lance_maintenance import cleanup_old_versions
from zettelforge.config import load_config

config = load_config()
uri = config["storage"]["lancedb"]["uri"]
table_names = ["notes", "embeddings", "entities"]

for table in table_names:
    removed = cleanup_old_versions(uri, table)
    print(f"{table}: removed {removed} old versions")
```

### 2. Schedule periodic maintenance

Add to your cron or systemd timer:

```bash
# Run daily at 03:00
0 3 * * * cd /path/to/your/project && python3 -c "
from zettelforge.lance_maintenance import cleanup_old_versions
from zettelforge.config import load_config
config = load_config()
uri = config['storage']['lancedb']['uri']
for t in ['notes', 'embeddings', 'entities']:
    cleanup_old_versions(uri, t)
"
```

### 3. Verify maintenance worked

Check the LanceDB table statistics before and after:

```python
import lancedb
db = lancedb.connect(uri)
table = db.open_table("notes")
print(f"Version count: {len(table.list_versions())}")
```

## When to Run Maintenance

| Condition | Action |
|-----------|--------|
| Write latency increases 2x+ over baseline | Run `cleanup_old_versions` immediately |
| Over 10,000 versions in any table | Schedule daily maintenance |
| Under 1,000 versions | Monthly maintenance is sufficient |

## Related

- [Configure LanceDB](configure-lancedb.md) — Initial setup and tuning
- [Reference: Configuration](../reference/configuration.md) — All config options
- `src/zettelforge/lance_maintenance.py` — Source implementation
- `tests/test_lance_maintenance.py` — Test coverage
