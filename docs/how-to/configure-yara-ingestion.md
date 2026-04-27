---
title: "Configure YARA Rule Ingestion"
description: "Ingest YARA rules into ZettelForge memory with CCCS metadata validation, tag resolution, and knowledge graph population."
diataxis_type: "how-to"
audience: "Detection engineers, malware analysts integrating YARA rules into ZettelForge"
tags: [yara, ingestion, detection-rules, cccs, knowledge-graph]
last_updated: "2026-04-27"
version: "2.7.0"
---

# Configure YARA Rule Ingestion

Ingest YARA rules into ZettelForge memory. Each rule is parsed via plyara, validated against the vendored CCCS (Canadian Centre for Cyber Security) metadata schema, mapped to a `YaraRule` entity with typed knowledge graph relations, and persisted as a memory note.

## Prerequisites

- ZettelForge installed (`pip install zettelforge`)
- YARA rule files in `.yar` or `.yara` format
- Embedding and LLM models available (download automatically on first use)

## Steps

### 1. Use the CLI (quick start)

Dry-run a directory to validate rules before ingesting:

```bash
python -m zettelforge.yara.ingest /path/to/yara/rules/ --dry-run
```

Output shows each parsed rule with CCCS compliance tier, MITRE references, and validation details:

```
[warn] SILENT_BANKER_LOADER (technique_loader.yar)  relations=3  mitre=T1218
    warn: missing required CCCS field: status
    warn: missing required CCCS field: sharing

Dry-run with machine-readable JSON output:

```bash
python -m zettelforge.yara.ingest /path/to/yara/rules/ --dry-run --json
```

Live ingestion into a MemoryManager:

```bash
python -m zettelforge.yara.ingest /path/to/yara/rules/ --tier warn --domain detection
```

### 2. Use the Python API

```python
from zettelforge import MemoryManager
from zettelforge.yara import ingest_rule, ingest_rules_dir

mm = MemoryManager()

# Ingest a single file (warn tier -- accepts non-CCCS metadata with warnings)
note, relations = ingest_rule(
    "/path/to/rule.yar",
    mm,
    domain="detection",
    tier="warn",
)
if note:
    print(f"Ingested: {note.id}, relations: {len(relations)}")
else:
    print("Rule was rejected (strict tier)")

# Ingest a directory (walks recursively)
result = ingest_rules_dir(
    "/path/to/yara/rules/",
    mm,
    tier="warn",
    domain="detection",
)
print(f"Ingested: {result['ingested']}, skipped: {result['skipped']}")
for err in result["errors"]:
    print(f"  Error: {err}")
```

### 3. CCCS metadata validation tiers

Three tiers control how strictly CCCS metadata is enforced:

```python
from zettelforge.yara import ingest_rule

# strict -- all required fields must be present and valid
# A rule missing status/sharing/source/author/description/category is REJECTED
# (returns note=None)
note, _ = ingest_rule("rule.yar", mm, tier="strict")

# warn -- same checks but failures are warnings only; rule is ACCEPTED
note, _ = ingest_rule("rule.yar", mm, tier="warn")

# non_cccs -- no validation; rule is ACCEPTED unconditionally
note, _ = ingest_rule("rule.yar", mm, tier="non_cccs")
```

### 4. Parse without persisting

For validation pipelines or custom workflows:

```python
from zettelforge.yara import parse_file, parse_yara, rule_to_entities

# Parse from file (returns list of rule dicts -- one file may hold multiple rules)
rules = parse_file("technique_loader.yar")
print(f"Found {len(rules)} rule(s) in file")

# Parse from YARA source text
yara_text = """
rule SILENT_BANKER_LOADER {
    meta:
        description = "Detects silent banker loader techniques"
        category = "TECHNIQUE"
        technique = "loader:memorymodule"
        mitre_att = "T1218"
    strings:
        $s1 = { 4D 5A 90 00 03 00 00 00 }
    condition:
        $s1
}
"""
rules = parse_yara(yara_text)

# Map to entity and KG relations (with CCCS validation)
entity, relations = rule_to_entities(rules[0], tier="warn")
print(f"Rule: {entity.title}")
print(f"Category: {entity.category}")
print(f"CCCS tier: {entity.extra.get('cccs_compliant')}")
print(f"Relations: {len(relations)}")

for rel in relations:
    print(f"  {rel['rel']} -> {rel['to_type']}:{rel['to_value']}")
```

### 5. Validate CCCS metadata standalone

Run the validator independently:

```python
from zettelforge.yara import validate_metadata, REQUIRED_FIELDS

# Check which fields are required
print("Required CCCS fields:", REQUIRED_FIELDS)

meta = {
    "id": "abc123def456ghi789",
    "fingerprint": "a" * 64,
    "version": "1.0",
    "modified": "2024-01-01",
    "status": "RELEASED",
    "sharing": "TLP:WHITE",
    "source": "CCCS",
    "author": "analyst@CCCS",
    "description": "Detects XYZ technique",
    "category": "TECHNIQUE",
    "technique": "loader:memorymodule",
    "mitre_att": "T1218",
}

result = validate_metadata(meta, tier="strict")
print(f"Accepted: {result.accepted}")
print(f"Warnings: {result.warnings}")
print(f"Errors: {result.errors}")
```

### 6. Understand idempotency

Re-ingesting an unchanged rule returns the original note. The `source_ref` follows the pattern `yara:<rule_id>:<content_sha256_prefix>`:

```python
first, _ = ingest_rule("technique_loader.yar", mm, tier="warn")
second, _ = ingest_rule("technique_loader.yar", mm, tier="warn")
assert first is not None and second is not None
assert first.id == second.id  # same note, no duplicate
```

### 7. CLI flags reference

```
usage: python -m zettelforge.yara.ingest [-h] [--tier {strict,warn,non_cccs}] [--dry-run] [--domain DOMAIN] [--json] path

positional arguments:
  path                  Path to a .yar file or directory of rules

options:
  --tier {strict,warn,non_cccs}
                        CCCS metadata validation tier (default: warn)
  --dry-run             Parse, validate, and summarise -- do not write to memory
  --domain DOMAIN       Memory domain for ingested notes (default: detection)
  --json                Emit machine-readable JSON output instead of a human summary
```

## LLM Quick Reference

**Task**: Ingest YARA rules into ZettelForge memory with CCCS metadata validation and knowledge graph population.

**Primary CLI**: `python -m zettelforge.yara.ingest <path>` with optional `--tier`, `--dry-run`, `--domain`, `--json`.

**Primary Python API**: `ingest_rule(source, mm, domain="detection", tier="warn")` returns `(note_or_None, relations_list)`. Accepts dict, raw text, or Path. Use `ingest_rules_dir(path, mm, tier="warn")` for directory ingest -- returns `{"ingested": int, "skipped": int, "errors": list[str]}`.

**Pipeline**: Input -> `parse_file()` or `parse_yara()` (plyara wrapper, returns list of rule dicts) -> `rule_to_entities()` (CCCS validation + entity mapping) -> `mm.remember()` (persist as memory note) -> KG edge persistence.

**CCCS validation**: Three tiers. `strict` rejects rules with missing or invalid required fields. `warn` (default) accepts with warnings. `non_cccs` accepts unconditionally. Required fields: `id`, `fingerprint`, `version`, `modified`, `status`, `sharing`, `source`, `author`, `description`, `category`.

**Relation types emitted**:
- `detects` -> `AttackPattern` (from `mitre_att` meta and inline tags matching `T####` pattern)
- `attributed_to` -> `ThreatActor` (from `actor` meta)
- `tagged_with` -> `YaraTag` (from `technique` meta, known category tokens like `APT`/`MAL`, and freeform tags)
- `references_cve` -> `Vulnerability` (from inline tags matching `CVE-YYYY-NNNN` pattern)

**Tag resolution**: YARA uses a single-emit pattern (one edge per tag with rel-swap, unlike Sigma which emits both raw and upgraded edges). Category tokens (`APT`, `MAL`, `WEBSHELL`, etc.) resolve to `YaraTag` with namespace `category`. Unknown tags become `YaraTag` with namespace `freeform`.

**Rule IDs**: Rules with a CCCS `id` use that as their `rule_id`. Rules without one get `yara_<content_hash_prefix>` to avoid name collisions between identically-named rules in different files.

**Idempotency**: Source ref pattern `yara:<rule_id>:<content_sha256[:12]>`. A store lookup precedes every write. Unchanged rules return the original note.

**Security**: File size capped at 1 MB. Symlinks are never followed during directory walk. Paths that resolve outside the rules root are skipped.

**Edge tagging**: All KG edges carry `edge_type: detection` and `source: yara_ingest` properties.
