from __future__ import annotations

import json
import os
from pathlib import Path

import click
import httpx
import yaml

from orchestrator import __version__
from orchestrator.config.loader import ConfigError, load_config
from orchestrator.engine.runner import EngineError, RunEngine
from orchestrator.http_probe import probe_headers
from orchestrator.lifecycle.factory import build_adapter
from orchestrator.monitoring.prometheus import PrometheusClient
from orchestrator.scheduler.service import Scheduler
from orchestrator.storage.db import Database
from orchestrator.storage.runs import RunStore


def _cfg_path(ctx) -> str:
    return ctx.obj["config"]


def _load(ctx):
    return load_config(_cfg_path(ctx), secrets_dir=ctx.obj.get("secrets_dir"))


@click.group()
@click.option(
    "--config",
    envvar="ORCHESTRATOR_CONFIG",
    default="/project/orchestrator.yml",
    show_default=True,
)
@click.option("--secrets-dir", envvar="ORCHESTRATOR_SECRETS_DIR", default=None)
@click.version_option(__version__)
@click.pass_context
def cli(ctx, config, secrets_dir):
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    ctx.obj["secrets_dir"] = secrets_dir


@cli.command()
@click.pass_context
def validate(ctx):
    """Validate YAML configuration."""
    cfg = _load(ctx)
    click.echo(f"OK project={cfg.project.name} suites={len(cfg.suites)} tests={len(cfg.tests)}")


@cli.command()
@click.option("--quick", is_flag=True)
@click.pass_context
def doctor(ctx, quick):
    """Check binaries, config, SSH, optional Prometheus/Influx."""
    checks = []

    def note(name, ok, detail=""):
        checks.append((name, ok, detail))
        mark = "ok" if ok else "FAIL"
        click.echo(f"[{mark}] {name} {detail}")

    try:
        cfg = _load(ctx)
        note("config", True, cfg.project.name)
    except ConfigError as exc:
        note("config", False, str(exc))
        raise SystemExit(1)

    from shutil import which

    note("k6", which(cfg.k6_bin) is not None, cfg.k6_bin)
    note("ssh", which("ssh") is not None)
    note("curl", which("curl") is not None)
    note("jq", which("jq") is not None)
    Path(cfg.storage.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    note("data_dir", os.access(Path(cfg.storage.sqlite_path).parent, os.W_OK), cfg.storage.sqlite_path)
    if quick:
        if not all(ok for _, ok, _ in checks):
            raise SystemExit(1)
        return
    adapter = build_adapter(cfg)
    conn = adapter.check_connection()
    note("target_ssh", conn.ok, conn.detail[:120])
    traffic = cfg.target.traffic
    url = cfg.health.test_url or traffic.test_base_url.rstrip("/") + traffic.health_path
    try:
        headers = probe_headers(traffic, public=False)
        resp = httpx.get(url, headers=headers, timeout=cfg.health.timeout_seconds)
        note("target_http", 200 <= resp.status_code < 300, f"{url} -> {resp.status_code}")
    except httpx.HTTPError as exc:
        note("target_http", False, str(exc))
    if cfg.monitoring.enabled and cfg.monitoring.prometheus_url:
        sample = PrometheusClient(cfg).sample()
        required = cfg.safety.abort_if_prometheus_unavailable
        note(
            "prometheus",
            sample.ok or not required,
            cfg.monitoring.prometheus_url + ("" if sample.ok else " (optional)"),
        )
    else:
        note("prometheus", True, "disabled")
    if cfg.storage.influx.enabled and cfg.storage.influx.url:
        try:
            r = httpx.get(cfg.storage.influx.url.rstrip("/") + "/health", timeout=5.0)
            note("influxdb", r.status_code < 500, cfg.storage.influx.url)
        except httpx.HTTPError as exc:
            note("influxdb", True, f"optional unavailable: {exc}")
    else:
        note("influxdb", True, "disabled")
    if cfg.database_snapshot.enabled:
        snap = adapter.probe_database_snapshot()
        note("db_snapshot", snap.ok, snap.detail[:200])
    else:
        note("db_snapshot", True, "disabled")
    if not all(ok for _, ok, _ in checks):
        raise SystemExit(1)


@cli.group(name="list")
def list_grp():
    pass


@list_grp.command("suites")
@click.pass_context
def list_suites(ctx):
    cfg = _load(ctx)
    for suite in cfg.suites.values():
        click.echo(f"{suite.id}: {', '.join(suite.order or suite.tests)}")


@list_grp.command("runs")
@click.pass_context
def list_runs(ctx):
    cfg = _load(ctx)
    store = RunStore(Database(cfg.storage.sqlite_path))
    for run in store.list():
        click.echo(f"{run['id']}\t{run['status']}\t{run.get('suite') or run.get('test')}")


@cli.command()
@click.option("--suite", "suite_id", default=None)
@click.option("--test", "test_id", default=None)
@click.pass_context
def run(ctx, suite_id, test_id):
    """Execute a suite or a single test (one-shot)."""
    if bool(suite_id) == bool(test_id):
        raise click.UsageError("specify exactly one of --suite or --test")
    cfg = _load(ctx)
    engine = RunEngine(cfg)
    try:
        result = engine.run_suite(suite_id) if suite_id else engine.run_test(test_id)
    except EngineError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({k: result.get(k) for k in ("id", "status", "error", "artifacts_dir")}, indent=2))
    if result.get("status") not in {"completed"}:
        raise SystemExit(1)


@cli.command()
@click.argument("run_id")
@click.pass_context
def status(ctx, run_id):
    cfg = _load(ctx)
    store = RunStore(Database(cfg.storage.sqlite_path))
    run = store.get(run_id)
    if not run:
        raise click.ClickException("run not found")
    click.echo(json.dumps(run, indent=2, default=str))


@cli.command()
@click.argument("run_id")
@click.option("--regenerate", is_flag=True, help="Rebuild HTML/MD/CSV/JSON from stored k6 summaries")
@click.pass_context
def report(ctx, run_id, regenerate):
    cfg = _load(ctx)
    store = RunStore(Database(cfg.storage.sqlite_path))
    run = store.get(run_id)
    if not run:
        raise click.ClickException("run not found")
    html = Path(run["artifacts_dir"]) / "report.html"
    if regenerate:
        from orchestrator.reporting.regenerate import regenerate_run_report

        paths = regenerate_run_report(cfg, run, store)
        click.echo(json.dumps(paths, indent=2))
        return
    click.echo(str(html) if html.exists() else json.dumps(run, indent=2, default=str))


@cli.command()
@click.argument("run_id")
@click.pass_context
def recover(ctx, run_id):
    cfg = _load(ctx)
    engine = RunEngine(cfg)
    result = engine.recover(run_id)
    click.echo(json.dumps(result, indent=2, default=str))


@cli.command()
@click.pass_context
def scheduler(ctx):
    """Persistent in-process scheduler (no host cron)."""
    cfg = _load(ctx)
    click.echo(f"scheduler timezone={cfg.schedule.timezone} jobs={len(cfg.schedule.jobs)}")
    Scheduler(cfg).loop_forever()


@cli.command()
def ping():
    """Lightweight health for Docker HEALTHCHECK."""
    click.echo("pong")


def main():
    cli(obj={})
