"""Durable store-and-forward buffer (SQLite, WAL) for uplink outages."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


class StoreForwardBuffer:
    """FIFO of (topic, key, value) records that survives restarts.

    Records older than ``max_age_s`` (default 72 h) are dropped and counted.
    """

    def __init__(self, path: str | Path = ":memory:", max_age_s: int = 72 * 3600, max_rows: int = 5_000_000):
        self.path = str(path)
        self.max_age_s = max_age_s
        self.max_rows = max_rows
        self.dropped = 0
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS buf (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, topic TEXT, k BLOB, v BLOB)"
        )

    def put(self, topic: str, key: bytes, value: bytes) -> None:
        with self._lock:
            self._db.execute("INSERT INTO buf (ts, topic, k, v) VALUES (?,?,?,?)", (time.time(), topic, key, value))
            n = self._db.execute("SELECT COUNT(*) FROM buf").fetchone()[0]
            if n > self.max_rows:
                excess = n - self.max_rows
                self._db.execute("DELETE FROM buf WHERE id IN (SELECT id FROM buf ORDER BY id LIMIT ?)", (excess,))
                self.dropped += excess

    def peek(self, limit: int = 500) -> list[tuple[int, str, bytes, bytes]]:
        self._expire()
        with self._lock:
            return self._db.execute("SELECT id, topic, k, v FROM buf ORDER BY id LIMIT ?", (limit,)).fetchall()

    def ack(self, up_to_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM buf WHERE id <= ?", (up_to_id,))

    def __len__(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM buf").fetchone()[0]

    def _expire(self) -> None:
        cutoff = time.time() - self.max_age_s
        with self._lock:
            cur = self._db.execute("DELETE FROM buf WHERE ts < ?", (cutoff,))
            self.dropped += cur.rowcount or 0
