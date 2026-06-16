"""
Wallet -> Transaction collector — AGE-120 (RFC-016 §5).

Given a ``CryptoWallet`` seed, fetches its recent transactions from an
Etherscan-compatible block-explorer API and emits one ``Transaction`` per
hit, linked to the wallet via ``sent_transaction`` (wallet is the sender) or
``received_transaction`` (wallet is the recipient). A self-transfer emits
both.

Scope: EVM hex wallets (``0x...``) on the Etherscan API only. Non-hex
addresses (e.g. Bitcoin base58) return ``[]`` — other chains are a follow-up.

Key handling
------------
The API key is read from ``ETHERSCAN_API_KEY`` at call time and passed only
as the ``apikey`` query parameter. It is never logged. Without the key the
collector fails closed and returns ``[]``.

No retries: AGENTS.OE Override 4 forbids silent retry. Any HTTP / parse
error logs a warning and returns ``[]``.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from zettelforge.log import get_logger
from zettelforge.osint.ontology import canonicalize_tx_hash, canonicalize_wallet
from zettelforge.osint.transform_registry import (
    TRANSFORM_REGISTRY,
    CollectorTuple,
    TransformMetadata,
)

_logger = get_logger("zettelforge.osint.collectors.wallet")

API_KEY_ENV = "ETHERSCAN_API_KEY"
API_URL = "https://api.etherscan.io/v2/api"
CHAIN = "eth"
CHAIN_ID = "1"
DEFAULT_TIMEOUT = 15.0
# Cap so a high-volume wallet cannot flood the graph in one collection.
MAX_TX = 100


def _fetch_transactions(wallet: str, api_key: str) -> list[dict[str, Any]]:
    """Call Etherscan V2 ``account/txlist``. Returns the parsed tx list.

    The API key travels only in the query string and is never logged. A
    ``status`` of ``"0"`` (no transactions or upstream error) yields ``[]``.
    """
    params = {
        "chainid": CHAIN_ID,
        "module": "account",
        "action": "txlist",
        "address": wallet,
        "startblock": "0",
        "endblock": "99999999",
        "page": "1",
        "offset": str(MAX_TX),
        "sort": "desc",
        "apikey": api_key,
    }
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            response = client.get(API_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        _logger.warning(
            "wallet_collector_http_error",
            wallet=wallet,
            error_type=exc.__class__.__name__,
            status_code=status_code,
        )
        return []
    except ValueError as exc:  # JSON decode error
        _logger.warning(
            "wallet_collector_json_error",
            wallet=wallet,
            error_type=exc.__class__.__name__,
        )
        return []
    if not isinstance(payload, dict):
        _logger.warning("wallet_collector_unexpected_shape", wallet=wallet)
        return []
    result = payload.get("result")
    if not isinstance(result, list):
        # status "0" with a string message (e.g. "No transactions found").
        _logger.debug("wallet_collector_no_result", wallet=wallet, status=payload.get("status"))
        return []
    return [tx for tx in result if isinstance(tx, dict)]


def _tx_props(record: dict[str, Any]) -> dict[str, Any] | None:
    """Map an Etherscan tx record to ``Transaction`` entity properties.

    Returns ``None`` if the record has no usable ``hash`` (the required field).
    """
    raw_hash = record.get("hash")
    if not isinstance(raw_hash, str) or not raw_hash.strip():
        return None
    props: dict[str, Any] = {"tx_hash": canonicalize_tx_hash(raw_hash), "chain": CHAIN}
    for src, dst in (
        ("from", "from_address"),
        ("to", "to_address"),
        ("value", "value"),
        ("timeStamp", "timestamp"),
        ("blockNumber", "block"),
    ):
        value = record.get(src)
        if isinstance(value, str) and value.strip():
            props[dst] = value.strip()
    return props


def _to_tuples(wallet: str, records: list[dict[str, Any]]) -> list[CollectorTuple]:
    """Map tx records to sent/received CollectorTuples for ``wallet``."""
    out: list[CollectorTuple] = []
    seen: set[tuple[str, str]] = set()
    for record in records[:MAX_TX]:
        props = _tx_props(record)
        if props is None:
            continue
        tx_hash = props["tx_hash"]
        sender = str(record.get("from", "")).strip().lower()
        recipient = str(record.get("to", "")).strip().lower()

        if sender == wallet and ("sent", tx_hash) not in seen:
            seen.add(("sent", tx_hash))
            out.append(
                CollectorTuple(
                    output_entity_type="Transaction",
                    output_value=tx_hash,
                    edge_type="sent_transaction",
                    from_entity_type="CryptoWallet",
                    to_entity_type="Transaction",
                    output_props=props,
                    edge_props={},
                )
            )
        if recipient == wallet and ("received", tx_hash) not in seen:
            seen.add(("received", tx_hash))
            out.append(
                CollectorTuple(
                    output_entity_type="Transaction",
                    output_value=tx_hash,
                    edge_type="received_transaction",
                    from_entity_type="CryptoWallet",
                    to_entity_type="Transaction",
                    output_props=props,
                    edge_props={},
                )
            )
    return out


def collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    """Enumerate transactions for a CryptoWallet. Fail-closed without key."""
    if input_entity_type != "CryptoWallet":
        return []

    wallet = canonicalize_wallet(input_value)
    # EVM hex wallets only; non-hex addresses are out of scope for this backend.
    if not wallet.startswith("0x"):
        _logger.debug("wallet_collector_non_evm", wallet=wallet)
        return []

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        _logger.debug("wallet_collector_no_api_key", env=API_KEY_ENV)
        return []

    return _to_tuples(wallet, _fetch_transactions(wallet, api_key))


_METADATA = TransformMetadata(
    name="wallet_collector",
    description="Block explorer: enumerate a wallet's sent/received transactions.",
    input_types=("CryptoWallet",),
    output_types=(
        ("Transaction", "sent_transaction"),
        ("Transaction", "received_transaction"),
    ),
    api_dependencies=("etherscan.io",),
    rate_limit=5.0,
)


TRANSFORM_REGISTRY.register(_METADATA, collect)
