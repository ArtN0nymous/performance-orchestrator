from __future__ import annotations

import json
import signal
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml

from orchestrator.artifacts.store import ArtifactStore
from orchestrator.config.models import OrchestratorConfig, K6Test
from orchestrator.http_probe import probe_headers
from orchestrator.k6.runner import K6Runner
from orchestrator.lifecycle.factory import build_adapter
from orchestrator.lifecycle.base import LifecycleResult
from orchestrator.monitoring.prometheus import PrometheusClient, Sample
from orchestrator.reporting.generate import generate_reports, stats_from_summary
from orchestrator.safety.controller import SafetyController, SafetyViolation
from orchestrator.safety.duration import parse_duration
from orchestrator.safety.masking import redact
from orchestrator.storage.db import Database
from orchestrator.storage.locks import RunLock
from orchestrator.storage.runs import RunStore, utcnow


class EngineError(Exception):
    pass


class RunEngine:
    def __init__(self, cfg: OrchestratorConfig, db: Database | None = None):
        self.cfg = cfg
        self.db = db or Database(cfg.storage.sqlite_path)
        self.store = RunStore(self.db)
        self.lock = RunLock(self.db, max_concurrent=cfg.max_concurrent_runs)
        self.k6 = K6Runner(cfg)
        self.safety = SafetyController(cfg)
        self.prom = PrometheusClient(cfg)
        self.abort = threading.Event()
        self._previous_handlers: dict = {}

    def _install_signals(self) -> None:
        def handler(signum, _frame):
            self.abort.set()
            self.k6.stop()
            self.store.event(self._run_id, f"received signal {signum}", "warn")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._previous_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, handler)
            except ValueError:
                # not in main thread
                pass

    def _restore_signals(self) -> None:
        for sig, prev in self._previous_handlers.items():
            try:
                signal.signal(sig, prev)
            except ValueError:
                pass

    def run_suite(self, suite_id: str) -> dict:
        if suite_id not in self.cfg.suites:
            raise EngineError(f"unknown suite: {suite_id}")
        suite = self.cfg.suites[suite_id]
        test_ids = suite.order or suite.tests
        tests = [self.cfg.tests[tid] for tid in test_ids]
        return self._execute(suite_id=suite_id, tests=tests, continue_on_failure=suite.continue_on_failure)

    def run_test(self, test_id: str) -> dict:
        if test_id not in self.cfg.tests:
            raise EngineError(f"unknown test: {test_id}")
        return self._execute(suite_id=None, tests=[self.cfg.tests[test_id]], continue_on_failure=False)

    def _execute(self, *, suite_id: str | None, tests: list[K6Test], continue_on_failure: bool) -> dict:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self._run_id = run_id
        artifacts = ArtifactStore(self.cfg.storage.results_dir, run_id)
        self.store.create(run_id, suite=suite_id, test=None if suite_id else tests[0].id, artifacts_dir=str(artifacts.root))
        if not self.lock.acquire(run_id):
            self.store.set_status(run_id, "failed", error="another run is in progress", force=True)
            raise EngineError("another run is in progress (max_concurrent_runs)")

        adapter = build_adapter(self.cfg)
        peaks = Sample()
        test_results: list[dict] = []
        maintenance_on = False
        snapshot_on = bool(self.cfg.database_snapshot.enabled)
        final_status = "completed"
        error = None
        db_counts_before: dict = {}
        db_counts_after: dict = {}
        self._install_signals()
        try:
            self.store.set_status(run_id, "preparing")
            artifacts.timeline("preflight", ts=utcnow())
            dumped = yaml.safe_load(self.cfg.model_dump_json())
            artifacts.write_yaml("resolved-config.yml", redact(dumped, self.cfg.redaction_keys))
            artifacts.write_json(
                "manifest.json",
                {"run_id": run_id, "suite": suite_id, "tests": [t.id for t in tests], "created_at": utcnow()},
            )

            conn = adapter.check_connection()
            artifacts.write_server("connection.txt", conn.detail)
            if not conn.ok:
                raise EngineError(f"SSH/target connection failed: {conn.detail}")

            if self.cfg.safety.abort_if_target_unreachable:
                health_url = self.cfg.health.test_url or (
                    self.cfg.target.traffic.test_base_url.rstrip("/") + self.cfg.target.traffic.health_path
                )
                if not _http_ok(health_url, self.cfg, public=False):
                    raise EngineError("target healthcheck failed before run")

            state = adapter.capture_state()
            artifacts.write_server("state-initial.json", json.dumps(state.data or {"raw": state.detail}, indent=2))

            if snapshot_on:
                self.store.set_status(run_id, "maintenance")
                # Snapshot DB before stub/window so restore returns to pre-test data.
                artifacts.timeline("backup_database", ts=utcnow())
                backup = adapter.backup_database()
                artifacts.write_server("db-backup.txt", backup.detail)
                if not backup.ok:
                    raise EngineError(f"backup_database failed: {backup.detail}")
                counts_before = adapter.database_row_counts()
                artifacts.write_server("db-counts-before.txt", counts_before.detail)
                if counts_before.ok and isinstance(counts_before.data, dict):
                    db_counts_before = {
                        k: v for k, v in counts_before.data.items() if isinstance(v, (int, float)) and k != "raw"
                    }
                    artifacts.write_json("db-counts-before.json", db_counts_before, under=artifacts.server)

            if self.cfg.maintenance.enabled:
                self.store.set_status(run_id, "maintenance")
                artifacts.timeline("enable_maintenance", ts=utcnow())
                enabled = adapter.enable_maintenance(ttl_seconds=self.cfg.maintenance.ttl_seconds)
                if not enabled.ok:
                    raise EngineError(f"enable_maintenance failed: {enabled.detail}")
                maintenance_on = True
                deadline = datetime.now(timezone.utc) + timedelta(seconds=self.cfg.maintenance.ttl_seconds)
                self.store.set_deadline(run_id, deadline.isoformat())
                verified = adapter.verify_maintenance()
                artifacts.write_server("maintenance-verify.txt", verified.detail)
                if not verified.ok:
                    raise EngineError(verified.detail)

            self.store.set_status(run_id, "running")
            monitor_stop = threading.Event()
            monitor_thread = threading.Thread(
                target=self._monitor_loop, args=(run_id, peaks, monitor_stop), daemon=True
            )
            monitor_thread.start()
            try:
                for test in tests:
                    if self.abort.is_set():
                        final_status = "aborted"
                        error = "aborted by signal or safety controller"
                        break
                    self.safety.validate_test(test)
                    missing = [item for item in test.required if not _required_present(item, self.cfg)]
                    if missing:
                        result = {"id": test.id, "status": "skipped", "error": f"missing required: {missing}", "stats": {}}
                        test_results.append(result)
                        self.store.add_test(run_id, test.id, "skipped", error=result["error"])
                        if not (continue_on_failure or test.continue_on_failure):
                            final_status = "failed"
                            error = result["error"]
                            break
                        continue
                    artifacts.timeline("test_start", ts=utcnow(), detail=test.id)
                    out_dir = artifacts.test_dir(test.id)
                    k6_result = self.k6.run(test, run_id, out_dir, abort_event=self.abort)
                    stats = stats_from_summary(k6_result.summary)
                    status = "passed" if k6_result.ok else "failed"
                    if k6_result.aborted:
                        status = "aborted"
                    err = None if k6_result.ok else (k6_result.stderr or f"k6 exit {k6_result.returncode}")
                    if not k6_result.ok and k6_result.returncode == 99:
                        err = "k6 threshold failure"
                    row = {
                        "id": test.id,
                        "status": status,
                        "duration": k6_result.duration_seconds,
                        "stats": stats,
                        "error": err,
                    }
                    test_results.append(row)
                    self.store.add_test(run_id, test.id, status, json.dumps(stats), err)
                    artifacts.timeline("test_end", ts=utcnow(), detail=f"{test.id}:{status}")
                    if status != "passed" and not (continue_on_failure or test.continue_on_failure):
                        final_status = "aborted" if status == "aborted" else "failed"
                        error = err
                        break
            finally:
                monitor_stop.set()
                monitor_thread.join(timeout=5)

            self.store.set_status(run_id, "collecting", force=True)
            diag = adapter.collect_diagnostics()
            for name, blob in (diag.data or {}).items():
                artifacts.write_server(f"{name}.txt", blob if isinstance(blob, str) else json.dumps(blob))
            if self.prom.enabled():
                sample = self.prom.sample()
                artifacts.write_json("metrics-final.json", sample.raw, under=artifacts.server)

            # Row counts after load (before restore) for report deltas.
            if snapshot_on:
                counts_after = adapter.database_row_counts()
                artifacts.write_server("db-counts-after.txt", counts_after.detail)
                if counts_after.ok and isinstance(counts_after.data, dict):
                    db_counts_after = {
                        k: v for k, v in counts_after.data.items() if isinstance(v, (int, float)) and k != "raw"
                    }
                    artifacts.write_json("db-counts-after.json", db_counts_after, under=artifacts.server)

        except SafetyViolation as exc:
            final_status = "aborted"
            error = exc.reason
            self.abort.set()
            self.k6.stop()
        except EngineError as exc:
            final_status = "failed"
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            final_status = "failed"
            error = f"unhandled: {exc}"
        finally:
            try:
                self.store.set_status(run_id, "cleanup", force=True)
                artifacts.timeline("cleanup", ts=utcnow())
                if snapshot_on:
                    artifacts.timeline("restore_database", ts=utcnow())
                    restored = adapter.restore_database()
                    artifacts.write_server("db-restore.txt", restored.detail)
                    if not restored.ok:
                        self.store.set_status(
                            run_id, "recovery_required", error=error or f"restore_database failed: {restored.detail}", force=True
                        )
                        final_status = "recovery_required"
                        error = error or f"restore_database failed: {restored.detail}"
                if maintenance_on or self.cfg.maintenance.enabled:
                    disabled = adapter.disable_maintenance()
                    artifacts.write_server("maintenance-disable.txt", disabled.detail)
                    live = adapter.verify_live()
                    artifacts.write_server("live-verify.txt", live.detail)
                    if not disabled.ok or not live.ok:
                        self.store.set_status(run_id, "recovery_required", error=error or "cleanup failed", force=True)
                        final_status = "recovery_required"
                        error = error or "maintenance cleanup failure"
                    else:
                        final_state = adapter.capture_state()
                        artifacts.write_server(
                            "state-final.json", json.dumps(final_state.data or {"raw": final_state.detail}, indent=2)
                        )
            except Exception as cleanup_exc:  # noqa: BLE001
                self.store.set_status(run_id, "recovery_required", error=str(cleanup_exc), force=True)
                final_status = "recovery_required"
                error = str(cleanup_exc)
            # Finalize status (incl. finished_at) before rendering reports.
            if final_status != "recovery_required":
                if self.abort.is_set() and final_status == "completed":
                    final_status = "aborted"
                self.store.set_status(run_id, final_status, error=error, force=True)
            run_snapshot = self.store.get(run_id) or {"id": run_id, "status": final_status, "error": error}
            db_delta = _db_count_delta(db_counts_before, db_counts_after)
            if db_delta.get("before") or db_delta.get("after") or db_delta.get("delta"):
                artifacts.write_json("db-snapshot.json", db_delta, under=artifacts.server)
            traffic = _traffic_totals(test_results)
            reports = generate_reports(
                artifacts,
                run_snapshot,
                test_results,
                {
                    "cpu": peaks.cpu,
                    "memory": peaks.memory,
                    "disk": peaks.disk,
                    "load": peaks.load,
                },
                self.cfg,
                traffic=traffic,
                db_snapshot=db_delta,
            )
            artifacts.write_json("report-index.json", reports)
            self.lock.release(run_id)
            self._restore_signals()
        return self.store.get(run_id) or {"id": run_id, "status": final_status, "error": error}

    def _monitor_loop(self, run_id: str, peaks: Sample, stop: threading.Event) -> None:
        started = time.time()
        max_duration = None
        try:
            max_duration = parse_duration(self.cfg.safety.max_test_duration)
        except ValueError:
            max_duration = None
        while not stop.is_set() and not self.abort.is_set():
            sample = self.prom.sample() if self.prom.enabled() else Sample()
            for attr in ("cpu", "memory", "disk", "network", "load"):
                val = getattr(sample, attr)
                cur = getattr(peaks, attr)
                if val is not None and (cur is None or val > cur):
                    setattr(peaks, attr, val)
            reachable = True
            if self.cfg.safety.abort_if_target_unreachable:
                health_url = self.cfg.health.test_url or (
                    self.cfg.target.traffic.test_base_url.rstrip("/") + self.cfg.target.traffic.health_path
                )
                reachable = _http_ok(health_url, self.cfg, public=False)
            decision = self.safety.evaluate_metrics(
                cpu=sample.cpu,
                memory=sample.memory,
                target_reachable=reachable,
                prometheus_ok=sample.ok if self.prom.enabled() else None,
                elapsed_seconds=time.time() - started,
                max_duration_seconds=max_duration,
            )
            if decision.abort:
                self.store.event(run_id, "safety abort: " + "; ".join(decision.reasons), "error")
                self.abort.set()
                self.k6.stop()
                break
            stop.wait(self.cfg.safety.poll_interval_seconds)

    def recover(self, run_id: str) -> dict:
        run = self.store.get(run_id)
        if not run:
            raise EngineError(f"unknown run {run_id}")
        adapter = build_adapter(self.cfg)
        artifacts = ArtifactStore(self.cfg.storage.results_dir, run_id)
        self.store.set_status(run_id, "cleanup", force=True)
        if self.cfg.database_snapshot.enabled:
            restored = adapter.restore_database()
            artifacts.write_server("recovery-restore.txt", restored.detail)
        else:
            restored = LifecycleResult(True, "restore skipped")
        disabled = adapter.disable_maintenance()
        artifacts.write_server("recovery-disable.txt", disabled.detail)
        live = adapter.verify_live()
        artifacts.write_server("recovery-live.txt", live.detail)
        if restored.ok and disabled.ok and live.ok:
            self.store.set_status(run_id, "completed", force=True)
        else:
            self.store.set_status(run_id, "recovery_required", error="recover failed", force=True)
        return self.store.get(run_id)


def _db_count_delta(before: dict, after: dict) -> dict:
    keys = sorted(set(before) | set(after))
    delta = {}
    for k in keys:
        b = before.get(k)
        a = after.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            delta[k] = int(a) - int(b)
        elif a is not None and b is None:
            delta[k] = a
    return {"before": before, "after": after, "delta": delta}


def _traffic_totals(tests: list[dict]) -> dict:
    http_reqs = 0
    for t in tests:
        n = (t.get("stats") or {}).get("http_reqs")
        if isinstance(n, (int, float)):
            http_reqs += int(n)
    return {"http_reqs": http_reqs, "tests": len(tests)}


def _http_ok(url: str, cfg: OrchestratorConfig, *, public: bool) -> bool:
    headers = probe_headers(cfg.target.traffic, public=public)
    try:
        resp = httpx.get(url, headers=headers, timeout=cfg.health.timeout_seconds)
        return 200 <= resp.status_code < 300
    except httpx.HTTPError:
        return False


def _required_present(item: str, cfg: OrchestratorConfig) -> bool:
    extra = cfg.extra or {}
    if item in extra and extra[item] not in (None, "", False):
        return True
    env_path = Path(os_env_get(item, ""))
    return bool(os_env_get(item)) or (env_path.is_file() if str(env_path) else False)


def os_env_get(name: str, default: str | None = None) -> str | None:
    import os

    return os.environ.get(name, default)
