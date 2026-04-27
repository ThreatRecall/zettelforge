---
title: "Sigma Schema Reference"
description: "Vendored SigmaHQ JSON schemas, schema dispatch logic, parser API, ValidationResult, and error types for Sigma rule validation in ZettelForge."
diataxis_type: "reference"
audience: "Detection engineers building Sigma validation pipelines, contributors extending schema support"
tags:
  - sigma
  - schema
  - validation
  - json-schema
  - parser
last_updated: "2026-04-27"
version: "2.7.0"
---

# Sigma Schema Reference

Module: `zettelforge.sigma.parser`, `zettelforge.sigma.schemas`

```python
from zettelforge.sigma.parser import (
    parse_yaml, parse_file, validate,
    SigmaParseError, SigmaValidationError, ValidationResult,
)
from zettelforge.sigma.ingest import ingest_rule, ingest_rules_dir
```

---

## Overview

ZettelForge vendors three SigmaHQ JSON schemas for rule validation and dispatches
rules to the correct schema based on their top-level keys. The parser uses
`jsonschema.Draft202012Validator` for schema conformance checking.

**SigmaHQ specification version**: V2.0.0 (2024-08-08)  
**JSON Schema draft**: 2020-12  

---

## Vendored Schemas

Three schema files live in `src/zettelforge/sigma/schemas/`:

| File | Schema Title | Used When |
|:-----|:-------------|:----------|
| `sigma-detection-rule-schema.json` | Sigma rule specification V2.0.0 | No `correlation:` or `filter:` key present |
| `sigma-correlation-rules-schema.json` | Sigma correlation rules | `correlation:` key present in top-level dict |
| `sigma-filters-schema.json` | Sigma filters | `filter:` key present in top-level dict |

### Schema Loading

Schemas are loaded lazily and cached in `_SCHEMA_CACHE`:

```python
def _load_schema(name: str) -> dict[str, Any]:
    """Load a vendored schema JSON by filename (cached)."""
```

The `importlib.resources` API locates schema files within the `zettelforge.sigma.schemas`
package directory. Schemas are loaded as raw JSON (not YAML) and validated against
the Draft 2020-12 meta-schema.

---

## Schema Dispatch Logic

The `_pick_schema()` function implements dispatch:

```python
def _pick_schema(rule: dict[str, Any]) -> dict[str, Any]:
    if isinstance(rule, dict):
        if "correlation" in rule:
            return _load_schema("sigma-correlation-rules-schema.json")
        if "filter" in rule:
            return _load_schema("sigma-filters-schema.json")
    return _load_schema("sigma-detection-rule-schema.json")
```

Dispatch order:
1. `correlation` key present -> correlation schema
2. `filter` key present -> filters schema
3. Otherwise -> detection-rule schema

---

## Detection Rule Schema (V2.0.0)

Required top-level keys: `title`, `logsource`, `detection`

### Top-Level Properties

| Property | Type | Required | Description |
|:---------|:-----|:--------:|:------------|
| `title` | `string` (max 256) | yes | Brief title describing what the rule detects |
| `id` | `string` (UUID format) | no | Globally unique identifier (UUID v4 recommended) |
| `related` | `array` of objects | no | Related rule references with `id` and `type` |
| `name` | `string` (max 256) | no | Human-readable name for correlation rule references |
| `taxonomy` | `string` (max 256) | no | Taxonomy used in the rule |
| `status` | `string` (enum) | no | One of `stable`, `test`, `experimental`, `deprecated`, `unsupported` |
| `description` | `string` | no | Detailed rule description |
| `references` | `array` of strings | no | External references and URLs |
| `author` | `string` | no | Rule author |
| `date` | `string` (date) | no | Creation date (ISO 8601) |
| `modified` | `string` (date) | no | Last modification date |
| `tags` | `array` of strings | no | Rule tags (MITRE ATT&CK, CVE, etc.) |
| `level` | `string` (enum) | no | One of `informational`, `low`, `medium`, `high`, `critical` |
| `logsource` | `object` | yes | Log source definition with `product`, `service`, `category` |
| `detection` | `object` | yes | Detection logic with selections and condition |
| `falsepositives` | `array` of strings | no | Known false-positive scenarios |
| `fields` | `array` of strings | no | Log field names required for correlation |
| `license` | `string` | no | Rule license identifier |

### `logsource` Object

| Property | Type | Description |
|:---------|:-----|:------------|
| `product` | `string` | Log source product (e.g. `windows`, `linux`) |
| `service` | `string` | Log source service (e.g. `security`, `sysmon`) |
| `category` | `string` | Log source category (e.g. `process_creation`, `file_event`) |
| `definition` | `string` | Log source definition text |

### `detection` Object

The detection block must contain at minimum a `condition` string and one or
more named selection groups. Each selection is a mapping of field names to
values or lists of values supporting Sigma's modifiers (`|contains`, `|endswith`,
`|startswith`, `|re`, etc.).

### `status` Enum Values

| Value | Description |
|:------|:------------|
| `stable` | No false positives in multiple environments over long period |
| `test` | No obvious false positives on limited test systems |
| `experimental` | New rule, potentially many false positives |
| `deprecated` | Replaced by another rule or no longer relevant |
| `unsupported` | Cannot be supported due to product changes |

### `level` Enum Values

| Value | Description |
|:------|:------------|
| `informational` | Not an attack, but of security interest |
| `low` | Low severity |
| `medium` | Medium severity |
| `high` | High severity |
| `critical` | Critical severity |

### `related[].type` Enum Values

| Value | Description |
|:------|:------------|
| `derived` | Rule derived from referred rule (rule may still be active) |
| `obsolete` | This rule obsoletes the referred rule |
| `merged` | Rule merged from referred rules |
| `renamed` | Rule was renamed from previous identifier |
| `similar` | Related rules with similar detection content |

---

## Correlation Rules Schema

The correlation schema adds the `correlation` object and removes the
`detection` requirement. A correlation rule defines relationships between
multiple detection rules.

Key properties (in addition to detection rule common fields):

| Property | Type | Description |
|:---------|:-----|:------------|
| `correlation` | `object` | Correlation definition with `type`, `rule`, `group-by`, `timespan` |
| `correlation.type` | `string` | One of `event_count`, `value_count`, `temporal`, `ordered`, `sequence` |
| `correlation.rule` | `string` or `array` | Referenced rule names or IDs |

---

## Filters Schema

The filters schema adds the `filter` key. Filter rules define event filtering
conditions applied before detection.

Key properties (in addition to detection rule common fields):

| Property | Type | Description |
|:---------|:-----|:------------|
| `filter` | `object` | Filter definition with selections and condition |

---

## Parser API

### parse_yaml()

```python
def parse_yaml(text: str) -> dict[str, Any]
```

Parses Sigma YAML text into a validated dict.

1. Calls `yaml.safe_load(text)` to parse YAML
2. Coerces YAML-parsed `date`/`datetime` objects back to ISO-8601 strings
   (PyYAML's default resolver converts ISO date strings to `datetime.date`)
3. Runs `validate()` against the appropriate vendored schema
4. Raises `SigmaParseError` on YAML errors or `SigmaValidationError` on schema violations

**Date coercion**: The `_stringify_dates()` function recursively walks the
parsed dict and converts any `datetime.date` or `datetime.datetime` instances
to ISO-8601 string format. This prevents false schema validation failures
caused by PyYAML's auto-conversion of date-like strings.

### parse_file()

```python
def parse_file(path: str | Path) -> dict[str, Any]
```

Parses a Sigma rule file into a validated dict.

- File size limit: `MAX_RULE_FILE_BYTES = 1_048_576` (1 MB)
- Raises `SigmaParseError` if the file is oversized ( > 1 MB) or unreadable
- Wraps any `SigmaParseError`/`SigmaValidationError` with the file path prefix

### validate()

```python
def validate(rule: dict[str, Any]) -> ValidationResult
```

Validates a parsed Sigma rule dict against the appropriate schema. Returns a
`ValidationResult` listing each violation with a dotted path to the offending
field rather than opaque jsonschema internals.

---

## Error Types

### SigmaParseError

```python
class SigmaParseError(ValueError)
```

Raised when a Sigma rule cannot be parsed (bad YAML, I/O error, oversized file).

### SigmaValidationError

```python
class SigmaValidationError(ValueError)
```

Raised when a Sigma rule fails JSON-schema validation against the vendored schema.

---

## ValidationResult

```python
@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid
```

`errors` contains human-readable messages with dotted field paths:
- `detection.condition: 'selections' is a required property`
- `logsource: 'product' is a required property`
- `<root>: 'title' is a required property`

---

## Ingestion Pipeline

The `ingest_rule()` function in `sigma.ingest` orchestrates the full pipeline:

1. **Parse & validate** YAML against the vendored SigmaHQ schema via `parse_file()` or `parse_yaml()`
2. **Build entity** via `from_rule_dict()` which returns a `SigmaRule` instance and a list of relation dicts
3. **Construct note content** (YAML body + summary line with title, level, status, logsource)
4. **Persist** note via `MemoryManager.remember()` with `source_type="sigma_rule"`
5. **Write KG edges** via `store.add_kg_edge()` for each relation

### Idempotency

Source ref pattern: `sigma:<rule_id>:<content_sha256[:12]>`
A store lookup precedes every write. Unchanged rules return the original note.

### Security Guards

- File size capped at 1 MB (`MAX_RULE_FILE_BYTES`)
- Symlinks are never followed during directory walk (`ingest_rules_dir`)
- Paths that resolve outside the rules root are skipped

### Edge Tagging

All KG edges emitted during ingest carry:
- `edge_type: detection` — distinguishes from causal or heuristic edges
- `source: sigma_ingest` — provenance tag for downstream filtering

---

## File Size Limit

```python
MAX_RULE_FILE_BYTES = 1_048_576  # 1 MB
```

Sigma rules are typically a few KB. The 1 MB ceiling catches runaway payloads
without blocking normal multi-rule files.

---

## Minimal Example

```python
from zettelforge.sigma import parse_yaml, validate

yaml_text = \"\"\"
title: Suspicious Whoami Execution
logsource:
  category: process_creation
  product: windows
detection:
  selection:
    Image|endswith: '\\\\whoami.exe'
  condition: selection
\"\"\"

rule = parse_yaml(yaml_text)
result = validate(rule)
print(f"Valid: {bool(result)}")
```

## Full Example

```python
from zettelforge.sigma import parse_file, from_rule_dict, SigmaValidationError

try:
    rule = parse_file("/path/to/sigma/rules/proc_creation_win_whoami.yml")
    entity, relations = from_rule_dict(rule)
    print(f"Rule: {entity.title}")
    print(f"Type: {entity.rule_type}")
    print(f"Logsource: product={entity.logsource_product}, category={entity.logsource_category}")
    print(f"Relations: {len(relations)}")
    for rel in relations:
        print(f"  {rel['rel']} -> {rel['to_type']}:{rel['to_value']}")
except SigmaValidationError as e:
    print(f"Validation failed: {e}")
```

---

## Dataclass Round-Trip

The parsed rule dict can be round-tripped through `from_rule_dict()` and
`ingest_rule()` (which accepts a pre-parsed dict as input):

```python
rule_dict = parse_yaml(yaml_text)
entity, relations = from_rule_dict(rule_dict)

# Pre-parsed dict can be fed back to ingest_rule without re-parsing
note, rels = ingest_rule(rule_dict, mm)
```
