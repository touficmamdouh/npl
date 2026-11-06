"""Operating-system-specific network discovery for NPL."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from typing import Callable

from collectors import CommandResult, run_command


class InterfaceOverrideError(ValueError):
    """Raised when a requested interface is not present on the host."""


@dataclass
class NetworkSnapshot:
    hostname: str
    interface: str | None = None
    vpn_interface: str | None = None
    gateway: str | None = None
    ipv4: str | None = None
    ipv6: str | None = None
    mac: str | None = None
    dns: list[str] = field(default_factory=list)
    ssid: str | None = None
    signal_dbm: int | None = None
    rx_bitrate_mbps: float | None = None
    tx_bitrate_mbps: float | None = None


Runner = Callable[..., CommandResult]


def _netmask_to_prefix(netmask: str) -> int | None:
    if netmask.startswith("0x"):
        try:
            return bin(int(netmask, 16)).count("1")
        except ValueError:
            return None
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen
    except ValueError:
        return None


def _parse_route(text: str) -> tuple[str | None, str | None]:
    gateway = re.search(r"^gateway:\s*(\S+)", text, re.MULTILINE)
    interface = re.search(r"^interface:\s*(\S+)", text, re.MULTILINE)
    return (
        gateway.group(1) if gateway else None,
        interface.group(1) if interface else None,
    )


def _parse_ifconfig(text: str) -> dict[str, str | None]:
    result: dict[str, str | None] = {
        "ipv4": None,
        "ipv6": None,
        "mac": None,
    }
    mac = re.search(r"\bether\s+([0-9a-f:]{17})", text, re.IGNORECASE)
    ipv4 = re.search(r"\binet\s+(\d+(?:\.\d+){3})\s+netmask\s+(\S+)", text)
    ipv6 = re.search(r"\binet6\s+([0-9a-f:]+)(?:%\S+)?\s+prefixlen\s+(\d+)", text, re.IGNORECASE)
    if mac:
        result["mac"] = mac.group(1).lower()
    if ipv4:
        prefix = _netmask_to_prefix(ipv4.group(2))
        result["ipv4"] = f"{ipv4.group(1)}/{prefix}" if prefix is not None else ipv4.group(1)
    if ipv6:
        result["ipv6"] = f"{ipv6.group(1)}/{ipv6.group(2)}"
    return result


def _parse_dns(text: str) -> list[str]:
    return re.findall(r"^nameserver\[\d+\]\s*:\s*(\S+)", text, re.MULTILINE)


class MacOSCollector:
    """Collect network data using commands present on macOS."""

    def __init__(self, runner: Runner = run_command) -> None:
        self.runner = runner

    def _interfaces(self) -> list[str]:
        result = self.runner(["ifconfig", "-l"])
        if not result.ok:
            return []
        return [item for item in result.stdout.split() if item and item != "lo0"]

    def discover(self, preferred: str | None = None) -> NetworkSnapshot:
        interfaces = self._interfaces()
        vpn_interface = next(
            (
                item
                for item in interfaces
                if item.startswith(("utun", "ppp", "ipsec"))
            ),
            None,
        )
        route_result = self.runner(["route", "-n", "get", "default"])
        gateway, route_interface = _parse_route(
            route_result.stdout if route_result.ok else ""
        )
        if preferred and interfaces and preferred not in interfaces:
            raise InterfaceOverrideError(
                f"interface {preferred!r} was not found; available: {', '.join(interfaces)}"
            )
        interface = preferred or route_interface
        if interface is None and interfaces:
            interface = interfaces[0]
        if preferred and not interfaces and preferred != route_interface:
            raise InterfaceOverrideError(f"interface {preferred!r} was not found")
        if interface is None:
            return NetworkSnapshot(
                hostname=socket.gethostname(), vpn_interface=vpn_interface
            )

        details_result = self.runner(["ifconfig", interface])
        details = _parse_ifconfig(details_result.stdout if details_result.ok else "")
        dns_result = self.runner(["scutil", "--dns"])
        airport_result = self.runner(["networksetup", "-getairportnetwork", interface])
        ssid_match = re.search(r"Current Wi-Fi Network:\s*(.+)", airport_result.stdout)
        return NetworkSnapshot(
            hostname=socket.gethostname(),
            interface=interface,
            vpn_interface=vpn_interface,
            gateway=gateway,
            ipv4=details["ipv4"],
            ipv6=details["ipv6"],
            mac=details["mac"],
            dns=_parse_dns(dns_result.stdout if dns_result.ok else ""),
            ssid=ssid_match.group(1).strip() if ssid_match else None,
        )

    def read_counters(self, interface: str) -> tuple[int, int] | None:
        result = self.runner(["netstat", "-ib", "-I", interface])
        if not result.ok:
            return None
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 10 or fields[0] != interface:
                continue
            try:
                return int(fields[6]), int(fields[9])
            except ValueError:
                continue
        return None


class LinuxCollector:
    """Marker adapter for Linux; legacy Linux parsing remains in collectors."""


def collector_for_platform(platform: str | None = None):
    platform = platform or __import__("sys").platform
    if platform == "darwin":
        return MacOSCollector()
    return LinuxCollector()
