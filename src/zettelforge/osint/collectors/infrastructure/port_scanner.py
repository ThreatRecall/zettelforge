"""
Port scanner collector — Phase 1.5 stub (RFC-016 §5).

WARNING: active scanning. This collector is gated behind a deliberate
opt-in environment variable (``ZETTELFORGE_OSINT_ACTIVE_SCAN=1``) AND
requires the target network to be owned or authorised for scanning.
Without the flag the collector returns ``[]`` immediately — no nmap
binary is invoked, no packets are sent.

Phase 1 ships registration metadata and the gating check. The full
nmap integration lands with Phase 1.5.
"""

from __future__ import annotations

import ipaddress
import os

from zettelforge.log import get_logger
from zettelforge.osint.ontology import canonicalize_port
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.port_scan")

ACTIVE_SCAN_FLAG = "ZETTELFORGE_OSINT_ACTIVE_SCAN"
DEFAULT_PORTS = (22, 80, 443, 445, 3389, 8080, 8443)


def _is_active_scan_enabled() -> bool:
    return os.environ.get(ACTIVE_SCAN_FLAG, "").strip() in ("1", "true", "TRUE", "yes")


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Scan common TCP ports on a host (gated; no-op by default).

    Returns ``[]`` unless ``ZETTELFORGE_OSINT_ACTIVE_SCAN=1`` AND a
    working ``python-nmap`` is importable AND ``nmap`` is on PATH.
    """
    if input_entity_type not in ("IPv4Address", "IPv6Address"):
        return []
    try:
        target = str(ipaddress.ip_address(input_value))
    except ValueError:
        return []

    if not _is_active_scan_enabled():
        _logger.debug("port_scan_gated_off", target=target, flag=ACTIVE_SCAN_FLAG)
        return []

    try:
        import nmap  # type: ignore[import-not-found]
    except ImportError:
        _logger.warning("port_scanner_missing_python_nmap", target=target)
        return []

    out: list[CollectorTuple] = []
    try:
        scanner = nmap.PortScanner()
        port_arg = ",".join(str(p) for p in DEFAULT_PORTS)
        scanner.scan(target, arguments=f"-sT -T4 -p {port_arg}")
    except Exception as exc:  # nmap binary missing / permission denied
        _logger.warning("port_scanner_failed", target=target, error=str(exc))
        return []

    for host in scanner.all_hosts():
        for proto in scanner[host].all_protocols():
            for port, state in scanner[host][proto].items():
                if state.get("state") != "open":
                    continue
                try:
                    canonical = canonicalize_port(port, proto)
                except ValueError:
                    continue
                out.append(
                    CollectorTuple(
                        output_entity_type="Port",
                        output_value=canonical,
                        edge_type="listens_on",
                        from_entity_type=input_entity_type,
                        to_entity_type="Port",
                        output_props={
                            "number": int(port),
                            "protocol": proto,
                            "service": state.get("name", ""),
                        },
                        edge_props={},
                    )
                )
    return out


_METADATA = TransformMetadata(
    name="port_scanner",
    description=(
        "Active TCP scan of common ports — gated behind "
        "ZETTELFORGE_OSINT_ACTIVE_SCAN=1 and requires network authorisation."
    ),
    input_types=("IPv4Address", "IPv6Address"),
    output_types=(("Port", "listens_on"),),
    api_dependencies=("python-nmap",),
    rate_limit=1.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
