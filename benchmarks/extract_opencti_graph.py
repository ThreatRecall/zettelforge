"""Extract the REAL CTI graph from the local OpenCTI instance (read-only).

OpenSearch is not published to the host, so every query is issued from inside
the ``opencti-opensearch`` container via ``docker exec ... curl``. We page all
relationship documents with the scroll API and dump a node + edge list to a
JSON file the graph backend benchmark loads identically into both backends.

This is strictly read-only: the OpenCTI instance is never written. We only
issue ``_search`` / ``_search/scroll`` reads and a final ``DELETE`` of our own
scroll context (a read-cursor cleanup, not a data write).

Node identity (R3 fidelity note):
    OpenCTI node identity is ``internal_id`` (a UUID), which is globally
    unique. Both ZettelForge backends key node identity on
    ``(entity_type, entity_value)``. To preserve the real graph topology
    exactly (no accidental merging of two distinct entities that happen to
    share a display name), we set ``entity_value = internal_id`` and carry the
    human ``name`` only for hub reporting. ``entity_type`` is the most specific
    STIX type from the connection's ``types[]`` (skipping the generic
    ``Basic-Object`` / ``Stix-*`` umbrella types).

Edges:
    Each relationship ``_source`` has ``relationship_type`` and a 2-element
    ``connections`` array; the entry whose ``role`` ends in ``_from`` is the
    source, ``_to`` is the target. We emit one directed edge per relationship.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

CONTAINER = "opencti-opensearch"
OS_URL = "http://localhost:9200"
INDICES = [
    "opencti_stix_core_relationships-000001",
    "opencti_inferred_relationships-000001",
]

# Generic STIX umbrella types we skip when picking the most specific entity
# type for a node. Whatever specific type remains (Malware, Intrusion-Set,
# Threat-Actor, Indicator, Identity, Attack-Pattern, ...) is used.
_GENERIC_TYPES = {
    "Basic-Object",
    "Stix-Object",
    "Stix-Core-Object",
    "Stix-Domain-Object",
    "Stix-Cyber-Observable",
    "Stix-Relationship",
    "Stix-Core-Relationship",
}


def _curl_json(path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a curl GET/POST against OpenSearch inside the container.

    Body (when present) is written to a temp file on the host and piped in via
    ``docker exec -i ... curl -d @-`` so large scroll bodies and JSON quoting
    survive the shell boundary intact.
    """
    if body is None:
        out = subprocess.run(
            ["docker", "exec", CONTAINER, "curl", "-s", f"{OS_URL}{path}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(out.stdout)
    payload = json.dumps(body)
    out = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "curl",
            "-s",
            "-H",
            "Content-Type: application/json",
            "-X",
            "POST",
            f"{OS_URL}{path}",
            "-d",
            "@-",
        ],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as exc:  # surface the real OpenSearch error
        raise RuntimeError(
            f"OpenSearch returned non-JSON for {path}: {out.stdout[:500]!r}"
        ) from exc


def _delete_scroll(scroll_id: str) -> None:
    """Best-effort cleanup of our scroll cursor (a read context, not data)."""
    body = json.dumps({"scroll_id": scroll_id})
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "curl",
            "-s",
            "-H",
            "Content-Type: application/json",
            "-X",
            "DELETE",
            f"{OS_URL}/_search/scroll",
            "-d",
            "@-",
        ],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )


def _most_specific_type(types: list[str]) -> str:
    specific = [t for t in types if t not in _GENERIC_TYPES]
    if specific:
        # Prefer the longest/most descriptive specific type deterministically.
        return sorted(specific, key=lambda t: (-len(t), t))[0]
    return types[0] if types else "Unknown"


def _scroll_index(index: str, page_size: int) -> list[dict[str, Any]]:
    """Page all docs of ``index`` via the scroll API; return their ``_source``s."""
    sources: list[dict[str, Any]] = []
    first = _curl_json(
        f"/{index}/_search?scroll=5m",
        {"size": page_size, "_source": ["relationship_type", "connections"]},
    )
    if "error" in first:
        raise RuntimeError(f"OpenSearch error on {index}: {first['error']}")
    scroll_id = first.get("_scroll_id")
    hits = first["hits"]["hits"]
    while hits:
        sources.extend(h["_source"] for h in hits)
        nxt = _curl_json("/_search/scroll", {"scroll": "5m", "scroll_id": scroll_id})
        if "error" in nxt:
            raise RuntimeError(f"OpenSearch scroll error on {index}: {nxt['error']}")
        scroll_id = nxt.get("_scroll_id", scroll_id)
        hits = nxt["hits"]["hits"]
    if scroll_id:
        _delete_scroll(scroll_id)
    return sources


def extract(page_size: int) -> dict[str, Any]:
    # node internal_id -> {"type": str, "name": str}; first specific type wins,
    # but a later, more-specific, non-generic type can upgrade it.
    nodes: dict[str, dict[str, str]] = {}
    # directed unique edges keyed (from_id, to_id, rel)
    edges: dict[tuple[str, str, str], None] = {}
    dropped = Counter()
    raw_docs = 0

    def register_node(conn: dict[str, Any]) -> str | None:
        iid = conn.get("internal_id")
        if not iid:
            return None
        etype = _most_specific_type(conn.get("types", []) or [])
        name = conn.get("name") or iid
        cur = nodes.get(iid)
        if cur is None:
            nodes[iid] = {"type": etype, "name": name}
        return iid

    for index in INDICES:
        print(f"Scrolling {index} ...")
        srcs = _scroll_index(index, page_size)
        print(f"  {len(srcs)} docs")
        raw_docs += len(srcs)
        for src in srcs:
            conns = src.get("connections") or []
            rel = src.get("relationship_type") or "related-to"
            if len(conns) != 2:
                dropped["bad_connection_count"] += 1
                continue
            from_conn = next((c for c in conns if str(c.get("role", "")).endswith("_from")), None)
            to_conn = next((c for c in conns if str(c.get("role", "")).endswith("_to")), None)
            if from_conn is None or to_conn is None:
                # Fall back to positional order if roles are not suffixed.
                from_conn, to_conn = conns[0], conns[1]
            fid = register_node(from_conn)
            tid = register_node(to_conn)
            if not fid or not tid:
                dropped["missing_internal_id"] += 1
                continue
            if fid == tid:
                dropped["self_loop"] += 1
                continue
            edges[(fid, tid, rel)] = None

    node_list = [
        {"internal_id": iid, "type": meta["type"], "name": meta["name"]}
        for iid, meta in nodes.items()
    ]
    edge_list = [
        {"from": fid, "to": tid, "rel": rel} for (fid, tid, rel) in edges
    ]
    return {
        "raw_docs": raw_docs,
        "nodes": node_list,
        "edges": edge_list,
        "dropped": dict(dropped),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=str,
        default=str(Path(__file__).parent / "opencti_graph.json"),
    )
    parser.add_argument("--page-size", type=int, default=2000)
    args = parser.parse_args()

    data = extract(args.page_size)

    # Degree stats and top hubs (by total degree, in + out).
    deg: Counter = Counter()
    for e in data["edges"]:
        deg[e["from"]] += 1
        deg[e["to"]] += 1
    name_of = {n["internal_id"]: n["name"] for n in data["nodes"]}
    type_of = {n["internal_id"]: n["type"] for n in data["nodes"]}
    top = deg.most_common(15)
    data["stats"] = {
        "nodes": len(data["nodes"]),
        "edges": len(data["edges"]),
        "raw_docs": data["raw_docs"],
        "dropped": data["dropped"],
        "avg_degree": round(2 * len(data["edges"]) / max(1, len(data["nodes"])), 2),
        "max_degree": top[0][1] if top else 0,
        "top_hubs": [
            {
                "internal_id": iid,
                "name": name_of.get(iid, iid),
                "type": type_of.get(iid, "?"),
                "degree": d,
            }
            for iid, d in top
        ],
    }

    with open(args.out, "w") as f:
        json.dump(data, f)
    print(f"Wrote {args.out}")
    print(json.dumps(data["stats"], indent=2))


if __name__ == "__main__":
    main()
