# -*- coding: utf-8 -*-
"""日志配置：text / json 两种格式，request_id 贯穿，手机号自动脱敏。"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

from backend.core.context import get_request_id

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        if isinstance(record.msg, str):
            record.msg = _PHONE_RE.sub(r"\1****\2", record.msg)
        return True


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"{record.levelname:<7} [{getattr(record, 'request_id', '-')}] "
            f"{record.name}: {record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())
    handler.setFormatter(_JsonFormatter() if fmt == "json" else _TextFormatter())
    root.addHandler(handler)

    # 降低第三方库噪声
    for noisy in ("httpx", "httpcore", "openai", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
