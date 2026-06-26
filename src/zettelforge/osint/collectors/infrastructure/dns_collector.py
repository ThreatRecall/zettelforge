"""
DNS collector — Phase 1 anchor (RFC-016 §5).

Resolves a DomainName input into A, AAAA, NS, and MX records. Each record
is emitted as a ``CollectorTuple`` ready for KG ingestion.

Design notes:
- Synchronous. The codebase has zero asyncio usage today; matching that is a
  Phase 1 decision recorded in SCOPING_DOC.md §0.
- Tests mock ``dns.resolver.Resolver.resolve`` to avoid network in CI.
- NXDOMAIN / NoAnswer / Timeout return an empty list (no exception). Other
  network errors propagate.
- TXT records are intentionally skipped: there is no Phase 1 entity for them.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from zettelforge.log import get_logger
from zettelforge.osint.ontology import (
    canonicalize_domain,
    canonicalize_ipv6,
    canonicalize_mx,
)
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.dns")

DEFAULT_TIMEOUT = 5.0
DEFAULT_LIFETIME = 5.0


def _make_resolver(timeout: float, lifetime: float) -> Any:
    """Return a dnspython ``Resolver`` or raise ``ImportError`` if missing.

    Isolated so tests can patch this single seam. dnspython is not strictly
    required for the module to load — collector will return [] and log if
    the import fails at call time.
    """
    import dns.resolver  # imported lazily so the package loads without dnspython

    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = lifetime
    return resolver


def _resolve(resolver: Any, domain: str, rdtype: str) -> list[Any]:
    """Run a single resolve; absorb the documented "empty result" exceptions."""
    import dns.exception
    import dns.resolver

    try:
        answer = resolver.resolve(domain, rdtype)
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.exception.Timeout,
    ) as exc:
        _logger.debug(
            "dns_empty_result",
            domain=domain,
            rdtype=rdtype,
            error=type(exc).__name__,
        )
        return []
    return list(answer)


def _reverse_pointer(ip: str) -> Any:
    """Return the dnspython reverse-pointer name for an IP. Seam for tests."""
    import dns.reversename

    return dns.reversename.from_address(ip)


def _collect_ptr(ip: str, timeout: float, lifetime: float) -> list[CollectorTuple]:
    """Reverse-resolve an IP to its PTR DomainName(s) via the ``hosts`` edge.

    Forward DNS (domain -> A/AAAA/NS/MX) was already live in Phase 1; this
    fills the inverse direction for IP seeds. Returns ``[]`` on invalid IP,
    missing dnspython, or no PTR record.
    """
    try:
        canonical_ip = ipaddress.ip_address(ip)
    except ValueError:
        _logger.debug("dns_invalid_ip", ip=ip)
        return []
    # Reverse DNS on private / reserved / documentation IPs is pointless and
    # would leak a needless query; skip them (also keeps unit tests offline).
    if not canonical_ip.is_global:
        _logger.debug("dns_skip_non_global_ip", ip=str(canonical_ip))
        return []
    family = "IPv6Address" if isinstance(canonical_ip, ipaddress.IPv6Address) else "IPv4Address"

    try:
        resolver = _make_resolver(timeout, lifetime)
        pointer = _reverse_pointer(str(canonical_ip))
    except ImportError:
        _logger.warning("dns_collector_missing_dnspython", ip=str(canonical_ip))
        return []

    out: list[CollectorTuple] = []
    seen: set[str] = set()
    for rdata in _resolve(resolver, pointer, "PTR"):
        name = canonicalize_domain(str(rdata))
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(
            CollectorTuple(
                output_entity_type="DomainName",
                output_value=name,
                edge_type="hosts",
                from_entity_type=family,
                to_entity_type="DomainName",
                output_props={"value": name},
                edge_props={},
            )
        )
    return out


def collect(
    input_entity_type: str,
    input_value: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    lifetime: float = DEFAULT_LIFETIME,
) -> list[CollectorTuple]:
    """Collect DNS records for a DomainName seed, or PTR for an IP seed.

    Parameters
    ----------
    input_entity_type : str
        ``"DomainName"`` (forward A/AAAA/NS/MX) or ``"IPv4Address"`` /
        ``"IPv6Address"`` (reverse PTR -> DomainName). Other types return [].
    input_value : str
        Domain or IP to resolve. Domains are canonicalized (lowercased,
        trailing dot stripped) before lookup.

    Returns
    -------
    list[CollectorTuple]
        One tuple per record. Empty list on lookup miss or when dnspython is
        not installed.
    """
    if input_entity_type in ("IPv4Address", "IPv6Address"):
        return _collect_ptr(input_value, timeout, lifetime)

    if input_entity_type != "DomainName":
        return []

    domain = canonicalize_domain(input_value)
    if not domain:
        return []

    try:
        resolver = _make_resolver(timeout, lifetime)
    except ImportError:
        _logger.warning("dns_collector_missing_dnspython", domain=domain)
        return []

    out: list[CollectorTuple] = []

    # A records → IPv4Address resolves_to
    for rdata in _resolve(resolver, domain, "A"):
        ip = str(rdata).strip()
        if not ip:
            continue
        out.append(
            CollectorTuple(
                output_entity_type="IPv4Address",
                output_value=ip,
                edge_type="resolves_to",
                from_entity_type="DomainName",
                to_entity_type="IPv4Address",
                output_props={"value": ip},
                edge_props={},
            )
        )

    # AAAA records → IPv6Address resolves_to
    for rdata in _resolve(resolver, domain, "AAAA"):
        try:
            canonical = canonicalize_ipv6(str(rdata))
        except (ValueError, TypeError):
            _logger.debug("dns_invalid_aaaa", domain=domain, raw=str(rdata))
            continue
        out.append(
            CollectorTuple(
                output_entity_type="IPv6Address",
                output_value=canonical,
                edge_type="resolves_to",
                from_entity_type="DomainName",
                to_entity_type="IPv6Address",
                output_props={"value": canonical},
                edge_props={},
            )
        )

    # NS records → NSRecord ns_for
    for rdata in _resolve(resolver, domain, "NS"):
        nsdname = canonicalize_domain(str(rdata))
        if not nsdname:
            continue
        out.append(
            CollectorTuple(
                output_entity_type="NSRecord",
                output_value=nsdname,
                edge_type="ns_for",
                from_entity_type="DomainName",
                to_entity_type="NSRecord",
                output_props={"nsdname": nsdname},
                edge_props={},
            )
        )

    # MX records → MXRecord mx_for
    for rdata in _resolve(resolver, domain, "MX"):
        priority = getattr(rdata, "preference", None)
        exchange = getattr(rdata, "exchange", None)
        if priority is None or exchange is None:
            continue
        try:
            canonical = canonicalize_mx(int(priority), str(exchange))
        except (ValueError, TypeError):
            _logger.debug("dns_invalid_mx", domain=domain, raw=str(rdata))
            continue
        out.append(
            CollectorTuple(
                output_entity_type="MXRecord",
                output_value=canonical,
                edge_type="mx_for",
                from_entity_type="DomainName",
                to_entity_type="MXRecord",
                output_props={
                    "priority": int(priority),
                    "exchange": canonicalize_domain(str(exchange)),
                },
                edge_props={},
            )
        )

    return out


_METADATA = TransformMetadata(
    name="dns_collector",
    description=(
        "Forward-resolve a domain to A, AAAA, NS, MX records, or "
        "reverse-resolve an IP to its PTR DomainName."
    ),
    input_types=("DomainName", "IPv4Address", "IPv6Address"),
    output_types=(
        ("IPv4Address", "resolves_to"),
        ("IPv6Address", "resolves_to"),
        ("NSRecord", "ns_for"),
        ("MXRecord", "mx_for"),
        ("DomainName", "hosts"),
    ),
    api_dependencies=("dnspython",),
    rate_limit=None,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
