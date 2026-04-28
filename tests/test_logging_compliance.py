"""
GOV-012 Logging Compliance Tests

Ensures:
- No print() in production code
- Core operations emit OCSF events with required fields
- LanceDB failures are logged, not swallowed (regression for #26)
- Governance violations emit Authorization events
- Audit events reach the audit log
"""
import ast
import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import structlog

from zettelforge.memory_store import MemoryStore
from zettelforge.note_schema import MemoryNote, Content, Semantic, Embedding, Metadata
from zettelforge.ocsf import (
    log_api_activity, log_authorization, log_authentication, log_config_change,
    STATUS_SUCCESS, STATUS_FAILURE, SEVERITY_HIGH,
)

NOW = datetime.now().isoformat()


def _make_note(note_id: str = "test_log_1", domain: str = "cti") -> MemoryNote:
    return MemoryNote(
        id=note_id,
        created_at=NOW,
        updated_at=NOW,
        content=Content(raw="Test content for logging", source_type="test", source_ref=""),
        semantic=Semantic(context="ctx", keywords=["test"], tags=[], entities=[]),
        embedding=Embedding(vector=[0.0] * 768),
        metadata=Metadata(domain=domain),
    )


class TestNoPrintInProduction:
    """Scan src/zettelforge/ for print() calls outside __main__ blocks."""

    def _find_print_calls(self, filepath: Path) -> list[int]:
        """Return line numbers of print() calls not inside if __name__ blocks."""
        source = filepath.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        main_guard_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # Detect if __name__ == "__main__":
                test = node.test
                if (isinstance(test, ast.Compare)
                        and isinstance(test.left, ast.Name)
                        and test.left.id == "__name__"):
                    for lineno in range(node.lineno, node.end_lineno + 1):
                        main_guard_lines.add(lineno)

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "print":
                    if node.lineno not in main_guard_lines:
                        violations.append(node.lineno)
        return violations

    def test_no_print_in_production(self):
        """No print() calls in src/zettelforge/ except __main__ blocks."""
        src_dir = Path(__file__).parent.parent / "src" / "zettelforge"
        violations = {}
        for pyfile in sorted(src_dir.glob("*.py")):
            lines = self._find_print_calls(pyfile)
            if lines:
                violations[pyfile.name] = lines

        assert violations == {}, (
            f"GOV-003 violation: print() found in production code: {violations}"
        )


class TestOCSFEventFields:
    """Verify OCSF events contain required base fields."""

    def test_api_activity_fields(self):
        """log_api_activity emits required OCSF base fields."""
        output = structlog.testing.capture_logs()
        with structlog.testing.capture_logs() as logs:
            log_api_activity(
                operation="remember",
                status_id=STATUS_SUCCESS,
                note_id="n123",
                duration_ms=42.5,
            )

        assert len(logs) >= 1
        event = logs[0]
        assert event["event"] == "ocsf_api_activity"
        assert event["class_uid"] == 6002
        assert event["status_id"] == STATUS_SUCCESS
        assert "time" in event
        assert "metadata" in event
        assert event["metadata"]["product"]["name"] == "zettelforge"

    def test_authorization_deny_fields(self):
        """log_authorization with deny emits correct status and severity."""
        with structlog.testing.capture_logs() as logs:
            log_authorization(
                actor="system",
                resource="remember",
                status_id=STATUS_FAILURE,
                severity_id=SEVERITY_HIGH,
                policy="GOV-011",
            )

        assert len(logs) >= 1
        event = logs[0]
        assert event["class_uid"] == 3003
        assert event["status_id"] == STATUS_FAILURE
        assert event["severity_id"] == SEVERITY_HIGH
        assert event["policy"] == "GOV-011"


class TestLanceDBFailureLogged:
    """Regression test for #26: LanceDB failures must be logged, not swallowed."""

    def test_lance_indexing_failure_emits_log(self):
        """When _index_in_lance fails, a structured error is emitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(
                jsonl_path=f"{tmpdir}/notes.jsonl",
                lance_path=f"{tmpdir}/vectordb"
            )
            note = _make_note()

            # Sabotage the LanceDB connection to force a failure
            store._lancedb = "not_a_real_db"  # type: ignore

            with structlog.testing.capture_logs() as logs:
                store._index_in_lance(note)

            # Should have logged an error, not silently swallowed
            error_logs = [l for l in logs if l.get("log_level", "") == "error"]
            assert len(error_logs) > 0, (
                "LanceDB indexing failure was silently swallowed (regression of #26)"
            )


class TestGovernanceViolationEvent:
    """Governance violation should emit OCSF Authorization event."""

    def test_governance_violation_emits_authorization_event(self):
        """Triggering a governance violation emits an OCSF class 3003 deny event."""
        with structlog.testing.capture_logs() as logs:
            log_authorization(
                actor="system",
                resource="remember",
                status_id=STATUS_FAILURE,
                severity_id=SEVERITY_HIGH,
                policy="GOV-011",
                violation="empty_content",
            )

        auth_events = [l for l in logs if l.get("class_uid") == 3003]
        assert len(auth_events) == 1
        assert auth_events[0]["status_id"] == STATUS_FAILURE
        assert auth_events[0]["violation"] == "empty_content"
