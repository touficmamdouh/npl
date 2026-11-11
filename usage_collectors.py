"""Per-process network usage collectors for Linux and macOS."""

from __future__ import annotations

import csv
import math
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from usage_store import UsageDelta


class CollectorUnavailable(RuntimeError):
    """The platform collector cannot run with the current system setup."""


@dataclass(frozen=True)
class CumulativeProcessUsage:
    source: str
    process_key: str
    name: str
    path: str | None
    pid: int | None
    session: str | None
    interface: str | None
    rx_bytes: int
    tx_bytes: int


_NUMBER = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$")
_NETHOGS_IDENTITY = re.compile(r"^(?P<path>.+)/(?P<pid>\d+)/(?P<uid>\d+)$")
_MAX_COUNTER = 2**63 - 1


def _parse_bytes(value: str) -> int | None:
    value = value.strip()
    if not _NUMBER.match(value) and not re.match(
        r"^-?(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d+$", value
    ):
        return None
    try:
        parsed = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed < 0 or parsed > _MAX_COUNTER:
        return None
    return int(parsed)


def _name_from_identity(identity: str) -> tuple[str, str | None, int | None, str | None]:
    match = _NETHOGS_IDENTITY.match(identity)
    if match:
        path = match.group("path")
        pid = int(match.group("pid"))
        return Path(path).name or path, path, pid, f"{pid}:{match.group('uid')}"
    name = identity.split()[0] if identity.split() else "unknown"
    return name, None, None, None


def parse_nethogs_trace(text: str) -> list[CumulativeProcessUsage]:
    """Parse nethogs ``-t -v 2`` rows, whose numeric columns are sent/received."""
    rows: list[CumulativeProcessUsage] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        sent = _parse_bytes(parts[-2])
        received = _parse_bytes(parts[-1])
        if sent is None or received is None:
            continue
        identity = " ".join(parts[:-2])
        name, path, pid, session = _name_from_identity(identity)
        process_key = f"{path}:{pid}" if path and pid is not None else identity
        rows.append(
            CumulativeProcessUsage(
                source="nethogs",
                process_key=process_key or "unknown",
                name=name,
                path=path,
                pid=pid,
                session=session,
                interface=None,
                rx_bytes=received,
                tx_bytes=sent,
            )
        )
    return rows


def parse_nettop(text: str) -> list[CumulativeProcessUsage]:
    """Parse the final CSV sample emitted by macOS nettop."""
    lines = text.splitlines()
    header_index = -1
    for index, line in enumerate(lines):
        if "bytes_in" in line and "bytes_out" in line:
            header_index = index
    if header_index < 0:
        return []

    rows: list[CumulativeProcessUsage] = []
    for raw_line in lines[header_index + 1 :]:
        parts = [part.strip() for part in next(csv.reader([raw_line]), [])]
        while parts and not parts[-1]:
            parts.pop()
        if len(parts) < 3:
            continue
        process_id, rx_text, tx_text = [part.strip() for part in parts[-3:]]
        rx_bytes = _parse_bytes(rx_text)
        tx_bytes = _parse_bytes(tx_text)
        if rx_bytes is None or tx_bytes is None:
            continue
        name, separator, pid_text = process_id.rpartition(".")
        if not separator or not pid_text.isdigit() or not name:
            continue
        pid = int(pid_text)
        rows.append(
            CumulativeProcessUsage(
                source="nettop",
                process_key=f"{name}:{pid}",
                name=name,
                path=None,
                pid=pid,
                session=str(pid),
                interface=None,
                rx_bytes=rx_bytes,
                tx_bytes=tx_bytes,
            )
        )
    return rows


class DeltaTracker:
    def __init__(self) -> None:
        self._baselines: dict[tuple[str, str | None], tuple[int, int]] = {}

    def update(
        self,
        cumulative_rows: Iterable[CumulativeProcessUsage],
        observed_at: datetime,
    ) -> list[UsageDelta]:
        deltas: list[UsageDelta] = []
        current_keys: set[tuple[str, str | None]] = set()
        for row in cumulative_rows:
            if row.rx_bytes < 0 or row.tx_bytes < 0:
                continue
            key = (row.process_key, row.session)
            current_keys.add(key)
            previous = self._baselines.get(key)
            self._baselines[key] = (row.rx_bytes, row.tx_bytes)
            if previous is None:
                continue
            previous_rx, previous_tx = previous
            if row.rx_bytes < previous_rx or row.tx_bytes < previous_tx:
                continue
            rx_delta = row.rx_bytes - previous_rx
            tx_delta = row.tx_bytes - previous_tx
            if rx_delta + tx_delta == 0:
                continue
            deltas.append(
                UsageDelta(
                    observed_at=observed_at,
                    source=row.source,
                    process_key=row.process_key,
                    name=row.name,
                    path=row.path,
                    pid=row.pid,
                    session=row.session,
                    interface=row.interface,
                    rx_bytes=rx_delta,
                    tx_bytes=tx_delta,
                )
            )
        for key in set(self._baselines) - current_keys:
            del self._baselines[key]
        return deltas


class _CommandCollector:
    source = "unknown"

    def __init__(self, interval: float = 5.0) -> None:
        self.interval = max(1.0, float(interval))

    def _run(self, args: Sequence[str], timeout: float) -> str:
        try:
            result = subprocess.run(
                list(args),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CollectorUnavailable(
                f"{args[0]} is not installed; install it before recording usage"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CollectorUnavailable(f"{args[0]} timed out while collecting usage") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "permission denied").strip()
            raise CollectorUnavailable(
                f"{args[0]} could not capture process usage: {detail}"
            )
        return result.stdout

    def close(self) -> None:
        return None


class NethogsCollector(_CommandCollector):
    source = "nethogs"

    def __init__(self, interval: float = 5.0) -> None:
        super().__init__(interval)
        self._process: subprocess.Popen[str] | None = None
        self._started_refresh = False
        self._refresh_lines: list[str] = []

    def collect(self) -> list[CumulativeProcessUsage]:
        delay = max(1, round(self.interval))
        if self._process is None:
            try:
                self._process = subprocess.Popen(
                    ["nethogs", "-t", "-v", "2", "-C", "-d", str(delay)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except FileNotFoundError as exc:
                raise CollectorUnavailable(
                    "nethogs is not installed; install it before recording usage"
                ) from exc
        assert self._process.stdout is not None
        while True:
            line = self._process.stdout.readline()
            if not line:
                returncode = self._process.poll()
                self.close()
                if returncode not in (None, 0):
                    raise CollectorUnavailable(
                        "nethogs could not capture process usage; "
                        "check capture permissions and run it once manually"
                    )
                raise CollectorUnavailable(
                    f"nethogs stopped while collecting usage (exit {returncode})"
                )
            if line.strip() == "Refreshing:":
                if self._started_refresh:
                    output = "\n".join(self._refresh_lines)
                    self._refresh_lines = []
                    return parse_nethogs_trace(output)
                self._started_refresh = True
                self._refresh_lines = []
            elif self._started_refresh:
                self._refresh_lines.append(line)

    def close(self) -> None:
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        self._process = None
        self._started_refresh = False
        self._refresh_lines = []


class NettopCollector(_CommandCollector):
    source = "nettop"

    def collect(self) -> list[CumulativeProcessUsage]:
        output = self._run(
            ["nettop", "-P", "-n", "-x", "-L", "1", "-J", "bytes_in,bytes_out"],
            timeout=self.interval + 10,
        )
        return parse_nettop(output)


def select_usage_collector(system: str | None = None):
    system = system or os.uname().sysname.lower()
    if system == "linux":
        return NethogsCollector
    if system in {"darwin", "macos"}:
        return NettopCollector
    raise CollectorUnavailable(f"per-process usage is unsupported on {system}")


def iter_usage_samples(
    interval: float = 5.0,
    system: str | None = None,
    collector: _CommandCollector | None = None,
) -> Iterator[list[UsageDelta]]:
    collector = collector or select_usage_collector(system)(interval)
    tracker = DeltaTracker()
    try:
        while True:
            rows = collector.collect()
            observed_at = datetime.now(timezone.utc)
            yield tracker.update(rows, observed_at)
            time.sleep(max(1.0, float(interval)))
    finally:
        collector.close()

