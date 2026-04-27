---
title: "MCP Protocol Reference"
description: "Complete reference for the ZettelForge MCP server: tool schemas, JSON-RPC 2.0 protocol details, request/response examples, error codes, and the lazy-singleton lifecycle."
diataxis_type: "reference"
audience: "Tool integrators, MCP client developers, LLM agent framework authors"
tags: [mcp, protocol, json-rpc, schema, server, reference]
last_updated: "2026-04-27"
version: "2.0.0"
---

# MCP Protocol Reference

The ZettelForge MCP server implements the [Model Context Protocol](https://modelcontextprotocol.io) specification (protocol version `2024-11-05`) over stdio transport using JSON-RPC 2.0.

## Protocol overview

- **Transport**: stdio (stdin for requests, stdout for responses)
- **Protocol**: JSON-RPC 2.0
- **MCP version**: `2024-11-05`
- **Server name**: `zettelforge`
- **Lazy initialization**: `MemoryManager` is instantiated on first tool call, not on import

## Lifecycle

The MCP lifecycle has three phases:

```
client                          server
  |                               |
  |--- initialize --------------->|  Phase 1: Initialization
  |<-- initialize result ---------|
  |--- notifications/initialized->|  (no response)
  |                               |
  |--- tools/list --------------->|  Phase 2: Tool discovery
  |<-- tools list ----------------|
  |                               |
  |--- tools/call --------------->|  Phase 3: Tool execution
  |<-- tool result ---------------|
  |                               |
  |--- tools/call --------------->|
  |<-- tool result ---------------|
```

### Lazy singleton contract

- Importing `zettelforge.mcp` (or `zettelforge.mcp.server`) does **not** instantiate `MemoryManager`.
- The `initialize` and `tools/list` methods work without touching the backend.
- `MemoryManager` is created on the first `tools/call` that reaches `handle_tool_call()`.
- This makes tool introspection side-effect-free for clients that only need the tool list.

```python
from zettelforge.mcp import TOOLS, run_stdio

# TOOLS is a static list — no backend started
assert len(TOOLS) == 7

# run_stdio reads stdin, processes requests, writes stdout
run_stdio()
```

## Tool schemas

### zettelforge_remember

Store threat intelligence in memory. Extracts entities (actors, CVEs, tools, campaigns) and populates the knowledge graph. With `evolve=True` (default), uses an LLM to compare against existing notes and decide whether to add, update, or supersede.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "zettelforge_remember",
    "arguments": {
      "content": "APT28 used CVE-2024-3094 against NATO networks.",
      "domain": "cti",
      "source": "report-2026-001",
      "evolve": true
    }
  }
}
```

**Response**:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"note_id\": \"abc123-def456\",\n  \"status\": \"created\",\n  \"entities\": [\"apt28\", \"cve-2024-3094\"]\n}"
      }
    ]
  }
}
```

**Input schema**:

| Property | Type | Required | Default | Description |
|---|---|---|---|---|
| `content` | string | yes | — | Threat intelligence text to store |
| `domain` | string | no | `"cti"` | Domain: `cti`, `incident`, `general` |
| `source` | string | no | `"mcp"` | Source reference string |
| `evolve` | boolean | no | `true` | Enable memory evolution (LLM-based dedup) |

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `note_id` | string or null | ID of the created/updated note, or null on error |
| `status` | string | `"created"`, `"updated"`, `"corrected"`, `"noop"` |
| `entities` | string[] | Up to 10 extracted entity values |

---

### zettelforge_recall

Search memory using blended vector + graph retrieval. Returns ranked results with entities, confidence scores, and tier metadata.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "zettelforge_recall",
    "arguments": {
      "query": "What tools does APT28 use?",
      "k": 10,
      "domain": "cti"
    }
  }
}
```

**Response**:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"results\": [\n    {\n      \"id\": \"note-123\",\n      \"content\": \"APT28 deployed Cobalt Strike beacons against NATO-aligned government networks in Q1 2026...\",\n      \"context\": \"actor:apt28 | tool:cobalt strike\",\n      \"entities\": [\"apt28\", \"cobalt strike\"],\n      \"tier\": \"verified\",\n      \"confidence\": 0.92\n    }\n  ],\n  \"count\": 1,\n  \"latency_ms\": 42\n}"
      }
    ]
  }
}
```

**Input schema**:

| Property | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Natural language search query |
| `k` | integer | no | `10` | Maximum number of results |
| `domain` | string | no | — | Optional domain filter |

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `results` | object[] | Ranked search results |
| `results[].id` | string | Note ID |
| `results[].content` | string | First 500 characters of note content |
| `results[].context` | string | Semantic context string |
| `results[].entities` | string[] | Up to 10 extracted entities |
| `results[].tier` | string | Epistemic tier: `verified`, `reported`, `inferred` |
| `results[].confidence` | number | Confidence score (0.0 to 1.0) |
| `count` | integer | Number of results returned |
| `latency_ms` | integer | Query latency in milliseconds |

---

### zettelforge_synthesize

Generate a synthesized answer from ZettelForge memories using RAG (Retrieval-Augmented Generation). Supports multiple output formats.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "zettelforge_synthesize",
    "arguments": {
      "query": "Describe the relationship between APT28 and Lazarus Group",
      "format": "relationship_map"
    }
  }
}
```

**Response**:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"synthesis\": {\n    \"answer\": \"Based on stored intelligence, APT28 and Lazarus Group are distinct North Korean and Russian state-sponsored threat actors respectively...\",\n    \"format\": \"relationship_map\"\n  },\n  \"sources_count\": 4\n}"
      }
    ]
  }
}
```

**Input schema**:

| Property | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Question to answer from memory |
| `format` | string | no | `"direct_answer"` | Output format: `direct_answer`, `synthesized_brief`, `timeline_analysis`, `relationship_map` |

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `synthesis` | object | The generated answer (shape varies by format) |
| `sources_count` | integer | Number of memory notes used as sources |

---

### zettelforge_entity

Fast entity lookup by type. Uses an O(1) index for direct entity-to-note mapping.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "zettelforge_entity",
    "arguments": {
      "type": "cve",
      "value": "CVE-2024-3094",
      "k": 5
    }
  }
}
```

**Response**:

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"results\": [\n    {\n      \"id\": \"note-456\",\n      \"content\": \"CVE-2024-3094 is a critical backdoor in xz-utils discovered in March 2024...\",\n      \"tier\": \"verified\"\n    }\n  ],\n  \"count\": 1\n}"
      }
    ]
  }
}
```

**Input schema**:

| Property | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | string | yes | — | Entity type: `actor`, `cve`, `tool`, `campaign`, `person`, `location` |
| `value` | string | yes | — | Entity value (e.g. `"apt28"`, `"CVE-2024-3094"`) |
| `k` | integer | no | `5` | Maximum results |

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `results` | object[] | Notes referencing this entity |
| `results[].id` | string | Note ID |
| `results[].content` | string | First 300 characters of note content |
| `results[].tier` | string | Epistemic tier |
| `count` | integer | Number of results |

---

### zettelforge_graph

Traverse the STIX 2.1 knowledge graph starting from a given entity. Shows relationships such as `uses`, `targets`, `attributed-to`.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "zettelforge_graph",
    "arguments": {
      "type": "actor",
      "value": "apt28",
      "max_depth": 2
    }
  }
}
```

**Response**:

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"paths\": [\n    [\n      {\"from\": \"apt28\", \"rel\": \"uses\", \"to\": \"cobalt strike\"},\n      {\"from\": \"cobalt strike\", \"rel\": \"targets\", \"to\": \"windows\"}\n    ]\n  ],\n  \"count\": 1\n}"
      }
    ]
  }
}
```

**Input schema**:

| Property | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | string | yes | — | Starting entity type |
| `value` | string | yes | — | Starting entity value |
| `max_depth` | integer | no | `2` | Maximum traversal depth |

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `paths` | object[][] | Up to 20 graph traversal paths |
| `paths[][].from` | string | Source entity value |
| `paths[][].rel` | string | Relationship type |
| `paths[][].to` | string | Target entity value |
| `count` | integer | Number of paths found |

---

### zettelforge_stats

Return memory system statistics including version, total note count, retrieval count, and entity index breakdown.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "tools/call",
  "params": {
    "name": "zettelforge_stats",
    "arguments": {}
  }
}
```

**Response**:

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"version\": \"2.0.0\",\n  \"total_notes\": 142,\n  \"retrievals\": 3891,\n  \"entity_index\": {\n    \"actor\": 12,\n    \"cve\": 34,\n    \"tool\": 28,\n    \"campaign\": 7,\n    \"person\": 3,\n    \"location\": 9\n  }\n}"
      }
    ]
  }
}
```

**Input schema**: No required or optional parameters.

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `version` | string | ZettelForge version string |
| `total_notes` | integer | Total number of stored notes |
| `retrievals` | integer | Cumulative retrieval count |
| `entity_index` | object | Entity type counts (keys vary by memory contents) |

---

### zettelforge_sync

Trigger a sync from OpenCTI. Pulls the latest reports, indicators, threat actors, malware, and vulnerabilities. Requires the `zettelforge-enterprise` package.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "tools/call",
  "params": {
    "name": "zettelforge_sync",
    "arguments": {
      "limit": 20
    }
  }
}
```

**Response (success)**:

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"synced\": {\n    \"reports\": 5,\n    \"indicators\": 20,\n    \"threat_actors\": 3,\n    \"malware\": 8,\n    \"vulnerabilities\": 4\n  },\n  \"errors\": []\n}"
      }
    ]
  }
}
```

**Response (enterprise not installed)**:

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"error\": \"OpenCTI sync requires the zettelforge-enterprise package.\"\n}"
      }
    ]
  }
}
```

**Input schema**:

| Property | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer | no | `20` | Maximum objects to pull per STIX type |

---

## JSON-RPC methods

### initialize

The client sends `initialize` as the first message to negotiate protocol version and discover server capabilities.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {
      "name": "my-client",
      "version": "1.0.0"
    }
  }
}
```

**Response**:

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {
      "tools": {
        "listChanged": false
      }
    },
    "serverInfo": {
      "name": "zettelforge",
      "version": "2.0.0"
    }
  }
}
```

### notifications/initialized

Sent by the client after receiving the initialize response. The server does not send a response.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/initialized"
}
```

The server silently skips this message (no response written to stdout).

### tools/list

Return the full list of available tools with their input schemas.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

**Response**:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "zettelforge_remember",
        "description": "Store threat intelligence in ZettelForge memory...",
        "inputSchema": {
          "type": "object",
          "properties": { ... }
        }
      }
    ]
  }
}
```

### tools/call

Execute a named tool with the provided arguments.

**Request**:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "zettelforge_recall",
    "arguments": {
      "query": "APT28",
      "k": 5
    }
  }
}
```

**Response (success)**:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{ ... }"
      }
    ]
  }
}
```

**Response (tool error, e.g. tool raised an exception)**:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"error\": \"Connection to TypeDB failed\"}"
      }
    ],
    "isError": true
  }
}
```

## Error codes

### JSON-RPC standard error codes

| Code | Meaning | When it occurs |
|---|---|---|
| `-32700` | Parse error | Invalid JSON in request |
| `-32600` | Invalid request | Request object is malformed |
| `-32601` | Method not found | Unknown method sent (not `initialize`, `tools/list`, `tools/call`, or `notifications/initialized`) |
| `-32602` | Invalid params | Tool arguments fail schema validation (handled by the MCP client; server does not validate schemas) |
| `-32603` | Internal error | Unhandled exception in tool handler |

### Method-not-found response example

```json
{
  "jsonrpc": "2.0",
  "id": 9,
  "error": {
    "code": -32601,
    "message": "Unknown method: does/not/exist"
  }
}
```

### Tool-level errors

Tool errors do not use JSON-RPC error codes. They are returned as successful JSON-RPC responses with `isError: true` in the result payload, and the error message inside the text content:

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"error\": \"Unknown tool: zettelforge_nonexistent\"}"
      }
    ],
    "isError": true
  }
}
```

Tool-level error scenarios:

| Scenario | Error message |
|---|---|
| Unknown tool name | `"Unknown tool: {name}"` |
| OpenCTI sync without enterprise | `"OpenCTI sync requires the zettelforge-enterprise package."` |
| OpenCTI sync failure | `"{exception message}"` (passthrough from enterprise package) |
| Backend connection failure | `"Connection to ... failed"` (from MemoryManager) |

## Backward compatibility

Tool names prefixed with `threatrecall_` (e.g. `threatrecall_stats`, `threatrecall_remember`) are transparently rewritten to `zettelforge_*` before dispatch. The server applies this rewrite:

```python
if name.startswith("threatrecall_"):
    name = name.replace("threatrecall_", "zettelforge_", 1)
```

This ensures existing agent workflows and configurations that reference the old naming continue to work without changes.

## Implementation details

### Server source location

The MCP server is implemented entirely in:

- `src/zettelforge/mcp/server.py` — Core logic: `TOOLS`, `handle_tool_call()`, `run_stdio()`, `get_mm()`
- `src/zettelforge/mcp/__init__.py` — Public API re-export
- `src/zettelforge/mcp/__main__.py` — Entrypoint for `python -m zettelforge.mcp`

### Module public API

```python
from zettelforge.mcp import TOOLS, handle_tool_call, run_stdio
```

| Symbol | Type | Description |
|---|---|---|
| `TOOLS` | `list[dict]` | Static tool definitions (7 tools) with input schemas |
| `handle_tool_call(name, arguments)` | `(str, dict) -> dict` | Route tool name and args to MemoryManager methods |
| `run_stdio()` | `() -> None` | Start the stdio-based JSON-RPC loop |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `ZETTELFORGE_BACKEND` | `sqlite` | Storage backend: `sqlite`, `jsonl`, `typedb`, `lancedb` |
| `ZETTELFORGE_HOME` | `~/.zettelforge` | Memory store directory |

The backend environment variable is set automatically to `sqlite` if no other value is provided, ensuring the server works out of the box without configuration.

### Test coverage

Unit tests are in `tests/test_mcp_server.py` and cover:

- Lazy singleton contract (import does not instantiate MemoryManager)
- `initialize` handshake response structure
- `tools/list` returns all 7 tools with valid schemas
- Unknown method returns JSON-RPC error code `-32601`
- `notifications/initialized` produces no response
- `threatrecall_*` backward-compatible name rewriting
