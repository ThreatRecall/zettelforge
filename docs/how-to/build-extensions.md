---
title: "Build an Extension Package"
description: "Create an optional extension package for ZettelForge that provides an alternative backend (TypeDB), an integration (OpenCTI), or an operational feature (multi-tenant auth)."
diataxis_type: "how-to"
audience: "Python developers extending ZettelForge with optional packages"
tags: [extensions, enterprise, packages, development, optional-features]
last_updated: "2026-04-27"
version: "2.6.0"
---

# Build an Extension Package

ZettelForge discovers installed extension packages at startup via `zettelforge.extensions.load_extensions()`. An extension is any Python package that registers itself under the `zettelforge.extensions` namespace or is importable as `zettelforge_enterprise`.

## Prerequisites

- ZettelForge installed (`pip install zettelforge`)
- Python 3.12+
- For enterprise features: separate `zettelforge-enterprise` package (not distributed on PyPI)

## How Extensions Are Loaded

The extension loader in `zettelforge.extensions` follows a two-check discovery:

1. **Try importing `zettelforge_enterprise`** -- if the package is installed, it is loaded as the `"enterprise"` extension.
2. **Legacy env var fallback** -- if no package was found, check `THREATENGRAM_LICENSE_KEY`. If it matches the `TG-XXXX-XXXX-XXXX-XXXX` pattern, a marker is stored so `has_extension("enterprise")` returns `True`.

```python
from zettelforge.extensions import load_extensions, has_extension, get_extension

load_extensions()
print(has_extension("enterprise"))  # True or False
```

The loader is idempotent -- subsequent calls return the cached result without re-scanning the environment.

## Steps

### 1. Name your package

Use the `zettelforge_` prefix to keep naming consistent and avoid collisions:

- `zettelforge_enterprise` -- enterprise features (TypeDB, OpenCTI, telemetry)
- `zettelforge_myfeature` -- your custom feature

### 2. Create the package structure

```
zettelforge-myfeature/
  pyproject.toml
  src/
    zettelforge_myfeature/
      __init__.py
      feature.py
```

The `__init__.py` can be empty -- the extension loader only needs the package to be importable.

### 3. Register as a ZettelForge extension (optional)

If you want your extension to be discoverable beyond the `zettelforge_enterprise` naming convention, register via a plugin entry point in `pyproject.toml`:

```toml
[project.entry-points."zettelforge.extensions"]
myfeature = "zettelforge_myfeature"
```

Then consumers can check for it by name:

```python
from zettelforge.extensions import has_extension

if has_extension("myfeature"):
    # activate custom behaviour
```

### 4. Respect the edition API

Use the `zettelforge.edition` module to gate features behind the active edition:

```python
from zettelforge.edition import is_enterprise, EditionError

if not is_enterprise():
    raise EditionError("This feature requires ZettelForge Enterprise")
```

Available edition functions:

| Function | Returns | Description |
|:---------|:--------|:------------|
| `is_enterprise()` | `bool` | True if enterprise extensions are loaded |
| `is_community()` | `bool` | True if no enterprise extensions |
| `get_edition()` | `Edition` | `Edition.ENTERPRISE` or `Edition.COMMUNITY` |
| `edition_name()` | `str` | `"ZettelForge + Extensions"` or `"ZettelForge"` |

### 5. Expose extension features

Your extension package should provide the actual feature implementations. The `get_extension()` function lets core code access your extension module:

```python
from zettelforge.extensions import get_extension

enterprise = get_extension("enterprise")
if enterprise is not None:
    # Access TypeDB backend, OpenCTI sync, telemetry, etc.
    enterprise.register_backends()
```

### 6. Test your extension

Use the `reset_extensions()` function in setup/teardown to clear cached state between tests:

```python
import os
from unittest.mock import patch
from zettelforge.extensions import load_extensions, has_extension, reset_extensions

def test_extension_loaded():
    reset_extensions()
    # Simulate having the enterprise package
    with patch.dict("sys.modules", {"zettelforge_enterprise": __import__("types")}):
        load_extensions()
        assert has_extension("enterprise") is True


def test_extension_not_loaded():
    reset_extensions()
    # Simulate missing package
    with patch.dict("sys.modules", {"zettelforge_enterprise": None}):
        load_extensions()
        assert has_extension("enterprise") is False


def test_legacy_env_var_activates():
    reset_extensions()
    os.environ["THREATENGRAM_LICENSE_KEY"] = "TG-1234-5678-9abc-def0"
    with patch.dict("sys.modules", {"zettelforge_enterprise": None}):
        load_extensions()
        assert has_extension("enterprise") is True


def test_invalid_env_var_does_not_activate():
    reset_extensions()
    os.environ["THREATENGRAM_LICENSE_KEY"] = "invalid-key"
    with patch.dict("sys.modules", {"zettelforge_enterprise": None}):
        load_extensions()
        assert has_extension("enterprise") is False


def test_get_missing_returns_none():
    reset_extensions()
    with patch.dict("sys.modules", {"zettelforge_enterprise": None}):
        assert get_extension("enterprise") is None
```

### 7. Use the optional-feature pattern for SDK dependencies

If your extension depends on an optional SDK (e.g., `typedb-client`, `pycti`), follow the optional-feature pattern:

```python
class MyFeature:
    def __init__(self):
        self._sdk = None
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        if self._sdk is not None:
            return
        with self._lock:
            if self._sdk is not None:
                return
            try:
                import typedb  # lazy import
            except ImportError as exc:
                raise ImportError(
                    "TypeDB feature requires typedb-client. "
                    "Install with: pip install zettelforge-enterprise"
                ) from exc
            self._sdk = typedb
```

This ensures core ZettelForge never depends on your SDK, and the error surfaces only at the point of use.

## LLM Quick Reference

**Task**: Create a ZettelForge extension package.

**Key functions**: `load_extensions()` (idempotent discovery), `has_extension(name)` (boolean check), `get_extension(name)` (module or None), `reset_extensions()` (test cleanup).

**Edition module**: `is_enterprise()`, `is_community()`, `get_edition()`, `edition_name()` let core code gate features behind edition.

**Activation paths**: Package import (`zettelforge_enterprise`) takes priority. Legacy env var (`THREATENGRAM_LICENSE_KEY=TG-XXXX-XXXX-XXXX-XXXX`) is the fallback for backward compatibility.

**Test pattern**: `reset_extensions()` in setup, `patch.dict("sys.modules", ...)` to control whether the package exists, `patch.dict(os.environ, ...)` for env var tests.

**Optional SDK pattern**: Lazy-import the SDK in a private `_ensure_loaded()` method. Never import at module level. Surface a clear `ImportError` with install instructions.

**Entry point registration**: Add `[project.entry-points."zettelforge.extensions"]` in pyproject.toml for discovery by name beyond the `zettelforge_enterprise` convention.
