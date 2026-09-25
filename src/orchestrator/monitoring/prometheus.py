from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from orchestrator.config.models import OrchestratorConfig


@dataclass
class Sample:
    cpu: float | None = None
    memory: float | None = None
    disk: float | None = None
    network: float | None = None
    load: float | None = None
    ok: bool = True
    raw: dict = field(default_factory=dict)


class PrometheusClient:
    def __init__(self, cfg: OrchestratorConfig, http: httpx.Client | None = None):
        self.cfg = cfg
        self.http = http or httpx.Client(timeout=5.0)

    def enabled(self) -> bool:
        return bool(self.cfg.monitoring.enabled and self.cfg.monitoring.prometheus_url)

    def query(self, expr: str) -> float | None:
        if not self.enabled() or not expr:
            return None
        url = self.cfg.monitoring.prometheus_url.rstrip("/") + "/api/v1/query"
        try:
            resp = self.http.get(url, params={"query": expr})
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            if not results:
                return None
            value = results[0].get("value", [None, None])[1]
            return float(value)
        except (httpx.HTTPError, ValueError, IndexError, KeyError, TypeError):
            return None

    def sample(self) -> Sample:
        if not self.enabled():
            return Sample(ok=True, raw={"monitoring": "disabled"})
        try:
            self.http.get(self.cfg.monitoring.prometheus_url.rstrip("/") + "/-/ready", timeout=3.0)
            ready = True
        except httpx.HTTPError:
            ready = False
        mon = self.cfg.monitoring
        return Sample(
            cpu=self.query(mon.cpu_query) if mon.cpu_query else None,
            memory=self.query(mon.memory_query) if mon.memory_query else None,
            disk=self.query(mon.disk_query) if mon.disk_query else None,
            network=self.query(mon.network_query) if mon.network_query else None,
            load=self.query(mon.load_query) if mon.load_query else None,
            ok=ready,
            raw={"ready": ready},
        )
