# RFC-015: ZettelForge Web Management Interface

## Metadata

- **Author**: Patrick Roland
- **Status**: Draft
- **Created**: 2026-04-25
- **Last Updated**: 2026-04-25
- **Reviewers**: TBD
- **Related Tickets**: ZF-015
- **Related RFCs**: RFC-003 (adversarial review), RFC-007 (operational telemetry), RFC-011 (local LLM backend), RFC-012 (LiteLLM provider), RFC-013 (PII detection), RFC-014 (content limits)

## Summary

Replace ZettelForge's inline HTML page (`web/app.py`, ~180 lines of embedded HTML+CSS+JS) with a full-featured single-page application that serves as the product's primary management interface. The new GUI provides: a 3D interactive knowledge graph viewer with orbital navigation, a live logs and telemetry dashboard, manual data ingestion panel, configuration editor with YAML schema support, feature toggles, system health monitoring, and session history — all styled with the ZettelForge Design System (Neural Dark, Neuropol + Inter + JetBrains Mono, `#00FFA3` signal accent).

## Motivation

The current web UI at `GET /` serves a single ~180-line inline HTML page with basic search, synthesis, remember, and OpenCTI sync tabs. It is functional for quick querying but lacks the depth needed for three core user personas:

**1. CTI analysts** need to explore the knowledge graph visually — not just read JSON-shaped results, but see entity nodes, edges, temporal relationships, and alias clusters in a 3D space they can navigate. The `KnowledgeGraph` module stores rich entity data (CVEs, actors, tools, campaigns) with causal triples and temporal edges, but the current UI renders only flat text results.

**2. System operators** need a dashboard showing telemetry (per-query latency, recall rates, synthesis quality), live log streaming (structlog events, OCSF audit events, JSONL telemetry), and system health indicators (LanceDB compaction status, enrichment queue depth, embedding model loaded, LLM provider status). The `TelemetryCollector` already writes detailed per-query JSONL files, but there is no way to inspect them without reading raw files.

**3. Configuration managers** need to view and edit `config.yaml` settings from the UI — toggle PII detection, switch LLM providers, adjust governance limits, select local backend engine (llama-cpp-python vs onnxruntime-genai), enable/disable features, and see which features are enterprise-gated vs community-available.

### What the user explicitly asked for

- Logs and telemetry visibility
- Knowledge graph representation with 3D navigation
- Manual ingestion (input CTI text and store it)
- Configuration and feature management

### What I've added based on gap analysis

- **System health panel**: embedding model status, storage backend type, enrichment queue depth, LLM provider connectivity, memory usage, data directory size
- **Session history / query log**: browse past searches, synthesis calls, and remember operations with timestamps, latency, and result counts
- **Entity browser**: table view of all indexed entities (actors, CVEs, tools, campaigns) with filter and search, linked to graph view
- **Synthesis format selector**: choose between direct_answer, synthesized_brief, timeline_analysis, and relationship_map from the UI
- **YAML config editor**: direct YAML editing with syntax highlighting, validation, and real-time apply (no restart) where possible
- **Dark theme by default**: the ZettelForge Design System specifies Neural Dark as canonical; no light mode for the app

## Proposed Design

### Architecture

The GUI is served as a static SPA from a new `web/ui/` directory. The existing FastAPI backend (`web/app.py`) is extended with new REST endpoints. The SPA communicates with the backend exclusively via JSON APIs — no server-side rendering, no templates.

```
web/
  app.py              # Extended with new endpoints
  auth.py             # Unchanged
  mcp_server.py       # Unchanged
  ui/                 # NEW — static SPA
    index.html        # Entry point (minimal shell)
    colors_and_type.css   # Design tokens (copied from design system)
    fonts/Neuropol.otf   # Brand font
    favicon.svg           # Brand favicon
    assets/               # Logo SVGs, mark icons
    js/
      app.js            # Main SPA — React-like vanilla JS framework
      router.js         # URL hash routing (#/dashboard, #/graph, #/logs, etc.)
      components/       # Reusable UI components
        header.js       # Top bar with brand mark, navigation, stats
        sidebar.js      # Navigation sidebar with sections
        search-bar.js   # CTI search input
        result-card.js  # Memory note display card
        tabs.js         # Tab bar component
        panel.js        # Config panel component
        modal.js        # Modal overlay
        toast.js        # Notification toast
        spinner.js      # Loading indicator
      views/            # Page-level views
        dashboard.js    # System health overview
        search.js       # Recall / synthesize search view
        graph.js        # 3D knowledge graph viewer
        logs.js         # Telemetry and log viewer
        ingest.js       # Manual ingestion panel
        config.js       # Configuration editor
        entities.js     # Entity browser
        history.js      # Session history
      lib/
        api.js          # fetch wrapper for all backend endpoints
        state.js        # Simple reactive state manager
        graph-3d.js     # Three.js-based 3D knowledge graph renderer
        yaml-editor.js  # Simple YAML editor with validation
        telemetry-charts.js   # Chart rendering (Chart.js via CDN)
        log-stream.js   # Server-Sent Events log stream consumer
```

### Backend API Extensions

New endpoints added to `web/app.py`:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | System health: version, edition, storage backend, embedding status, LLM status, enrichment queue depth, memory usage, data dir size |
| `GET` | `/api/config` | Current config (redacted secrets) as YAML or JSON |
| `PUT` | `/api/config` | Apply config changes (subset supported at runtime, full reload requires restart) |
| `GET` | `/api/telemetry` | Telemetry summary: daily aggregates, recent queries, top intents |
| `GET` | `/api/telemetry/stream` | Server-Sent Events stream of live telemetry events |
| `GET` | `/api/logs` | Recent structlog events (last N lines from log file) |
| `GET` | `/api/logs/stream` | Server-Sent Events stream of live log entries |
| `GET` | `/api/graph/nodes` | All entity nodes for graph rendering |
| `GET` | `/api/graph/edges` | All relationship edges for graph rendering |
| `GET` | `/api/graph/search?q=...` | Search graph nodes by entity name/type/alias |
| `GET` | `/api/entities` | Paginated entity index with filters (type, tier, date range) |
| `GET` | `/api/entities/:id` | Single entity detail with connected entities and timeline |
| `GET` | `/api/history` | Recent session activity (recall/synthesize/remember calls) |
| `GET` | `/api/storage` | Storage stats: total notes, entity count, graph size, db size |
| `POST` | `/api/ingest` | Bulk ingestion endpoint (accept text, URL fetch, or JSON report) |
| `POST` | `/api/restart` | Trigger graceful restart after config changes |

### Views Detail

#### 1. Dashboard (system health)

A tiled overview of system status:

```
+--------------------------------------------------------------+
|  ZETTELFORGE / SYSTEM HEALTH                                 |
|                                                              |
|  [Storage]        [LLM]            [Embedding]    [Queue]    |
|  SQLite + LanceDB  Ollama / LlamaCpp  Fastembed   0 pending  |
|  4,060 notes       qwen3.5:9b       loaded        idle      |
|  847 entities      47ms avg         7ms/chunk     --------  |
|  25 MB             97% uptime       768-dim       --------  |
|                                                              |
|  [Telemetry Today]              [Top Intents This Week]      |
|  142 queries · 47ms avg         factual   ████████ 48%      |
|  28 syntheses · 312ms avg       temporal  ████     22%      |
|  15 remembers · 45ms avg        causal    ███      17%      |
|                                 relational ██      10%      |
|  [Quick Actions]               exploratory █       3%       |
|  [Run Compaction]  [Force Sync]                              |
+--------------------------------------------------------------+
```

Telemetry data from `TelemetryCollector` JSONL files is aggregated server-side into daily summaries. Client renders using Chart.js (lightweight, no build step) for bar/line charts of query volume and latency over time.

#### 2. Knowledge Graph (3D viewer)

Three.js-based 3D force-directed graph with orbital navigation:

- **Camera controls**: orbit (drag to rotate), pan (right-drag or shift-drag), zoom (scroll wheel or pinch). Inspired by the existing `DesignCanvas.jsx` in the design system (pan/zoom with gesture support), extended to 3D.
- **Nodes**: entity types rendered as distinct shapes — threat actors as hexagons (`#58A6FF`), CVEs as diamonds (`#F85149`), tools as squares (`#A371F7`), campaigns as circles (`#D29922`), notes as small dots (`#8B949E`). Active/selected node gets the `#00FFA3` signal glow.
- **Edges**: relationship types color-coded — `uses` (blue `#58A6FF`), `targets` (red `#F85149`), `attributed_to` (purple `#A371F7`), temporal `before`/`after` (orange `#F0883E`), `supersedes` (pink `#DB61A2`). Dashed lines for temporal edges, solid for semantic.
- **Interaction**: click a node to show entity detail panel (name, aliases, tier, confidence, connected entities, timeline of events). Double-click to center and zoom. Hover to show label. Mouse wheel zooms.
- **Search**: text input to highlight matching nodes. Alias resolution — searching "Fancy Bear" highlights the APT28 node.
- **Controls panel**: toggle edge labels, filter by entity type, filter by tier (A/B/C), time-range slider for temporal edges, reset camera button, export as SVG.
- **Performance**: node count capped at 2,000 visible nodes with distance-based LOD. Beyond that, clusters are collapsed into aggregate nodes with count badges.

Rendering approach: use Three.js via CDN (`https://cdnjs.cloudflare.com/ajax/libs/three.js/r152/three.min.js`) plus OrbitControls. The force-directed layout runs in a Web Worker to keep the UI responsive. Spring-based force simulation (repulsion between nodes, attraction along edges, centering force) runs at ~30fps on the GPU.

#### 3. Logs and Telemetry

Two-panel layout:

**Log panel** (left / top):
- Virtual-scrolled list of recent structlog events, one row per event
- Columns: timestamp, level (color-coded badge: ERROR=red, WARNING=amber, INFO=default, DEBUG=dim), logger name, message
- Filter by level, logger name, text search
- Auto-scroll with pause toggle (when paused, new entries append silently; a "N new" badge appears)
- Server-Sent Events stream for live updates (`/api/logs/stream`)
- Expand row to show full structured context (JSON dict)

**Telemetry panel** (right / bottom):
- Tabbed: Query Volume, Latency, Intent Distribution, Feedback
- Charts from Chart.js: daily query count bar chart, latency percentile line chart (p50/p95/p99), intent distribution donut, feedback utility histogram (1-5)
- Date range picker (today, 7 days, 30 days, custom)
- Data source: aggregated from `~/.amem/telemetry/telemetry_YYYY-MM-DD.jsonl` files
- Export as CSV button

#### 4. Manual Ingestion

Evolution of the current "Remember" tab with additional capabilities:

- **Text input**: large textarea (same as current `RememberPanel.jsx`) with placeholder "Paste threat intelligence text, IOCs, or report content..."
- **Source metadata**: domain selector (cti, sigma, yara, report, general), source type selector (manual, report, feed, api), source ref text input (URL or document ID), tier override (auto/A/B/C)
- **File upload**: drag-and-drop area or file picker for .txt, .json (STIX bundle), .md, .csv (IOC list). Server extracts entities client-side preview before submission.
- **Bulk mode**: submit multiple items at once with progress indicator (N/M stored, per-item status)
- **Feedback row**: after ingestion, show what was detected — extracted entities list, aliases resolved, tier assigned, confidence score. Collapsible detail section.

#### 5. Configuration and Features

Dual-mode panel:

**Feature flags view** (default):
- Grouped section cards: Core, Retrieval, Synthesis, Governance, LLM, Embedding, Storage, Extensions
- Each feature shows name, current value, description, and whether it requires enterprise edition
- Toggle switches for boolean configs (governance.enabled, pii.enabled, etc.)
- Dropdown selects for constrained values (llm.provider, embedding.provider, governance.pii.action)
- Number inputs for numeric configs (retrieval.default_k, governance.limits.max_content_length)
- "Requires restart" badge next to fields that need a process restart
- "Apply Changes" button pushes `PUT /api/config` with only changed values

**YAML editor view** (advanced):
- Full config.yaml display in a monospace textarea with YAML syntax highlighting (client-side, simple regex-based)
- Validation indicator (green checkmark / red error with line number)
- "Apply" button sends the full YAML to `PUT /api/config` (server validates, rejects invalid fields)
- "Reset to defaults" button
- Warning banner: "Some changes require a restart. Click 'Restart Now' when ready."

**Secrets redaction**: both views show `***` for sensitive fields (api_key, password, license_key). The `PUT /api/config` endpoint accepts the redacted value as a no-op sentinel (skip field if value is `***`).

#### 6. Entity Browser

Table view of all indexed entities:

- Columns: entity name, type (actor, CVE, tool, campaign, etc.), tier, confidence, aliases, first seen, last seen, connected count
- Sortable columns, client-side pagination (50 per page)
- Filter bar: type dropdown, tier checkboxes, text search across name and aliases
- Click row to expand inline detail: full entity JSON, timeline of related notes, connected entities graph (small 2D force graph in a modal)
- Link to graph view ("View in Knowledge Graph") that pre-fills the graph view with the entity highlighted

#### 7. Session History

Chronological activity log:

- One row per `start_query()` call tracked by `TelemetryCollector`
- Columns: timestamp, query text (truncated), type (recall/synthesize/remember), latency (ms), result count, intent
- Click to expand: show full query, all retrieved note IDs, synthesis result text, feedback events
- Date range filter
- Export as JSON or CSV
- "Re-run query" button that navigates to search view and executes the same query

### Navigation

Left sidebar with icon-labeled items:

```
|  ZF  |  ZettelForge v2.4.3
|------|
|  [~] |  Dashboard
|  [/] |  Search / Explore
|  [G] |  Knowledge Graph
|  [L] |  Logs & Telemetry
|  [+] |  Ingest Data
|  [E] |  Entities
|  [H] |  History
|  [*] |  Configuration
|------|
|  [i] |  System Info
```

Sidebar collapses to icon-only at <960px viewport width. Active section is highlighted with the `#00FFA3` signal green left border accent.

### Design System Integration

All visual decisions follow `colors_and_type.css` from the design system archive:

- **Background**: `#0A0E17` (graphite-0) — the canonical Neural Dark canvas
- **Surfaces**: `#161B22` (graphite-3) with `1px solid #30363D` (graphite-5) borders
- **Typographic hierarchy**: Inter for UI labels and body, JetBrains Mono for all data (entity IDs, CVEs, timestamps, metrics, config YAML, log lines), Neuropol for the wordmark only
- **Signal accent**: `#00FFA3` reserved for one element per view — the active navigation item, the currently selected graph node, the status indicator
- **Card radius**: `8px` for panels and cards, `6px` for inputs/buttons, `9999px` for entity pill tags
- **No shadows** in the app UI (flat per design system rules). Focus states use `0 0 0 3px rgba(88,166,255,0.10)` halo
- **Hover**: border color shifts to `#58A6FF` (the link/info-blue)
- **Spacing**: `--sp-4: 16px` interior card padding, `--sp-6: 24px` page padding, `--sp-8: 32px` section spacing
- **Icons**: Lucide via CDN (`16px` inline, `currentColor`). The design system explicitly recommends Lucide for UI icons.
- **Font loading**: Neuropol via `@font-face { src: url('fonts/Neuropol.otf') }`, Inter + JetBrains Mono via Google Fonts CDN

### Component Inventory (from design system)

The existing `ui_kits/web_ui/` components are directly reusable:

| Component | Design System File | Reuse in New GUI |
|-----------|-------------------|------------------|
| Header | `Header.jsx` | Direct — brand mark, stats, user avatar |
| SearchBar | `SearchBar.jsx` | Direct — query input with focus styling |
| TabBar | `TabBar.jsx` | Adapted — sub-navigation within views |
| ResultCard | `ResultCard.jsx` | Direct — memory note display |
| SynthesisBlock | `SynthesisBlock.jsx` | Direct — synthesis answer display |
| RememberPanel | `RememberPanel.jsx` | Extended — source metadata + file upload |
| EmptyState | `Misc.jsx` (EmptyState) | Direct |
| MetaBar | `Misc.jsx` (MetaBar) | Direct |
| SyncPanel | `Misc.jsx` (SyncPanel) | Kept for enterprise-gated sync UI |

### 3D Graph Rendering Library Options

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| Three.js (CDN) | Battle-tested, GPU-accelerated, OrbitControls support, large ecosystem, ~140KB gzipped | Higher learning curve, no built-in graph layout | **Chosen** — best performance with thousands of nodes |
| D3-force + canvas | Lighter (single D3 module), familiar force layout | No 3D, 2D only, slower with 500+ nodes | Rejected — user explicitly asked for 3D navigation |
| Vis.js Network | Drop-in graph component, built-in physics | No 3D, limited styling, unmaintained | Rejected — no 3D, stale project |
| Sigma.js | WebGL-accelerated 2D graph, fast | No 3D, dependency on WebGL without 3D benefit | Rejected — 2D only |

Three.js is preferred despite the size because:
- It supports true 3D orbital navigation (the user's explicit requirement)
- GPU rendering handles 2,000+ nodes at 60fps
- OrbitControls provides camera rotation, pan, and zoom out of the box
- The existing design system's `DesignCanvas.jsx` proves pan/zoom is a first-class pattern in the brand

### File Changes

| File | Change Type | Purpose |
|------|-------------|---------|
| `web/app.py` | Modify | Add 15+ new API endpoints, SSE stream handlers |
| `web/ui/index.html` | Create | SPA shell — CSS, JS imports, root div, no server-side content |
| `web/ui/colors_and_type.css` | Copy | Design tokens from ZettelForge Design System archive |
| `web/ui/fonts/Neuropol.otf` | Copy | Brand display font |
| `web/ui/favicon.svg` | Copy | Brand favicon from design system assets |
| `web/ui/assets/logo.svg` | Copy | Shield-and-neuron mark |
| `web/ui/assets/threatrecall-lockup.svg` | Copy | Wordmark variant |
| `web/ui/assets/zettelforge_architecture.svg` | Copy | Architecture diagram (system info view) |
| `web/ui/js/app.js` | Create | Main application shell, route switching, state management |
| `web/ui/js/router.js` | Create | Hash-based SPA router |
| `web/ui/js/lib/api.js` | Create | fetch wrapper with auth headers, error handling, retry |
| `web/ui/js/lib/state.js` | Create | Reactive state store (pub/sub pattern, no framework) |
| `web/ui/js/lib/graph-3d.js` | Create | Three.js 3D graph renderer with force layout, orbit controls, node/edge styling |
| `web/ui/js/lib/yaml-editor.js` | Create | YAML text editor with syntax highlighting and validation |
| `web/ui/js/lib/telemetry-charts.js` | Create | Chart.js wrapper for dashboard charts |
| `web/ui/js/lib/log-stream.js` | Create | EventSource consumer for SSE log and telemetry streams |
| `web/ui/js/components/*.js` (10 files) | Create | Reusable UI components |
| `web/ui/js/views/*.js` (8 files) | Create | Page-level view modules |
| `config.default.yaml` | Modify | Add `web.ui` config section (port, ui_dir path, etc.) |
| `src/zettelforge/config.py` | Modify | Add `WebConfig` dataclass with ui settings |
| `tests/test_web_api.py` | Create | Integration tests for new API endpoints |
| `pyproject.toml` | Modify | Add `web` extra with optional deps (three.js not needed — CDN) |

### Backend Implementation Notes

#### API: `/api/health`

```python
@app.get("/api/health")
async def health(request: Request):
    import psutil  # optional, graceful fallback
    mm = get_mm_for_request(request)
    from zettelforge.telemetry import get_telemetry

    return {
        "version": __version__,
        "edition": "enterprise" if is_enterprise() else "community",
        "storage_backend": os.environ.get("ZETTELFORGE_BACKEND", "sqlite"),
        "embedding_provider": get_config().embedding.provider,
        "embedding_model": get_config().embedding.model,
        "llm_provider": get_config().llm.provider,
        "llm_model": get_config().llm.model,
        "llm_local_backend": get_config().llm.local_backend,
        "enrichment_queue_depth": mm._enrichment_queue.qsize() if hasattr(mm, '_enrichment_queue') else 0,
        "governance_enabled": get_config().governance.enabled,
        "pii_enabled": get_config().governance.pii.enabled,
        "uptime_seconds": time.monotonic() - _start_time,
        "data_dir": get_config().storage.data_dir,
        "memory_usage_mb": _get_memory_mb(),  # psutil or /proc/self/status
        "data_size_mb": _get_data_dir_size_mb(),
    }
```

#### API: `/api/graph/nodes` and `/api/graph/edges`

These endpoints serialize the in-memory `KnowledgeGraph` caches into a format Three.js can consume:

```python
@app.get("/api/graph/nodes")
async def graph_nodes(request: Request):
    mm = get_mm_for_request(request)
    kg = mm._knowledge_graph  # access the KG instance
    nodes = []
    for nid, node in kg._nodes.items():
        nodes.append({
            "id": nid,
            "label": node.get("name", nid),
            "type": node.get("entity_type", "unknown"),
            "tier": node.get("tier", "C"),
            "aliases": node.get("aliases", []),
            "confidence": node.get("confidence", 0.5),
            "created_at": node.get("created_at"),
        })
    return {"nodes": nodes, "count": len(nodes)}

@app.get("/api/graph/edges")
async def graph_edges(request: Request):
    mm = get_mm_for_request(request)
    kg = mm._knowledge_graph
    edges = []
    for eid, edge in kg._edges.items():
        edges.append({
            "id": eid,
            "source": edge.get("source_id"),
            "target": edge.get("target_id"),
            "relationship": edge.get("relationship"),
            "created_at": edge.get("created_at"),
        })
    return {"edges": edges, "count": len(edges)}
```

#### SSE Log Streaming

```python
import asyncio

@app.get("/api/logs/stream")
async def log_stream(request: Request):
    async def event_generator():
        # Tail the structlog file
        log_path = Path(get_config().logging.log_file).expanduser()
        if not log_path.exists():
            yield f"data: {json.dumps({'event': 'log file not found', 'level': 'WARNING'})}\n\n"
            return

        with open(log_path) as f:
            f.seek(0, 2)  # tail end
            while True:
                line = f.readline()
                if line:
                    try:
                        event = json.loads(line)
                        yield f"data: {json.dumps(event)}\n\n"
                    except json.JSONDecodeError:
                        pass
                else:
                    await asyncio.sleep(0.1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

#### Config PUT Endpoint

```python
@app.put("/api/config")
async def update_config(data: dict, request: Request):
    # Validate incoming keys match known config fields
    # Apply changes to in-memory config (subset supported)
    # For changes requiring restart, set a flag
    # Return list of applied changes + list of pending-restart changes
    pass
```

#### Ingest Endpoint

```python
from pydantic import BaseModel
from typing import Optional

class IngestItem(BaseModel):
    content: str
    source_type: str = "manual"
    source_ref: str = ""
    domain: str = "cti"
    evolve: bool = True
    tier: Optional[str] = None  # override auto-tiering

class IngestRequest(BaseModel):
    items: list[IngestItem]

@app.post("/api/ingest")
async def ingest(request: Request, req: IngestRequest):
    tenant_mm = get_mm_for_request(request)
    results = []
    for item in req.items:
        try:
            note, status_text = tenant_mm.remember(
                content=item.content,
                source_type=item.source_type,
                source_ref=item.source_ref,
                domain=item.domain,
                evolve=item.evolve,
            )
            results.append({
                "note_id": note.id,
                "status": status_text,
                "entities": note.semantic.entities[:10],
                "success": True,
            })
        except Exception as e:
            results.append({
                "status": "error",
                "error": str(e),
                "success": False,
            })
    return {
        "total": len(results),
        "succeeded": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results,
    }
```

### Zero-Dependency Frontend Approach

The SPA is built with vanilla JavaScript — no React, no build step, no npm, no Webpack. Rationale:

1. **CDN-loaded libraries** (Three.js, Chart.js, Lucide) are the only external dependencies. The application code is pure ES6 modules served as static files.
2. **No build step** means the UI ships as plain HTML/CSS/JS in the repo. Users can hack on it in any text editor. No `npm install`, no `node_modules`, no build errors.
3. **Zero npm supply chain risk** — every dependency is loaded from a pinned CDN URL with integrity hashes. No transitive dependency surprises.
4. **Fast cold start** — `python web/app.py` serves the UI immediately. No npm install step in setup or CI.
5. **Consistent with project philosophy** — the project explicitly avoids heavy frameworks (no LangChain, no LiteLLM as a framework). The UI follows the same principle.

The `app.js` module uses a lightweight reactive pattern:

```javascript
// Simple observable store
const store = {
  _state: { view: 'dashboard', sidebar: true },
  _listeners: {},
  get(key) { return this._state[key]; },
  set(key, value) {
    this._state[key] = value;
    (this._listeners[key] || []).forEach(fn => fn(value));
  },
  on(key, fn) {
    (this._listeners[key] = this._listeners[key] || []).push(fn);
  },
};
```

Routing uses `hashchange`:

```javascript
window.addEventListener('hashchange', () => {
  const view = location.hash.slice(1) || 'dashboard';
  renderView(view);
});
```

### Responsive Layout

- **>960px**: sidebar visible + content area. Sidebar is fixed-width (200px) with the header above.
- **<960px**: sidebar collapses to icon-only (64px). Content fills remaining width. Header stats move to a collapsible menu.
- **<640px**: sidebar becomes a bottom tab bar (mobile-style). Header compresses to brand mark only.
- The 960px content max-width from the design system is preserved for search and reading views. Dashboard and config views use full width within the sidebar-constrained area.

## Migration

**Existing users:** Zero changes. The existing `GET /` inline HTML page is replaced by the SPA at the same route. All existing API endpoints (`/api/recall`, `/api/remember`, `/api/synthesize`, `/api/sync`, `/api/stats`, `/api/edition`, `/auth/*`) remain unchanged and functional. The old inline HTML is removed.

**Programmatic API consumers:** Unaffected. All new endpoints are additive. The existing REST API surface is preserved.

**Design System archive:** The `colors_and_type.css`, `fonts/Neuropol.otf`, and `assets/` are copied into `web/ui/` at build/setup time. The original archive at `/mnt/usb-hdd/ZettelForge Design System.zip` remains the canonical source.

## Dependencies

| Dependency | Version | Source | Size (gzip) | Purpose |
|------------|---------|--------|-------------|---------|
| Three.js | r152+ | CDN | ~140 KB | 3D graph rendering |
| OrbitControls | r152+ | CDN | ~8 KB | 3D camera controls |
| Chart.js | v4+ | CDN | ~70 KB | Telemetry charts |
| Lucide | latest | CDN | ~30 KB (tree-shaken via icons used) | UI icons |
| psutil | 5.9+ | PyPI (optional) | ~1 MB | System health metrics |

psutil is added as an optional dependency (`pip install zettelforge[web]`). The health endpoint degrades gracefully without it (returns `null` for memory/disk metrics instead of raising).

## Alternatives Considered

**Alternative 1: React SPA with Vite build.** React 18 + Vite + npm build pipeline. Rejected because: (a) adds a build step to a currently zero-build project; (b) introduces npm audit, supply chain risk, and dependency churn; (c) the project's CLAUDE.md explicitly avoids adding frameworks; (d) the existing design system's web UI kit is vanilla JSX (Babel-transpiled in-browser), not a React project with a build system.

**Alternative 2: Keep the old inline HTML, add tabs.** Extend the existing `HTML_PAGE` constant with more tabs. Rejected because: (a) the page is already 180+ lines of inline HTML+CSS+JS — adding 8 views to a single string is not maintainable; (b) inline HTML precludes modular JS, CDN library loading, and SSE streaming; (c) the 3D graph viewer cannot be embedded in an inline string.

**Alternative 3: Multi-page server-rendered templates (Jinja2).** FastAPI + Jinja2 templates for each page. Rejected because: (a) server-rendered pages mean reload on every navigation — worse UX than SPA; (b) the 3D graph viewer is inherently client-side; (c) SSE log streaming is harder to integrate with page reloads; (d) the design system explicitly describes the UI as "a single-page search tool, not a dashboard shell" — but the user is now asking for a dashboard.

**Alternative 4: Grafana for telemetry, separate GraphDB UI.** Use existing tools instead of building. Rejected because: (a) adds external service dependencies; (b) the project philosophy is in-process, no external services; (c) Grafana cannot render the knowledge graph; (d) the user explicitly wants one integrated interface.

## Open Questions

1. **Should the 3D graph viewer support AR/VR (WebXR)?** Three.js has WebXR support. Could be useful for SOC wall displays. Deferred to v2 — v1 focuses on desktop orbital navigation.

2. **Should the config editor support live-reload for all fields?** Some config fields (data_dir, provider switches) require full restart. A restart endpoint (`POST /api/restart`) is proposed, but async restart handling (wait for active queries to drain, then restart the process) needs design. Proposal for v1: mark restart-required fields in the UI, provide a manual restart button. Streamlined zero-downtime restart is v2.

3. **What about WebSocket-based log streaming instead of SSE?** SSE is simpler (no reconnect logic needed, browser-native EventSource API) and sufficient for one-way log streaming. WebSocket would allow bidirectional (e.g., sending commands from the UI to the server). Proposal: SSE for v1. WebSocket for v2 if needed.

4. **Should the entity browser support bulk tag/edit operations?** v1 is browse-only. Bulk operations (merge entities, retier, delete) are v2.

5. **How should the 3D graph handle very large graphs (10,000+ nodes)?** Proposal for v1: cap at 2,000 visible nodes with hierarchical clustering. Entities with >50 connections become "supernodes" with expandable subgraphs. Full graph export to JSONL available via download. Proper LOD and spatial indexing deferred to v2.

## Decision

**Decision**: [Pending review]
**Date**: [Pending]
**Decision Maker**: [Pending]
**Rationale**: [Pending]

## Implementation Plan

### Phase 1: Backend API Extensions + Frontend Scaffold (v2.5.0)

1. Add health, config, telemetry, graph nodes/edges, entities, history, ingest API endpoints to `web/app.py`
2. Add SSE log streaming endpoint to `web/app.py`
3. Create `web/ui/` directory with `index.html` SPA shell, `colors_and_type.css` (from design system), favicon/logo assets
4. Create `web/ui/js/app.js`, `router.js`, `lib/api.js`, `lib/state.js`
5. Create all component files in `web/ui/js/components/`
6. Create Dashboard and Search views
7. Update `config.default.yaml` and `config.py` with `WebConfig`
8. Add `web` extra to `pyproject.toml`
9. Write integration tests for new API endpoints
10. Replace `GET /` inline HTML with SPA redirect (or inline embed of the SPA shell)

### Phase 2: Knowledge Graph 3D Viewer (v2.5.0 or v2.6.0)

1. Create `web/ui/js/lib/graph-3d.js` — Three.js scene setup, OrbitControls, force layout
2. Create the Graph view (`web/ui/js/views/graph.js`)
3. Wire up `/api/graph/nodes` and `/api/graph/edges` to the 3D renderer
4. Handle node click/interaction/selection with entity detail panel
5. Add search, filter, and export controls
6. Performance testing with 500/1000/2000 node graphs

### Phase 3: Logs, Telemetry, Config, History, Ingestion (v2.5.0 or v2.6.0)

1. Create Logs & Telemetry view with SSE streaming and Chart.js charts
2. Create Config view with feature flags and YAML editor
3. Create Entity Browser view with table and detail
4. Create History view with session activity log
5. Enhance Ingestion view with file upload and bulk mode
6. Create Ingest and Config views
7. Add responsive layout breakpoints

### Phase 4: Polish and Edge Cases (v2.6.0)

1. Error boundaries in all views (API failure fallbacks)
2. Loading states and skeleton screens
3. Keyboard shortcuts (Shift+/ to focus search, Escape to close panels, etc.)
4. Browser history integration (back/forward navigation)
5. Performance optimization (lazy view loading, request debouncing)
6. Documentation in `docs/` for the web interface

## Rollout Strategy

**Phase 1** (v2.5.0): New API endpoints ship alongside existing endpoints. The old inline HTML is removed; `GET /` serves the new SPA. If the SPA fails to load (missing assets), the API endpoints still work from curl/scripts.

**Rollback:** `git revert web/app.py` and restore the old `HTML_PAGE` constant. The SPA directory can be removed without breaking the API.

**Backward compatibility:** All existing API endpoints, auth flows, and integration points (MCP server, LangChain retriever) are untouched.
