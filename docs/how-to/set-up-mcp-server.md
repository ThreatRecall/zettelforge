---
title: "Set Up the MCP Server"
description: "Run the ZettelForge MCP server over stdio and wire it into Claude Code for direct access to memory, recall, entity lookup, knowledge graph traversal, and RAG synthesis."
diataxis_type: "how-to"
audience: "AI agent developers, security engineers integrating ZettelForge with LLM agents"
tags: [mcp, claude-code, model-context-protocol, integration, stdio]
last_updated: "2026-04-27"
version: "2.0.0"
---

# Set Up the MCP Server

The ZettelForge MCP server exposes the full memory system as tools through the [Model Context Protocol](https://modelcontextprotocol.io) (MCP). Any MCP-compatible AI agent — Claude Code, OpenClaw, Cline, or a custom client — can call `zettelforge_remember`, `zettelforge_recall`, and five other tools over stdio transport.

## Prerequisites

- ZettelForge installed (`pip install zettelforge`)
- Python 3.12+
- For Claude Code: the `claude` CLI installed and authenticated
- Embedding and LLM models available (downloaded automatically on first tool call)

## Steps

### 1. Verify the server starts

Run the server directly to confirm it accepts stdin and writes JSON-RPC responses to stdout:

```bash
echo '{"jsonrpc":"2.0","id":0,"method":"initialize"}' | python -m zettelforge.mcp
```

Expected output (one line):

```json
{"jsonrpc": "2.0", "id": 0, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": false}}, "serverInfo": {"name": "zettelforge", "version": "2.0.0"}}}
```

If you see this response, the server is functional.

### 2. List available tools

Send a `tools/list` request to verify all seven tools are registered:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python -m zettelforge.mcp
```

Seven tools are returned:

| Tool | Purpose |
|---|---|
| `zettelforge_remember` | Store threat intelligence with entity extraction and memory evolution |
| `zettelforge_recall` | Search memory with blended vector + graph retrieval |
| `zettelforge_synthesize` | Generate RAG-synthesized answers (direct_answer, brief, timeline, relationship map) |
| `zettelforge_entity` | Fast entity lookup by type (actor, cve, tool, campaign, person, location) |
| `zettelforge_graph` | Traverse the STIX 2.1 knowledge graph from an entity |
| `zettelforge_stats` | Get memory system statistics (note count, entity index, retrievals) |
| `zettelforge_sync` | Trigger OpenCTI sync (requires enterprise package) |

### 3. Wire into Claude Code

Create or edit `.claude.json` in your project root (or `~/.claude/.claude.json` for global access):

```json
{
  "mcpServers": {
    "zettelforge": {
      "command": "python3",
      "args": ["-m", "zettelforge.mcp"]
    }
  }
}
```

If ZettelForge is installed in a virtual environment, use the full path to that Python interpreter:

```json
{
  "mcpServers": {
    "zettelforge": {
      "command": "/home/user/.venvs/zettelforge/bin/python",
      "args": ["-m", "zettelforge.mcp"]
    }
  }
}
```

### 4. Verify the integration

Start Claude Code and check that the tools are available:

```bash
claude
```

Inside the Claude Code session, ask:

```
What tools do you have available from zettelforge?
```

Claude Code should list the seven tools. Test a simple recall:

```
Use zettelforge_recall with query "APT28" and k=3 to check my memory.
```

If the memory store is empty, store a fact first:

```
Use zettelforge_remember to store this intelligence:
"APT28 (Fancy Bear) deployed Cobalt Strike against NATO networks in Q1 2026."
```

### 5. Configure backend storage (optional)

The MCP server defaults to SQLite. Set the environment variable before starting Claude Code or the server to change this:

```bash
export ZETTELFORGE_BACKEND=jsonl
claude
```

Supported backends: `sqlite` (default), `jsonl`, `typedb`, `lancedb`.

### 6. Customize the memory directory

If your memory store is at a non-default location, set `ZETTELFORGE_HOME`:

```bash
export ZETTELFORGE_HOME=/data/threat-intel/zettelforge
claude
```

## Test each tool manually

You can send raw JSON-RPC requests to verify each tool's behaviour. Use a memory store with existing content for meaningful results.

### zettelforge_remember

```bash
echo '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"zettelforge_remember","arguments":{"content":"APT28 used CVE-2024-3094 against NATO targets.","domain":"cti","source":"manual-test","evolve":true}}}' | python -m zettelforge.mcp
```

### zettelforge_recall

```bash
echo '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"zettelforge_recall","arguments":{"query":"What tools does APT28 use?","k":5}}}' | python -m zettelforge.mcp
```

### zettelforge_entity

```bash
echo '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"zettelforge_entity","arguments":{"type":"actor","value":"apt28","k":3}}}' | python -m zettelforge.mcp
```

### zettelforge_graph

```bash
echo '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"zettelforge_graph","arguments":{"type":"actor","value":"apt28","max_depth":2}}}' | python -m zettelforge.mcp
```

### zettelforge_stats

```bash
echo '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"zettelforge_stats","arguments":{}}}' | python -m zettelforge.mcp
```

## Troubleshooting

**Server starts but no tools appear in Claude Code.**
Make sure the virtual environment Python is the one specified in `.claude.json`. Test by running the initialize handshake directly (step 1).

**"ModuleNotFoundError: No module named 'zettelforge'".**
ZettelForge is not installed in the Python environment used by the MCP server. Run `pip install zettelforge` or point the `command` to the correct venv Python.

**Backward-compatible tool names.**
If you have existing workflows using `threatrecall_remember`, `threatrecall_recall`, etc., those names still work — the server transparently rewrites `threatrecall_*` to `zettelforge_*`.

**The `zettelforge_sync` tool returns an error.**
OpenCTI sync requires the `zettelforge-enterprise` package. It is not available in the open-source (MIT) distribution.

## LLM Quick Reference

**Task**: Wire ZettelForge into an MCP-compatible AI agent (Claude Code, Cline, OpenClaw).

**Server entrypoint**: `python -m zettelforge.mcp` runs the stdio server. It reads JSON-RPC 2.0 requests from stdin and writes responses to stdout.

**Configuration file**: `.claude.json` (project or home directory) with `mcpServers.zettelforge.command` and `mcpServers.zettelforge.args`.

**Seven tools**: `remember`, `recall`, `synthesize`, `entity`, `graph`, `stats`, `sync`. The `sync` tool requires the enterprise package.

**Lazy singleton**: MemoryManager is not instantiated on import — only on the first tool call (or the first JSON-RPC request). Importing `zettelforge.mcp` to inspect the `TOOLS` list has no side effects on the backend.

**Backend default**: SQLite. Override with `ZETTELFORGE_BACKEND=jsonl` or `ZETTELFORGE_BACKEND=typedb`.

**Protocol**: JSON-RPC 2.0 over stdio. Initialize handshake first, then `tools/list` and `tools/call`. Notifications (`notifications/initialized`) produce no response. Unknown methods return error code -32601.
