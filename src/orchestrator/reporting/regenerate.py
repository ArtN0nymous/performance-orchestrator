from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.artifacts.store import ArtifactStore
from orchestrator.reporting.generate import generate_reports, stats_from_summary


def regenerate_run_report(cfg, run: dict[str, Any], store) -> dict[str, str]:
    """Rebuild report artifacts from per-test k6 summary.json files."""
    artifacts_dir = Path(run["artifacts_dir"])
    if not artifacts_dir.is_dir():
        raise FileNotFoundError(f"artifacts_dir missing: {artifacts_dir}")

    run_id = run["id"]
    prev_by_id: dict[str, dict[str, Any]] = {}
    summary_path = artifacts_dir / "summary.json"
    peaks: dict[str, Any] = {"cpu": None, "memory": None, "disk": None, "load": None}
    if summary_path.exists():
        try:
            prev = json.loads(summary_path.read_text(encoding="utf-8"))
            peaks = prev.get("peaks") or peaks
            for t in prev.get("tests") or []:
                if t.get("id"):
                    prev_by_id[t["id"]] = t
        except json.JSONDecodeError:
            pass

    # Prefer a coherent finished status when regenerating an already-done run.
    run_out = dict(run)
    if not run_out.get("finished_at") and run_out.get("status") in {"completed", "failed", "aborted"}:
        run_out["finished_at"] = run_out.get("updated_at")

    stored_tests = store.tests(run_id)
    test_results: list[dict[str, Any]] = []
    for row in stored_tests:
        test_id = row["test_id"]
        k6_summary_path = artifacts_dir / "tests" / test_id / "summary.json"
        stats: dict[str, Any] = {}
        if k6_summary_path.exists():
            summary = json.loads(k6_summary_path.read_text(encoding="utf-8"))
            stats = stats_from_summary(summary)
        elif row.get("summary_json"):
            try:
                stats = json.loads(row["summary_json"])
            except json.JSONDecodeError:
                stats = {}
        duration = (prev_by_id.get(test_id) or {}).get("duration")
        test_results.append(
            {
                "id": test_id,
                "status": row["status"],
                "duration": duration,
                "stats": stats,
                "error": row.get("error"),
            }
        )

    artifacts = ArtifactStore(str(artifacts_dir.parent), run_id)
    db_snapshot: dict[str, Any] = {}
    snap_path = artifacts_dir / "server" / "db-snapshot.json"
    if snap_path.exists():
        try:
            db_snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            db_snapshot = {}
    elif summary_path.exists():
        try:
            prev = json.loads(summary_path.read_text(encoding="utf-8"))
            db_snapshot = prev.get("db_snapshot") or {}
        except json.JSONDecodeError:
            pass
    paths = generate_reports(
        artifacts,
        run_out,
        test_results,
        peaks,
        cfg,
        db_snapshot=db_snapshot,
    )
    artifacts.write_json("report-index.json", paths)
    return paths
