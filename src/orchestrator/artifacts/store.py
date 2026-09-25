from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


class ArtifactStore:
    def __init__(self, results_dir: str, run_id: str):
        self.root = Path(results_dir) / run_id
        self.server = self.root / "server"
        self.root.mkdir(parents=True, exist_ok=True)
        self.server.mkdir(parents=True, exist_ok=True)
        self.timeline_path = self.root / "timeline.jsonl"

    def test_dir(self, test_id: str) -> Path:
        path = self.root / "tests" / test_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(self, name: str, payload: Any, *, under: Path | None = None) -> Path:
        path = (under or self.root) / name
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def write_text(self, name: str, text: str, *, under: Path | None = None) -> Path:
        path = (under or self.root) / name
        path.write_text(text, encoding="utf-8")
        return path

    def write_yaml(self, name: str, payload: Any) -> Path:
        path = self.root / name
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return path

    def timeline(self, event: str, **fields: Any) -> None:
        rec = {"event": event, **fields}
        with self.timeline_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")

    def write_server(self, name: str, text: str) -> Path:
        return self.write_text(name, text, under=self.server)
