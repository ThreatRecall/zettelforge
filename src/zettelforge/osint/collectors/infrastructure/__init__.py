"""
Infrastructure-tier collectors (RFC-016 Phase 1 + 1.5).

Importing this package imports each collector module so the modules can
self-register with ``TRANSFORM_REGISTRY`` at load time.

Phase 1 (functional): dns, whois, cert.
Phase 1.5 (stubs): bgp, port_scanner.
"""

from zettelforge.osint.collectors.infrastructure import (
    bgp_collector,
    cert_collector,
    dns_collector,
    port_scanner,
    whois_collector,
)

__all__ = [
    "bgp_collector",
    "cert_collector",
    "dns_collector",
    "port_scanner",
    "whois_collector",
]
