## Summary

Replace the inline HTML page with a full-featured SPA management interface served from web/ui/. The old 200-line HTML_PAGE constant is removed; GET / now serves the SPA from web/ui/index.html.

## Backend (13 new API endpoints)

| Endpoint | Purpose |
|----------|---------|
| GET /api/health | System health: version, edition, storage/embedding/LLM status, queue depth, memory, uptime |
| GET /api/config | Full config as JSON with secrets redacted |
| PUT /api/config | Apply in-memory config changes; returns applied + pending-restart lists |
| GET /api/graph/nodes | All KG entity nodes for graph rendering |
| GET /api/graph/edges | All KG relationship edges |
| GET /api/entities | Paginated entity index with type/tier/text filters |
| GET /api/history | Recent activity from telemetry JSONL files |
| POST /api/ingest | Bulk ingestion (up to 100 items, rate-limited) |
| GET /api/telemetry | Aggregated daily summary with intents and latency percentiles |
| GET /api/storage | Storage stats: notes, entities, graph nodes/edges |
| GET /api/logs | Tail structlog with level filter |
| GET /api/logs/stream | SSE stream for live log tailing |
| GET /api/telemetry/stream | SSE stream for live telemetry |

## Frontend (28 files, 5,295 lines)

- Vanilla JS SPA - no React, no npm, no build step. Zero npm supply chain risk.
- Design system fidelity - colors_and_type.css tokens, Neuropol/Inter/JetBrains Mono, Neural Dark palette
- 8 views: Dashboard, Search, Knowledge Graph (2D SVG force-directed), Logs & Telemetry, Ingest, Entity Browser, History, Configuration (feature flags + YAML editor)
- 6 components: header, sidebar, result-card, tabs, toast, spinner
- Hash-based routing with reactive state store

## Config changes

- WebConfig dataclass in config.py (enabled, host, port, ui_dir)
- web: section in config.default.yaml with docs and env override examples
- psutil added to [web] extra in pyproject.toml

## Testing

- All Python files pass AST parsing
- All 20 JS files pass Node --check syntax validation
- YAML config parses correctly
