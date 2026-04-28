"""
ThreatRecall Web UI — FastAPI backend + minimal HTML frontend.

A search-and-recall interface for ZettelForge's CTI memory system.

Usage:
    python web/app.py                    # Start on port 8088
    python web/app.py --port 9000        # Custom port
    uvicorn web.app:app --reload         # Dev mode

Endpoints:
    GET  /                    → Search UI (HTML)
    POST /api/recall          → Blended recall (vector + graph)
    POST /api/remember        → Store a note
    POST /api/synthesize      → RAG synthesis
    GET  /api/stats           → Memory system stats
    POST /api/sync            → Trigger OpenCTI sync
"""
import os
import sys
import time
import logging
from pathlib import Path

# Ensure zettelforge is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

os.environ.setdefault("ZETTELFORGE_BACKEND", "jsonl")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

from zettelforge import MemoryManager, __version__
from zettelforge.edition import is_enterprise, edition_name, EditionError
from web.auth import register_auth_routes, get_mm_for_request, get_current_user

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ThreatRecall" if is_enterprise() else "ZettelForge",
    description=edition_name(),
    version=__version__,
)

# Register OAuth/JWT auth routes (Enterprise: full OAuth, Community: pass-through)
register_auth_routes(app)

# Default memory manager (for unauthenticated/single-tenant mode)
mm = MemoryManager()


# ── Pydantic models ──────────────────────────────────────────────────────────

class RecallRequest(BaseModel):
    query: str
    k: int = 10
    domain: Optional[str] = None

class RememberRequest(BaseModel):
    content: str
    domain: str = "cti"
    source_type: str = "manual"
    source_ref: str = ""
    evolve: bool = True

class SynthesizeRequest(BaseModel):
    query: str
    format: str = "direct_answer"
    k: int = 10

class SyncRequest(BaseModel):
    limit: int = 20
    entity_types: Optional[List[str]] = None


# ── API endpoints ────────────────────────────────────────────────────────────

@app.post("/api/recall")
async def recall(request: Request, req: RecallRequest):
    tenant_mm = get_mm_for_request(request)
    start = time.perf_counter()
    results = tenant_mm.recall(req.query, domain=req.domain, k=req.k, exclude_superseded=False)
    latency = time.perf_counter() - start

    return {
        "query": req.query,
        "results": [
            {
                "id": n.id,
                "content": n.content.raw[:500],
                "domain": n.metadata.domain,
                "tier": n.metadata.tier,
                "confidence": n.metadata.confidence,
                "created_at": n.created_at,
                "entities": n.semantic.entities[:10],
                "context": n.semantic.context,
            }
            for n in results
        ],
        "count": len(results),
        "latency_ms": round(latency * 1000),
    }


@app.post("/api/remember")
async def remember(request: Request, req: RememberRequest):
    tenant_mm = get_mm_for_request(request)
    start = time.perf_counter()
    note, status = tenant_mm.remember(
        content=req.content,
        source_type=req.source_type,
        source_ref=req.source_ref,
        domain=req.domain,
        evolve=req.evolve,
    )
    latency = time.perf_counter() - start

    return {
        "note_id": note.id,
        "status": status,
        "entities": note.semantic.entities[:10],
        "latency_ms": round(latency * 1000),
    }


@app.post("/api/synthesize")
async def synthesize(request: Request, req: SynthesizeRequest):
    tenant_mm = get_mm_for_request(request)
    start = time.perf_counter()
    result = tenant_mm.synthesize(req.query, format=req.format, k=req.k)
    latency = time.perf_counter() - start

    return {
        "query": req.query,
        "format": req.format,
        "synthesis": result.get("synthesis", {}),
        "sources_count": result.get("metadata", {}).get("sources_count", 0),
        "latency_ms": round(latency * 1000),
    }


@app.get("/api/stats")
async def stats(request: Request):
    tenant_mm = get_mm_for_request(request)
    s = tenant_mm.get_stats()
    return {
        "version": __version__,
        "edition": "enterprise" if is_enterprise() else "community",
        "edition_name": edition_name(),
        "total_notes": s.get("total_notes", 0),
        "notes_created": s.get("notes_created", 0),
        "retrievals": s.get("retrievals", 0),
        "entity_index": s.get("entity_index", {}),
    }



@app.get("/api/config")
async def get_config(request: Request):
    """Return current config as nested dict for the settings panel."""
    from zettelforge.config import get_config
    cfg = get_config()
    return {
        "backend": cfg.backend,
        "storage": {"data_dir": cfg.storage.data_dir},
        "embedding": {
            "provider": cfg.embedding.provider,
            "model": cfg.embedding.model,
            "url": cfg.embedding.url,
            "dimensions": cfg.embedding.dimensions,
        },
        "llm": {
            "provider": cfg.llm.provider,
            "model": cfg.llm.model,
            "url": cfg.llm.url,
            "temperature": cfg.llm.temperature,
        },
        "extraction": {
            "max_facts": cfg.extraction.max_facts,
            "min_importance": cfg.extraction.min_importance,
        },
        "retrieval": {
            "default_k": cfg.retrieval.default_k,
            "similarity_threshold": cfg.retrieval.similarity_threshold,
            "entity_boost": cfg.retrieval.entity_boost,
            "max_graph_depth": cfg.retrieval.max_graph_depth,
        },
        "synthesis": {
            "max_context_tokens": cfg.synthesis.max_context_tokens,
            "default_format": cfg.synthesis.default_format,
            "tier_filter": cfg.synthesis.tier_filter,
        },
        "governance": {
            "enabled": cfg.governance.enabled,
            "min_content_length": cfg.governance.min_content_length,
        },
        "cache": {
            "ttl_seconds": cfg.cache.ttl_seconds,
            "max_entries": cfg.cache.max_entries,
        },
        "logging": {
            "level": cfg.logging.level,
            "log_to_stdout": cfg.logging.log_to_stdout,
            "log_file": cfg.logging.log_file,
        },
        "enterprise": {
            "license_key": cfg.enterprise.license_key,
        },
        "opencti": {
            "url": cfg.opencti.url,
            "token": cfg.opencti.token,
            "sync_interval": cfg.opencti.sync_interval,
        },
        # RFC-008 salience/spacing/decay/retrieval_weights
        "salience": {
            "enabled": cfg.salience.enabled,
            "distinctiveness_weight": cfg.salience.distinctiveness_weight,
            "signal_weight": cfg.salience.signal_weight,
            "isolation_weight": cfg.salience.isolation_weight,
            "recompute_interval_days": cfg.salience.recompute_interval_days,
        },
        "spacing": {
            "enabled": cfg.spacing.enabled,
            "half_life_days": cfg.spacing.half_life_days,
            "reinforcement_factor": cfg.spacing.reinforcement_factor,
            "decay_rate": cfg.spacing.decay_rate,
            "implicit_confirm_window_hours": cfg.spacing.implicit_confirm_window_hours,
            "reinforcement_threshold": cfg.spacing.reinforcement_threshold,
            "max_strength": cfg.spacing.max_strength,
        },
        "decay": {
            "enabled": cfg.decay.enabled,
            "hot_threshold": cfg.decay.hot_threshold,
            "hot_max_age_days": cfg.decay.hot_max_age_days,
            "warm_threshold_days": cfg.decay.warm_threshold_days,
            "frozen_threshold_days": cfg.decay.frozen_threshold_days,
            "relevance_freeze_threshold": cfg.decay.relevance_freeze_threshold,
        },
        "retrieval_weights": {
            "salience_weight": cfg.retrieval_weights.salience_weight,
            "tier_hot_multiplier": cfg.retrieval_weights.tier_hot_multiplier,
            "tier_warm_multiplier": cfg.retrieval_weights.tier_warm_multiplier,
            "tier_cold_multiplier": cfg.retrieval_weights.tier_cold_multiplier,
            "tier_frozen_multiplier": cfg.retrieval_weights.tier_frozen_multiplier,
        },
    }


RESTART_FIELDS = {
    "backend", "embedding.provider", "embedding.url", "llm.provider",
    "llm.model", "llm.url", "storage.data_dir", "logging.log_file",
    "logging.level",
}


@app.get("/api/config/meta")
async def config_meta():
    """Return schema metadata: restart-required fields, available enums."""
    return {
        "restart_required_fields": list(RESTART_FIELDS),
        "enums": {
            "backend": ["sqlite", "lance"],
            "embedding.provider": ["fastembed", "ollama"],
            "llm.provider": ["ollama", "local", "mock", "litellm"],
            "llm.local_backend": ["llama-cpp-python", "onnxruntime-genai"],
            "logging.level": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            "synthesis.default_format": ["direct_answer", "synthesized_brief"],
            "governance.pii.action": ["log", "redact", "block"],
        },
    }


@app.put("/api/config")
async def put_config(request: Request):
    """Apply a nested dict payload to the live config (env vars win on reload)."""
    from zettelforge.config import get_config, reload_config
    data = await request.json()
    cfg = get_config()
    applied = []
    pending_restart = []

    def apply_nested(obj, prefix, section):
        for k, v in (obj or {}).items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                apply_nested(v, path, section)
            elif hasattr(section, k):
                setattr(section, k, v)
                applied.append(path)
                if path in RESTART_FIELDS:
                    pending_restart.append(path)

    apply_nested(data, "", cfg)

    # Persist to yaml file so reload() picks it up next start
    from zettelforge.config import _find_config_file, _load_yaml, _save_yaml
    import yaml
    config_file = _find_config_file()
    if config_file and config_file.exists():
        file_data = _load_yaml(config_file)
    else:
        file_data = {}

    def merge_into(target, source):
        for k, v in (source or {}).items():
            if isinstance(v, dict) and k in target and isinstance(target[k], dict):
                merge_into(target[k], v)
            else:
                target[k] = v

    merge_into(file_data, data)
    _save_yaml(file_data, config_file or Path("config.yaml"))

    return {"applied": applied, "pending_restart": pending_restart}


@app.get("/api/edition")
async def edition_info():
    """Return current edition and available features."""
    features = {
        # Community — full-featured agentic memory system
        "vector_search": True,
        "blended_retrieval": True,
        "cross_encoder_reranking": True,
        "two_phase_extraction": True,
        "intent_adaptive_routing": True,
        "causal_triple_extraction": True,
        "entity_extraction_llm": True,
        "knowledge_graph_jsonl": True,
        "direct_answer_synthesis": True,
        "mcp_server": True,
        # Enterprise — scale, analyst workflows, integrations, ops
        "typedb_stix_ontology": is_enterprise(),
        "temporal_graph_queries": is_enterprise(),
        "graph_traversal_multihop": is_enterprise(),
        "advanced_synthesis_formats": is_enterprise(),
        "report_ingestion": is_enterprise(),
        "alias_resolution_typedb": is_enterprise(),
        "opencti_integration": is_enterprise(),
        "sigma_generation": is_enterprise(),
        "context_injection": is_enterprise(),
        "multi_tenant_auth": is_enterprise(),
    }
    return {
        "edition": "enterprise" if is_enterprise() else "community",
        "edition_name": edition_name(),
        "version": __version__,
        "features": features,
        "upgrade_url": "https://threatengram.com/enterprise" if not is_enterprise() else None,
    }


@app.post("/api/sync")
async def sync(request: Request, req: SyncRequest):
    if not is_enterprise():
        return JSONResponse(
            status_code=402,
            content={
                "error": "OpenCTI sync requires ThreatRecall Enterprise",
                "upgrade_url": "https://threatengram.com/enterprise",
            },
        )
    try:
        from zettelforge_enterprise.opencti_sync import sync_opencti
        tenant_mm = get_mm_for_request(request)
        result = sync_opencti(
            tenant_mm,
            limit=req.limit,
            entity_types=req.entity_types,
            use_extraction=False,
        )
        return result
    except Exception:
        logger.exception("OpenCTI sync failed")
        return JSONResponse(status_code=500, content={"error": "Internal server error"})


# ── HTML Frontend ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ThreatRecall</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0a0e17; color: #c9d1d9; min-height: 100vh; }
        .header { background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 24px; display: flex; align-items: center; gap: 16px; }
        .header h1 { font-size: 20px; color: #58a6ff; font-weight: 600; }
        .header .version { color: #8b949e; font-size: 13px; }
        .header .stats { margin-left: auto; color: #8b949e; font-size: 13px; }
        .container { max-width: 960px; margin: 0 auto; padding: 24px; }
        .search-box { display: flex; gap: 8px; margin-bottom: 24px; }
        .search-box input { flex: 1; padding: 12px 16px; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; font-size: 15px; outline: none; }
        .search-box input:focus { border-color: #58a6ff; box-shadow: 0 0 0 3px rgba(88,166,255,0.1); }
        .search-box button { padding: 12px 24px; background: #238636; border: none; border-radius: 6px; color: #fff; font-size: 15px; cursor: pointer; font-weight: 500; }
        .search-box button:hover { background: #2ea043; }
        .tabs { display: flex; gap: 4px; margin-bottom: 16px; }
        .tabs button { padding: 8px 16px; background: transparent; border: 1px solid #30363d; border-radius: 6px; color: #8b949e; cursor: pointer; font-size: 13px; }
        .tabs button.active { background: #21262d; color: #c9d1d9; border-color: #58a6ff; }
        .settings-group { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
        .settings-group h3 { color: #58a6ff; font-size: 14px; margin-bottom: 12px; font-weight: 600; }
        .settings-group h4 { color: #8b949e; font-size: 12px; margin-top: 12px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
        .settings-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
        .settings-row label { color: #c9d1d9; font-size: 13px; min-width: 180px; }
        .settings-row input[type="range"] { flex: 1; accent-color: #58a6ff; }
        .settings-row .val { color: #58a6ff; font-size: 12px; min-width: 40px; text-align: right; font-family: monospace; }
        .settings-row input[type="number"] { width: 80px; padding: 4px 8px; background: #0d1117; border: 1px solid #30363d; border-radius: 4px; color: #c9d1d9; font-size: 13px; }
        .settings-row input[type="checkbox"] { width: 16px; height: 16px; accent-color: #238636; }
        .settings-toggle { display: flex; align-items: center; gap: 8px; }
        .settings-toggle span { font-size: 13px; color: #8b949e; }
        .settings-divider { border: none; border-top: 1px solid #30363d; margin: 12px 0; }

        .meta { color: #8b949e; font-size: 13px; margin-bottom: 16px; }
        .results { display: flex; flex-direction: column; gap: 12px; }
        .result { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
        .result:hover { border-color: #58a6ff; }
        .result .title { color: #58a6ff; font-size: 13px; margin-bottom: 8px; font-family: monospace; }
        .result .content { color: #c9d1d9; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
        .result .footer { display: flex; gap: 12px; margin-top: 8px; color: #8b949e; font-size: 12px; }
        .result .tag { display: inline-block; padding: 2px 8px; background: #21262d; border-radius: 12px; font-size: 11px; color: #8b949e; }
        .result .tag.tier-a { background: #1a472a; color: #3fb950; }
        .result .tag.tier-b { background: #2a1a47; color: #a371f7; }
        .synthesis { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
        .synthesis h3 { color: #58a6ff; margin-bottom: 12px; }
        .synthesis .answer { font-size: 15px; line-height: 1.7; }
        .input-section { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 24px; }
        .input-section textarea { width: 100%; min-height: 100px; padding: 12px; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; font-size: 14px; resize: vertical; font-family: inherit; }
        .input-section .actions { display: flex; gap: 8px; margin-top: 8px; }
        .input-section button { padding: 8px 16px; background: #238636; border: none; border-radius: 6px; color: #fff; cursor: pointer; font-size: 13px; }
        .empty { text-align: center; padding: 48px; color: #484f58; }
        .empty h2 { font-size: 18px; margin-bottom: 8px; color: #8b949e; }
        .spinner { display: none; text-align: center; padding: 24px; color: #8b949e; }
    </style>
</head>
<body>
    <div class="header">
        <h1>ThreatRecall</h1>
        <span class="version" id="version"></span>
        <span class="stats" id="stats"></span>
        <span id="user-info" style="margin-left:auto;display:flex;align-items:center;gap:8px;"></span>
    </div>
    <div class="container">
        <div class="search-box">
            <input type="text" id="query" placeholder="Search threat intelligence... (e.g., What tools does APT28 use?)" autofocus>
            <button onclick="doSearch()">Search</button>
        </div>
        <div class="tabs">
            <button class="active" onclick="setMode('recall')">Recall</button>
            <button onclick="setMode('synthesize')">Synthesize</button>
            <button onclick="setMode('remember')">Remember</button>
            <button onclick="setMode('sync')">OpenCTI Sync</button>
            <button onclick="setMode('settings')">Settings</button>
        </div>
        <div id="remember-section" class="input-section" style="display:none;">
            <textarea id="remember-content" placeholder="Paste threat intelligence to store..."></textarea>
            <div class="actions">
                <button onclick="doRemember()">Store in Memory</button>
            </div>
        </div>
        <div id="sync-section" class="input-section" style="display:none;">
            <p style="color:#8b949e;margin-bottom:12px;">Pull latest from OpenCTI into ThreatRecall memory.</p>
            <div class="actions">
                <button onclick="doSync()">Sync Now (20 per type)</button>
            </div>
        </div>
        <div id="settings-section" style="display:none;">
            <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;">
                <button onclick="applyPreset('purist')" style="padding:6px 14px;background:#1a472a;border:1px solid #3fb950;border-radius:4px;color:#3fb950;font-size:12px;cursor:pointer;">Cognitive Purist</button>
                <button onclick="applyPreset('conservative')" style="padding:6px 14px;background:#2a1a47;border:1px solid #a371f7;border-radius:4px;color:#a371f7;font-size:12px;cursor:pointer;">Conservative</button>
                <button onclick="applyPreset('minimal')" style="padding:6px 14px;background:#21262d;border:1px solid #8b949e;border-radius:4px;color:#8b949e;font-size:12px;cursor:pointer;">Minimal</button>
                <button onclick="applyPreset('off')" style="padding:6px 14px;background:#2d1a1a;border:1px solid #f85149;border-radius:4px;color:#f85149;font-size:12px;cursor:pointer;">Off</button>
            </div>
            <div id="settings-form" style="display:flex;flex-direction:column;gap:20px;"></div>
            <div style="margin-top:16px;display:flex;gap:8px;align-items:center;">
                <button onclick="saveSettings()" style="padding:8px 20px;background:#238636;border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:14px;">Save Settings</button>
                <span id="settings-status" style="color:#8b949e;font-size:13px;"></span>
            </div>
        </div>
        <div class="meta" id="meta"></div>
        <div class="spinner" id="spinner">Searching...</div>
        <div id="synthesis"></div>
        <div class="results" id="results">
            <div class="empty">
                <h2>ThreatRecall CTI Memory</h2>
                <p>Search across threat actors, CVEs, tools, campaigns, and reports.</p>
            </div>
        </div>
    </div>
    <script>
        let mode = 'recall';
        function setMode(m) {
            mode = m;
            document.querySelectorAll('.tabs button').forEach((b,i) => b.classList.toggle('active', ['recall','synthesize','remember','sync','settings'][i] === m));
            document.getElementById('remember-section').style.display = m === 'remember' ? 'block' : 'none';
            document.getElementById('sync-section').style.display = m === 'sync' ? 'block' : 'none';
            document.getElementById('settings-section').style.display = m === 'settings' ? 'block' : 'none';
            if (m === 'settings') loadSettings();
        }
        async function doSearch() {
            const q = document.getElementById('query').value.trim();
            if (!q) return;
            document.getElementById('spinner').style.display = 'block';
            document.getElementById('results').innerHTML = '';
            document.getElementById('synthesis').innerHTML = '';
            document.getElementById('meta').textContent = '';
            try {
                if (mode === 'synthesize') {
                    const res = await fetch('/api/synthesize', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query:q, format:'synthesized_brief'})});
                    const data = await res.json();
                    const syn = data.synthesis || {};
                    document.getElementById('synthesis').innerHTML = `<div class="synthesis"><h3>Synthesis (${data.latency_ms}ms)</h3><div class="answer">${syn.summary || syn.answer || JSON.stringify(syn)}</div></div>`;
                } else {
                    const res = await fetch('/api/recall', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query:q, k:10})});
                    const data = await res.json();
                    document.getElementById('meta').textContent = `${data.count} results in ${data.latency_ms}ms`;
                    if (data.results.length === 0) {
                        document.getElementById('results').innerHTML = '<div class="empty"><h2>No results</h2></div>';
                    } else {
                        document.getElementById('results').innerHTML = data.results.map(r => `
                            <div class="result">
                                <div class="title">${r.id} <span class="tag tier-${r.tier.toLowerCase()}">${r.tier}</span> <span class="tag">${r.domain}</span></div>
                                <div class="content">${escHtml(r.content)}</div>
                                <div class="footer">
                                    <span>${r.created_at?.slice(0,10) || ''}</span>
                                    <span>confidence: ${r.confidence}</span>
                                    ${r.entities.map(e => `<span class="tag">${e}</span>`).join('')}
                                </div>
                            </div>`).join('');
                    }
                }
            } catch(e) { document.getElementById('results').innerHTML = `<div class="empty"><h2>Error: ${e.message}</h2></div>`; }
            document.getElementById('spinner').style.display = 'none';
        }
        async function doRemember() {
            const content = document.getElementById('remember-content').value.trim();
            if (!content) return;
            const res = await fetch('/api/remember', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({content, domain:'cti'})});
            const data = await res.json();
            document.getElementById('meta').textContent = `Stored: ${data.note_id} (${data.status}, ${data.latency_ms}ms, entities: ${data.entities.join(', ')})`;
            document.getElementById('remember-content').value = '';
        }
        async function doSync() {
            document.getElementById('meta').textContent = 'Syncing from OpenCTI...';
            try {
                const res = await fetch('/api/sync', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({limit:20})});
                const data = await res.json();
                document.getElementById('meta').textContent = `Synced ${data.synced || 0} objects, ${data.skipped || 0} skipped, ${data.errors || 0} errors (${data.duration_s || 0}s)`;
            } catch(e) { document.getElementById('meta').textContent = `Sync error: ${e.message}`; }
        }
        async function loadSettings() {
            try {
                const [cfgRes, metaRes] = await Promise.all([
                    fetch('/api/config'),
                    fetch('/api/config/meta'),
                ]);
                const cfg = await cfgRes.json();
                const meta = await metaRes.json();
                window._cfg = cfg;
                window._meta = meta;
                buildSettingsForm(cfg, meta);
            } catch(e) { console.error('Failed to load settings:', e); }
        }
        function buildSettingsForm(cfg, meta) {
            const el = document.getElementById('settings-form');
            const restartFields = new Set(meta.restart_required_fields);
            function section(title, rows) {
                const div = document.createElement('div');
                div.className = 'settings-group';
                const h = document.createElement('h3');
                h.textContent = title;
                div.appendChild(h);
                rows.forEach(row => div.appendChild(row));
                return div;
            }
            function row(label, field, control, restart) {
                const d = document.createElement('div');
                d.className = 'settings-row';
                const lbl = document.createElement('label');
                lbl.textContent = label;
                d.appendChild(lbl);
                d.appendChild(control);
                if (restart) {
                    const badge = document.createElement('span');
                    badge.textContent = '↺ restart required';
                    badge.style.cssText = 'color:#d29922;font-size:11px;margin-left:8px;';
                    d.appendChild(badge);
                }
                return d;
            }
            function slider(path, min, max, step, label) {
                const val = getVal(cfg, path);
                const wrapper = document.createElement('div');
                wrapper.style.cssText = 'display:flex;align-items:center;gap:8px;flex:1;';
                const input = document.createElement('input');
                input.type = 'range'; input.min = min; input.max = max; input.step = step;
                input.value = val;
                input.style.flex = '1';
                input.id = 'cfg_' + path.replace(/\./g, '__');
                input.onchange = () => document.getElementById('cfg_val_' + path.replace(/\./g, '__')).textContent = input.value;
                const displayVal = document.createElement('span');
                displayVal.id = 'cfg_val_' + path.replace(/\./g, '__');
                displayVal.className = 'val';
                displayVal.textContent = val;
                wrapper.appendChild(input);
                wrapper.appendChild(displayVal);
                return row(label, path, wrapper, restartFields.has(path));
            }
            function toggle(path, label) {
                const val = getVal(cfg, path);
                const wrapper = document.createElement('div');
                wrapper.className = 'settings-toggle';
                const cb = document.createElement('input');
                cb.type = 'checkbox'; cb.checked = val;
                cb.id = 'cfg_' + path.replace(/\./g, '__');
                const sp = document.createElement('span');
                sp.textContent = val ? 'ON' : 'OFF';
                cb.onchange = () => { sp.textContent = cb.checked ? 'ON' : 'OFF'; };
                wrapper.appendChild(cb);
                wrapper.appendChild(sp);
                return row(label, path, wrapper, restartFields.has(path));
            }
            function number(path, label) {
                const val = getVal(cfg, path);
                const input = document.createElement('input');
                input.type = 'number'; input.value = val;
                input.id = 'cfg_' + path.replace(/\./g, '__');
                input.min = 0; input.style.width = '70px';
                return row(label, path, input, restartFields.has(path));
            }
            function hr() {
                const r = document.createElement('hr');
                r.className = 'settings-divider';
                return r;
            }
            el.innerHTML = '';
            // Salience
            el.appendChild(section('Salience Scoring (Von Restorff)', [
                toggle('salience.enabled', 'Enable salience scoring'),
                hr(),
                slider('salience.distinctiveness_weight', 0, 1, 0.05, 'Distinctiveness weight'),
                slider('salience.signal_weight', 0, 1, 0.05, 'Signal weight'),
                slider('salience.isolation_weight', 0, 1, 0.05, 'Isolation weight'),
            ]));
            // Spacing
            el.appendChild(section('Spacing Effect', [
                toggle('spacing.enabled', 'Enable spacing effect'),
                hr(),
                number('spacing.half_life_days', 'Half-life (days)'),
                number('spacing.reinforcement_threshold', 'Reinforcement threshold'),
                slider('spacing.reinforcement_factor', 0, 0.5, 0.05, 'Reinforcement factor'),
                slider('spacing.decay_rate', 0, 0.1, 0.01, 'Decay rate'),
            ]));
            // Decay
            el.appendChild(section('Tiered Decay', [
                toggle('decay.enabled', 'Enable tiered decay'),
                hr(),
                number('decay.hot_threshold', 'HOT threshold (min confirmations)'),
                number('decay.hot_max_age_days', 'HOT max age (days)'),
                number('decay.warm_threshold_days', 'WARM→COLD after (days)'),
                number('decay.frozen_threshold_days', 'COLD→FROZEN after (days)'),
                number('decay.relevance_freeze_threshold', 'Freeze if relevance below'),
            ]));
            // Retrieval weights
            el.appendChild(section('Retrieval Weights', [
                slider('retrieval_weights.salience_weight', 0, 2, 0.1, 'Salience weight'),
                slider('retrieval_weights.tier_hot_multiplier', 0, 2, 0.1, 'HOT tier multiplier'),
                slider('retrieval_weights.tier_warm_multiplier', 0, 1, 0.1, 'WARM tier multiplier'),
                slider('retrieval_weights.tier_cold_multiplier', 0, 1, 0.1, 'COLD tier multiplier'),
                slider('retrieval_weights.tier_frozen_multiplier', 0, 1, 0.1, 'FROZEN tier multiplier'),
            ]));
            // General config
            el.appendChild(section('General', [
                toggle('governance.enabled', 'Governance checks'),
                toggle('extraction.intent_adaptive_routing', 'Intent-adaptive routing'),
                number('retrieval.default_k', 'Default recall k'),
                number('extraction.max_facts', 'Max facts per note'),
                number('synthesis.max_context_tokens', 'Max context tokens'),
            ]));
        }
        function getVal(obj, path) {
            return path.split('.').reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), obj);
        }
        function applyPreset(name) {
            const presets = {
                purist: {
                    salience: { enabled: true, distinctiveness_weight: 0.4, signal_weight: 0.4, isolation_weight: 0.2 },
                    spacing: { enabled: true, half_life_days: 30, reinforcement_threshold: 3, reinforcement_factor: 0.1, decay_rate: 0.02 },
                    decay: { enabled: true, hot_threshold: 3, hot_max_age_days: 7, warm_threshold_days: 30, frozen_threshold_days: 90, relevance_freeze_threshold: 0.1 },
                    retrieval_weights: { salience_weight: 0.5, tier_hot_multiplier: 1.0, tier_warm_multiplier: 0.5, tier_cold_multiplier: 0.1, tier_frozen_multiplier: 0.0 },
                },
                conservative: {
                    salience: { enabled: true, distinctiveness_weight: 0.2, signal_weight: 0.6, isolation_weight: 0.2 },
                    spacing: { enabled: true, half_life_days: 60, reinforcement_threshold: 5, reinforcement_factor: 0.08, decay_rate: 0.015 },
                    decay: { enabled: true, hot_threshold: 5, hot_max_age_days: 14, warm_threshold_days: 60, frozen_threshold_days: 180, relevance_freeze_threshold: 0.15 },
                    retrieval_weights: { salience_weight: 0.3, tier_hot_multiplier: 1.0, tier_warm_multiplier: 0.6, tier_cold_multiplier: 0.15, tier_frozen_multiplier: 0.0 },
                },
                minimal: {
                    salience: { enabled: false, distinctiveness_weight: 0.4, signal_weight: 0.4, isolation_weight: 0.2 },
                    spacing: { enabled: true, half_life_days: 30, reinforcement_threshold: 3, reinforcement_factor: 0.1, decay_rate: 0.02 },
                    decay: { enabled: false, hot_threshold: 3, hot_max_age_days: 7, warm_threshold_days: 30, frozen_threshold_days: 90, relevance_freeze_threshold: 0.1 },
                    retrieval_weights: { salience_weight: 0.5, tier_hot_multiplier: 1.0, tier_warm_multiplier: 0.5, tier_cold_multiplier: 0.1, tier_frozen_multiplier: 0.0 },
                },
                off: {
                    salience: { enabled: false, distinctiveness_weight: 0.4, signal_weight: 0.4, isolation_weight: 0.2 },
                    spacing: { enabled: false, half_life_days: 30, reinforcement_threshold: 3, reinforcement_factor: 0.1, decay_rate: 0.02 },
                    decay: { enabled: false, hot_threshold: 3, hot_max_age_days: 7, warm_threshold_days: 30, frozen_threshold_days: 90, relevance_freeze_threshold: 0.1 },
                    retrieval_weights: { salience_weight: 0.0, tier_hot_multiplier: 1.0, tier_warm_multiplier: 0.5, tier_cold_multiplier: 0.1, tier_frozen_multiplier: 0.0 },
                },
            };
            if (presets[name]) {
                window._cfg = { ...window._cfg, ...presets[name] };
                buildSettingsForm(window._cfg, window._meta || {});
            }
        }
        async function saveSettings() {
            const status = document.getElementById('settings-status');
            status.textContent = 'Saving...';
            status.style.color = '#8b949e';
            try {
                // Collect all input values from the form
                const data = {};
                document.querySelectorAll('#settings-form input').forEach(input => {
                    const path = input.id.replace(/^cfg_/, '').replace(/__/g, '.');
                    const parts = path.split('.');
                    let obj = data;
                    for (let i = 0; i < parts.length - 1; i++) {
                        if (!obj[parts[i]]) obj[parts[i]] = {};
                        obj = obj[parts[i]];
                    }
                    if (input.type === 'checkbox') {
                        obj[parts[parts.length - 1]] = input.checked;
                    } else if (input.type === 'range' || input.type === 'number') {
                        obj[parts[parts.length - 1]] = parseFloat(input.value);
                    }
                });
                const res = await fetch('/api/config', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
                const result = await res.json();
                if (result.pending_restart && result.pending_restart.length > 0) {
                    status.textContent = `Saved ✓  ↺ restart required: ${result.pending_restart.join(', ')}`;
                    status.style.color = '#d29922';
                } else {
                    status.textContent = 'Saved ✓';
                    status.style.color = '#3fb950';
                }
                setTimeout(() => { status.textContent = ''; }, 4000);
            } catch(e) {
                status.textContent = 'Error: ' + e.message;
                status.style.color = '#f85149';
            }
        }
        function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
        document.getElementById('query').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
        // Load stats + edition
        fetch('/api/stats').then(r=>r.json()).then(d => {
            const edBadge = d.edition === 'enterprise' ? 'Enterprise' : 'Community';
            document.getElementById('version').textContent = `v${d.version} (${edBadge})`;
            document.getElementById('stats').textContent = `${d.total_notes} notes | ${d.retrievals} recalls`;
            // Hide enterprise-only tabs in Community
            if (d.edition !== 'enterprise') {
                document.querySelectorAll('.tabs button').forEach(b => {
                    if (b.textContent === 'OpenCTI Sync') b.style.display = 'none';
                });
            }
        });
        // Load auth state
        fetch('/auth/me').then(r=>r.json()).then(d => {
            const el = document.getElementById('user-info');
            if (d.authenticated) {
                el.innerHTML = `<img src="${d.picture||''}" style="width:24px;height:24px;border-radius:50%;" onerror="this.style.display='none'"> <span style="color:#c9d1d9;font-size:13px;">${d.name}</span> <a href="/auth/logout" style="color:#8b949e;font-size:12px;text-decoration:none;">logout</a>`;
            } else {
                fetch('/auth/providers').then(r=>r.json()).then(p => {
                    if (p.providers.length > 0) {
                        el.innerHTML = p.providers.map(pr => `<a href="/auth/login/${pr}" style="padding:4px 12px;background:#21262d;border-radius:4px;color:#58a6ff;font-size:12px;text-decoration:none;">Login with ${pr}</a>`).join(' ');
                    }
                });
            }
        });
    </script>
</body>
</html>"""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ThreatRecall Web UI")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    import uvicorn
    print(f"ThreatRecall v{__version__} — http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
