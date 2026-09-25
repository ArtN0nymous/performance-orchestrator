from pathlib import Path

import pytest
import yaml

from orchestrator.config.loader import ConfigError, load_config
from orchestrator.config.secrets import resolve_tree


def _cfg(tmp_path: Path, extra: dict | None = None) -> Path:
    data = {
        "project": {"name": "t", "timezone": "UTC"},
        "target": {
            "type": "none",
            "traffic": {
                "public_base_url": "http://public",
                "test_base_url": "http://test",
                "health_path": "/health",
            },
        },
        "maintenance": {"enabled": True},
        "suites": {"smoke": {"tests": ["smoke"]}},
        "tests": {
            "smoke": {
                "script": "k6/smoke.js",
                "params": {"executor": "constant-vus", "vus": 1, "duration": "10s"},
            }
        },
    }
    if extra:
        data.update(extra)
    path = tmp_path / "o.yml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_load_ok(tmp_path):
    cfg = load_config(_cfg(tmp_path))
    assert cfg.project.name == "t"
    assert "smoke" in cfg.suites


def test_rejects_same_url_without_bypass(tmp_path):
    path = _cfg(
        tmp_path,
        {
            "target": {
                "type": "none",
                "traffic": {
                    "public_base_url": "http://same",
                    "test_base_url": "http://same",
                    "health_path": "/health",
                    "public_expect_status_when_maintenance": 503,
                    "test_expect_status_when_maintenance": 200,
                },
            }
        },
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_allows_same_url_when_api_stays_live_stub_mode(tmp_path):
    """Stub-live mode: EXTERNAL_API_STUB_ENABLED keeps HTTP 200 — no 503 split."""
    path = _cfg(
        tmp_path,
        {
            "target": {
                "type": "none",
                "traffic": {
                    "public_base_url": "http://same",
                    "test_base_url": "http://same",
                    "health_path": "/health",
                    "public_expect_status_when_maintenance": 200,
                    "test_expect_status_when_maintenance": 200,
                },
            }
        },
    )
    cfg = load_config(path)
    assert cfg.target.traffic.public_expect_status_when_maintenance == 200


def test_allows_same_url_with_bypass(tmp_path):
    path = _cfg(
        tmp_path,
        {
            "target": {
                "type": "none",
                "traffic": {
                    "public_base_url": "http://same",
                    "test_base_url": "http://same",
                    "bypass_header_name": "X-Bypass",
                    "bypass_header_value": "yes",
                    "health_path": "/health",
                    "public_expect_status_when_maintenance": 503,
                },
            }
        },
    )
    cfg = load_config(path)
    assert cfg.target.traffic.bypass_header_value == "yes"


def test_unknown_test_ref(tmp_path):
    path = _cfg(tmp_path, {"suites": {"smoke": {"tests": ["missing"]}}})
    with pytest.raises(ConfigError):
        load_config(path)


def test_secret_env(monkeypatch):
    monkeypatch.setenv("FOO_TOKEN", "abc")
    assert resolve_tree({"x": "${FOO_TOKEN}"})["x"] == "abc"


def test_secret_default():
    assert resolve_tree({"x": "${MISSING_TOKEN:-def}"})["x"] == "def"


def test_rejects_externally_controlled(tmp_path):
    path = _cfg(
        tmp_path,
        {
            "tests": {
                "smoke": {
                    "script": "x.js",
                    "params": {"executor": "externally-controlled"},
                }
            }
        },
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_database_snapshot_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_SNAPSHOT_ENABLED", "true")
    monkeypatch.setenv("DB_SNAPSHOT_DISABLE_SSL", "false")
    path = tmp_path / "o.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "project": {"name": "t"},
                "target": {
                    "type": "none",
                    "traffic": {
                        "public_base_url": "http://public",
                        "test_base_url": "http://test",
                    },
                },
                "maintenance": {"enabled": True},
                "database_snapshot": {
                    "enabled": "${DB_SNAPSHOT_ENABLED:-false}",
                    "disable_ssl": "${DB_SNAPSHOT_DISABLE_SSL:-true}",
                },
                "suites": {"smoke": {"tests": ["smoke"]}},
                "tests": {
                    "smoke": {
                        "script": "k6/smoke.js",
                        "params": {"executor": "constant-vus", "vus": 1, "duration": "10s"},
                    }
                },
            }
        )
    )
    cfg = load_config(path)
    assert cfg.database_snapshot.enabled is True
    assert cfg.database_snapshot.disable_ssl is False
    assert cfg.database_snapshot.resolved_mysql_opts() == ""
