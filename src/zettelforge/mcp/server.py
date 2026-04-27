"""ZettelForge MCP server implementation — JSON-RPC 2.0 over stdio."""

import json
import os
import sys
import threading
import time

from zettelforge import MemoryManager, __version__

# SQLite is the v2.2.0 community default; honour any caller-provided override.
# Setting this at import time (before MemoryManager is ever instantiated) keeps
# `from zettelforge.mcp import TOOLS` side-effect free while still ensuring the
# backend defaults to sqlite when the server actually runs.
os.environ.setdefault("ZETTELFORGE_BACKEND", "sqlite")

_mm: MemoryManager | None = None
_mm_lock = threading.Lock()


def get_mm() -> MemoryManager:
    """Return the process-wide MemoryManager, instantiating on first call.

    Deliberately lazy: importing ``zettelforge.mcp`` to inspect ``TOOLS`` or
    pull in ``run_stdio`` should not spin up a backend or start the
    enrichment worker thread. The cost is paid on the first tool call (or
    the first JSON-RPC request in ``run_stdio``).
    """
    global _mm
    if _mm is None:
        with _mm_lock:
            if _mm is None:
                _mm = MemoryManager()
    return _mm


def handle_tool_call(name: str, arguments: dict) -> dict:
    """Route MCP tool calls to ZettelForge methods."""

    # Backward compat: accept old threatrecall_* names.
    if name.startswith("threatrecall_"):
        name = name.replace("threatrecall_", "zettelforge_", 1)

    mm = get_mm()

    if name == "zettelforge_remember":
        content = arguments.get("content", "")
        domain = arguments.get("domain", "cti")
        source = arguments.get("source", "mcp")
        evolve = arguments.get("evolve", True)
        note, status = mm.remember(
            content, source_type="mcp", source_ref=source, domain=domain, evolve=evolve
        )
        return {
            "note_id": note.id if note else None,
            "status": status,
            "entities": note.semantic.entities[:10] if note else [],
        }

    elif name == "zettelforge_recall":
        query = arguments.get("query", "")
        k = arguments.get("k", 10)
        domain = arguments.get("domain")
        start = time.perf_counter()
        results = mm.recall(query, domain=domain, k=k, exclude_superseded=False)
        latency = time.perf_counter() - start
        return {
            "results": [
                {
                    "id": n.id,
                    "content": n.content.raw[:500],
                    "context": n.semantic.context,
                    "entities": n.semantic.entities[:10],
                    "tier": n.metadata.tier,
                    "confidence": n.metadata.confidence,
                }
                for n in results
            ],
            "count": len(results),
            "latency_ms": round(latency * 1000),
        }

    elif name == "zettelforge_synthesize":
        query = arguments.get("query", "")
        fmt = arguments.get("format", "direct_answer")
        result = mm.synthesize(query, format=fmt, k=10)
        return {
            "synthesis": result.get("synthesis", {}),
            "sources_count": result.get("metadata", {}).get("sources_count", 0),
        }

    elif name == "zettelforge_entity":
        entity_type = arguments.get("type", "actor")
        value = arguments.get("value", "")
        k = arguments.get("k", 5)
        results = mm.recall_entity(entity_type, value, k=k)
        return {
            "results": [
                {"id": n.id, "content": n.content.raw[:300], "tier": n.metadata.tier}
                for n in results
            ],
            "count": len(results),
        }

    elif name == "zettelforge_graph":
        entity_type = arguments.get("type", "actor")
        value = arguments.get("value", "")
        max_depth = arguments.get("max_depth", 2)
        paths = mm.traverse_graph(entity_type, value, max_depth=max_depth)
        return {
            "paths": [
                [
                    {"from": s["from_value"], "rel": s["relationship"], "to": s["to_value"]}
                    for s in path
                ]
                for path in paths[:20]
            ],
            "count": len(paths),
        }

    elif name == "zettelforge_stats":
        s = mm.get_stats()
        return {
            "version": __version__,
            "total_notes": s.get("total_notes", 0),
            "retrievals": s.get("retrievals", 0),
            "entity_index": s.get("entity_index", {}),
        }

    elif name == "zettelforge_sync":
        from zettelforge.edition import is_enterprise

        if not is_enterprise():
            return {"error": "OpenCTI sync requires the zettelforge-enterprise package."}
        try:
            from zettelforge_enterprise.opencti_sync import sync_opencti

            limit = arguments.get("limit", 20)
            return sync_opencti(mm, limit=limit, use_extraction=False)
        except Exception as e:
            return {"error": str(e)}

    else:
        return {"error": f"Unknown tool: {name}"}


# ── MCP Protocol (stdio JSON-RPC) ───────────────────────────────────────────

TOOLS = [
    {
        "name": "zettelforge_remember",
        "description": "Store threat intelligence in ZettelForge memory. Extracts entities (CVEs, actors, tools) and adds to knowledge graph. With evolve=true (default), uses LLM to compare against existing notes and decide whether to add, update, or supersede.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The threat intelligence text to store",
                },
                "domain": {
                    "type": "string",
                    "description": "Domain: cti, incident, general",
                    "default": "cti",
                },
                "source": {"type": "string", "description": "Source reference", "default": "mcp"},
                "evolve": {
                    "type": "boolean",
                    "description": "Enable memory evolution: LLM compares against existing notes and decides ADD/UPDATE/DELETE/NOOP. Slower but prevents duplicate/stale knowledge.",
                    "default": True,
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "zettelforge_recall",
        "description": "Search ZettelForge memory using blended vector + graph retrieval. Returns ranked results with entities, confidence, and tier.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query (e.g., 'What tools does APT28 use?')",
                },
                "k": {"type": "integer", "description": "Max results to return", "default": 10},
                "domain": {"type": "string", "description": "Filter by domain (optional)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "zettelforge_synthesize",
        "description": "Generate a synthesized answer from ZettelForge memories using RAG. Formats: direct_answer, synthesized_brief, timeline_analysis, relationship_map.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Question to answer from memory"},
                "format": {
                    "type": "string",
                    "description": "Output format",
                    "default": "direct_answer",
                    "enum": [
                        "direct_answer",
                        "synthesized_brief",
                        "timeline_analysis",
                        "relationship_map",
                    ],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "zettelforge_entity",
        "description": "Fast entity lookup by type (actor, cve, tool, campaign, person, location). O(1) index lookup.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Entity type",
                    "enum": ["actor", "cve", "tool", "campaign", "person", "location"],
                },
                "value": {
                    "type": "string",
                    "description": "Entity value (e.g., 'apt28', 'CVE-2024-3094')",
                },
                "k": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["type", "value"],
        },
    },
    {
        "name": "zettelforge_graph",
        "description": "Traverse the STIX 2.1 knowledge graph from an entity. Shows relationships: uses, targets, attributed-to, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "Starting entity type"},
                "value": {"type": "string", "description": "Starting entity value"},
                "max_depth": {
                    "type": "integer",
                    "description": "Max traversal depth",
                    "default": 2,
                },
            },
            "required": ["type", "value"],
        },
    },
    {
        "name": "zettelforge_stats",
        "description": "Get ZettelForge memory system statistics: total notes, entity counts, retrieval count.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "zettelforge_sync",
        "description": "Trigger sync from OpenCTI — pulls latest reports, indicators, threat actors, malware, and vulnerabilities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max objects per type", "default": 20},
            },
        },
    },
]


def run_stdio() -> None:
    """Run MCP server over stdio (JSON-RPC 2.0)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "zettelforge", "version": __version__},
                },
            }

        elif method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS},
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            try:
                result = handle_tool_call(tool_name, tool_args)
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(result, indent=2, default=str)}
                        ],
                    },
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                        "isError": True,
                    },
                }

        elif method == "notifications/initialized":
            continue  # No response needed

        else:
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
            }

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
