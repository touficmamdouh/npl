#!/usr/bin/env python3
"""NPL terminal network dashboard."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from collectors import (
    collect_snapshot,
    load_config,
    rates_from_counters,
    read_net_counters,
    run_speedtest,
)
from formatting import render_dashboard

APP_VERSION = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="npl",
        description="Terminal network, usage, and speed dashboard",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="print one snapshot and exit",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print one JSON snapshot and exit",
    )
    parser.add_argument(
        "--speedtest",
        action="store_true",
        help="run a speed test and exit",
    )
    parser.add_argument("--interface", help="override the physical interface")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
    )
    return parser


class NplApp(App):
    TITLE = "NPL"
    CSS = """
    Screen { background: #101418; color: #d8dee9; }
    #dashboard-text { padding: 1 2; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("t", "speedtest", "Speed test"),
        ("i", "switch_interface", "Interface"),
        ("p", "toggle_pause", "Pause"),
        ("?", "help", "Help"),
    ]

    def __init__(self, snapshot: dict[str, Any], config: dict[str, Any]) -> None:
        super().__init__()
        self.snapshot = snapshot
        self.config = config
        self.samples: list[tuple[float, float]] = []
        self.previous_counters: tuple[int, int] | None = None
        self.previous_time: float | None = None
        self.paused = False
        self.speedtest_armed = False
        self.speedtest_running = False
        self.warning: str | None = None
        self.selected_interface = snapshot.get("local", {}).get("interface")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="dashboard-text", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(1.0, self.tick)
        refresh_seconds = min(
            float(self.config.get("usage_refresh_seconds", 60)),
            float(self.config.get("local_refresh_seconds", 30)),
            float(self.config.get("ip_refresh_seconds", 60)),
        )
        self.set_interval(refresh_seconds, self.action_refresh)
        self.update_view()

    def update_view(self) -> None:
        content = render_dashboard(
            self.snapshot,
            self.samples,
            self.selected_interface,
            self.paused,
            self.warning,
        )
        self.query_one("#dashboard-text", Static).update(content)

    def tick(self) -> None:
        if self.paused:
            return
        now = time.monotonic()
        counters = read_net_counters(self.selected_interface)
        if counters and self.previous_counters and self.previous_time:
            rate = rates_from_counters(
                self.previous_counters,
                counters,
                now - self.previous_time,
            )
            self.samples.append(rate)
            self.samples = self.samples[-60:]
        self.previous_counters = counters
        self.previous_time = now
        self.update_view()

    def action_refresh(self) -> None:
        self.warning = "Refreshing..."
        self.update_view()
        self.run_worker(self._refresh_worker, thread=True, exclusive=True)

    def _refresh_worker(self) -> None:
        try:
            snapshot = collect_snapshot(self.config)
        except Exception as exc:
            self.call_from_thread(self._set_warning, f"Refresh failed: {exc}")
            return
        self.call_from_thread(self._apply_snapshot, snapshot)

    def _set_warning(self, message: str | None) -> None:
        self.warning = message
        self.update_view()

    def _apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        existing_speedtest = self.snapshot.get("speedtest")
        self.snapshot = snapshot
        if existing_speedtest is not None:
            self.snapshot["speedtest"] = existing_speedtest
        interfaces = [
            self.snapshot.get("local", {}).get("interface"),
            self.snapshot.get("usage", {}).get("vpn", {}).get("interface"),
        ]
        if self.selected_interface not in [item for item in interfaces if item]:
            self.selected_interface = interfaces[0]
            self.previous_counters = None
            self.previous_time = None
        self.warning = None
        self.update_view()

    def action_switch_interface(self) -> None:
        interfaces = [
            self.snapshot.get("local", {}).get("interface"),
            self.snapshot.get("usage", {}).get("vpn", {}).get("interface"),
        ]
        interfaces = [item for item in interfaces if item]
        if not interfaces:
            return
        index = (
            interfaces.index(self.selected_interface)
            if self.selected_interface in interfaces
            else -1
        )
        self.selected_interface = interfaces[(index + 1) % len(interfaces)]
        self.samples.clear()
        self.previous_counters = None
        self.previous_time = None
        self.update_view()

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        self.update_view()

    def action_help(self) -> None:
        self.warning = (
            "q Quit | r Refresh | t Speed test | i Switch interface | "
            "p Pause | ? Help"
        )
        self.update_view()

    def action_speedtest(self) -> None:
        if self.speedtest_running:
            return
        if not self.speedtest_armed:
            self.speedtest_armed = True
            self.warning = (
                "Speed test uses about 12 MB. Press t again within 10 seconds "
                "to confirm."
            )
            self.set_timer(10.0, self._disarm_speedtest)
            self.update_view()
            return
        self.speedtest_armed = False
        self.speedtest_running = True
        self.warning = "Running speed test..."
        self.update_view()
        self.run_worker(self._speedtest_worker, thread=True, exclusive=False)

    def _disarm_speedtest(self) -> None:
        if self.speedtest_armed:
            self.speedtest_armed = False
            self.warning = None
            self.update_view()

    def _speedtest_worker(self) -> None:
        try:
            result = run_speedtest(
                int(self.config["speedtest_down_bytes"]),
                int(self.config["speedtest_up_bytes"]),
            )
        except Exception as exc:
            result = {
                "download_bps": None,
                "upload_bps": None,
                "latency_ms": None,
                "bytes_used": 0,
                "error": str(exc),
            }
        self.call_from_thread(self._apply_speedtest, result)

    def _apply_speedtest(self, result: dict[str, Any]) -> None:
        self.speedtest_running = False
        self.snapshot["speedtest"] = result
        self.warning = (
            f"Speed test failed: {result['error']}"
            if result.get("error")
            else None
        )
        self.update_view()


def _print_snapshot(snapshot: dict[str, Any]) -> None:
    print(render_dashboard(snapshot))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, config_warning = load_config()
    if args.interface:
        config["physical_interface"] = args.interface
    if config_warning:
        print(f"npl: {config_warning}", file=sys.stderr)

    if args.speedtest:
        result = run_speedtest(
            int(config["speedtest_down_bytes"]),
            int(config["speedtest_up_bytes"]),
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("error") is None else 1

    try:
        snapshot = collect_snapshot(
            config,
            interface=args.interface or config.get("physical_interface") or None,
        )
    except Exception as exc:
        print(f"npl: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
        return 0
    if args.once:
        _print_snapshot(snapshot)
        return 0

    app = NplApp(snapshot, config)
    app.warning = config_warning
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
