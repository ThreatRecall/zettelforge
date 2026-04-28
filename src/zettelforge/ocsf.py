"""
OCSF v1.3 event emitters for ZettelForge (GOV-012 compliant).

Provides typed helper functions for each OCSF event class required by
GOV-012. All emitters include the mandatory OCSF base fields and use
structlog for output.

Event classes:
    6002 - API Activity (remember, recall, synthesize)
    3001 - Authentication (MCP server auth, API key validation)
    3003 - Authorization (governance validation decisions)
    5002 - Configuration Change (config.yaml changes)
    1001 - File Activity (JSONL writes, LanceDB operations)
    1007 - Process Activity (service start/stop, rebuild)
    3005 - Account Change (stub for multi-tenant)
"""

from datetime import datetime, timezone
from typing import Any, Optional

from zettelforge.log import get_logger

logger = get_logger("zettelforge.ocsf")

_PRODUCT_VERSION = "2.1.1"

# OCSF severity mapping
SEVERITY_UNKNOWN = 0
SEVERITY_INFO = 1
SEVERITY_LOW = 2
SEVERITY_MEDIUM = 3
SEVERITY_HIGH = 4
SEVERITY_CRITICAL = 5

_SEVERITY_NAMES = {
    0: "Unknown",
    1: "Informational",
    2: "Low",
    3: "Medium",
    4: "High",
    5: "Critical",
}

# OCSF status mapping
STATUS_SUCCESS = 1
STATUS_FAILURE = 2


def _base_fields(
    class_uid: int,
    class_name: str,
    category_uid: int,
    category_name: str,
    activity_id: int,
    activity_name: str,
    severity_id: int,
    status_id: int,
) -> dict[str, Any]:
    """Build the required OCSF base fields."""
    return {
        "class_uid": class_uid,
        "class_name": class_name,
        "category_uid": category_uid,
        "category_name": category_name,
        "severity_id": severity_id,
        "severity": _SEVERITY_NAMES.get(severity_id, "Unknown"),
        "activity_id": activity_id,
        "activity_name": activity_name,
        "status_id": status_id,
        "status": "Success" if status_id == STATUS_SUCCESS else "Failure",
        "time": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "version": "1.3.0",
            "product": {
                "name": "zettelforge",
                "vendor_name": "threatengram",
                "version": _PRODUCT_VERSION,
            },
            "log_name": "application",
            "log_provider": "structlog",
        },
    }


# ── 6002: API Activity ──────────────────────────────────────────────────


def log_api_activity(
    operation: str,
    status_id: int = STATUS_SUCCESS,
    severity_id: int = SEVERITY_INFO,
    actor: Optional[str] = None,
    resource: Optional[str] = None,
    duration_ms: Optional[float] = None,
    **details: Any,
) -> None:
    """Emit an OCSF API Activity event (class 6002).

    Covers: remember, recall, synthesize, remember_report, etc.
    """
    event = _base_fields(
        class_uid=6002,
        class_name="API Activity",
        category_uid=6,
        category_name="Application Activity",
        activity_id=1 if status_id == STATUS_SUCCESS else 2,
        activity_name=operation,
        severity_id=severity_id,
        status_id=status_id,
    )
    if actor:
        event["actor"] = {"user": {"name": actor}}
    if resource:
        event["resource"] = resource
    if duration_ms is not None:
        event["duration_ms"] = round(duration_ms, 2)
    event.update(details)
    logger.info("ocsf_api_activity", **event)


# ── 3001: Authentication ─────────────────────────────────────────────────


def log_authentication(
    actor: str,
    auth_protocol: str,
    status_id: int = STATUS_SUCCESS,
    severity_id: int = SEVERITY_INFO,
    src_endpoint: Optional[str] = None,
    **details: Any,
) -> None:
    """Emit an OCSF Authentication event (class 3001).

    Covers: MCP server auth, API key validation.
    """
    event = _base_fields(
        class_uid=3001,
        class_name="Authentication",
        category_uid=3,
        category_name="Identity & Access Management",
        activity_id=1,
        activity_name="Logon",
        severity_id=severity_id,
        status_id=status_id,
    )
    event["actor"] = {"user": {"name": actor}}
    event["auth_protocol"] = auth_protocol
    if src_endpoint:
        event["src_endpoint"] = {"ip": src_endpoint}
    event.update(details)
    logger.info("ocsf_authentication", **event)


# ── 3003: Authorization ──────────────────────────────────────────────────


def log_authorization(
    actor: str,
    resource: str,
    status_id: int = STATUS_SUCCESS,
    severity_id: int = SEVERITY_INFO,
    privileges: Optional[str] = None,
    policy: Optional[str] = None,
    **details: Any,
) -> None:
    """Emit an OCSF Authorization event (class 3003).

    Covers: governance validation allow/deny decisions.
    """
    event = _base_fields(
        class_uid=3003,
        class_name="Authorization",
        category_uid=3,
        category_name="Identity & Access Management",
        activity_id=1 if status_id == STATUS_SUCCESS else 2,
        activity_name="Access Grant" if status_id == STATUS_SUCCESS else "Access Deny",
        severity_id=severity_id,
        status_id=status_id,
    )
    event["actor"] = {"user": {"name": actor}}
    event["resource"] = resource
    if privileges:
        event["privileges"] = privileges
    if policy:
        event["policy"] = policy
    event.update(details)
    logger.info("ocsf_authorization", **event)


# ── 5002: Configuration Change ───────────────────────────────────────────


def log_config_change(
    resource: str,
    status_id: int = STATUS_SUCCESS,
    severity_id: int = SEVERITY_INFO,
    actor: Optional[str] = None,
    prev_value: Optional[str] = None,
    new_value: Optional[str] = None,
    **details: Any,
) -> None:
    """Emit an OCSF Configuration Change event (class 5002).

    Covers: config.yaml changes, governance enable/disable.
    """
    event = _base_fields(
        class_uid=5002,
        class_name="Configuration Change",
        category_uid=5,
        category_name="Discovery",
        activity_id=1,
        activity_name="Update",
        severity_id=severity_id,
        status_id=status_id,
    )
    if actor:
        event["actor"] = {"user": {"name": actor}}
    event["resource"] = resource
    if prev_value is not None:
        event["prev_value"] = prev_value
    if new_value is not None:
        event["new_value"] = new_value
    event.update(details)
    logger.info("ocsf_config_change", **event)


# ── 1001: File Activity ─────────────────────────────────────────────────


def log_file_activity(
    file_path: str,
    activity: str,
    status_id: int = STATUS_SUCCESS,
    severity_id: int = SEVERITY_INFO,
    actor: Optional[str] = None,
    duration_ms: Optional[float] = None,
    **details: Any,
) -> None:
    """Emit an OCSF File Activity event (class 1001).

    Covers: JSONL writes, LanceDB table operations, index rebuilds.
    """
    activity_map = {"Create": 1, "Read": 2, "Update": 3, "Delete": 4}
    event = _base_fields(
        class_uid=1001,
        class_name="File Activity",
        category_uid=1,
        category_name="System Activity",
        activity_id=activity_map.get(activity, 0),
        activity_name=activity,
        severity_id=severity_id,
        status_id=status_id,
    )
    if actor:
        event["actor"] = {"user": {"name": actor}}
    event["file"] = {"path": file_path}
    if duration_ms is not None:
        event["duration_ms"] = round(duration_ms, 2)
    event.update(details)
    logger.info("ocsf_file_activity", **event)


# ── 1007: Process Activity ──────────────────────────────────────────────


def log_process_activity(
    process_name: str,
    activity: str,
    status_id: int = STATUS_SUCCESS,
    severity_id: int = SEVERITY_INFO,
    **details: Any,
) -> None:
    """Emit an OCSF Process Activity event (class 1007).

    Covers: service start/stop, rebuild script execution.
    """
    activity_map = {"Start": 1, "Stop": 2, "Crash": 3, "Restart": 4}
    event = _base_fields(
        class_uid=1007,
        class_name="Process Activity",
        category_uid=1,
        category_name="System Activity",
        activity_id=activity_map.get(activity, 0),
        activity_name=activity,
        severity_id=severity_id,
        status_id=status_id,
    )
    event["process"] = {"name": process_name}
    event.update(details)
    logger.info("ocsf_process_activity", **event)


# ── 3005: Account Change (stub) ─────────────────────────────────────────


def log_account_change(
    actor: str,
    user: str,
    activity: str,
    status_id: int = STATUS_SUCCESS,
    severity_id: int = SEVERITY_INFO,
    prev_value: Optional[str] = None,
    new_value: Optional[str] = None,
    **details: Any,
) -> None:
    """Emit an OCSF Account Change event (class 3005).

    Stub for future multi-tenant support.
    """
    activity_map = {"Create": 1, "Update": 2, "Disable": 3, "Delete": 4}
    event = _base_fields(
        class_uid=3005,
        class_name="Account Change",
        category_uid=3,
        category_name="Identity & Access Management",
        activity_id=activity_map.get(activity, 0),
        activity_name=activity,
        severity_id=severity_id,
        status_id=status_id,
    )
    event["actor"] = {"user": {"name": actor}}
    event["user"] = {"name": user}
    if prev_value is not None:
        event["prev_value"] = prev_value
    if new_value is not None:
        event["new_value"] = new_value
    event.update(details)
    logger.info("ocsf_account_change", **event)
