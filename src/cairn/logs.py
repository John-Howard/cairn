"""Structured JSON logging to stdout (NFRs §6).

No personal data in log lines: identifiers and event types only, never field
contents — the AuditEvent table, not the log stream, is the forensic record.
Security-relevant events go through security_event() so they carry structured
fields the estate's aggregation can filter on.
"""

import json
import logging
import sys
from datetime import UTC, datetime

# LogRecord's own attributes; anything else on the record came in via `extra`.
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(json_format: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # Route uvicorn's loggers through the root handler so all stdout is one format.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


_security = logging.getLogger("cairn.security")


def security_event(event: str, **fields: object) -> None:
    """One structured line per security-relevant event. Callers must pass only
    non-personal fields (paths, roles, opaque subjects) — never emails or names."""
    _security.info(event, extra={"event": event, **fields})
