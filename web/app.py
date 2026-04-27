"""
ZettelForge Web UI — FastAPI backend + RFC-015 management SPA.

A management interface for ZettelForge's CTI memory system.

Usage:
    python web/app.py                    # Start on port 8088
    python web/app.py --port 9000        # Custom port
    uvicorn web.app:app --reload         # Dev mode

Endpoints:
    GET  /                    → Management SPA (HTML)
    POST /api/recall          → Blended recall (vector + graph)
    POST /api/remember        → Store a note
    POST /api/synthesize      → RAG synthesis
    GET  /api/stats           → Memory system stats
    POST /api/sync            → Trigger OpenCTI sync
"""

# isort: skip_file

import asyncio
import json
import logging
import os
import secrets
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# Ensure both the package and the web namespace are importable when this file is
# launched directly as `python web/app.py`.
_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(_repo_root / "src"))

os.environ.setdefault("ZETTELFORGE_BACKEND", "sqlite")

from zettelforge import MemoryManager, __version__  # noqa: E402
from zettelforge.config import get_config, reload_config, _apply_yaml  # noqa: E402
from zettelforge.edition import edition_name, is_enterprise  # noqa: E402
from zettelforge.knowledge_graph import get_knowledge_graph  # noqa: E402
from web.auth import get_mm_for_request, register_auth_routes  # noqa: E402

# ── Jinja2 + static files ──────────────────────────────────────────────────
_web_dir = Path(__file__).parent
templates = Jinja2Templates(directory=str(_web_dir / "templates"))
templates.env.globals["version"] = __version__

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ZettelForge",
    description=edition_name(),
    version=__version__,
)

# Mount static files after app is created
app.mount("/static", StaticFiles(directory=str(_web_dir / "static")), name="static")
app.mount("/ui", StaticFiles(directory=str(_web_dir / "ui")), name="ui")

# Uptime tracking (monotonic clock, reset on process restart)
_start_time = time.monotonic()

# Register OAuth/JWT auth routes (Enterprise: full OAuth, Community: pass-through)
register_auth_routes(app)

# Default memory manager (for unauthenticated/single-tenant mode)
mm = MemoryManager()

MAX_QUERY_CHARS = int(os.environ.get("ZETTELFORGE_WEB_MAX_QUERY_CHARS", "1000"))
MAX_CONTENT_CHARS = int(os.environ.get("ZETTELFORGE_WEB_MAX_CONTENT_CHARS", "50000"))
MAX_K = int(os.environ.get("ZETTELFORGE_WEB_MAX_K", "50"))
MAX_SYNC_LIMIT = int(os.environ.get("ZETTELFORGE_WEB_MAX_SYNC_LIMIT", "200"))
API_KEY = os.environ.get("ZETTELFORGE_WEB_API_KEY", "")
RATE_LIMIT_PER_MINUTE = int(os.environ.get("ZETTELFORGE_WEB_RATE_LIMIT_PER_MINUTE", "60"))
WRITE_CONCURRENCY = int(os.environ.get("ZETTELFORGE_WEB_WRITE_CONCURRENCY", "2"))
SYNTHESIS_FORMATS = {
    "direct_answer",
    "synthesized_brief",
    "timeline_analysis",
    "relationship_map",
}

_rate_lock = threading.Lock()
_rate_windows = defaultdict(deque)
_write_slots = threading.BoundedSemaphore(max(1, WRITE_CONCURRENCY))


# ── Pydantic models ──────────────────────────────────────────────────────────


class RecallRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    k: int = Field(default=10, ge=1, le=MAX_K)
    domain: Optional[str] = Field(default=None, max_length=100)


class RememberRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    domain: str = Field(default="cti", min_length=1, max_length=100)
    source_type: str = Field(default="manual", min_length=1, max_length=100)
    source_ref: str = Field(default="", max_length=500)
    evolve: bool = True


class SynthesizeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    format: str = Field(default="direct_answer", max_length=50)
    k: int = Field(default=10, ge=1, le=MAX_K)


class SyncRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=MAX_SYNC_LIMIT)
    entity_types: Optional[List[str]] = None


# ── API endpoints ────────────────────────────────────────────────────────────


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    window_start = now - 60
    with _rate_lock:
        hits = _rate_windows[key]
        while hits and hits[0] < window_start:
            hits.popleft()
        if len(hits) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
            )
        hits.append(now)


async def require_api_guard(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None),
) -> None:
    client_ip = _client_ip(request)
    supplied_key = x_api_key
    if not supplied_key and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            supplied_key = value

    if API_KEY:
        if not supplied_key or not secrets.compare_digest(supplied_key, API_KEY):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid API key required",
            )
    elif not _is_loopback(client_ip):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Set ZETTELFORGE_WEB_API_KEY before exposing the web API",
        )

    _check_rate_limit(supplied_key or client_ip)


@app.post("/api/recall", dependencies=[Depends(require_api_guard)])
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


@app.post("/api/remember", dependencies=[Depends(require_api_guard)])
async def remember(request: Request, req: RememberRequest):
    tenant_mm = get_mm_for_request(request)
    start = time.perf_counter()
    if not _write_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Write capacity exhausted; retry shortly",
        )
    try:
        note, status_text = tenant_mm.remember(
            content=req.content,
            source_type=req.source_type,
            source_ref=req.source_ref,
            domain=req.domain,
            evolve=req.evolve,
        )
    finally:
        _write_slots.release()
    latency = time.perf_counter() - start

    return {
        "note_id": note.id,
        "status": status_text,
        "entities": note.semantic.entities[:10],
        "latency_ms": round(latency * 1000),
    }


@app.post("/api/synthesize", dependencies=[Depends(require_api_guard)])
async def synthesize(request: Request, req: SynthesizeRequest):
    if req.format not in SYNTHESIS_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported synthesis format")
    tenant_mm = get_mm_for_request(request)
    start = time.perf_counter()
    if not _write_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Synthesis capacity exhausted; retry shortly",
        )
    try:
        result = tenant_mm.synthesize(req.query, format=req.format, k=req.k)
    finally:
        _write_slots.release()
    latency = time.perf_counter() - start

    return {
        "query": req.query,
        "format": req.format,
        "synthesis": result.get("synthesis", {}),
        "sources_count": result.get("metadata", {}).get("sources_count", 0),
        "latency_ms": round(latency * 1000),
    }


@app.get("/api/stats", dependencies=[Depends(require_api_guard)])
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


@app.get("/api/edition", dependencies=[Depends(require_api_guard)])
async def edition_info():
    """Return current edition and available features."""
    features = {
        # Core — full-featured agentic memory system
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
        # Ungated features
        "typedb_stix_ontology": is_enterprise(),
        "temporal_graph_queries": True,
        "graph_traversal_multihop": True,
        "advanced_synthesis_formats": True,
        "report_ingestion": True,
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
    }


@app.post("/api/sync", dependencies=[Depends(require_api_guard)])
async def sync(request: Request, req: SyncRequest):
    if not is_enterprise():
        return JSONResponse(
            status_code=501,
            content={
                "error": "OpenCTI sync requires the zettelforge-enterprise package.",
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


# ── System Endpoints ────────────────────────────────────────────────────────────


def _redact_secrets(data: Any, depth: int = 0) -> Any:
    """Recursively redact sensitive values (api_key, password, token, license_key)."""
    SENSITIVE_KEYS = {"api_key", "password", "token", "license_key"}
    if depth > 10:
        return data
    if isinstance(data, dict):
        return {
            k: ("***" if k.lower() in SENSITIVE_KEYS else _redact_secrets(v, depth + 1))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact_secrets(item, depth + 1) for item in data]
    return data


def _config_to_dict(obj: Any) -> Any:
    """Convert nested dataclass config to plain dict for JSON/YAML serialization."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _config_to_dict(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, dict):
        return {k: _config_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_config_to_dict(item) for item in obj]
    if isinstance(obj, (int, float, bool, str, type(None))):
        return obj
    return str(obj)


def _flatten_keys(data: dict, prefix: str = "") -> list[str]:
    """Flatten a nested dict to dotted paths (leaves only)."""
    out: list[str] = []
    for k, v in data.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.extend(_flatten_keys(v, path))
        else:
            out.append(path)
    return out


def _expand_dotted_keys(data: dict) -> dict:
    """Convert {"retrieval.default_k": 5} to {"retrieval": {"default_k": 5}}."""
    expanded: dict[str, Any] = {}
    for key, value in data.items():
        if "." not in key:
            if isinstance(value, dict):
                expanded[key] = _expand_dotted_keys(value)
            else:
                expanded[key] = value
            continue

        cursor = expanded
        parts = [part for part in key.split(".") if part]
        if not parts:
            continue
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return expanded


_RESTART_REQUIRED_FIELDS = {
    "backend",
    "embedding.provider",
    "embedding.url",
    "llm.provider",
    "llm.model",
    "llm.url",
    "storage.data_dir",
    "logging.log_file",
    "logging.level",
}


@app.get("/api/health", dependencies=[Depends(require_api_guard)])
async def health():
    """System health endpoint — version, config, queue depths, uptime."""
    try:
        cfg = get_config()
        kg = get_knowledge_graph()
        uptime = time.monotonic() - _start_time
        enrichment_depth = 0
        try:
            enrichment_depth = mm._enrichment_queue.qsize()
        except Exception:
            pass
        return {
            "status": "ok",
            "version": __version__,
            "edition": "enterprise" if is_enterprise() else "community",
            "edition_name": edition_name(),
            "storage_backend": cfg.backend,
            "embedding_provider": cfg.embedding.provider,
            "embedding_model": cfg.embedding.model,
            "llm_provider": cfg.llm.provider,
            "llm_model": cfg.llm.model,
            "llm_local_backend": cfg.llm.local_backend,
            "enrichment_queue_depth": enrichment_depth,
            "queue_status": "idle" if enrichment_depth == 0 else "active",
            "governance_enabled": cfg.governance.enabled,
            "pii_enabled": cfg.governance.pii.enabled,
            "uptime_seconds": round(uptime, 1),
            "data_dir": cfg.storage.data_dir,
            "graph_node_count": len(kg._nodes),
            "graph_edge_count": len(kg._edges),
        }
    except Exception as e:
        logger.exception("health_check_failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/config", dependencies=[Depends(require_api_guard)])
async def get_config_endpoint():
    """Return current config as JSON with secrets redacted."""
    try:
        cfg = get_config()
        return _redact_secrets(_config_to_dict(cfg))
    except Exception as e:
        logger.exception("get_config_failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/config/meta", dependencies=[Depends(require_api_guard)])
async def get_config_meta():
    """Return UI-side config metadata so the editor stays in sync with server.

    Currently exposes the dotted-leaf paths that require a process restart.
    This is the canonical source for the UI's "restart required" badge —
    hardcoded fallbacks in the editor exist only for offline-server safety.
    """
    return {
        "restart_required_fields": sorted(_RESTART_REQUIRED_FIELDS),
    }


class ConfigUpdateRequest(BaseModel):
    """Accepted fields: any config section key, value pairs."""
    pass


@app.put("/api/config", dependencies=[Depends(require_api_guard)])
async def update_config(req: dict):
    """Apply config changes in-memory. Returns applied + pending-restart fields."""
    try:
        cfg = get_config()
        req = _expand_dotted_keys(req)

        _apply_yaml(cfg, req)

        # Flatten the nested payload to dotted leaf paths so we can compare
        # against _RESTART_REQUIRED_FIELDS (also dotted). A top-level key like
        # "embedding" must not match a restart-required leaf like
        # "embedding.provider".
        leaves = _flatten_keys(req)
        applied = [k for k in leaves if k not in _RESTART_REQUIRED_FIELDS]
        pending_restart = [k for k in leaves if k in _RESTART_REQUIRED_FIELDS]

        if pending_restart:
            message = "Config updated in-memory. Some changes require a restart."
        else:
            message = "Config updated in-memory."

        return {
            "applied": applied,
            "pending_restart": pending_restart,
            "message": message,
        }
    except Exception as e:
        logger.exception("update_config_failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/graph/nodes", dependencies=[Depends(require_api_guard)])
async def graph_nodes():
    """Return all knowledge graph nodes."""
    try:
        kg = get_knowledge_graph()
        nodes = []
        for node_id, node in kg._nodes.items():
            nodes.append({
                "id": node.get("node_id", node_id),
                "label": node.get("entity_value", ""),
                "type": node.get("entity_type", ""),
                "tier": node.get("properties", {}).get("tier", ""),
                "aliases": node.get("properties", {}).get("aliases", []),
                "confidence": node.get("properties", {}).get("confidence", 0.0),
                "created_at": node.get("created_at", ""),
            })
        return {"nodes": nodes, "count": len(nodes)}
    except Exception as e:
        logger.exception("graph_nodes_failed")
        return JSONResponse(status_code=500, content={"error": str(e), "nodes": []})


@app.get("/api/graph/edges", dependencies=[Depends(require_api_guard)])
async def graph_edges():
    """Return all knowledge graph edges."""
    try:
        kg = get_knowledge_graph()
        edges = []
        for edge_id, edge in kg._edges.items():
            edges.append({
                "id": edge.get("edge_id", edge_id),
                "source": edge.get("from_node_id", ""),
                "target": edge.get("to_node_id", ""),
                "relationship": edge.get("relationship", ""),
                "created_at": edge.get("created_at", ""),
            })
        return {"edges": edges, "count": len(edges)}
    except Exception as e:
        logger.exception("graph_edges_failed")
        return JSONResponse(status_code=500, content={"error": str(e), "edges": []})


@app.get("/api/entities", dependencies=[Depends(require_api_guard)])
async def entities(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    type: Optional[str] = Query(default=None),
    tier: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
):
    """Paginated entity index query."""
    try:
        # Use entity indexer from memory manager if available
        idx = getattr(mm, "indexer", None)
        if idx is None:
            return {"entities": [], "total": 0, "offset": offset, "limit": limit}

        all_entities = []
        for etype, entities in idx.index.items():
            if type and etype != type:
                continue
            for evalue, note_ids in entities.items():
                if q and q.lower() not in evalue.lower():
                    continue
                # Look up tier from earliest note if possible
                ent_tier = tier if tier else ""
                all_entities.append({
                    "id": f"{etype}:{evalue}",
                    "name": evalue,
                    "type": etype,
                    "aliases": [],
                    "confidence": None,
                    "connected_count": len(note_ids),
                    "entity_type": etype,
                    "entity_value": evalue,
                    "note_count": len(note_ids),
                    "tier": ent_tier or "b",
                })

        total = len(all_entities)
        page = all_entities[offset:offset + limit]
        return {"entities": page, "total": total, "offset": offset, "limit": limit}
    except Exception as e:
        logger.exception("entities_failed")
        return JSONResponse(status_code=500, content={"error": str(e), "entities": [], "total": 0, "offset": offset, "limit": limit})


@app.get("/api/history", dependencies=[Depends(require_api_guard)])
async def history(
    limit: int = Query(default=100, ge=1, le=500),
    days: int = Query(default=5, ge=1, le=30),
):
    """Recent activity from telemetry JSONL files."""
    try:
        cfg = get_config()
        data_dir = Path(os.path.expanduser(cfg.storage.data_dir))
        telemetry_dir = data_dir / "telemetry"
        if not telemetry_dir.exists():
            return []

        entries = []
        cutoff = datetime.now() - timedelta(days=days)

        for telemetry_file in sorted(telemetry_dir.glob("telemetry_*.jsonl"), reverse=True):
            if len(entries) >= limit:
                break
            try:
                file_date_str = telemetry_file.stem.split("_")[1]
                file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
                if file_date < cutoff:
                    continue
            except (IndexError, ValueError):
                continue

            with open(telemetry_file) as f:
                for line in f:
                    if len(entries) >= limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue

        return entries
    except Exception as e:
        logger.exception("History endpoint failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


class BulkIngestItem(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    source_type: str = "manual"
    domain: str = "cti"
    evolve: bool = True


class BulkIngestRequest(BaseModel):
    items: list[BulkIngestItem] = Field(min_length=1, max_length=100)


@app.post("/api/ingest", dependencies=[Depends(require_api_guard)])
async def ingest(request: Request, req: BulkIngestRequest):
    """Bulk ingestion — remember multiple items."""
    tenant_mm = get_mm_for_request(request)
    total = len(req.items)
    succeeded = 0
    failed = 0
    results = []

    for item in req.items:
        if not _write_slots.acquire(blocking=False):
            results.append({
                "note_id": None,
                "status": "skipped",
                "entities": [],
                "success": False,
                "error": "Write capacity exhausted",
            })
            failed += 1
            continue
        try:
            note, status_text = tenant_mm.remember(
                content=item.content,
                source_type=item.source_type,
                domain=item.domain,
                evolve=item.evolve,
            )
            succeeded += 1
            results.append({
                "note_id": note.id,
                "status": status_text,
                "entities": note.semantic.entities[:10],
                "success": True,
                "error": None,
            })
        except Exception as e:
            failed += 1
            results.append({
                "note_id": None,
                "status": "error",
                "entities": [],
                "success": False,
                "error": str(e),
            })
        finally:
            _write_slots.release()

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


@app.get("/api/telemetry", dependencies=[Depends(require_api_guard)])
async def telemetry_summary():
    """Aggregated telemetry summary from today's telemetry JSONL."""
    try:
        cfg = get_config()
        data_dir = Path(os.path.expanduser(cfg.storage.data_dir))
        telemetry_dir = data_dir / "telemetry"
        today = datetime.now().strftime("%Y-%m-%d")
        fpath = telemetry_dir / f"telemetry_{today}.jsonl"

        if not fpath.exists():
            return {
                "total_queries": 0,
                "queries_today": 0,
                "recall_count": 0,
                "synthesis_count": 0,
                "syntheses_today": 0,
                "avg_latency_ms": 0,
                "p50_ms": 0,
                "p95_ms": 0,
                "top_intents": {},
            }

        latencies = []
        recall_count = 0
        synthesis_count = 0
        top_intents = {}

        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ev_type = ev.get("event_type", "")
                if ev_type == "recall":
                    recall_count += 1
                elif ev_type == "synthesis":
                    synthesis_count += 1

                dms = ev.get("duration_ms", 0)
                if isinstance(dms, (int, float)) and dms > 0:
                    latencies.append(dms)

                intent = ev.get("intent", "")
                if intent:
                    top_intents[intent] = top_intents.get(intent, 0) + 1

        total_queries = recall_count + synthesis_count
        avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0

        # Percentiles
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0

        return {
            "total_queries": total_queries,
            "queries_today": total_queries,
            "recall_count": recall_count,
            "synthesis_count": synthesis_count,
            "syntheses_today": synthesis_count,
            "avg_latency_ms": avg_latency,
            "p50_ms": p50,
            "p95_ms": p95,
            "top_intents": top_intents,
        }
    except Exception as e:
        logger.exception("telemetry_summary_failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/storage", dependencies=[Depends(require_api_guard)])
async def storage_stats():
    """Storage statistics — notes, entities, graph counts."""
    try:
        s = mm.get_stats()
        kg = get_knowledge_graph()
        return {
            "total_notes": s.get("total_notes", 0),
            "entity_count": sum(
                stats.get("unique_entities", 0)
                for stats in s.get("entity_index", {}).values()
            ),
            "graph_node_count": len(kg._nodes),
            "graph_edge_count": len(kg._edges),
        }
    except Exception as e:
        logger.exception("storage_stats_failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/logs", dependencies=[Depends(require_api_guard)])
async def logs(
    lines: int = Query(default=100, ge=1, le=10000),
    level: Optional[str] = Query(default=None),
):
    """Read last N lines from the structlog file. Optionally filter by level."""
    try:
        cfg = get_config()
        log_path = cfg.logging.log_file
        if not log_path:
            return {"logs": [], "truncated": False, "error": "No log file configured"}

        log_path = os.path.expanduser(log_path) if log_path.startswith("~") else log_path
        log_file = Path(log_path)
        if not log_file.exists():
            return {"logs": [], "truncated": False, "error": f"Log file not found: {log_path}"}

        # Read last N lines
        with open(log_file) as f:
            all_lines = f.readlines()

        truncated = len(all_lines) > lines
        tail = all_lines[-lines:]

        parsed_logs = []
        for line in tail:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                entry = {"message": line}

            log_level = entry.get("level", entry.get("event", "")).upper()
            if level and level.upper() != log_level:
                continue

            parsed_logs.append(entry)

        return {"logs": parsed_logs, "truncated": truncated}
    except Exception as e:
        logger.exception("logs_failed")
        return JSONResponse(status_code=500, content={"error": str(e), "logs": [], "truncated": False})


@app.get("/api/logs/stream", dependencies=[Depends(require_api_guard)])
async def log_stream():
    """SSE endpoint that tails the structlog file."""
    cfg = get_config()
    log_path = cfg.logging.log_file
    if not log_path:
        return JSONResponse(status_code=400, content={"error": "No log file configured"})

    log_path = os.path.expanduser(log_path) if log_path.startswith("~") else log_path
    log_file = Path(log_path)

    async def event_generator():
        seen_inodes = 0
        last_size = 0
        try:
            if log_file.exists():
                stat = log_file.stat()
                seen_inodes = stat.st_ino
                last_size = stat.st_size
                # Seek to end
        except Exception:
            pass

        while True:
            try:
                if not log_file.exists():
                    await asyncio.sleep(0.1)
                    continue

                stat = log_file.stat()
                current_inode = stat.st_ino

                # Handle log rotation (new inode)
                if current_inode != seen_inodes:
                    seen_inodes = current_inode
                    last_size = 0

                current_size = stat.st_size
                if current_size > last_size:
                    with open(log_file) as f:
                        f.seek(last_size)
                        new_data = f.read()
                        last_size = f.tell()
                        if new_data:
                            for line in new_data.splitlines():
                                if line.strip():
                                    yield f"data: {line}\n\n"

                await asyncio.sleep(0.1)
            except Exception:
                await asyncio.sleep(0.1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/telemetry/stream", dependencies=[Depends(require_api_guard)])
async def telemetry_stream():
    """SSE endpoint for live telemetry. Watches today's telemetry JSONL file."""
    cfg = get_config()
    data_dir = Path(os.path.expanduser(cfg.storage.data_dir))
    telemetry_dir = data_dir / "telemetry"
    today = datetime.now().strftime("%Y-%m-%d")
    fpath = telemetry_dir / f"telemetry_{today}.jsonl"

    async def event_generator():
        last_size = 0
        while True:
            try:
                telemetry_dir.mkdir(parents=True, exist_ok=True)
                if fpath.exists():
                    current_size = fpath.stat().st_size
                    if current_size > last_size:
                        with open(fpath) as f:
                            f.seek(last_size)
                            new_data = f.read()
                            last_size = f.tell()
                            if new_data:
                                for line in new_data.splitlines():
                                    if line.strip():
                                        yield f"data: {line}\n\n"
                await asyncio.sleep(0.1)
            except Exception:
                await asyncio.sleep(0.1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── HTML Frontend ────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the SPA."""
    return FileResponse(_web_dir / "ui" / "index.html", media_type="text/html")


@app.get(
    "/config",
    response_class=HTMLResponse,
    dependencies=[Depends(require_api_guard)],
)
async def config_page(request: Request):
    """Serve the config editor (auth-gated; SPA also fetches /api/config)."""
    try:
        import yaml
        cfg = get_config()
        config_yaml = yaml.dump(
            _redact_secrets(_config_to_dict(cfg)),
            default_flow_style=False,
            sort_keys=False,
        )
    except Exception:
        logger.exception("config_page_render_failed")
        config_yaml = ""
    return templates.TemplateResponse(
        request, "config_editor.html",
        {"config_yaml": config_yaml, "config_path": "config.yaml"}
    )


@app.get("/api/version", dependencies=[Depends(require_api_guard)])
async def version_info():
    """Return version and basic stats for the SPA header."""
    try:
        s = mm.get_stats()
        return {
            "version": __version__,
            "notes": s.get("total_notes", 0),
            "edition": "enterprise" if is_enterprise() else "community",
        }
    except Exception as e:
        logger.exception("version_info_failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ZettelForge Web UI")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if args.host in {"0.0.0.0", "::"} and not API_KEY:
        parser.error("Set ZETTELFORGE_WEB_API_KEY before binding the web app to all interfaces")

    import uvicorn

    print(f"ZettelForge v{__version__} — http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
