import pytest

from orchestrator.storage.db import Database
from orchestrator.storage.runs import InvalidTransition, RunStore


def test_transitions(tmp_path):
    store = RunStore(Database(str(tmp_path / "db.sqlite")))
    store.create("r1", suite="smoke", test=None, artifacts_dir="/tmp")
    store.set_status("r1", "preparing")
    store.set_status("r1", "maintenance")
    store.set_status("r1", "running")
    store.set_status("r1", "collecting")
    store.set_status("r1", "cleanup")
    store.set_status("r1", "completed")
    with pytest.raises(InvalidTransition):
        store.set_status("r1", "running")


def test_force_recovery(tmp_path):
    store = RunStore(Database(str(tmp_path / "db.sqlite")))
    store.create("r1", suite="smoke", test=None, artifacts_dir="/tmp")
    store.set_status("r1", "recovery_required", force=True)
    assert store.get("r1")["status"] == "recovery_required"
