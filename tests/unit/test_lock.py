from orchestrator.storage.db import Database
from orchestrator.storage.locks import RunLock


def test_lock_release(tmp_path):
    db = Database(str(tmp_path / "l.db"))
    lock = RunLock(db)
    assert lock.acquire("a")
    assert lock.acquire("b") is False
    lock.release("a")
    assert lock.acquire("b")
