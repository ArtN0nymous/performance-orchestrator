from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from orchestrator.config.models import OrchestratorConfig, SuiteDef, K6Test
from orchestrator.config.secrets import resolve_tree


class ConfigError(ValueError):
    pass


def load_yaml(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping: {path}")
    return data


def _index_by_id(items: Any, cls):
    if items is None:
        return {}
    if isinstance(items, dict):
        return {k: cls(id=k, **(v or {})) if "id" not in (v or {}) else cls(**v) for k, v in items.items()}
    out = {}
    for item in items:
        obj = cls(**item)
        out[obj.id] = obj
    return out


def load_config(path: str | Path, *, secrets_dir: str | None = None) -> OrchestratorConfig:
    data = resolve_tree(load_yaml(path), secrets_dir=secrets_dir)
    suites = data.pop("suites", {})
    tests = data.pop("tests", {})
    try:
        cfg = OrchestratorConfig(
            **data,
            suites=_index_by_id(suites, SuiteDef),
            tests=_index_by_id(tests, K6Test),
        )
    except Exception as exc:  # noqa: BLE001 — surface as ConfigError
        raise ConfigError(str(exc)) from exc
    _validate_refs(cfg)
    return cfg


def _validate_refs(cfg: OrchestratorConfig) -> None:
    for suite in cfg.suites.values():
        for dep in suite.depends_on:
            if dep not in cfg.suites:
                raise ConfigError(f"Suite {suite.id} depends on unknown suite {dep}")
        ordered = suite.order or suite.tests
        for test_id in ordered:
            if test_id not in cfg.tests:
                raise ConfigError(f"Suite {suite.id} references unknown test {test_id}")
    for test in cfg.tests.values():
        if test.params.executor == "externally-controlled":
            raise ConfigError("externally-controlled executor is not supported")


def dump_resolved(cfg: OrchestratorConfig) -> str:
    payload = cfg.model_dump(mode="json")
    return yaml.safe_dump(payload, sort_keys=False)
