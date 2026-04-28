"""
WHOIS collector — Phase 1 (RFC-016 §5).

Two input branches:

- ``DomainName`` — use ``python-whois`` to extract the registrant
  Organization. Emits an Organization entity with an ``owned_by`` edge from
  the input domain.
- ``IPv4Address`` (or ``IPv6Address``) — use ``ipwhois`` to extract the
  containing Netblock, the registrant Organization, and the origin AS.
  Emits ``associated_with`` (IP -> Netblock), ``owned_by`` (Netblock -> Org),
  and ``part_of_as`` (IP -> ASNumber) edges.

Both backends are optional: a missing import logs a warning and returns
``[]``. Tests inject fakes for both libraries via the seam helpers below.

No retries. WHOIS is rate-limited by upstream; surfacing the failure is
preferable to silent retry per AGENTS.OE Override 4.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from zettelforge.log import get_logger
from zettelforge.osint.ontology import (
    canonicalize_asn,
    canonicalize_cidr,
    canonicalize_domain,
)
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.whois")


# ---------------------------------------------------------------------------
# Library seams (so tests can patch a single function)
# ---------------------------------------------------------------------------


def _lookup_domain(domain: str) -> Any | None:
    """Run a domain WHOIS via ``python-whois``. Returns the parsed object."""
    try:
        import whois
    except ImportError:
        _logger.warning("whois_collector_missing_python_whois", domain=domain)
        return None
    return whois.whois(domain)


def _lookup_ip(ip: str) -> dict | None:
    """Run an IP WHOIS via ``ipwhois``. Returns the RDAP-shaped dict.

    Returns None on:
    - ipwhois library missing,
    - reserved / non-routable IPs (RFC 5735 / 5737 / 6890 ranges that
      ipwhois rejects with IPDefinedError),
    - any other ipwhois failure (network, parse, etc.).

    AGENTS.OE Override 4 applies: surface failures, no silent retry.
    Reserved-IP cases are logged at debug; real network failures at warning.
    """
    try:
        from ipwhois import IPWhois
        from ipwhois.exceptions import BaseIpwhoisException, IPDefinedError
    except ImportError:
        _logger.warning("whois_collector_missing_ipwhois", ip=ip)
        return None
    try:
        obj = IPWhois(ip)
        return obj.lookup_rdap(depth=0)
    except IPDefinedError as exc:
        # 192.0.2.x (TEST-NET-1), 10.0.0.x (private), 127.0.0.1, etc.
        _logger.debug("whois_ip_reserved", ip=ip, error=str(exc))
        return None
    except BaseIpwhoisException as exc:
        _logger.warning("whois_ip_lookup_failed", ip=ip, error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Helpers for parsing whois library output
# ---------------------------------------------------------------------------


def _first_string(value: Any) -> str | None:
    """python-whois returns either str or list[str] for many fields."""
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value).strip() or None


def _domain_org(record: Any) -> str | None:
    """Extract the registrant org from a python-whois record.

    python-whois exposes attributes (``record.org``) AND dict-style access.
    Try the common keys in order of specificity.
    """
    for attr in ("org", "organization", "registrant", "name"):
        try:
            value = getattr(record, attr, None)
        except Exception:  # pragma: no cover — defensive
            value = None
        if value is None and isinstance(record, dict):
            value = record.get(attr)
        org = _first_string(value)
        if org:
            return org
    return None


# ---------------------------------------------------------------------------
# Branch implementations
# ---------------------------------------------------------------------------


def _collect_domain(domain: str) -> list[CollectorTuple]:
    record = _lookup_domain(domain)
    if record is None:
        return []
    org = _domain_org(record)
    if not org:
        _logger.debug("whois_no_registrant", domain=domain)
        return []
    return [
        CollectorTuple(
            output_entity_type="Organization",
            output_value=org,
            edge_type="owned_by",
            from_entity_type="DomainName",
            to_entity_type="Organization",
            output_props={"name": org},
            edge_props={},
        )
    ]


def _ip_address_family(ip: str) -> str:
    parsed = ipaddress.ip_address(ip)
    return "IPv6Address" if isinstance(parsed, ipaddress.IPv6Address) else "IPv4Address"


def _collect_ip(ip: str) -> list[CollectorTuple]:
    try:
        canonical_ip = str(ipaddress.ip_address(ip))
    except ValueError:
        _logger.debug("whois_invalid_ip", ip=ip)
        return []

    rdap = _lookup_ip(canonical_ip)
    if rdap is None:
        return []

    family = _ip_address_family(canonical_ip)
    out: list[CollectorTuple] = []

    network = rdap.get("network") or {}
    cidr_raw = network.get("cidr")
    org_name: str | None = None

    # Walk RDAP entities to find the registrant org if available.
    for entity in rdap.get("objects", {}).values() if isinstance(rdap.get("objects"), dict) else []:
        contact = entity.get("contact") or {}
        candidate = contact.get("name")
        if candidate:
            org_name = str(candidate).strip()
            break

    if not org_name:
        # ipwhois sometimes nests the registrant name on the network entry itself.
        org_name = network.get("name") if isinstance(network.get("name"), str) else None

    if cidr_raw:
        # ipwhois returns cidr as either a single CIDR string or a comma-list.
        primary_cidr = cidr_raw.split(",")[0].strip()
        try:
            cidr = canonicalize_cidr(primary_cidr)
        except ValueError:
            _logger.debug("whois_invalid_cidr", ip=canonical_ip, raw=primary_cidr)
            cidr = None
        if cidr:
            out.append(
                CollectorTuple(
                    output_entity_type="Netblock",
                    output_value=cidr,
                    edge_type="associated_with",
                    from_entity_type=family,
                    to_entity_type="Netblock",
                    output_props={"cidr": cidr},
                    edge_props={},
                )
            )
            if org_name:
                out.append(
                    CollectorTuple(
                        output_entity_type="Organization",
                        output_value=org_name,
                        edge_type="owned_by",
                        from_entity_type="Netblock",
                        to_entity_type="Organization",
                        output_props={"name": org_name},
                        edge_props={"cidr": cidr},
                    )
                )

    asn_raw = rdap.get("asn")
    if asn_raw:
        # asn may contain whitespace-separated multiple ASNs; take the first.
        first = str(asn_raw).split()[0]
        try:
            asn = canonicalize_asn(first)
        except ValueError:
            _logger.debug("whois_invalid_asn", ip=canonical_ip, raw=asn_raw)
            asn = None
        if asn:
            asn_props: dict[str, Any] = {"number": int(asn)}
            for key, target in (
                ("asn_description", "description"),
                ("asn_country_code", "description"),
            ):
                value = rdap.get(key)
                if isinstance(value, str) and value.strip():
                    asn_props.setdefault(target, value.strip())
            out.append(
                CollectorTuple(
                    output_entity_type="ASNumber",
                    output_value=asn,
                    edge_type="part_of_as",
                    from_entity_type=family,
                    to_entity_type="ASNumber",
                    output_props=asn_props,
                    edge_props={},
                )
            )

    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Run a WHOIS lookup for the given input and emit collector tuples.

    Accepts ``DomainName``, ``IPv4Address``, or ``IPv6Address``.
    Other types return ``[]``.
    """
    if input_entity_type == "DomainName":
        domain = canonicalize_domain(input_value)
        if not domain:
            return []
        return _collect_domain(domain)
    if input_entity_type in ("IPv4Address", "IPv6Address"):
        return _collect_ip(input_value)
    return []


_METADATA = TransformMetadata(
    name="whois_collector",
    description="Domain or IP WHOIS lookup; emits Organization, Netblock, and ASNumber.",
    input_types=("DomainName", "IPv4Address", "IPv6Address"),
    output_types=(
        ("Organization", "owned_by"),
        ("Netblock", "associated_with"),
        ("ASNumber", "part_of_as"),
    ),
    api_dependencies=("python-whois", "ipwhois"),
    rate_limit=None,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
