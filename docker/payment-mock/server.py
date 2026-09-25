from __future__ import annotations

import json
import os
import time
from flask import Flask, jsonify, request

app = Flask(__name__)
CHARGES = []


@app.get("/health")
def health():
    return jsonify({"status": "ok", "sandbox": True})


@app.post("/charge")
def charge():
    body = request.get_json(force=True, silent=True) or {}
    scenario = body.get("scenario") or request.headers.get("X-Payment-Scenario") or "success"
    if scenario == "timeout":
        time.sleep(float(os.environ.get("MOCK_TIMEOUT_SECONDS", "6")))
        return jsonify({"error": "timeout"}), 504
    if scenario == "slow":
        time.sleep(2)
    if scenario == "500":
        return jsonify({"error": "upstream 500"}), 500
    if scenario == "network":
        return jsonify({"error": "connection reset"}), 502
    if scenario == "decline":
        rec = {"status": "declined", "sandbox": True}
        CHARGES.append(rec)
        return jsonify(rec), 402
    rec = {"status": "succeeded", "sandbox": True, "id": f"ch_lab_{len(CHARGES)+1}"}
    CHARGES.append(rec)
    return jsonify(rec)


@app.post("/webhooks/replay")
def replay():
    body = request.get_json(force=True, silent=True) or {}
    return jsonify({"replayed": True, "event": body, "sandbox": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8090")))
