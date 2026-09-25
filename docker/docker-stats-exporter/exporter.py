#!/usr/bin/env python3
"""Expose Docker container CPU / memory for Prometheus (Docker Desktop friendly)."""

from __future__ import annotations

import concurrent.futures
import http.client
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOCKET_PATH = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
LISTEN = os.environ.get("LISTEN", "0.0.0.0:9101")
SCRAPE_INTERVAL = float(os.environ.get("SCRAPE_INTERVAL", "5"))
NAME_FILTER = os.environ.get("NAME_FILTER", "")  # substring; empty = all
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "8"))

_cache: dict[str, float | str] = {"body": "", "ts": 0.0}


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, sock_path: str, timeout: float = 12.0):
        super().__init__("localhost", timeout=timeout)
        self.sock_path = sock_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.sock_path)
        self.sock = sock


def _docker(path: str, timeout: float = 12.0) -> dict | list:
    conn = UnixHTTPConnection(SOCKET_PATH, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read()
        if resp.status != 200:
            raise RuntimeError(f"Docker API {resp.status} for {path}: {raw[:200]!r}")
        return json.loads(raw.decode())
    finally:
        conn.close()


def _cpu_ratio(stats: dict) -> float | None:
    try:
        cpu = stats["cpu_stats"]
        precpu = stats["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
        system_delta = cpu["system_cpu_usage"] - precpu["system_cpu_usage"]
        online = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or [1])
        if system_delta <= 0 or cpu_delta < 0:
            return None
        return (cpu_delta / system_delta) * online
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def _memory_bytes(stats: dict) -> float | None:
    try:
        usage = float(stats["memory_stats"]["usage"])
        cache = float(stats["memory_stats"].get("stats", {}).get("cache", 0) or 0)
        return max(0.0, usage - cache)
    except (KeyError, TypeError, ValueError):
        return None


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _one(c: dict) -> list[str]:
    names = c.get("Names") or []
    name = (names[0] if names else c.get("Id", "")[:12]).lstrip("/")
    if NAME_FILTER and NAME_FILTER not in name:
        return []
    try:
        stats = _docker(f"/containers/{c['Id']}/stats?stream=false", timeout=15.0)
    except Exception:
        return []
    cpu = _cpu_ratio(stats)
    mem = _memory_bytes(stats)
    label = f'name="{_escape(name)}"'
    out: list[str] = []
    if cpu is not None:
        out.append(f"docker_container_cpu_cores{{{label}}} {cpu}")
    if mem is not None:
        out.append(f"docker_container_memory_working_set_bytes{{{label}}} {mem}")
    return out


def collect() -> str:
    containers = _docker("/containers/json")
    lines = [
        "# HELP docker_container_cpu_cores Approximate CPU cores used (docker stats).",
        "# TYPE docker_container_cpu_cores gauge",
        "# HELP docker_container_memory_working_set_bytes Working set memory bytes.",
        "# TYPE docker_container_memory_working_set_bytes gauge",
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for part in pool.map(_one, containers):
            lines.extend(part)
    lines.append("")
    return "\n".join(lines)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        now = time.time()
        if now - float(_cache["ts"]) >= SCRAPE_INTERVAL or not _cache["body"]:
            try:
                _cache["body"] = collect()
                _cache["ts"] = now
            except Exception as exc:  # noqa: BLE001
                body = f"# exporter_error {exc}\n"
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode())
                return
        body = str(_cache["body"]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host, _, port_s = LISTEN.partition(":")
    server = ThreadingHTTPServer((host or "0.0.0.0", int(port_s or "9101")), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
