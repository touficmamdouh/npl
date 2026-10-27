"""Pure formatting helpers for npl."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

IEC_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
SPARK_CHARS = "▁▂▃▄▅▆▇█"


def format_bytes(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    number = max(float(value), 0.0)
    for unit in IEC_UNITS:
        if number < 1024.0 or unit == IEC_UNITS[-1]:
            if unit == "B":
                return f"{int(number)} B"
            return f"{number:.1f} {unit}"
        number /= 1024.0
    return "N/A"


def format_rate(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{format_bytes(value)}/s"


def format_latency(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.0f} ms" if value >= 10 else f"{value:.1f} ms"


def format_budget(used: int, limit: int | None, width: int = 10) -> str:
    if not limit or limit <= 0:
        return "not set"
    ratio = min(max(used / limit, 0.0), 1.0)
    filled = round(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {ratio * 100:5.1f}%"


def sparkline(values: Iterable[float], width: int = 20) -> str:
    vals = [float(value) for value in values][-width:]
    if not vals:
        return ""
    low = min(vals)
    high = max(vals)
    if high <= 0:
        return SPARK_CHARS[0] * len(vals)
    if high == low:
        return SPARK_CHARS[(len(SPARK_CHARS) - 1) // 2] * len(vals)
    span = high - low
    return "".join(
        SPARK_CHARS[round((value - low) / span * (len(SPARK_CHARS) - 1))]
        for value in vals
    )


def _window_sum(
    entries: Sequence[dict[str, Any]] | None,
    now: datetime,
    seconds: int,
) -> dict[str, int]:
    cutoff = now.timestamp() - seconds
    rx = 0
    tx = 0
    for item in entries or []:
        timestamp = item.get("timestamp")
        if timestamp is not None and timestamp >= cutoff:
            rx += int(item.get("rx", 0) or 0)
            tx += int(item.get("tx", 0) or 0)
    return {"rx": rx, "tx": tx}


def usage_windows(
    traffic: dict[str, Any],
    now: datetime,
) -> dict[str, dict[str, int]]:
    hours = traffic.get("hour", [])
    days = traffic.get("day", [])
    return {
        "last_24h": _window_sum(hours, now, 24 * 3600),
        "last_48h": _window_sum(hours, now, 48 * 3600),
        "last_7d": _window_sum(days, now, 7 * 86400),
        "last_30d": _window_sum(days, now, 30 * 86400),
    }


def available_days(
    days: Sequence[dict[str, Any]] | None,
    now: datetime,
) -> int:
    timestamps = [
        item["timestamp"]
        for item in (days or [])
        if item.get("timestamp") is not None
    ]
    if not timestamps:
        return 0
    oldest = min(timestamps)
    span = int((now.timestamp() - oldest) // 86400) + 1
    return max(1, min(30, span))


def month_usage(
    traffic: dict[str, Any],
    now: datetime,
) -> dict[str, int]:
    rx = 0
    tx = 0
    for item in traffic.get("month", []) or []:
        stamp = item.get("timestamp")
        if stamp is None:
            continue
        entry_dt = datetime.fromtimestamp(stamp, tz=now.tzinfo)
        if entry_dt.year == now.year and entry_dt.month == now.month:
            rx += int(item.get("rx", 0) or 0)
            tx += int(item.get("tx", 0) or 0)
    return {"rx": rx, "tx": tx}


def daily_series(
    days: Sequence[dict[str, Any]] | None,
    now: datetime,
    count: int = 7,
) -> list[int]:
    buckets: dict[str, int] = {}
    for item in days or []:
        stamp = item.get("timestamp")
        if stamp is None:
            continue
        key = datetime.fromtimestamp(stamp, tz=now.tzinfo).date().isoformat()
        buckets[key] = (
            buckets.get(key, 0)
            + int(item.get("rx", 0) or 0)
            + int(item.get("tx", 0) or 0)
        )
    return [
        buckets.get((now.date() - timedelta(days=offset)).isoformat(), 0)
        for offset in range(count - 1, -1, -1)
    ]


def _text(value: Any) -> str:
    return "N/A" if value is None or value == "" else str(value)


def _pair(pair: dict[str, int] | None) -> str:
    pair = pair or {}
    return f"↓ {format_bytes(pair.get('rx', 0))}  ↑ {format_bytes(pair.get('tx', 0))}"


def _speedtest_line(test: dict[str, Any] | None) -> str:
    if not test:
        return "SPEED TEST  press t (about 12 MB)"
    if test.get("error"):
        return f"SPEED TEST  error: {test['error']}"
    download = test.get("download_bps")
    upload = test.get("upload_bps")
    latency = test.get("latency_ms")
    if download is None or upload is None:
        return "SPEED TEST  N/A"
    return (
        f"SPEED TEST  ↓ {download / 1_000_000:.1f} Mbit/s  "
        f"↑ {upload / 1_000_000:.1f} Mbit/s  "
        f"ping {format_latency(latency)}"
    )


def render_dashboard(
    snapshot: dict[str, Any],
    samples: Sequence[tuple[float, float]] = (),
    selected_interface: str | None = None,
    paused: bool = False,
    warning: str | None = None,
) -> str:
    public = snapshot.get("public", {})
    usage = snapshot.get("usage", {})
    physical = usage.get("physical", {})
    vpn = usage.get("vpn", {})
    local = snapshot.get("local", {})
    latency = snapshot.get("latency", {})
    budget = snapshot.get("budget", {})
    interface = selected_interface or local.get("interface") or "N/A"
    vpn_state = "ON" if public.get("vpn_active") else "OFF"
    clock = str(snapshot.get("timestamp", ""))[11:19]
    ssid = local.get("ssid") or "wired"
    lines = [
        f"NPL   {interface} · {ssid}   [VPN: {vpn_state}]   {clock}",
        "─" * 72,
        "PUBLIC IP",
        f"IPv4 {_text(public.get('ipv4'))}        IPv6 {_text(public.get('ipv6'))}",
        f"ISP  {_text(public.get('isp'))}     ASN {_text(public.get('asn'))}",
        f"City {_text(public.get('city'))}           Region {_text(public.get('region'))}     Country {_text(public.get('country'))}",
    ]
    if public.get("vpn_active"):
        lines.append("! ISP/location reflect the VPN exit node while VPN is active.")
    elif public.get("stale_seconds"):
        lines.append(f"! Cached IP data age: {public['stale_seconds']} seconds.")
    lines.extend(
        [
            "",
            f"{'DATA USAGE':<20}{'Physical (' + _text(physical.get('interface')) + ')':<27}{'VPN (' + _text(vpn.get('interface')) + ')'}",
        ]
    )
    for label, key in (
        ("24 hours", "last_24h"),
        ("48 hours", "last_48h"),
        ("7 days", "last_7d"),
        ("30 days", "last_30d"),
    ):
        lines.append(
            f"{label:<20}{_pair(physical.get(key)):<27}{_pair(vpn.get(key))}"
        )
    lines.append(
        f"{'This month':<20}{format_budget(int(budget.get('used', 0) or 0), budget.get('limit'))}"
    )
    lines.append(
        f"{'7-day usage':<20}{sparkline(physical.get('daily_series', []), width=7)}"
    )
    lines.append(
        f"{'History available':<20}physical {physical.get('days_available', 0)} days · "
        f"VPN {vpn.get('days_available', 0)} days"
    )

    last_rx, last_tx = samples[-1] if samples else (0.0, 0.0)
    speed_header = f"LIVE SPEED · {interface}" + ("   [PAUSED]" if paused else "")
    lines.extend(
        [
            "",
            speed_header,
            f"Download  {format_rate(last_rx):>12}  {sparkline([sample[0] for sample in samples])}",
            f"Upload    {format_rate(last_tx):>12}  {sparkline([sample[1] for sample in samples])}",
            _speedtest_line(snapshot.get("speedtest")),
            "",
            "LOCAL NETWORK",
            f"IPv4 {_text(local.get('ipv4'))}      IPv6 {_text(local.get('ipv6'))}",
            f"Gateway {_text(local.get('gateway'))}       MAC {_text(local.get('mac'))}",
            f"Wi-Fi {_text(local.get('ssid'))} · {_text(local.get('signal_dbm'))} dBm · "
            f"{_text(local.get('rx_bitrate_mbps'))}/{_text(local.get('tx_bitrate_mbps'))} Mbps",
            f"DNS {', '.join(local.get('dns') or []) or 'N/A'}",
            f"Latency  gateway {format_latency(latency.get('gateway_ms'))} · "
            f"1.1.1.1 {format_latency(latency.get('internet_ms'))}",
            "",
            "[q] Quit   [r] Refresh   [t] Speed test   [i] Switch interface   [p] Pause   [?] Help",
        ]
    )
    if warning:
        lines.insert(2, f"! {warning}")
    return "\n".join(lines)
