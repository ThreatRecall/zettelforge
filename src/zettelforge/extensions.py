"""
Extension loader for optional packages.

ZettelForge checks for installed extension packages at startup.
Extensions provide alternative backends (TypeDB), integrations
(OpenCTI), and operational features (multi-tenant auth).

If no extensions are installed, all features use built-in backends.
"""

import logging
import os
from typing import Any

_logger = logging.getLogger("zettelforge.extensions")
_extensions: dict[str, Any] = {}
_loaded = False


def load_extensions() -> None:
    """Discover and load installed extension packages."""
    global _loaded
    if _loaded:
        return

    # Check 1: Try importing the enterprise package
    try:
        import zettelforge_enterprise

        _extensions["enterprise"] = zettelforge_enterprise
        _logger.info("Loaded zettelforge-enterprise extensions")
    except ImportError:
        pass

    # Check 2: Legacy env var fallback (backward compat for existing users)
    if "enterprise" not in _extensions:
        key = os.environ.get("THREATENGRAM_LICENSE_KEY", "").strip()
        if key.startswith("TG-") and len(key.split("-")) == 5:
            _extensions["enterprise"] = True  # Marker, not a module
            _logger.info("Enterprise activated via THREATENGRAM_LICENSE_KEY")

    _loaded = True


def has_extension(name: str) -> bool:
    """Check if an extension is available."""
    if not _loaded:
        load_extensions()
    return name in _extensions


def get_extension(name: str) -> Any | None:
    """Get a loaded extension module, or None."""
    if not _loaded:
        load_extensions()
    return _extensions.get(name)


def reset_extensions() -> None:
    """Reset extension state (for testing)."""
    import sys

    global _loaded
    _extensions.clear()
    _loaded = False
    # Remove cached enterprise module so next load_extensions() re-evaluates
    sys.modules.pop("zettelforge_enterprise", None)
