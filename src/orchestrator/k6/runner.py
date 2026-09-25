from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.config.models import OrchestratorConfig, K6Test


class K6Error(Exception):
    def __init__(self, message: str, returncode: int = 1, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@dataclass
class K6Result:
    returncode: int
    stdout: str
    stderr: str
    summary: dict = field(default_factory=dict)
    duration_seconds: float = 0.0
    aborted: bool = False

    @property
    def ok(self) -> bool:
        if self.aborted:
            return False
        if self.returncode == 0:
            return True
        if self.returncode == 99:
            return False
        if self.returncode == 1 and self.summary:
            failed = (
                ((self.summary.get("metrics") or {}).get("http_req_failed") or {}).get("values") or {}
            ).get("rate")
            if failed in (0, 0.0, None):
                return True
        return False


class K6Runner:
    def __init__(self, cfg: OrchestratorConfig):
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def env_for(self, test: K6Test, run_id: str, out_dir: Path) -> dict[str, str]:
        env = os.environ.copy()
        traffic = self.cfg.target.traffic
        env.update(
            {
                "K6_RUN_ID": run_id,
                "TESTID": run_id,
                "BASE_URL": traffic.test_base_url,
                "PUBLIC_BASE_URL": traffic.public_base_url,
                "K6_OUT_DIR": str(out_dir),
                "K6_WEB_DASHBOARD": "false",
            }
        )
        if traffic.bypass_header_name and traffic.bypass_header_value:
            env["BYPASS_HEADER_NAME"] = traffic.bypass_header_name
            env["BYPASS_HEADER_VALUE"] = traffic.bypass_header_value
        if test.params.vus is not None:
            env["VUS"] = str(test.params.vus)
        if test.duration or test.params.duration:
            env["DURATION"] = test.duration or test.params.duration or ""
        if test.params.iterations is not None:
            env["ITERATIONS"] = str(test.params.iterations)
        if test.params.rate:
            env["RATE"] = str(test.params.rate)
        if test.params.stages:
            env["STAGES_JSON"] = json.dumps(test.params.stages)
        env["THRESHOLDS_JSON"] = json.dumps(test.thresholds.as_k6_map())
        env["EXECUTOR"] = test.params.executor
        influx = self.cfg.storage.influx
        if influx.enabled and influx.url:
            env["K6_INFLUXDB_ORGANIZATION"] = influx.org or ""
            env["K6_INFLUXDB_BUCKET"] = influx.bucket or ""
            env["K6_INFLUXDB_TOKEN"] = influx.token or ""
            env["K6_INFLUXDB_ADDR"] = influx.url
        env.update(test.env)
        extra = self.cfg.extra or {}
        for key, value in extra.items():
            if isinstance(value, (str, int, float)):
                env.setdefault(str(key).upper(), str(value))
        return env

    def build_cmd(self, test: K6Test, run_id: str, out_dir: Path) -> list[str]:
        script = Path(self.cfg.k6_root) / test.script
        summary = out_dir / "summary.json"
        cmd = [
            self.cfg.k6_bin,
            "run",
            "--tag",
            f"testid={run_id}",
            "--tag",
            f"run_id={run_id}",
            "--tag",
            f"test={test.id}",
            "--summary-export",
            str(summary),
        ]
        # Optional raw JSON stream (can be hundreds of MB and is not required for reports).
        if os.environ.get("K6_RAW_JSON_METRICS", "").strip() in {"1", "true", "yes"}:
            cmd.extend(["--out", f"json={out_dir / 'metrics.json'}"])
        influx = self.cfg.storage.influx
        if influx.enabled and influx.url:
            outputs = self._available_outputs()
            if "xk6-influxdb" in outputs:
                cmd.extend(["--out", f"xk6-influxdb={influx.url}"])
        cmd.append(str(script))
        return cmd

    def _available_outputs(self) -> set[str]:
        cached = getattr(self, "_outputs", None)
        if cached is not None:
            return cached
        try:
            proc = subprocess.run(
                [self.cfg.k6_bin, "run", "--out", "__probe__", "-"],
                input="export default function () {}",
                capture_output=True,
                text=True,
                timeout=10,
            )
            text = (proc.stderr or "") + (proc.stdout or "")
            marker = "available types are:"
            if marker in text:
                types = text.split(marker, 1)[1].split("\n", 1)[0]
                self._outputs = {t.strip() for t in types.replace('"', "").split(",") if t.strip()}
            else:
                self._outputs = {"json"}
        except (OSError, subprocess.TimeoutExpired):
            self._outputs = {"json"}
        return self._outputs

    def run(self, test: K6Test, run_id: str, out_dir: Path, abort_event: threading.Event | None = None) -> K6Result:
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.build_cmd(test, run_id, out_dir)
        env = self.env_for(test, run_id, out_dir)
        started = time.time()
        stdout_path = out_dir / "stdout.log"
        stderr_path = out_dir / "stderr.log"
        # Stream to files (not PIPE): k6 progress floods stdout and can deadlock the parent.
        with stdout_path.open("w", encoding="utf-8") as stdout_f, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_f:
            with self._lock:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=stdout_f,
                    stderr=stderr_f,
                    text=True,
                    env=env,
                    start_new_session=True,
                )
                proc = self._proc
            aborted = False
            try:
                while True:
                    if abort_event and abort_event.is_set():
                        aborted = True
                        self.stop()
                        break
                    ret = proc.poll()
                    if ret is not None:
                        break
                    time.sleep(0.2)
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    self.stop()
                    proc.wait(timeout=30)
                    aborted = True
            except Exception:
                self.stop()
                aborted = True
                raise
        duration = time.time() - started
        summary: dict = {}
        summary_path = out_dir / "summary.json"
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                summary = {}
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
        return K6Result(proc.returncode or (130 if aborted else 1), stdout, stderr, summary, duration, aborted)

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
        if not proc or proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGINT)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
