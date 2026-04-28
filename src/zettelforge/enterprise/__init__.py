"""
ThreatRecall Enterprise stub.

The enterprise package has moved to a separate private repository.
Install it with: pip install zettelforge-enterprise

This stub allows edition detection to check for the enterprise package.
"""


def is_licensed() -> bool:
    """Check for enterprise license via the separate enterprise package."""
    try:
        from zettelforge_enterprise import is_licensed as _check

        return _check()
    except ImportError:
        return False
