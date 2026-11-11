"""Text and JSON formatting for per-process usage reports."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable

from usage_store import UsageTotal


def _format_bytes(value: int) -> str:
    amount = float(value)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(amount) < 1024 or suffix == "TiB":
            return f"{amount:.1f} {suffix}"
        amount /= 1024
    return f"{value} B"


def _started_value(started_at: str | datetime | None) -> str | None:
    if started_at is None:
        return None
    return started_at.isoformat() if isinstance(started_at, datetime) else str(started_at)


def render_usage_report(
    rows: Iterable[UsageTotal],
    period: str,
    source: str | None,
    started_at: str | datetime | None,
    json_output: bool = False,
) -> str:
    rows = list(rows)
    total_bytes = sum(row.total_bytes for row in rows)
    started = _started_value(started_at)
    payload_rows: list[dict[str, Any]] = []
    for row in rows:
        share = (row.total_bytes / total_bytes * 100) if total_bytes else 0.0
        payload_rows.append(
            {
                "name": row.name,
                "path": row.path,
                "source": row.source,
                "rx_bytes": row.rx_bytes,
                "tx_bytes": row.tx_bytes,
                "total_bytes": row.total_bytes,
                "share_percent": round(share, 1),
            }
        )
    if json_output:
        return json.dumps(
            {
                "period": period,
                "source": source,
                "recorded_since": started,
                "total_bytes": total_bytes,
                "rows": payload_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    if not rows:
        return (
            f"Usage report: {period}\n"
            "No usage data recorded yet. Run `npl usage record` first."
        )
    lines = [
        f"Usage report: {period}",
        f"Source: {source or 'unknown'}",
        f"Recorded since: {started or 'unknown'}",
        "",
        f"{'Program':<24} {'RX':>12} {'TX':>12} {'Total':>12} {'Share':>8}",
    ]
    for row, payload in zip(rows, payload_rows):
        name = row.name[:24]
        lines.append(
            f"{name:<24} {_format_bytes(row.rx_bytes):>12} "
            f"{_format_bytes(row.tx_bytes):>12} "
            f"{_format_bytes(row.total_bytes):>12} "
            f"{payload['share_percent']:>7.1f}%"
        )
    lines.append("")
    lines.append(f"Total: {_format_bytes(total_bytes)}")
    return "\n".join(lines)

