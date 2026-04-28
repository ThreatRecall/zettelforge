---
title: "Governance Controls Reference"
description: "GOV-003, GOV-007, GOV-011, and GOV-012 governance controls with enforcement points, validation rules, and error handling."
diataxis_type: "reference"
audience: "Senior CTI Practitioner"
tags:
  - governance
  - compliance
  - validation
  - security
  - audit
last_updated: "2026-04-09"
version: "2.0.0"
---

# Governance Controls Reference

Module: `zettelforge.governance_validator`

```python
from zettelforge.governance_validator import GovernanceValidator, GovernanceViolationError
```

---

## Control Summary

| Control ID | Name | Category | Enforcement Point | Validation Rule | Error Type |
|:-----------|:-----|:---------|:-------------------|:----------------|:-----------|
| GOV-003 | Python Standards | Code Quality | Build / CI | Type hints required; PEP 8 naming conventions enforced | Static analysis failure |
| GOV-007 | Testing Standards | Quality Assurance | Build / CI | Test coverage >= 80% required | CI gate failure |
| GOV-011 | Access Control & Input Validation | Security | Runtime (`remember`, `synthesize`) | All inputs validated before storage; no hardcoded secrets | `GovernanceViolationError` |
| GOV-012 | Audit Logging | Observability | Runtime (`remember`, `recall`, `synthesize`) | All memory operations logged with structured format | Silent (log-only) |

---

## GOV-003: Python Standards

**Purpose:** Enforce consistent code quality across the ZettelForge codebase.

| Rule | Requirement | Enforcement |
|:-----|:------------|:------------|
| Type hints | All public method signatures must include type annotations | Static analysis (mypy / pyright) |
| Naming | PEP 8 naming conventions: `snake_case` for functions and variables, `PascalCase` for classes | Linter (ruff / flake8) |
| Docstrings | All public classes and methods must have docstrings | Linter rule |

**Loaded rule key:** `python_standards`, `type_hints`, `naming`

```python
rules["GOV-003"] = {
    "python_standards": True,
    "type_hints": True,
    "naming": True
}
```

---

## GOV-007: Testing Standards

**Purpose:** Ensure adequate test coverage for memory operations.

| Rule | Requirement | Enforcement |
|:-----|:------------|:------------|
| Coverage threshold | Minimum 80% line coverage | CI gate (pytest-cov) |
| Test existence | Every public method must have at least one test | CI gate |

**Loaded rule key:** `testing`, `coverage`

```python
rules["GOV-007"] = {
    "testing": True,
    "coverage": 0.8
}
```

---

## GOV-011: Access Control & Input Validation

**Purpose:** Validate all inputs before memory storage. Prevent injection of malformed or dangerous content.

| Rule | Requirement | Enforcement |
|:-----|:------------|:------------|
| Input validation | Content must be a `str` or an object with a `content` attribute | Runtime check in `enforce()` |
| No hardcoded secrets | Content must not contain API keys, tokens, or credentials | Runtime check |
| Minimum content length | Content length >= `governance.min_content_length` (default: 1) | Config-driven |

**Loaded rule key:** `security`, `input_validation`, `no_hardcoded_secrets`

```python
rules["GOV-011"] = {
    "security": True,
    "input_validation": True,
    "no_hardcoded_secrets": True
}
```

**Enforcement behavior:**

```python
def enforce(self, operation: str, data: Any = None) -> None:
    """Raises GovernanceViolationError on validation failure."""
    is_valid, violations = self.validate_operation(operation, data)
    if not is_valid:
        raise GovernanceViolationError(
            f"Governance violation in {operation}: {violations}"
        )
```

**Operations validated:**

| Operation | Checks Applied |
|:----------|:---------------|
| `remember` | Input type validation (must be `str` or have `.content` attribute) |
| `synthesize` | Audit logging trigger (GOV-012) |

**Exception class:**

```python
class GovernanceViolationError(Exception):
    """Raised when a governance rule is violated."""
    pass
```

---

## GOV-012: Audit Logging

**Purpose:** Maintain an audit trail of all memory operations for compliance and debugging.

| Rule | Requirement | Enforcement |
|:-----|:------------|:------------|
| Structured logging | All operations emit structured log entries | Runtime (observability module) |
| Operation coverage | `remember`, `recall`, `synthesize` operations are logged | Silent enforcement |

**Loaded rule key:** `observability`, `structured_logging`

```python
rules["GOV-012"] = {
    "observability": True,
    "structured_logging": True
}
```

**Logging configuration:**

| Config Key | Type | Default | Description |
|:-----------|:-----|:--------|:------------|
| `logging.level` | `str` | `"INFO"` | Minimum log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `logging.log_intents` | `bool` | `True` | Log intent classification results. |
| `logging.log_causal` | `bool` | `True` | Log causal triple extraction results. |

---

## GovernanceValidator API

### Constructor

```python
class GovernanceValidator:
    def __init__(self, governance_dir: Path = None) -> None
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `governance_dir` | `Path` | `~/.openclaw/workspace/governance-documentation-package/governance` | Directory containing governance documentation files. |

### `validate_operation`

```python
def validate_operation(
    self,
    operation: str,
    data: Any = None
) -> Tuple[bool, List[str]]
```

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `operation` | `str` | *(required)* | Operation name: `remember`, `recall`, `synthesize`. |
| `data` | `Any` | `None` | Operation payload to validate. |

**Returns:** `Tuple[bool, List[str]]` -- `(is_valid, list_of_violation_strings)`.

### `enforce`

```python
def enforce(self, operation: str, data: Any = None) -> None
```

Calls `validate_operation` and raises `GovernanceViolationError` if any violations are found.

---

## Configuration

| Config Key | Type | Default | Env Override | Description |
|:-----------|:-----|:--------|:-------------|:------------|
| `governance.enabled` | `bool` | `True` | -- | Enable or disable governance validation. Set `False` for benchmarks. |
| `governance.min_content_length` | `int` | `1` | -- | Minimum character length for content passed to `remember()`. |

---

## LLM Quick Reference

ZettelForge enforces four governance controls at build time and runtime. GOV-003 and GOV-007 are build-time controls enforced through CI: GOV-003 requires type hints and PEP 8 naming; GOV-007 requires 80% test coverage.

GOV-011 is the primary runtime control. The `GovernanceValidator.enforce()` method is called at the start of every `remember()` operation. It validates that the input is a string or has a `.content` attribute. If validation fails, it raises `GovernanceViolationError`, which halts the operation before any data is written. The validator loads its rules from governance documentation files but also has hardcoded rule definitions as fallback.

GOV-012 is a silent runtime control that ensures audit logging. All memory operations (`remember`, `recall`, `synthesize`) trigger structured log entries. Logging granularity is controlled by the `logging.level`, `logging.log_intents`, and `logging.log_causal` configuration keys.

Governance can be disabled entirely by setting `governance.enabled: false` in config.yaml, which is recommended only for benchmarking and testing. The `min_content_length` config key (default 1) sets the minimum character count for stored content. The governance directory defaults to `~/.openclaw/workspace/governance-documentation-package/governance` and is configurable via the constructor parameter.
