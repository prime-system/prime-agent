"""Minimal JSON logger compatible with tests and app expectations."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

_STANDARD_RECORD_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
}


_original_make_record = logging.Logger.makeRecord


def _safe_make_record(
    self: logging.Logger,
    name: str,
    level: int,
    fn: str,
    lno: int,
    msg: Any,
    args: Any,
    exc_info: Any,
    func: str | None = None,
    extra: dict[str, Any] | None = None,
    sinfo: str | None = None,
) -> logging.LogRecord:
    """Allow extra fields to override `message`/`asctime` without KeyError."""
    if extra is None:
        return _original_make_record(self, name, level, fn, lno, msg, args, exc_info, func, None, sinfo)

    extra_copy = dict(extra)
    message_override = extra_copy.pop("message", None)
    asctime_override = extra_copy.pop("asctime", None)

    record = _original_make_record(
        self,
        name,
        level,
        fn,
        lno,
        msg,
        args,
        exc_info,
        func,
        extra_copy,
        sinfo,
    )

    if message_override is not None:
        record.__dict__["message"] = message_override
    if asctime_override is not None:
        record.__dict__["asctime"] = asctime_override

    return record


logging.Logger.makeRecord = _safe_make_record  # type: ignore[assignment]


class JsonFormatter(logging.Formatter):
    """Simple JSON formatter with `level` and ISO timestamps."""

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: str = "%",
        *,
        rename_fields: dict[str, str] | None = None,
        timestamp: bool = False,
        json_default: Any | None = None,
        json_encoder: type[json.JSONEncoder] | None = None,
        **_: Any,
    ) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)
        self.rename_fields = rename_fields or {}
        self.timestamp = timestamp
        self.json_default = json_default
        self.json_encoder = json_encoder

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 - match logging API
        extra_message = record.__dict__.get("message")
        if extra_message is not None and extra_message != record.msg:
            message = extra_message
        else:
            message = record.getMessage()

        payload: dict[str, Any] = {
            "message": message,
            "level": record.levelname,
            "name": record.name,
        }

        if self.timestamp:
            timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
            payload["timestamp"] = timestamp.isoformat().replace("+00:00", "Z")

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS:
                continue
            payload[key] = value

        if self.rename_fields:
            for old_key, new_key in list(self.rename_fields.items()):
                if old_key in payload:
                    payload[new_key] = payload.pop(old_key)

        return json.dumps(
            payload,
            default=self.json_default,
            cls=self.json_encoder,
            ensure_ascii=False,
        )
