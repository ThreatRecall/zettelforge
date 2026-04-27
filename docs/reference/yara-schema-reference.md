---
title: "YARA Schema Reference"
description: "Vendored CCCS YARA metadata schemas, validation tiers, parser API, ValidationResult, and error types for YARA rule validation in ZettelForge."
diataxis_type: "reference"
audience: "Detection engineers building YARA validation pipelines, malware analysts, contributors extending schema support"
tags:
  - yara
  - cccs
  - schema
  - validation
  - parser
  - metadata
last_updated: "2026-04-27"
version: "2.7.0"
---

# YARA Schema Reference

Module: `zettelforge.yara.parser`, `zettelforge.yara.cccs_metadata`, `zettelforge.yara.schemas`

```python
from zettelforge.yara.parser import parse_yara, parse_file, YaraParseError
from zettelforge.yara.cccs_metadata import (
    validate_metadata, ValidationResult,
    CCCS_YARA_SPEC, CCCS_YARA_VALUES, REQUIRED_FIELDS,
    Tier,
)
from zettelforge.yara.ingest import ingest_rule, ingest_rules_dir
```

---

## Overview

ZettelForge provides a complete YARA rule handling pipeline: plyara-based
parsing, clean-room CCCS (Canadian Centre for Cyber Security) metadata validation
against vendored schema files, entity extraction, and knowledge graph population.

**Parser**: plyara 2.2.x wrapper  
**Metadata schema**: Vendored `CCCS_YARA.yml` and `CCCS_YARA_values.yml`  
**Validation**: Clean-room reimplementation — no upstream code is vendored

---

## Vendored Schemas

Two schema files live in `src/zettelforge/yara/schemas/`:

| File | Description | Loaded At |
|:-----|:------------|:----------|
| `CCCS_YARA.yml` | CCCS YARA metadata field definitions (required fields, types, optionality) | Import time via `_load_yaml()` |
| `CCCS_YARA_values.yml` | CCCS enumerated value sets (statuses, categories, sharing classifications, etc.) | Import time via `_load_yaml()` |

See `src/zettelforge/yara/schemas/NOTICE.md` for licensing information about
the vendored schema files.

---

## CCCS Metadata Fields

Derived from `CCCS_YARA.yml`. Fields marked as `optional: No` or
`optional: Optional` are treated as required under `strict` tier validation.

| Field | Type | Required (strict) | Validation |
|:------|:-----|:-----------------:|:-----------|
| `id` | `string` | yes | Base62 UUID (16+ chars) |
| `fingerprint` | `string` | yes | Hex digest 40-64 chars (SHA-1/SHA-256) |
| `version` | `string` | yes | Semantic version `x.y` |
| `modified` | `string` | yes | ISO date `YYYY-MM-DD` |
| `status` | `string` | yes | Must match `rule_statuses` value set |
| `sharing` | `string` | yes | Must match `sharing_classifications` value set |
| `source` | `string` | yes | Non-empty string (uppercase convention) |
| `author` | `string` | yes | Must match author regex (email-like format) |
| `description` | `string` | yes | Non-empty string |
| `category` | `string` | yes | Must match `category_types` value set |
| `date` | `string` | no | ISO date `YYYY-MM-DD` |
| `malware_type` | `string` | no | Must match `malware_types` value set |
| `actor_type` | `string` | no | Must match `actor_types` value set |
| `actor` | `string` | no | Free-form string |
| `technique` | `string` | no | Free-form string |
| `mitre_att` | `string` | no | Pattern `T####`, `G####`, `S####`, or `TA####` |
| `hash` | `string` | no | Must match `hash_types` value set |

### REQUIRED_FIELDS (dynamic)

The `_required_fields()` function walks `CCCS_YARA_SPEC` and collects all
keys where `optional` is `False` (YAML `No`) or the string `"Optional"`:

```python
REQUIRED_FIELDS: list[str] = [
    "id", "fingerprint", "version", "modified",
    "status", "sharing", "source", "author",
    "description", "category",
]
```

### Value Set Definitions

From `CCCS_YARA_values.yml`. Each value set is compiled to a list of
regex patterns at import time:

#### `rule_statuses`

Standard CCCS rule maturity statuses (e.g., `RELEASED`, `DRAFT`, `TEST`,
`DEPRECATED`). Validated via regex alternation.

#### `sharing_classifications`

TLP marking labels and CCCS sharing classifications (e.g., `TLP:WHITE`,
`TLP:GREEN`, `TLP:AMBER`, `TLP:RED`). Validated via regex alternation.

#### `category_types`

Rule categories (e.g., `INFO`, `EXPLOIT`, `TECHNIQUE`, `TOOL`, `MALWARE`).
Validated via regex alternation.

#### `malware_types`

Malware type identifiers when `category=MALWARE`. Validated via regex
alternation.

#### `actor_types`

Threat actor type identifiers when `actor` meta is present. Validated via
regex alternation.

#### `hash_types`

Known hash length patterns (MD5, SHA-1, SHA-256, SHA-512). Validated via
regex alternation.

---

## Per-Field Validators

Clean-room implementations of CCCS validator names. Each validator is a
pure function returning either `None` (valid) or an error string.

| Field | Validator Function | Pattern |
|:------|:-------------------|:--------|
| `id` | `_UUID_REGEX` | `^[0-9A-Za-z]{16,}$` (base62 UUID) |
| `fingerprint` | `_FINGERPRINT_REGEX` | `^[a-fA-F0-9]{40,64}$` (SHA-1/SHA-256 hex) |
| `version` | `_VERSION_REGEX` | `^\d+\.\d+$` |
| `date`, `modified` | `_DATE_REGEX` | `^\d{4}-\d{2}-\d{2}$` |
| `status` | `_STATUS_REGEXES` | Alternation of allowed values |
| `sharing` | `_SHARING_REGEXES` | Alternation of allowed values |
| `category` | `_CATEGORY_REGEXES` | Alternation of allowed values |
| `malware_type` | `_MALWARE_TYPE_REGEXES` | Alternation of allowed values |
| `actor_type` | `_ACTOR_TYPE_REGEXES` | Alternation of allowed values |
| `hash` | `_HASH_REGEXES` | Alternation of known hash lengths |
| `mitre_att` | `_MITRE_ATT_REGEX` | `^(TA\|T\|M\|G\|S)\d{4}(\.\d{3})?$` |
| `author` | `_AUTHOR_REGEX ` | Email-like format |
| `source` | Always valid | Non-empty string accepted |
| `description` | Always valid | Non-empty string accepted |

---

## Validation Tiers

```python
Tier = Literal["strict", "warn", "non_cccs"]
```

| Tier | Behaviour |
|:-----|:----------|
| `strict` | Every required field must be present and valid. Any failure sets `accepted=False` and populates `errors`. Rules missing or invalid required fields are **rejected** (note returned as `None` from `ingest_rule()`). |
| `warn` | Same checks as strict, but failures are recorded as `warnings` and `accepted` stays `True` (default). Rules are accepted with warning annotations. |
| `non_cccs` | Accept unconditionally — no validation checks performed. Returns `(True, [], [])`. |

---

## ValidationResult

```python
class ValidationResult(NamedTuple):
    accepted: bool
    warnings: list[str]
    errors: list[str]
```

- `accepted`: `True` for `warn` and `non_cccs` tiers; `True` for `strict` only when no errors
- `warnings`: Validation issues that did not cause rejection (metadata missing or invalid under `warn` tier)
- `errors`: Validation failures that caused rejection (only populated under `strict` tier)

---

## Parser API

### parse_yara()

```python
def parse_yara(text: str) -> list[dict[str, Any]]
```

Parses YARA source text into a list of normalized rule dicts. A single `.yar`
file may contain multiple rules — one dict per rule.

**Normalization applied to each rule dict:**

1. **`meta`**: Flattened dict from plyara's `metadata` (list-of-single-key-dicts)
   using `_flatten_metadata()`
2. **`imports`**: Copied from parser-level `Plyara.imports` when the rule dict
   lacks its own import list
3. **`tags`**: Defaults to empty list when absent
4. **`raw_rule`**: Raw source text substring carved by `start_line`/`stop_line`
   markers — useful for persisting rule text back into a note

### parse_file()

```python
def parse_file(path: str | Path) -> list[dict[str, Any]]
```

Parses a `.yar` or `.yara` file into a list of normalized rule dicts.

- File size limit: `MAX_RULE_FILE_BYTES = 1_048_576` (1 MB)
- Raises `YaraParseError` if the file is oversized (` > 1 MB`) or unreadable

### parse_text()

```python
def parse_text(yara_text: str) -> list[dict[str, Any]]
```

Legacy alias for `parse_yara()`. Retained for scaffold compatibility.

---

## Error Types

### YaraParseError

```python
class YaraParseError(ValueError)
```

Raised when a YARA rule file cannot be parsed or is otherwise rejected before
it reaches plyara (I/O error, oversized file, etc.).

### YaraValidationError

```python
class YaraValidationError(ValueError)
```

Mirrors `SigmaValidationError`. Raised when CCCS metadata validation fails
hard enough that callers should treat the rule as unacceptable. The
`validate_metadata()` function itself returns a `ValidationResult` so
strict/warn/non_cccs callers can inspect the outcome without catching.

---

## Rule Dict Shape (plyara Normalized)

After parsing, each rule dict contains plyara's original keys plus these
additions:

| Key | Type | Description |
|:----|:-----|:------------|
| `rule_name` | `str` | Rule name from YARA source |
| `meta` | `dict` | Flattened metadata from `metadata` list |
| `strings` | `list` | Rule string definitions |
| `condition` | `str` | Rule condition expression |
| `condition_terms` | `list` | Parsed condition terms |
| `tags` | `list[str]` | Inline rule tags |
| `imports` | `list[str]` | Module imports (e.g., `pe`, `hash`) |
| `raw_meta` | `str` | Raw meta section text |
| `raw_strings` | `str` | Raw strings section text |
| `raw_condition` | `str` | Raw condition section text |
| `start_line` | `int` | Line number where the rule starts (1-indexed) |
| `stop_line` | `int` | Line number where the rule ends (inclusive) |
| `raw_rule` | `str` | Source text substring from start_line to stop_line |

---

## Ingestion Pipeline

The `ingest_rule()` function in `yara.ingest` orchestrates the per-rule pipeline:

1. **Parse** via plyara wrapper
2. **Validate CCCS metadata** against vendored schemas
3. **Extract entities** via `rule_to_entities()` which returns a `YaraRule` instance and relation list
4. **Construct note content** (raw rule text + summary with name, category, technique, author, CCCS tier)
5. **Persist** note via `MemoryManager.remember()` with `source_type="yara"`
6. **Write KG edges** via `store.add_kg_edge()` for each relation

### Idempotency

Source ref pattern: `yara:<rule_id>:<content_sha256[:12]>`
A store lookup via `get_note_by_source_ref()` precedes every write.

### Edge Tagging

All KG edges carry:
- `edge_type: detection` — distinguishes from causal or heuristic edges
- `source: yara_ingest` — provenance tag for downstream filtering

### Relation Types Emitted

| Relation | Target Type | Source | Description |
|:---------|:------------|:-------|:------------|
| `detects` | `AttackPattern` | `mitre_att` meta | MITRE technique detection |
| `tagged_with` | `YaraTag` | inline tags + CCCS technique | Lossless tag edge |
| `attributed_to` | `ThreatActor` | `actor` / `actor_type` meta | Threat actor attribution |
| `references_cve` | `Vulnerability` | inline tags resolving to CVE | CVE reference |

---

## File Size Limit

```python
MAX_RULE_FILE_BYTES = 1_048_576  # 1 MB
```

YARA rules are text, typically a few KB. The 1 MB ceiling catches runaway
payloads without blocking normal multi-rule files.

---

## Minimal Example

```python
from zettelforge.yara import parse_yara

yara_text = \"\"\"
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
\"\"\"

rules = parse_yara(yara_text)
print(f"Parsed {len(rules)} rule(s)")
print(f"Name: {rules[0]['rule_name']}")
print(f"Meta flattened: {list(rules[0]['meta'].keys())}")
```

## Full Example

```python
from zettelforge.yara import (
    parse_file, validate_metadata, rule_to_entities,
    REQUIRED_FIELDS, YaraValidationError,
)

# Parse a file
rules = parse_file("technique_loader.yar")

for rule_dict in rules:
    # Validate CCCS metadata
    result = validate_metadata(rule_dict["meta"], tier="warn")
    print(f"Accepted: {result.accepted}, Warnings: {len(result.warnings)}")

    # Map to entity and relations
    entity, relations = rule_to_entities(rule_dict, tier="warn")
    print(f"Rule: {entity.title}")
    print(f"CCCS tier: {entity.extra.get('cccs_compliant')}")
    print(f"Relations: {len(relations)}")
    for rel in relations:
        print(f"  {rel['rel']} -> {rel['to_type']}:{rel['to_value']}")
```

## Standalone Validation

```python
from zettelforge.yara import validate_metadata, REQUIRED_FIELDS

print("Required CCCS fields:", REQUIRED_FIELDS)

meta = {
    "id": "abc123def456ghi789",
    "fingerprint": "a" * 64,
    "version": "1.0",
    "modified": "2024-01-01",
    "status": "RELEASED",
    "sharing": "TLP:WHITE",
    "source": "CCCS",
    "author": "analyst@cccs-cnc.gc.ca",
    "description": "Detects XYZ technique",
    "category": "TECHNIQUE",
}

result = validate_metadata(meta, tier="strict")
print(f"Accepted: {result.accepted}")
for warn in result.warnings:
    print(f"  Warning: {warn}")
for err in result.errors:
    print(f"  Error: {err}")
```
