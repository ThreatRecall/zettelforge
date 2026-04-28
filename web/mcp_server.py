#!/usr/bin/env python3
"""
ThreatRecall MCP Server — Model Context Protocol interface for ZettelForge.

Exposes ZettelForge's memory system as MCP tools that any AI agent
(Claude Code, OpenClaw, etc.) can call via stdio transport.

Tools:
    threatrecall_remember    — Store threat intelligence
    threatrecall_recall      — Search and retrieve memories
    threatrecall_synthesize  — RAG synthesis over memories
    threatrecall_entity      — Fast entity lookup (actor, CVE, tool)
    threatrecall_graph       — Knowledge graph traversal
    threatrecall_stats       — Memory system statistics
    threatrecall_sync        — Trigger OpenCTI sync

Usage:
    python web/mcp_server.py                    # stdio transport (for Claude Code)
    Add to .claude.json or .mcp.json:
    {
        "mcpServers": {
            "threatrecall": {
                "command": "python3",
                "args": ["web/mcp_server.py"]
            }
        }
    }
"""
import os
import sys
import json
import time
from pathlib import Path

# Ensure zettelforge is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
os.environ.setdefault("ZETTELFORGE_BACKEND", "jsonl")

from zettelforge import MemoryManager, __version__

# Global memory manager
mm = MemoryManager()


def handle_tool_call(name: str, arguments: dict) -> dict:
    """Route MCP tool calls to ZettelForge methods."""

    if name == "threatrecall_remember":
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

    elif name == "threatrecall_recall":
        query = arguments.get("query", "")
        k = arguments.get("k", 10)
        domain = arguments.get("domain", None)
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

    elif name == "threatrecall_synthesize":
        query = arguments.get("query", "")
        fmt = arguments.get("format", "direct_answer")
        result = mm.synthesize(query, format=fmt, k=10)
        return {
            "synthesis": result.get("synthesis", {}),
            "sources_count": result.get("metadata", {}).get("sources_count", 0),
        }

    elif name == "threatrecall_entity":
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

    elif name == "threatrecall_graph":
        entity_type = arguments.get("type", "actor")
        value = arguments.get("value", "")
        max_depth = arguments.get("max_depth", 2)
        paths = mm.traverse_graph(entity_type, value, max_depth=max_depth)
        return {
            "paths": [
                [{"from": s["from_value"], "rel": s["relationship"], "to": s["to_value"]} for s in path]
                for path in paths[:20]
            ],
            "count": len(paths),
        }

    elif name == "threatrecall_stats":
        s = mm.get_stats()
        return {
            "version": __version__,
            "total_notes": s.get("total_notes", 0),
            "retrievals": s.get("retrievals", 0),
            "entity_index": s.get("entity_index", {}),
        }

    elif name == "threatrecall_sync":
        from zettelforge.edition import is_enterprise
        if not is_enterprise():
            return {"error": "OpenCTI sync requires ThreatRecall Enterprise. https://threatengram.com/enterprise"}
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
        "name": "threatrecall_remember",
        "description": "Store threat intelligence in ThreatRecall memory. Extracts entities (CVEs, actors, tools) and adds to knowledge graph. With evolve=true (default), uses LLM to compare against existing notes and decide whether to add, update, or supersede.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The threat intelligence text to store"},
                "domain": {"type": "string", "description": "Domain: cti, incident, general", "default": "cti"},
                "source": {"type": "string", "description": "Source reference", "default": "mcp"},
                "evolve": {"type": "boolean", "description": "Enable memory evolution: LLM compares against existing notes and decides ADD/UPDATE/DELETE/NOOP. Slower but prevents duplicate/stale knowledge.", "default": True},
            },
            "required": ["content"],
        },
    },
    {
        "name": "threatrecall_recall",
        "description": "Search ThreatRecall memory using blended vector + graph retrieval. Returns ranked results with entities, confidence, and tier.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query (e.g., 'What tools does APT28 use?')"},
                "k": {"type": "integer", "description": "Max results to return", "default": 10},
                "domain": {"type": "string", "description": "Filter by domain (optional)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "threatrecall_synthesize",
        "description": "Generate a synthesized answer from ThreatRecall memories using RAG. Formats: direct_answer, synthesized_brief, timeline_analysis, relationship_map.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Question to answer from memory"},
                "format": {"type": "string", "description": "Output format", "default": "direct_answer", "enum": ["direct_answer", "synthesized_brief", "timeline_analysis", "relationship_map"]},
            },
            "required": ["query"],
        },
    },
    {
        "name": "threatrecall_entity",
        "description": "Fast entity lookup by type (actor, cve, tool, campaign, person, location). O(1) index lookup.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "Entity type", "enum": ["actor", "cve", "tool", "campaign", "person", "location"]},
                "value": {"type": "string", "description": "Entity value (e.g., 'apt28', 'CVE-2024-3094')"},
                "k": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["type", "value"],
        },
    },
    {
        "name": "threatrecall_graph",
        "description": "Traverse the STIX 2.1 knowledge graph from an entity. Shows relationships: uses, targets, attributed-to, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "Starting entity type"},
                "value": {"type": "string", "description": "Starting entity value"},
                "max_depth": {"type": "integer", "description": "Max traversal depth", "default": 2},
            },
            "required": ["type", "value"],
        },
    },
    {
        "name": "threatrecall_stats",
        "description": "Get ThreatRecall memory system statistics: total notes, entity counts, retrieval count.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "threatrecall_sync",
        "description": "Trigger sync from OpenCTI — pulls latest reports, indicators, threat actors, malware, and vulnerabilities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max objects per type", "default": 20},
            },
        },
    },
]


def run_stdio():
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
                    "serverInfo": {"name": "threatrecall", "version": __version__},
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
                        "content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}],
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


if __name__ == "__main__":
    run_stdio()
