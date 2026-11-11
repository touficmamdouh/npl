"""Local storage and period aggregation for per-process network usage."""

from __future__ import annotations

import sqlite3
import os
import fcntl
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ProcessUsage:
    source: str
    process_key: str
    name: str
    path: str | None
    pid: int | None
    session: str | None
    interface: str | None
    rx_bytes: int
    tx_bytes: int


@dataclass(frozen=True)
class UsageDelta:
    observed_at: datetime
    source: str
    process_key: str
    name: str
    path: str | None
    pid: int | None
    session: str | None
    interface: str | None
    rx_bytes: int
    tx_bytes: int


@dataclass(frozen=True)
class UsageTotal:
    process_key: str
    name: str
    path: str | None
    source: str
    rx_bytes: int
    tx_bytes: int
    total_bytes: int


class UsageRecorderLocked(RuntimeError):
    """Another recorder already owns this database."""


class UsageRecorderLock:
    def __init__(self, database: Path | str) -> None:
        database = Path(database)
        self.path = database.with_name(database.name + ".lock")
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise UsageRecorderLocked(
                f"another usage recorder is already using {self.path.parent}"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> "UsageRecorderLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


def _epoch(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def period_bounds(period: str, now: datetime | None = None) -> tuple[float, float]:
    """Return the local-calendar start and current end for a report period."""
    now = now or datetime.now()
    if period == "today":
        start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    elif period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"unsupported usage period: {period}")
    return start.timestamp(), now.timestamp()


class UsageStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS usage_samples (
                id INTEGER PRIMARY KEY,
                observed_at REAL NOT NULL,
                source TEXT NOT NULL,
                process_key TEXT NOT NULL,
                name TEXT NOT NULL,
                path TEXT,
                pid INTEGER,
                session TEXT,
                interface TEXT,
                rx_bytes INTEGER NOT NULL CHECK (rx_bytes >= 0),
                tx_bytes INTEGER NOT NULL CHECK (tx_bytes >= 0)
            );
            CREATE INDEX IF NOT EXISTS idx_usage_samples_time
                ON usage_samples (observed_at);
            CREATE INDEX IF NOT EXISTS idx_usage_samples_process
                ON usage_samples (process_key, observed_at);
            """
        )
        self.connection.commit()

    def record_deltas(self, deltas: Iterable[UsageDelta]) -> int:
        rows = []
        for item in deltas:
            rx_bytes = int(item.rx_bytes)
            tx_bytes = int(item.tx_bytes)
            if rx_bytes < 0 or tx_bytes < 0 or rx_bytes + tx_bytes == 0:
                continue
            rows.append(
                (
                    _epoch(item.observed_at),
                    item.source,
                    item.process_key,
                    item.name,
                    item.path,
                    item.pid,
                    item.session,
                    item.interface,
                    rx_bytes,
                    tx_bytes,
                )
            )
        if not rows:
            return 0
        self.connection.executemany(
            """
            INSERT INTO usage_samples (
                observed_at, source, process_key, name, path, pid, session,
                interface, rx_bytes, tx_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.connection.commit()
        return len(rows)

    def summarize(self, start: float, end: float, limit: int = 20) -> list[UsageTotal]:
        safe_limit = max(0, int(limit))
        if safe_limit == 0:
            return []
        start_value = _epoch(start) if isinstance(start, datetime) else float(start)
        end_value = _epoch(end) if isinstance(end, datetime) else float(end)
        rows = self.connection.execute(
            """
            SELECT MIN(process_key) AS process_key, name, path,
                   MAX(source) AS source,
                   SUM(rx_bytes) AS rx_bytes, SUM(tx_bytes) AS tx_bytes
            FROM usage_samples
            WHERE observed_at >= ? AND observed_at < ?
            GROUP BY name, path
            ORDER BY (SUM(rx_bytes) + SUM(tx_bytes)) DESC, name ASC
            LIMIT ?
            """,
            (start_value, end_value, safe_limit),
        ).fetchall()
        return [
            UsageTotal(
                process_key=row["process_key"],
                name=row["name"],
                path=row["path"],
                source=row["source"],
                rx_bytes=int(row["rx_bytes"]),
                tx_bytes=int(row["tx_bytes"]),
                total_bytes=int(row["rx_bytes"] + row["tx_bytes"]),
            )
            for row in rows
        ]

    def period_total(self, start: float, end: float) -> int:
        start_value = _epoch(start) if isinstance(start, datetime) else float(start)
        end_value = _epoch(end) if isinstance(end, datetime) else float(end)
        row = self.connection.execute(
            """
            SELECT COALESCE(SUM(rx_bytes + tx_bytes), 0) AS total_bytes
            FROM usage_samples
            WHERE observed_at >= ? AND observed_at < ?
            """,
            (start_value, end_value),
        ).fetchone()
        return int(row["total_bytes"])

    def prune(self, before: datetime | float) -> int:
        cutoff = _epoch(before) if isinstance(before, datetime) else float(before)
        cursor = self.connection.execute(
            "DELETE FROM usage_samples WHERE observed_at < ?", (cutoff,)
        )
        self.connection.commit()
        return cursor.rowcount

    def first_observed_at(self) -> datetime | None:
        row = self.connection.execute(
            "SELECT MIN(observed_at) AS observed_at FROM usage_samples"
        ).fetchone()
        if row is None or row["observed_at"] is None:
            return None
        return datetime.fromtimestamp(float(row["observed_at"]), timezone.utc)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "UsageStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

