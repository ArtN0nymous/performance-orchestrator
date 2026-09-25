"""Redact secrets from logs, configs, and reports."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_KEYS = (
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "stripe",
    "identity_file",
    "private_key",
    "client_secret",
    "webhook_secret",
)

_BEARER = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]+)", re.I)
_BASIC = re.compile(r"(Basic\s+)([A-Za-z0-9=._\-]+)", re.I)


def _is_sensitive_key(key: str, extra: list[str] | None = None) -> bool:
    lowered = key.lower().replace("-", "_")
    needles = list(DEFAULT_KEYS) + [k.lower() for k in (extra or [])]
    return any(n in lowered for n in needles)


def mask_value(value: str) -> str:
    if not value:
        return value
    if len(value) <= 8:
        return "****"
    return value[:2] + "****" + value[-2:]


def redact_text(text: str) -> str:
    text = _BEARER.sub(lambda m: m.group(1) + "****", text)
    text = _BASIC.sub(lambda m: m.group(1) + "****", text)
    return text


def redact(data: Any, extra_keys: list[str] | None = None) -> Any:
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if _is_sensitive_key(str(k), extra_keys):
                out[k] = "****" if not isinstance(v, (dict, list)) else redact(v, extra_keys)
            else:
                out[k] = redact(v, extra_keys)
        return out
    if isinstance(data, list):
        return [redact(v, extra_keys) for v in data]
    if isinstance(data, str):
        return redact_text(data)
    return data
