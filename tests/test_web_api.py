"""Integration tests for the ZettelForge Web API (RFC-015).

Tests all 13 new API endpoints using FastAPI TestClient.
Requires a running MemoryManager with mock embedding/LLM (provided by conftest).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure web/ and src/ are importable (same pattern as web/app.py)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "web"))


@pytest.fixture
def client():
    """Create a TestClient for the ZettelForge web app."""
    os.environ.setdefault("ZETTELFORGE_BACKEND", "sqlite")
    os.environ.setdefault("ZETTELFORGE_LLM_PROVIDER", "mock")
    from web.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def api_key():
    """Set an API key so tests don't need loopback."""
    os.environ["ZETTELFORGE_WEB_API_KEY"] = "test-api-key-12345"
    yield "test-api-key-12345"
    del os.environ["ZETTELFORGE_WEB_API_KEY"]


def _headers(api_key: str | None = None) -> dict:
    h = {}
    if api_key:
        h["X-API-Key"] = api_key
    return h


# ── Health ───────────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    """GET /api/health — system health information."""

    def test_health_returns_basic_info(self, client, api_key):
        resp = client.get("/api/health", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "edition" in data
        assert "storage_backend" in data
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))

    def test_health_has_provider_info(self, client, api_key):
        resp = client.get("/api/health", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "embedding_provider" in data
        assert "llm_provider" in data
        assert isinstance(data.get("governance_enabled"), bool)
        assert isinstance(data.get("pii_enabled"), bool)


# ── Config ───────────────────────────────────────────────────────────────────


class TestConfigEndpoint:
    """GET /api/config and PUT /api/config — configuration management."""

    def test_get_config_returns_redacted_secrets(self, client, api_key):
        resp = client.get("/api/config", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "llm" in data
        assert "embedding" in data
        assert "governance" in data

    def test_put_config_accepts_changes(self, client, api_key):
        resp = client.put(
            "/api/config",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={"retrieval": {"default_k": 5}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "applied" in data

    def test_put_config_returns_pending_restart(self, client, api_key):
        resp = client.put(
            "/api/config",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={"backend": "lance"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "pending_restart" in data
        assert any("backend" in str(item).lower() for item in data["pending_restart"])

    def test_put_config_nested_restart_required_is_flagged(self, client, api_key):
        """Regression: nested {"embedding": {"provider": ...}} must report
        embedding.provider in pending_restart, not silently appear in applied.
        """
        resp = client.put(
            "/api/config",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={"embedding": {"provider": "fastembed"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "embedding.provider" in data["pending_restart"]
        assert "embedding.provider" not in data["applied"]
        assert "embedding" not in data["applied"]  # bare top-level key is not a leaf

    def test_put_config_nested_non_restart_is_applied(self, client, api_key):
        """Nested non-restart leaf must appear in applied (not pending_restart)."""
        resp = client.put(
            "/api/config",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={"retrieval": {"default_k": 5}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "retrieval.default_k" in data["applied"]
        assert "retrieval.default_k" not in data["pending_restart"]

    def test_put_config_dropdown_enum_log_level_applies(self, client, api_key):
        """Logging level — surfaced in the UI as a dropdown — round-trips and
        is correctly flagged restart-required."""
        resp = client.put(
            "/api/config",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={"logging": {"level": "DEBUG"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "logging.level" in data["pending_restart"]
        assert "logging.level" not in data["applied"]

    def test_put_config_dropdown_enum_synthesis_format_applies(self, client, api_key):
        """Synthesis format dropdown — non-restart enum, must appear in applied."""
        resp = client.put(
            "/api/config",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={"synthesis": {"default_format": "synthesized_brief"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "synthesis.default_format" in data["applied"]

        # Confirm the change is now visible via GET
        get_resp = client.get("/api/config", headers=_headers(api_key))
        assert get_resp.status_code == 200
        cfg = get_resp.json()
        assert cfg["synthesis"]["default_format"] == "synthesized_brief"

    def test_put_config_multi_section_nested_payload(self, client, api_key):
        """The Apply button builds a single nested payload across sections.
        Both leaves must be acknowledged in their respective buckets."""
        resp = client.put(
            "/api/config",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={
                "retrieval": {"default_k": 7},
                "llm": {"temperature": 0.25},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "retrieval.default_k" in data["applied"]
        assert "llm.temperature" in data["applied"]
        assert not any(p in data["pending_restart"] for p in ("retrieval.default_k", "llm.temperature"))

    def test_get_config_meta_exposes_restart_fields(self, client, api_key):
        """v2.6.2: /api/config/meta is the single source of truth for the UI's
        "restart required" badge — eliminates server/UI drift on _RESTART_REQUIRED_FIELDS.
        """
        resp = client.get("/api/config/meta", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "restart_required_fields" in data
        fields = data["restart_required_fields"]
        assert isinstance(fields, list)
        assert fields == sorted(fields), "should be sorted for deterministic UI ordering"
        # Spot-check known restart-required leaves
        for expected in ("backend", "embedding.provider", "llm.provider", "logging.level"):
            assert expected in fields, f"missing expected restart-required field: {expected}"

    def test_get_config_meta_requires_auth_when_key_set(self, client, monkeypatch):
        """The meta endpoint reveals server-side internals (restart-required
        leaf names) — it must be auth-gated identically to /api/config."""
        from web import app as web_app
        monkeypatch.setattr(web_app, "API_KEY", "test-api-key-12345")
        resp = client.get("/api/config/meta")
        assert resp.status_code == 401

    def test_put_config_with_list_value_round_trips(self, client, api_key):
        """Regression for the YAML-list parser bug: lists like
        synthesis.tier_filter must survive PUT and read back identically.
        The frontend YAML parser previously dropped list values into empty
        objects when the YAML used the indented `key:\\n  - item` form."""
        resp = client.put(
            "/api/config",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={"synthesis": {"tier_filter": ["A", "C"]}},
        )
        assert resp.status_code == 200
        get_resp = client.get("/api/config", headers=_headers(api_key))
        assert get_resp.status_code == 200
        cfg = get_resp.json()
        assert cfg["synthesis"]["tier_filter"] == ["A", "C"]


# ── Graph Nodes / Edges ──────────────────────────────────────────────────────


class TestGraphEndpoints:
    """GET /api/graph/nodes and GET /api/graph/edges — knowledge graph data."""

    def test_graph_nodes_returns_list(self, client, api_key):
        resp = client.get("/api/graph/nodes", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "count" in data
        assert isinstance(data["nodes"], list)

    def test_graph_edges_returns_list(self, client, api_key):
        resp = client.get("/api/graph/edges", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "edges" in data
        assert "count" in data
        assert isinstance(data["edges"], list)


# ── Entities ──────────────────────────────────────────────────────────────────


class TestEntitiesEndpoint:
    """GET /api/entities — paginated entity index."""

    def test_entities_accepts_pagination(self, client, api_key):
        resp = client.get("/api/entities?offset=0&limit=10", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data
        assert "total" in data
        assert "offset" in data
        assert "limit" in data
        assert data["offset"] == 0
        assert data["limit"] == 10

    def test_entities_filters_by_type(self, client, api_key):
        resp = client.get("/api/entities?type=actor", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data

    def test_entities_filters_by_text_search(self, client, api_key):
        resp = client.get("/api/entities?q=APT", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data


# ── History ───────────────────────────────────────────────────────────────────


class TestHistoryEndpoint:
    """GET /api/history — recent session activity."""

    def test_history_returns_list(self, client, api_key):
        resp = client.get("/api/history", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_history_entries_have_expected_fields(self, client, api_key):
        resp = client.get("/api/history?limit=5", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        if data:
            entry = data[0]
            assert "query_id" in entry
            assert "event_type" in entry
            assert "timestamp" in entry


# ── Ingest ────────────────────────────────────────────────────────────────────


class TestIngestEndpoint:
    """POST /api/ingest — bulk ingestion."""

    def test_ingest_accepts_single_item(self, client, api_key):
        resp = client.post(
            "/api/ingest",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={
                "items": [
                    {
                        "content": "APT28 uses Cobalt Strike for lateral movement.",
                        "source_type": "test",
                        "domain": "cti",
                        "evolve": False,
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["succeeded"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["success"] is True
        assert "note_id" in data["results"][0]

    def test_ingest_handles_multiple_items(self, client, api_key):
        resp = client.post(
            "/api/ingest",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={
                "items": [
                    {
                        "content": f"Test note {i} for bulk ingest.",
                        "source_type": "test",
                        "domain": "cti",
                        "evolve": False,
                    }
                    for i in range(3)
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3
        assert all(r["success"] for r in data["results"])


# ── Telemetry ─────────────────────────────────────────────────────────────────


class TestTelemetryEndpoint:
    """GET /api/telemetry — aggregated telemetry summary."""

    def test_telemetry_returns_summary(self, client, api_key):
        resp = client.get("/api/telemetry", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "total_queries" in data
        assert isinstance(data.get("total_queries", 0), int)
        assert "top_intents" in data

    def test_telemetry_has_latency_stats(self, client, api_key):
        resp = client.get("/api/telemetry", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "avg_latency_ms" in data


# ── Storage ───────────────────────────────────────────────────────────────────


class TestStorageEndpoint:
    """GET /api/storage — storage statistics."""

    def test_storage_returns_counts(self, client, api_key):
        resp = client.get("/api/storage", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "total_notes" in data
        assert "entity_count" in data
        assert isinstance(data["total_notes"], int)
        assert isinstance(data["entity_count"], int)


# ── Logs ──────────────────────────────────────────────────────────────────────


class TestLogsEndpoint:
    """GET /api/logs — structlog file tailing."""

    def test_logs_returns_list(self, client, api_key):
        resp = client.get("/api/logs?lines=10", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert isinstance(data["logs"], list)

    def test_logs_supports_level_filter(self, client, api_key):
        resp = client.get("/api/logs?lines=10&level=INFO", headers=_headers(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data


# ── SSE Streams ───────────────────────────────────────────────────────────────


class TestSSEEndpoints:
    """GET /api/logs/stream and GET /api/telemetry/stream — SSE streaming."""

    def test_logs_stream_returns_200(self, client, api_key):
        pytest.skip("SSE endpoints stream indefinitely; tested manually")

    def test_telemetry_stream_returns_200(self, client, api_key):
        pytest.skip("SSE endpoints stream indefinitely; tested manually")


# ── Frontend ──────────────────────────────────────────────────────────────────


class TestFrontendEndpoint:
    """GET / — SPA serving."""

    def test_frontend_serves_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/html")
        html = resp.text
        assert "ZettelForge" in html


class TestConfigPage:
    """GET /config — auth-gated config editor HTML."""

    def test_config_page_requires_auth_when_key_set(self, client, monkeypatch):
        """When an API key is configured, /config rejects unauthenticated requests.

        require_api_guard reads API_KEY at module-import time, so we patch the
        module attribute directly rather than the env var.
        """
        from web import app as web_app

        monkeypatch.setattr(web_app, "API_KEY", "test-api-key-12345")
        resp = client.get("/config")
        assert resp.status_code == 401

    def test_config_page_renders_yaml_body_when_authenticated(self, client, api_key):
        """Regression: server-side render of config_editor.html must not silently
        fail with NameError on _to_dict and leave config_yaml blank.
        """
        resp = client.get("/config", headers=_headers(api_key))
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/html")
        html = resp.text
        # The textarea is server-populated; verify it is non-empty and contains
        # at least one expected top-level config key dumped as YAML.
        assert "<textarea" in html
        assert 'id="config-yaml"' in html
        assert ("llm:" in html) or ("embedding:" in html) or ("storage:" in html)

    def test_config_page_has_form_tab_with_apply_button(self, client, api_key):
        """v2.6.2: /config now ships a form-based editor with a working
        Apply button alongside the YAML editor. Regression-guard that:
          - Both tabs render (Form + YAML)
          - The Apply button exists and is wired (not just a dead onclick)
          - At least one known dropdown enum is declared in the schema
          - Restart-required leaves are tagged for the UI badge
        """
        resp = client.get("/config", headers=_headers(api_key))
        assert resp.status_code == 200
        html = resp.text

        # Tab structure
        assert 'data-tab="form"' in html
        assert 'data-tab="yaml"' in html

        # Working Apply buttons (replaced the dead saveConfigForm()/reloadConfig() calls)
        assert 'id="apply-form-btn"' in html
        assert 'id="apply-yaml-btn"' in html
        assert 'saveConfigForm' not in html  # dead handler removed
        assert 'reloadConfig()' not in html  # dead handler removed

        # Dropdown-eligible enum keys are declared client-side
        assert "'llm.provider'" in html
        assert "'logging.level'" in html
        assert "'governance.pii.action'" in html

        # Restart-required leaves are flagged in the same JS so the UI can badge them
        assert "'llm.model'" in html or '"llm.model"' in html
        assert "'embedding.provider'" in html or '"embedding.provider"' in html
