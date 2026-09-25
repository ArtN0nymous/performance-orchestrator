"""Shared HTTP probe headers for health / maintenance verification."""

from __future__ import annotations

from orchestrator.config.models import TrafficConfig


def probe_headers(traffic: TrafficConfig, *, public: bool = False) -> dict[str, str]:
    headers = dict(traffic.health_headers or {})
    if not public and traffic.bypass_header_name and traffic.bypass_header_value:
        headers[traffic.bypass_header_name] = traffic.bypass_header_value
    return headers
