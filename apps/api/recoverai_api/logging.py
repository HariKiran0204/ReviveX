from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from recoverai_api.request_context import get_request_id

_SECRET_KEYS = frozenset(
    {
        "llm_api_key",
        "razorpay_key_secret",
        "razorpay_webhook_secret",
        "password",
        "secret",
        "authorization",
        "api_key",
        "key_secret",
    }
)


class JsonLogFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        for key in ("correlation_id", "merchant_id", "event_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def configure_logging(service: str, level: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(service=service))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def redact(mapping: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in mapping.items():
        if key.lower() in _SECRET_KEYS:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted
