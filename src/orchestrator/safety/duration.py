from __future__ import annotations

import re

_UNITS = {
    "ms": 0.001,
    "s": 1,
    "m": 60,
    "h": 3600,
}


def parse_duration(value: str) -> float:
    """Parse k6-style durations like 30s, 5m, 1h30m, 250ms."""
    if not value:
        raise ValueError("empty duration")
    total = 0.0
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", value.strip()):
        total += float(number) * _UNITS[unit]
    if total <= 0:
        raise ValueError(f"invalid duration: {value}")
    return total
