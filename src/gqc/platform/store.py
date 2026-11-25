"""A versioned key-value store with optimistic concurrency: a transaction records the version of every key it
read and commits only if none of them changed since. Two backends: memory (the lab) and SQLite (the service)."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol

Key = tuple[str, str]


class Conflict(RuntimeError):
    """A key read by the transaction changed before it committed. Read again and retry."""


class Store(Protocol):
    def read(self, table: str, key: str) -> tuple[int, Any]: ...
    def scan(self, table: str) -> list[tuple[str, int, Any]]: ...
    def commit(self, reads: dict[Key, int], writes: dict[Key, Any]) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self._data: dict[Key, tuple[int, Any]] = {}
        self._lock = threading.Lock()

    def read(self, table: str, key: str) -> tuple[int, Any]:
        with self._lock:
            v, val = self._data.get((table, key), (0, None))
            return v, copy.deepcopy(val)

    def scan(self, table: str) -> list[tuple[str, int, Any]]:
        with self._lock:
            return sorted((k, v, copy.deepcopy(val)) for (t, k), (v, val) in self._data.items() if t == table and val is not None)

    def commit(self, reads: dict[Key, int], writes: dict[Key, Any]) -> None:
        with self._lock:
            for k, ver in reads.items():
                if self._data.get(k, (0, None))[0] != ver:
                    raise Conflict(f"{k} changed")
            for k, val in writes.items():
                self._data[k] = (self._data.get(k, (0, None))[0] + 1, copy.deepcopy(val))


class SQLiteStore:
    """One connection per thread; BEGIN IMMEDIATE makes the version check and the writes one atomic step."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._local = threading.local()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS kv (tbl TEXT, key TEXT, version INTEGER, value TEXT, PRIMARY KEY (tbl, key))")

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.execute("PRAGMA journal_mode=WAL")
            self._local.conn = c
        return c

    def read(self, table: str, key: str) -> tuple[int, Any]:
        row = self._conn().execute("SELECT version, value FROM kv WHERE tbl=? AND key=?", (table, key)).fetchone()
        return (0, None) if row is None else (int(row[0]), json.loads(row[1]))

    def scan(self, table: str) -> list[tuple[str, int, Any]]:
        rows = self._conn().execute("SELECT key, version, value FROM kv WHERE tbl=? ORDER BY key", (table,)).fetchall()
        return [(k, int(v), json.loads(val)) for k, v, val in rows if val != "null"]

    def commit(self, reads: dict[Key, int], writes: dict[Key, Any]) -> None:
        c = self._conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            for (t, k), ver in reads.items():
                row = c.execute("SELECT version FROM kv WHERE tbl=? AND key=?", (t, k)).fetchone()
                if (0 if row is None else int(row[0])) != ver:
                    raise Conflict(f"{(t, k)} changed")
            for (t, k), val in writes.items():
                c.execute(
                    "INSERT INTO kv (tbl, key, version, value) VALUES (?, ?, 1, ?) ON CONFLICT (tbl, key) DO UPDATE SET version = version + 1, value = excluded.value",
                    (t, k, json.dumps(val, sort_keys=True)),
                )
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise


class Tx:
    """Reads see the transaction's own writes. cas=False drops the version check (the lab's broken variant)."""

    def __init__(self, store: Store, cas: bool = True) -> None:
        self.store = store
        self.cas = cas
        self.reads: dict[Key, int] = {}
        self.writes: dict[Key, Any] = {}

    def get(self, table: str, key: str) -> Any:
        if (table, key) in self.writes:
            return copy.deepcopy(self.writes[(table, key)])
        v, val = self.store.read(table, key)
        self.reads.setdefault((table, key), v)
        return val

    def put(self, table: str, key: str, value: Any) -> None:
        self.writes[(table, key)] = copy.deepcopy(value)

    def commit(self) -> None:
        self.store.commit(self.reads if self.cas else {}, self.writes)
