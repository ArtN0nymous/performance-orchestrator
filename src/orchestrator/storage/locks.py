from __future__ import annotations

from orchestrator.storage.db import Database
from orchestrator.storage.runs import utcnow


class RunLock:
    def __init__(self, db: Database, name: str = "orchestrator", max_concurrent: int = 1):
        self.db = db
        self.name = name
        self.max_concurrent = max_concurrent
        self._held = False

    def acquire(self, holder: str) -> bool:
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        with self.db.exclusive() as conn:
            row = conn.execute("SELECT holder FROM locks WHERE name=?", (self.name,)).fetchone()
            if row:
                return False
            conn.execute(
                "INSERT INTO locks (name, holder, acquired_at) VALUES (?, ?, ?)",
                (self.name, holder, utcnow()),
            )
            self._held = True
            return True

    def release(self, holder: str | None = None) -> None:
        with self.db.exclusive() as conn:
            if holder:
                conn.execute("DELETE FROM locks WHERE name=? AND holder=?", (self.name, holder))
            else:
                conn.execute("DELETE FROM locks WHERE name=?", (self.name,))
        self._held = False

    def holder(self) -> str | None:
        row = self.db.connect().execute("SELECT holder FROM locks WHERE name=?", (self.name,)).fetchone()
        return row["holder"] if row else None
