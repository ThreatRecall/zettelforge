---
title: "Use the ZettelForge Web Management Interface"
description: "Install, configure, and navigate the ZettelForge web GUI. Start the server, explore the dashboard, search threat intelligence, browse the knowledge graph, monitor logs and telemetry, and manage configuration from your browser."
diataxis_type: "how-to"
audience: "SOC Analyst / CTI Practitioner"
tags: [how-to, web-ui, gui, dashboard, configuration]
last_updated: "2026-04-25"
version: "2.5.0"
---

# Use the ZettelForge Web Management Interface

ZettelForge ships with a full-featured web management interface served at `http://localhost:8088`. It replaces the old in-page HTML search with a single-page application covering system health monitoring, threat intelligence search and synthesis, knowledge graph exploration, log and telemetry streaming, bulk data ingestion, entity browsing, session history, and live configuration editing.

**Prerequisites:**

- [ ] ZettelForge installed (`pip install zettelforge`)
- [ ] Web dependencies installed (`pip install zettelforge[web]`)
- [ ] At least one note stored (see [quickstart](../tutorials/01-quickstart.md))

---

## Step 1: Start the Server

```bash
# From the project root directory
python web/app.py
```

Expected output:

```
ZettelForge v2.5.0 -- http://127.0.0.1:8088
```

> If you bind to `0.0.0.0` (making the server accessible on your network), you must set `ZETTELFORGE_WEB_API_KEY` first:
>
> ```bash
> ZETTELFORGE_WEB_API_KEY=my-secret-key python web/app.py --host 0.0.0.0
> ```

Open `http://localhost:8088` in your browser. You should see the ZettelForge SPA with the shield-neuron mark in the header and a navigation sidebar on the left.

### Custom port

```bash
python web/app.py --port 9000
# or via config
# Set ZETTELFORGE_WEB_PORT=9000 in your environment
```

### Disable the web UI

Set the following in your configuration:

```yaml
web:
  enabled: false
```

Or set `ZETTELFORGE_WEB_ENABLED=false` in your environment.

---

## Step 2: Navigate the Interface

The SPA has three zones: a **header** (top bar with brand mark, version/edition badge, and operational stats), a **sidebar** (navigation links with Lucide icons), and a **content area** (the active view).

Click any sidebar item to navigate. The active item is highlighted with a neon green (`#00FFA3`) left border and text color.

| Sidebar Item | Icon | Description |
|:-------------|:-----|:------------|
| Dashboard | layout-dashboard | System health tiles, telemetry summary, quick actions |
| Search | search | Threat intelligence recall, synthesis, and storage |
| Knowledge Graph | git-graph | 2D force-directed entity graph with search and filters |
| Logs & Telemetry | scroll-text | Log file tailing, telemetry charts, live SSE streaming |
| Ingest | upload | Manual and bulk data ingestion with file upload |
| Entities | database | Paginated entity browser with type/tier/text filters |
| History | clock | Recent session activity with date filters and re-run |
| Configuration | settings | Feature flag toggles and raw YAML editor |

---

## Step 3: Explore Each View

### Dashboard

The dashboard shows system health at a glance. Four status tiles display:

- **Storage** -- backend type (sqlite), total notes, total entities, data directory size
- **LLM** -- provider (ollama/local/litellm), model name, local backend engine, uptime
- **Embedding** -- provider (fastembed/ollama), model name, vector dimensions
- **Queue** -- enrichment queue depth and operational status

Below the tiles is a telemetry summary showing today's query volume, synthesis count, and average latency. A bar chart breaks down query intents (factual, temporal, relational, causal, exploratory). Quick action buttons let you run LanceDB compaction or force a config reload.

### Search

The search view replaces the old inline HTML search page. Three tabs:

- **Recall** -- Enter a query (e.g., "What tools does APT28 use?"). Results appear as cards showing note ID, tier pill (A/B/C color-coded), domain, content, entity tags, confidence, and timestamp. Cards get a blue border on hover.
- **Synthesize** -- Same query input but with a format selector (direct_answer, synthesized_brief, timeline_analysis, relationship_map). Results render as a synthesis block with source note IDs.
- **Remember** -- Textarea for storing new CTI content. After submission, shows the note ID, status (ADD/UPDATE/DELETE/NOOP), latency, and extracted entities.

### Knowledge Graph

The knowledge graph view renders entity nodes and relationship edges as a 2D SVG force-directed layout (3D Three.js rendering is planned for a future release). Each node type has a distinct color:

- **Threat actors**: blue (`#58A6FF`), hexagonal
- **CVEs**: red (`#F85149`), diamond
- **Tools**: purple (`#A371F7`), square
- **Campaigns**: amber (`#D29922`), circle
- **Other entities**: grey (`#8B949E`), small dot

Node size varies by confidence score. Edges are colored by relationship type (uses, targets, attributed_to, temporal). Click any node to see a detail panel with the entity name, aliases, tier, confidence, and connected entities. Use the search input to highlight nodes by name or alias -- alias resolution works here too ("Fancy Bear" highlights the APT28 node). The filter panel lets you toggle labels, filter by entity type, or tier.

### Logs & Telemetry

Two-panel layout:

- **Log panel** -- Filterable table of structlog events. Columns: timestamp, level badge (ERROR=red, WARNING=amber, INFO=default, DEBUG=dim), logger name, message. Use the level dropdown to filter by severity or the text input to search. Enable auto-refresh to poll every 3 seconds. Click any row to expand the full structured JSON context. The SSE stream endpoint provides live updates.
- **Telemetry panel** -- Aggregated daily statistics: query volume, latency percentiles, intent distribution. Charts render with Chart.js (loaded from CDN).

### Ingest

Three input modes:

- **Text area** -- Paste CTI content and submit. Configure source metadata (domain: cti/sigma/yara/report/general; source_type: manual/report/feed/api; evolve toggle). After submission, see the note ID, extracted entities, and latency.
- **Bulk mode** -- Multi-line textarea (one item per line). Submits via the `/api/ingest` endpoint. Progress shows N/M stored, per-item success/failure status.
- **File upload** -- Drag and drop `.txt`, `.md`, `.json` (STIX bundle), or `.csv` files. File content is read and populates the textarea for review before submission.

### Entities

A paginated table showing all entities in the knowledge graph. Columns: entity name, type badge, tier pill, confidence, aliases, first seen, last seen, connected count. Use the filter bar (type dropdown, tier checkboxes, text search) to narrow results. Click column headers to sort. Click any row to expand an inline detail panel showing the full entity data and a link to "View in Knowledge Graph".

### History

A chronological table of recent activity tracked by the TelemetryCollector. Columns: timestamp, type badge (recall=blue, synthesis=purple, remember=green), query text, latency (ms), result count, intent. Use the date range filter (today, 7 days, 30 days, all). Click any row to expand full details: note IDs retrieved, synthesis text, feedback events. The "Re-run query" button navigates to the Search view and pre-fills the query. The "Export JSON" button downloads a blob.

### Configuration

Two modes:

- **Feature Flags** -- Grouped cards showing every config section (LLM, Embedding, Retrieval, Synthesis, Governance, etc.). Boolean fields render as toggle switches. Text/number fields are editable inputs. Secrets (API keys, passwords, tokens) show as `***` and are read-only. Click "Apply Changes" to send updates. Fields requiring a restart show an amber "Restart Required" badge.
- **YAML Editor** -- Full `config.yaml` content in a monospace textarea. Edit directly, then click "Apply". A warning banner notes that some changes require a restart.

---

## API Authentication

All API endpoints (except `GET /`) require authentication. Two modes:

- **Loopback** (default): When the server is bound to `127.0.0.1`, no API key is required. The testclient hostname is also in the loopback allowlist.
- **API key**: When the server is bound to `0.0.0.0` or any non-loopback address, set `ZETTELFORGE_WEB_API_KEY` and pass it via the `X-API-Key` header or as a Bearer token in the `Authorization` header.

```bash
# Set the API key
export ZETTELFORGE_WEB_API_KEY=my-secret-key

# Use it in requests
curl -H "X-API-Key: my-secret-key" http://your-host:8088/api/health
```

The SPA reads the API key from `localStorage` key `zettelforgeApiKey`. Set it in browser developer tools or via a script:

```javascript
localStorage.setItem('zettelforgeApiKey', 'my-secret-key');
```

---

## Next Steps

- [Web API Reference](../reference/web-api.md) -- Full endpoint documentation with request/response examples.
- [Configuration Reference](../reference/configuration.md) -- All config keys including the `web:` section.
- [Quickstart Tutorial](../tutorials/01-quickstart.md) -- Store your first CTI notes.
- [Memory Manager API](../reference/memory-manager-api.md) -- Python API used under the hood.
