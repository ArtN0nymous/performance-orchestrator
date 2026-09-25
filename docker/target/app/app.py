from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

import psycopg
from flask import Flask, g, jsonify, request

app = Flask(__name__)
DB_DSN = os.environ.get("DATABASE_URL", "postgresql://perf:perf@target-db:5432/perf")
MAINT_FILE = os.environ.get("MAINTENANCE_FLAG", "/var/run/maintenance")
TOKENS: dict[str, str] = {}
lock = threading.Lock()


def db():
    if "db" not in g:
        g.db = psycopg.connect(DB_DSN, autocommit=True)
    return g.db


@app.teardown_appcontext
def close_db(_err):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    for _ in range(30):
        try:
            with psycopg.connect(DB_DSN, autocommit=True) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS items (
                      id SERIAL PRIMARY KEY,
                      name TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS payments (
                      id SERIAL PRIMARY KEY,
                      amount_cents INTEGER NOT NULL,
                      status TEXT NOT NULL,
                      idempotency_key TEXT UNIQUE,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS webhooks (
                      id SERIAL PRIMARY KEY,
                      event_id TEXT,
                      payload JSONB,
                      received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("database unavailable")


def maintenance_active() -> bool:
    return os.path.exists(MAINT_FILE)


@app.before_request
def maybe_block_public():
    if request.path in ("/health", "/ready", "/metrics", "/maintenance"):
        return None
    # Test traffic uses a dedicated port (handled by nginx). App itself stays live.


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/ready")
def ready():
    try:
        db().execute("SELECT 1")
        return jsonify({"status": "ready"})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "not-ready", "error": str(exc)}), 503


@app.get("/maintenance")
def maintenance_status():
    return jsonify({"maintenance": maintenance_active()})


@app.get("/metrics")
def metrics():
    # Minimal Prometheus text for local safety queries.
    return (
        "# HELP fixture_up 1 if process is running\n"
        "# TYPE fixture_up gauge\n"
        "fixture_up 1\n",
        200,
        {"Content-Type": "text/plain; version=0.0.4"},
    )


@app.post("/auth/login")
def login():
    body = request.get_json(force=True, silent=True) or {}
    if body.get("username") != "tester" or body.get("password") != "tester":
        return jsonify({"error": "invalid credentials"}), 401
    token = "lab-" + os.urandom(8).hex()
    with lock:
        TOKENS[token] = body["username"]
    return jsonify({"token": token})


def _auth():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header.split(" ", 1)[1]
    return TOKENS.get(token)


@app.get("/items")
def list_items():
    if not _auth():
        return jsonify({"error": "unauthorized"}), 401
    rows = db().execute("SELECT id, name, created_at FROM items ORDER BY id DESC LIMIT 50").fetchall()
    return jsonify({"items": [{"id": r[0], "name": r[1], "created_at": r[2].isoformat()} for r in rows]})


@app.post("/items")
def create_item():
    if not _auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(force=True, silent=True) or {}
    name = body.get("name") or "item"
    row = db().execute("INSERT INTO items (name) VALUES (%s) RETURNING id", (name,)).fetchone()
    return jsonify({"id": row[0], "name": name}), 201


@app.get("/slow")
def slow():
    delay = min(float(request.args.get("delay_ms", "500")), 5000) / 1000.0
    time.sleep(delay)
    return jsonify({"delayed_ms": delay * 1000})


@app.get("/error")
def error():
    return jsonify({"error": "intentional"}), 500


@app.post("/payments")
def payments():
    if not _auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(force=True, silent=True) or {}
    scenario = request.headers.get("X-Payment-Scenario") or body.get("scenario") or "success"
    amount = int(body.get("amount_cents") or 500)
    key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    mock = os.environ.get("PAYMENT_MOCK_URL", "http://payment-mock:8090")
    if scenario == "timeout":
        time.sleep(float(os.environ.get("PAYMENT_TIMEOUT_SLEEP", "8")))
        return jsonify({"error": "timeout"}), 504
    if scenario == "slow":
        time.sleep(2)
    if scenario == "network":
        return jsonify({"error": "network failure"}), 502
    if scenario == "500":
        return jsonify({"error": "payment provider 500"}), 500
    if scenario == "decline":
        status = "declined"
        code = 402
    else:
        status = "succeeded"
        code = 200
    if key:
        existing = db().execute("SELECT id, status FROM payments WHERE idempotency_key=%s", (key,)).fetchone()
        if existing:
            return jsonify({"id": existing[0], "status": existing[1], "idempotent_replay": True})
    row = db().execute(
        "INSERT INTO payments (amount_cents, status, idempotency_key) VALUES (%s,%s,%s) RETURNING id",
        (amount, status, key),
    ).fetchone()
    # Best-effort call to mock (sandbox only).
    try:
        import urllib.request

        req = urllib.request.Request(
            mock + "/charge",
            data=json.dumps({"amount": amount, "scenario": scenario}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass
    return jsonify({"id": row[0], "status": status, "amount_cents": amount}), code if status != "succeeded" else 200


@app.post("/webhooks/payment")
def webhook():
    payload = request.get_json(force=True, silent=True) or {}
    event_id = payload.get("id") or request.headers.get("X-Event-Id")
    delayed = request.args.get("delay") == "1" or payload.get("delayed")
    if delayed:
        time.sleep(1)
    db().execute(
        "INSERT INTO webhooks (event_id, payload) VALUES (%s, %s::jsonb)",
        (event_id, json.dumps(payload)),
    )
    count = db().execute("SELECT count(*) FROM webhooks WHERE event_id=%s", (event_id,)).fetchone()[0]
    return jsonify({"received": True, "duplicates": int(count) > 1, "at": datetime.now(timezone.utc).isoformat()})


def main():
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), threaded=True)


init_db()

if __name__ == "__main__":
    main()
