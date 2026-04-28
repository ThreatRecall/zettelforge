"""
Structured logging for ZettelForge (GOV-012 compliant).

All structured/OCSF logs go to rotating files only (never stdout).
Only WARNING+ errors are printed to stderr so operators see failures
without OCSF event noise drowning out application output.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import structlog

_configured = False

# OCSF event prefixes routed to the dedicated audit log
_AUDIT_EVENT_PREFIXES = (
    "ocsf_authentication",
    "ocsf_authorization",
    "ocsf_account_change",
    "ocsf_config_change",
)


class _AuditFilter(logging.Filter):
    """Filter that only passes audit-critical OCSF events to the audit log."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return any(prefix in msg for prefix in _AUDIT_EVENT_PREFIXES)


def configure_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    audit_log_file: Optional[str] = None,
    log_to_stderr: bool = True,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 9,
    audit_backup_count: int = 52,
) -> None:
    """Configure structlog with JSON output per GOV-012.

    Structured logs (including OCSF events) go to rotating log files only.
    stderr receives WARNING+ messages so operators see errors without
    info-level OCSF noise.

    Args:
        level: Minimum log level for file output (DEBUG, INFO, WARNING, ERROR).
        log_file: Path to rotating log file. None disables file logging.
        audit_log_file: Path to audit log for security events (OCSF 3001/3003/3005/5002).
        log_to_stderr: Whether to print WARNING+ to stderr.
        max_bytes: Max bytes per log file before rotation.
        backup_count: Number of rotated backup files to keep.
        audit_backup_count: Number of audit log backups (~1 year at 10MB each).
    """
    global _configured
    if _configured:
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Build the list of file destinations for structlog
    _log_files: list[object] = []

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _log_files.append(open(log_path, "a"))  # noqa: SIM115 — long-lived file handle

    # Audit log: separate file for security-critical OCSF events
    # (handled at the stdlib level via a filter, not structlog)
    if audit_log_file:
        audit_path = Path(audit_log_file)
        audit_path.parent.mkdir(parents=True, exist_ok=True)

    # stdlib logging: used only for stderr warnings and audit log routing
    stdlib_handlers: list[logging.Handler] = []

    if log_to_stderr:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.WARNING)
        stderr_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        stdlib_handlers.append(stderr_handler)

    if log_file:
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        stdlib_handlers.append(file_handler)

    if audit_log_file:
        audit_handler = RotatingFileHandler(
            str(audit_path),
            maxBytes=max_bytes,
            backupCount=audit_backup_count,
        )
        audit_handler.setLevel(logging.INFO)
        audit_handler.setFormatter(logging.Formatter("%(message)s"))
        audit_handler.addFilter(_AuditFilter())
        stdlib_handlers.append(audit_handler)

    logging.basicConfig(
        format="%(message)s",
        level=numeric_level,
        handlers=stdlib_handlers,
        force=True,
    )

    # structlog: JSON to log file (not stdout/stderr)
    # Use stdlib integration so structlog events flow through the handlers above
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="time"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Formatter for stdlib handlers that renders structlog events as JSON
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
    )
    for handler in stdlib_handlers:
        handler.setFormatter(formatter)

    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a named structlog logger.

    Args:
        name: Logger name, typically module path (e.g. "zettelforge.memory").

    Returns:
        A bound structlog logger instance.
    """
    if not _configured:
        data_dir = os.environ.get("AMEM_DATA_DIR", str(Path.home() / ".amem"))
        logs_dir = Path(data_dir) / "logs"
        log_file = str(logs_dir / "zettelforge.log")
        audit_log_file = str(logs_dir / "audit.log")
        configure_logging(log_file=log_file, audit_log_file=audit_log_file)
    return structlog.get_logger(name)
