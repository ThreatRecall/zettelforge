---
title: "Web API Reference"
description: "Complete reference for all ZettelForge web API endpoints, including request/response schemas, status codes, authentication, and examples for every endpoint."
diataxis_type: "reference"
audience: "Developer / Integrator"
tags: [reference, api, rest, endpoints, web-ui]
last_updated: "2026-04-25"
version: "2.5.0"
---

# Web API Reference

Server: FastAPI at `http://localhost:8088`.

All endpoints (except `GET /`) require authentication. See [Authentication](#authentication) below.

---

## Authentication

Two modes controlled by the `ZETTELFORGE_WEB_API_KEY` environment variable:

- **Loopback mode** (no env var set, server on `127.0.0.1`): no authentication required. `localhost`, `::1`, and `testclient` are in the allowlist.
- **API key mode** (env var set): pass the key via `X-API-Key` header or `Authorization: Bearer <key>`:

```bash
curl -H "X-API-Key: my-key" http://localhost:8088/api/health
```

All endpoints also enforce rate limiting (60 requests per minute per key/IP by default). Exceeding the limit returns `429 Too Many Requests`.

---

## Existing Endpoints (preserved)

### `POST /api/recall`

Blended vector + graph retrieval.

**Request:**
```json
{"query": "What tools does APT28 use?", "k": 10, "domain": "cti"}
```

**Response:**
```json
{
  "query": "What tools does APT28 use?",
  "results": [
    {
      "id": "zf-03f1a2b4",
      "content": "APT28 has shifted tactics...",
      "domain": "cti",
      "tier": "B",
      "confidence": 0.84,
      "created_at": "2026-04-12T...",
      "entities": ["APT28", "Cobalt Strike", "T1190"]
    }
  ],
  "count": 1,
  "latency_ms": 47
}
```

### `POST /api/remember`

Store a single note.

**Request:**
```json
{"content": "APT28 uses Cobalt Strike.", "domain": "cti", "source_type": "manual", "evolve": true}
```

**Response:**
```json
{"note_id": "zf-abc123", "status": "created", "entities": ["APT28", "Cobalt Strike"], "latency_ms": 45}
```

### `POST /api/synthesize`

RAG synthesis from memory.

**Request:**
```json
{"query": "What we know about APT28?", "format": "synthesized_brief", "k": 10}
```

**Formats:** `direct_answer`, `synthesized_brief`, `timeline_analysis`, `relationship_map`.

### `GET /api/stats`

Memory system statistics.

**Response:**
```json
{
  "version": "2.5.0",
  "edition": "community",
  "edition_name": "ZettelForge Community",
  "total_notes": 4060,
  "notes_created": 4060,
  "retrievals": 1247,
  "entity_index": {"apt28": ["actor"], "cve-2024-3094": ["cve"]}
}
```

### `GET /api/edition`

Current edition and available feature flags. Enterprise features are `false` in Community edition.

### `POST /api/sync`

OpenCTI sync (Enterprise only). Returns `501` in Community edition.

---

## New Endpoints (RFC-015)

### `GET /api/health`

System health information.

**Response:**
```json
{
  "version": "2.5.0",
  "edition": "community",
  "storage_backend": "sqlite",
  "embedding_provider": "fastembed",
  "embedding_model": "nomic-ai/nomic-embed-text-v1.5-Q",
  "embedding_dimensions": 768,
  "llm_provider": "ollama",
  "llm_model": "qwen3.5:9b",
  "llm_local_backend": "llama-cpp-python",
  "enrichment_queue_depth": 0,
  "governance_enabled": true,
  "pii_enabled": false,
  "uptime_seconds": 3600.5,
  "data_dir": "~/.amem",
  "memory_usage_mb": 245.3,
  "data_size_mb": 25.0,
  "total_notes": 4060,
  "retrievals": 1247
}
```

**Notes:**
- `memory_usage_mb` is `null` if `psutil` is not installed (`pip install zettelforge[web]`)
- `data_size_mb` is `null` if the data directory doesn't exist yet

### `GET /api/config`

Full configuration as JSON with secrets redacted.

**Response:** All `ZettelForgeConfig` fields. Sensitive keys (`api_key`, `password`, `token`, `secret`, `license_key`) are replaced with `"***"`.

**Example excerpt:**
```json
{
  "storage": {"data_dir": "~/.amem"},
  "backend": "sqlite",
  "embedding": {"provider": "fastembed", "model": "nomic-ai/nomic-embed-text-v1.5-Q", "dimensions": 768},
  "llm": {"provider": "ollama", "api_key": "***", "local_backend": "llama-cpp-python"},
  "governance": {"enabled": true, "pii": {"enabled": false}}
}
```

### `PUT /api/config`

Apply configuration changes in-memory.

**Request:** Arbitrary nested config dict. Only fields that exist in the config dataclasses are applied.

**Response:**
```json
{
  "applied": ["retrieval.default_k", "synthesis.tier_filter"],
  "pending_restart": [],
  "message": "Configuration updated."
}
```

When the change requires a restart (e.g., `backend`, `storage.data_dir`, `embedding.provider`, `llm.provider`):
```json
{
  "applied": ["backend"],
  "pending_restart": ["backend"],
  "message": "Configuration updated. Some changes require a restart."
}
```

### `GET /api/graph/nodes`

All knowledge graph entity nodes.

**Response:**
```json
{
  "nodes": [
    {
      "id": "apt28",
      "label": "APT28",
      "type": "actor",
      "tier": "B",
      "aliases": ["Fancy Bear", "Sofacy", "STRONTIUM"],
      "confidence": 0.85,
      "created_at": "2026-04-10"
    }
  ],
  "count": 47
}
```

### `GET /api/graph/edges`

All knowledge graph relationship edges.

**Response:**
```json
{
  "edges": [
    {
      "id": "edge-001",
      "source": "apt28",
      "target": "cobalt_strike",
      "relationship": "uses",
      "created_at": "2026-04-10"
    }
  ],
  "count": 89
}
```

### `GET /api/entities`

Paginated entity index with filters.

**Query parameters:**

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `offset` | int | 0 | Pagination offset |
| `limit` | int | 50 | Page size (max 200) |
| `type` | str | -- | Entity type filter (actor, cve, tool, campaign) |
| `tier` | str | -- | Tier filter (A, B, C) |
| `q` | str | -- | Text search across name and aliases |

**Response:**
```json
{
  "entities": [
    {
      "id": "apt28",
      "name": "APT28",
      "type": "actor",
      "tier": "B",
      "confidence": 0.85,
      "aliases": ["Fancy Bear", "Sofacy"],
      "first_seen": "2026-04-10",
      "last_seen": null,
      "connected_count": 3
    }
  ],
  "total": 47,
  "offset": 0,
  "limit": 50
}
```

### `GET /api/history`

Recent activity from telemetry JSONL files.

**Query parameters:**

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `limit` | int | 100 | Max entries (max 500) |
| `days` | int | 5 | Lookback window in days (max 30) |

**Response:** Array of telemetry entries, each containing:
```json
{
  "query_id": "a1b2c3d4",
  "actor": null,
  "query": "What tools does APT28 use?",
  "event_type": "recall",
  "timestamp": 1745612345.67,
  "result_count": 3,
  "duration_ms": 47,
  "intent": "factual"
}
```

### `POST /api/ingest`

Bulk ingestion for multiple notes.

**Request:**
```json
{
  "items": [
    {"content": "APT28 used X-Agent.", "source_type": "report", "domain": "cti", "evolve": false},
    {"content": "Lazarus targeted defense contractors.", "source_type": "report", "domain": "cti", "evolve": false}
  ]
}
```

**Response:**
```json
{
  "total": 2,
  "succeeded": 2,
  "failed": 0,
  "results": [
    {"note_id": "zf-abc123", "status": "created", "entities": ["APT28", "X-Agent"], "success": true},
    {"note_id": "zf-def456", "status": "created", "entities": ["Lazarus"], "success": true}
  ]
}
```

**Limits:** Up to 100 items per request. Each item uses a write slot (max 2 concurrent writes).

### `GET /api/telemetry`

Aggregated telemetry summary from today's data.

**Response:**
```json
{
  "total_queries": 142,
  "recall_count": 114,
  "synthesis_count": 28,
  "avg_latency_ms": 47.3,
  "p50_ms": 35,
  "p95_ms": 210,
  "top_intents": {"factual": 68, "temporal": 31, "causal": 24, "relational": 14, "exploratory": 5}
}
```

When no telemetry data exists yet for today:
```json
{"total_queries": 0, "recall_count": 0, "synthesis_count": 0, "avg_latency_ms": null, "p50_ms": null, "p95_ms": null, "top_intents": {}}
```

### `GET /api/storage`

Storage statistics.

**Response:**
```json
{
  "total_notes": 4060,
  "entity_count": 47,
  "graph_node_count": 47,
  "graph_edge_count": 89
}
```

### `GET /api/logs`

Tail the structlog file with optional level filter.

**Query parameters:**

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `lines` | int | 100 | Number of lines to return (max 1000) |
| `level` | str | -- | Filter by level (DEBUG, INFO, WARNING, ERROR) |

**Response:**
```json
{
  "logs": [
    {"event": "note_stored", "level": "INFO", "logger": "zettelforge.memory_manager", "note_id": "zf-abc", "timestamp": "..."}
  ],
  "truncated": false
}
```

### `GET /api/logs/stream`

Server-Sent Events stream for live log tailing. Polls the log file every 100ms for new lines.

```
data: {"event": "note_stored", "level": "INFO", ...}
data: {"event": "recall_completed", "level": "INFO", ...}
```

### `GET /api/telemetry/stream`

Server-Sent Events stream for live telemetry. Polls today's telemetry JSONL file every 100ms.

```
data: {"event_type": "recall", "query_id": "abc", "duration_ms": 47, ...}
data: {"event_type": "synthesis", "query_id": "def", ...}
```

### `GET /`

Serves the ZettelForge SPA from `web/ui/index.html`. If the UI directory is not found, returns a fallback HTML message.

---

## Status Codes

| Code | Meaning |
|:-----|:--------|
| `200` | Success |
| `400` | Bad request (invalid parameters, unsupported synthesis format) |
| `401` | Unauthorized (missing or invalid API key) |
| `429` | Rate limit exceeded (60 req/min) or write capacity exhausted |
| `500` | Internal server error (exception details in response) |
| `501` | Feature requires zettelforge-enterprise (OpenCTI sync) |
| `503` | API key required (server bound to non-loopback address without key) |
