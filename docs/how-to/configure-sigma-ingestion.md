---
title: "Configure Sigma Rule Ingestion"
description: "Ingest Sigma detection rules into ZettelForge memory with automatic entity extraction, tag resolution, and knowledge graph population."
diataxis_type: "how-to"
audience: "Detection engineers, SOC analysts integrating Sigma rules into ZettelForge"
tags: [sigma, ingestion, detection-rules, knowledge-graph, sigmahq]
last_updated: "2026-04-27"
version: "2.7.0"
---

# Configure Sigma Rule Ingestion

Ingest Sigma detection rules (SigmaHQ format) into ZettelForge memory. Each rule is parsed, validated against the vendored SigmaHQ JSON schema, mapped to a `SigmaRule` entity with typed knowledge graph relations, and persisted as a memory note.

## Prerequisites

- ZettelForge installed (`pip install zettelforge`)
- Sigma rule files in `.yml` or `.yaml` format (SigmaHQ specification V2.0.0)
- Embedding and LLM models available (download automatically on first use)

## Steps

### 1. Use the CLI (quick start)

Dry-run a directory to validate rules before ingesting:

```bash
python -m zettelforge.sigma.ingest /path/to/sigma/rules/ --dry-run
```

Output shows each parsed rule with its id, rule type, tag count, and relation count:

```
OK  /path/to/sigma/rules/proc_creation_win_whoami.yml  id=sigma_a1b2c3d4e5f67890  type=detection  tags=3  edges=6
OK  /path/to/sigma/rules/susp_ps_execution.yml  id=55043c5f-3c72-4fb6-aa22-70b6f7e98d4a  type=detection  tags=5  edges=9

Dry-run summary: 2/2 parsed, 0 failed.
```

Live ingestion into a MemoryManager:

```bash
python -m zettelforge.sigma.ingest /path/to/sigma/rules/ --domain detection
```

### 2. Use the Python API

```python
from zettelforge import MemoryManager
from zettelforge.sigma import ingest_rule, ingest_rules_dir

mm = MemoryManager()

# Ingest a single file
note, relations = ingest_rule(
    "/path/to/rule.yml",
    mm,
    domain="detection",
)
print(f"Ingested: {note.id}, relations: {len(relations)}")

# Ingest a directory (walks recursively)
ingested, skipped = ingest_rules_dir(
    "/path/to/sigma/rules/",
    mm,
    glob="**/*.yml",
    domain="detection",
)
print(f"Ingested: {ingested}, skipped: {skipped}")
```

### 3. Parse without persisting

For validation pipelines or custom workflows, parse rules without memory storage:

```python
from zettelforge.sigma import parse_file, parse_yaml, from_rule_dict

# Parse from file
rule_dict = parse_file("rule.yml")

# Parse from YAML string
yaml_text = """
title: Suspicious Whoami Execution
logsource:
  category: process_creation
  product: windows
detection:
  selection:
    Image|endswith: '\\whoami.exe'
  condition: selection
"""
rule_dict = parse_yaml(yaml_text)

# Map to entity and KG relations
entity, relations = from_rule_dict(rule_dict)
print(f"Rule: {entity.title}")
print(f"Logsource: product={entity.logsource_product}, category={entity.logsource_category}")
print(f"Relation types: {set(r['rel'] for r in relations)}")
```

### 4. Accept multiple input types

`ingest_rule()` accepts a parsed dict, raw YAML string, or `Path`:

```python
# Dict (pre-parsed)
note, rels = ingest_rule(rule_dict, mm)

# YAML string
note, rels = ingest_rule(yaml_text, mm)

# Path object
from pathlib import Path
note, rels = ingest_rule(Path("rule.yml"), mm)

# File path as string (auto-detected if it looks like a path)
note, rels = ingest_rule("rule.yml", mm)
```

### 5. Validate against the Sigma schema

Run standalone validation without entity mapping:

```python
from zettelforge.sigma import validate, parse_yaml, SigmaValidationError

rule = parse_yaml(yaml_text)
result = validate(rule)
if not result.valid:
    for error in result.errors:
        print(f"  Validation error: {error}")
```

### 6. Understand idempotency

Re-ingesting an unchanged rule returns the original note. The `source_ref` follows the pattern `sigma:<rule_id>:<content_sha256_prefix>` and is checked before any write:

```python
first, _ = ingest_rule("rule.yml", mm)
second, _ = ingest_rule("rule.yml", mm)
assert first.id == second.id  # same note, no duplicate
```

### 7. CLI flags reference

```
usage: python -m zettelforge.sigma.ingest [-h] [--domain DOMAIN] [--dry-run] [--glob GLOB] path

positional arguments:
  path              Sigma rule file or directory

options:
  --domain DOMAIN   Memory domain for ingested notes (default: detection)
  --dry-run         Parse + validate + map without persisting to memory
  --glob GLOB       Glob used when path is a directory (default: **/*.yml)
```

## LLM Quick Reference

**Task**: Ingest Sigma rules into ZettelForge memory with automatic knowledge graph population.

**Primary CLI**: `python -m zettelforge.sigma.ingest <path>` with optional `--dry-run`, `--domain`, `--glob`.

**Primary Python API**: `ingest_rule(source, mm, domain="detection")` returns `(MemoryNote, relations_list)`. Accepts dict, string, or Path. `ingest_rules_dir(path, mm)` walks a directory tree and returns `(ingested_count, skipped_count)`.

**Pipeline**: Input -> `parse_file()` or `parse_yaml()` (YAML load + JSON-schema validation against vendored SigmaHQ schemas) -> `from_rule_dict()` (map to `SigmaRule` entity + relations) -> `mm.remember()` (persist as memory note) -> KG edge persistence.

**Validation**: `validate(rule_dict)` returns `ValidationResult(valid, errors)`. Two error types: `SigmaParseError` (bad YAML or I/O) and `SigmaValidationError` (schema violation). Both bubble through `ingest_rule()`.

**Schema dispatch**: Detection rules validate against `sigma-detection-rule-schema.json`. Rules with a `correlation:` key use the correlation schema. Rules with a `filter:` key use the filters schema.

**Tag resolution**: Sigma tags (`attack.t1059`, `cve.2021-44228`) upgrade to typed KG edges (`detects` -> `AttackPattern`, `references_cve` -> `Vulnerability`, `attributed_to` -> `IntrusionSet`/`Malware`). Raw `tagged_with` -> `SigmaTag` edges are always preserved alongside upgrade edges. `tlp.*` and `detection.*` tags are metadata-only (no upgrade).

**Logsource edges**: Every populated logsource facet (product, service, category) generates an `applies_to` -> `LogSource` edge with the facet type and value in properties.

**Related rule edges**: The `related:` block maps to `superseded_by` (type: `obsolete`) or `related_to` (all other types).

**Idempotency**: Source ref pattern `sigma:<rule_id>:<content_sha256[:12]>`. A store lookup precedes every write. Unchanged rules return the original note.

**Security**: File size capped at 1 MB. Symlinks are never followed during directory walk. Paths that resolve outside the rules root are skipped.

**Edge tagging**: All KG edges emitted during ingest carry `edge_type: detection` and `source: sigma_ingest` properties for downstream filtering.
