"""System and network data collectors for npl."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import tomllib
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from formatting import (
    available_days,
    daily_series,
    month_usage,
    usage_windows,
)


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    ok: bool
    error: str = ""


@dataclass
class NetworkInfo:
    hostname: str
    physical_interface: str | None = None
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


def run_command(
    args: list[str],
    timeout: float = 5.0,
    input_data: bytes | None = None,
) -> CommandResult:
    try:
        process = subprocess.run(
            args,
            input=input_data,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult("", False, str(exc))
    stdout = process.stdout.decode("utf-8", errors="replace")
    stderr = process.stderr.decode("utf-8", errors="replace")
    return CommandResult(
        stdout,
        process.returncode == 0,
        stderr or f"exit {process.returncode}",
    )


def _parse_nmcli_types(nmcli_text: str) -> dict[str, str]:
    types: dict[str, str] = {}
    for line in nmcli_text.splitlines():
        parts = line.split(":", 3)
        if len(parts) >= 2:
            types[parts[0]] = parts[1]
    return types


def _pick_address(link: dict[str, Any], family: str) -> str | None:
    candidates = [
        address
        for address in link.get("addr_info", [])
        if address.get("family") == family and address.get("scope") != "host"
    ]
    if not candidates:
        return None
    global_addresses = [
        address for address in candidates if address.get("scope") == "global"
    ]
    selected = (global_addresses or candidates)[0]
    return f"{selected['local']}/{selected['prefixlen']}"


def parse_network(
    address_json: list[dict[str, Any]],
    default_routes: list[dict[str, Any]],
    nmcli_text: str,
    hostname: str,
    preferred: str | None = None,
) -> NetworkInfo:
    links = {
        entry["ifname"]: entry for entry in address_json if "ifname" in entry
    }
    types = _parse_nmcli_types(nmcli_text)
    vpn_candidates = [
        name
        for name, interface_type in types.items()
        if interface_type in {"tun", "wireguard"} and name in links
    ]
    vpn_interface = vpn_candidates[0] if vpn_candidates else None

    route = None
    if preferred:
        route = next(
            (
                candidate
                for candidate in default_routes
                if candidate.get("dev") == preferred
            ),
            None,
        )
    else:
        route = next(
            (
                candidate
                for candidate in default_routes
                if candidate.get("dev") in links
                and candidate.get("dev") != vpn_interface
            ),
            None,
        )
        if route is None and default_routes:
            route = default_routes[0]

    physical_interface = preferred or (route or {}).get("dev")
    if physical_interface not in links:
        physical_interface = next(
            (
                name
                for name, interface_type in types.items()
                if interface_type in {"wifi", "ethernet"} and name in links
            ),
            physical_interface,
        )
    if physical_interface not in links:
        return NetworkInfo(hostname=hostname, vpn_interface=vpn_interface)

    link = links[physical_interface]
    return NetworkInfo(
        hostname=hostname,
        physical_interface=physical_interface,
        vpn_interface=vpn_interface,
        gateway=(route or {}).get("gateway"),
        ipv4=_pick_address(link, "inet"),
        ipv6=_pick_address(link, "inet6"),
        mac=link.get("address"),
    )


def enrich_local(info: NetworkInfo, dns_text: str, iw_text: str) -> NetworkInfo:
    dns = [
        part.strip()
        for part in re.split(r"[|,]", dns_text)
        if part.strip()
    ]
    ssid_match = re.search(r"SSID:\s*(.+)", iw_text)
    signal_match = re.search(r"signal:\s*(-?\d+)\s*dBm", iw_text)
    rx_match = re.search(r"rx bitrate:\s*([\d.]+)\s*MBit/s", iw_text)
    tx_match = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s", iw_text)
    return replace(
        info,
        dns=dns,
        ssid=ssid_match.group(1).strip() if ssid_match else None,
        signal_dbm=int(signal_match.group(1)) if signal_match else None,
        rx_bitrate_mbps=float(rx_match.group(1)) if rx_match else None,
        tx_bitrate_mbps=float(tx_match.group(1)) if tx_match else None,
    )


def _decode_json(result: CommandResult, fallback: Any) -> Any:
    if not result.ok:
        return fallback
    try:
        import json

        return json.loads(result.stdout)
    except (TypeError, ValueError):
        return fallback


def discover_network(
    preferred: str | None = None,
    runner: Runner = run_command,
) -> NetworkInfo:
    import socket

    address_json = _decode_json(
        runner(["ip", "-j", "address", "show"]),
        [],
    )
    default_routes = _decode_json(
        runner(["ip", "-j", "route", "show", "default"]),
        [],
    )
    nmcli = runner(
        ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"]
    )
    nmcli_text = nmcli.stdout if nmcli.ok else ""
    info = parse_network(
        address_json,
        default_routes,
        nmcli_text,
        socket.gethostname(),
        preferred=preferred,
    )

    if info.physical_interface:
        dns_result = runner(
            ["nmcli", "-g", "IP4.DNS", "device", "show", info.physical_interface]
        )
        types = _parse_nmcli_types(nmcli_text)
        iw_result = (
            runner(["iw", "dev", info.physical_interface, "link"])
            if types.get(info.physical_interface) == "wifi"
            else CommandResult("", True, "")
        )
        info = enrich_local(
            info,
            dns_result.stdout if dns_result.ok else "",
            iw_result.stdout if iw_result.ok else "",
        )
    return info


@dataclass
class PublicIPInfo:
    ipv4: str | None
    ipv6: str | None
    isp: str | None
    asn: str | None
    city: str | None
    region: str | None
    country: str | None
    vpn_active: bool
    stale_seconds: int | None = None


def _parse_org(org: str | None) -> tuple[str | None, str | None]:
    if not org:
        return None, None
    match = re.match(r"^(AS\d+)\s+(.+)$", org)
    if match:
        return match.group(1), match.group(2)
    return None, org


def _default_cache_path() -> Path:
    cache_root = Path(
        os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    )
    return cache_root / "npl" / "ip.json"


def fetch_ipinfo(
    family: str,
    runner: Runner = run_command,
) -> dict[str, Any] | None:
    result = runner(
        [
            "curl",
            f"-{family}",
            "-fsS",
            "--max-time",
            "5",
            "https://ipinfo.io/json",
        ],
        timeout=6,
    )
    payload = _decode_json(result, None)
    if not isinstance(payload, dict) or not payload.get("ip"):
        return None
    return payload


def _public_from_payload(
    payload: dict[str, Any],
    vpn_active: bool,
    stale_seconds: int,
) -> PublicIPInfo:
    ipv4 = payload.get("v4") or {}
    ipv6 = payload.get("v6") or {}
    primary = ipv4 if ipv4 else ipv6
    asn, isp = _parse_org(primary.get("org"))
    return PublicIPInfo(
        ipv4=ipv4.get("ip"),
        ipv6=ipv6.get("ip"),
        isp=isp,
        asn=asn,
        city=primary.get("city"),
        region=primary.get("region"),
        country=primary.get("country"),
        vpn_active=vpn_active,
        stale_seconds=stale_seconds,
    )


def read_ip_info(
    vpn_active: bool,
    cache_path: Path | None = None,
    now: datetime | None = None,
    fetcher: Callable[[str], dict[str, Any] | None] = fetch_ipinfo,
) -> PublicIPInfo:
    now = now or datetime.now().astimezone()
    cache_path = Path(cache_path) if cache_path else _default_cache_path()

    payload: dict[str, Any] | None = None
    if cache_path.exists():
        try:
            cached_text = cache_path.read_text(encoding="utf-8")
        except OSError:
            cached_text = ""
        payload = _decode_json(CommandResult(cached_text, bool(cached_text), ""), None)
        if isinstance(payload, dict):
            age = now.timestamp() - float(payload.get("timestamp", 0))
            if 0 <= age < 600:
                return _public_from_payload(payload, vpn_active, 0)

    ipv4 = fetcher("4")
    ipv6 = fetcher("6")
    if ipv4 or ipv6:
        payload = {
            "timestamp": now.timestamp(),
            "v4": ipv4,
            "v6": ipv6,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        cache_path.chmod(0o600)
        return _public_from_payload(payload, vpn_active, 0)

    if isinstance(payload, dict):
        age = max(0, int(now.timestamp() - float(payload.get("timestamp", 0))))
        return _public_from_payload(payload, vpn_active, age)

    return PublicIPInfo(
        ipv4=None,
        ipv6=None,
        isp=None,
        asn=None,
        city=None,
        region=None,
        country=None,
        vpn_active=vpn_active,
        stale_seconds=None,
    )


DEFAULT_CONFIG: dict[str, Any] = {
    "monthly_budget_gb": 0,
    "ip_refresh_seconds": 60,
    "usage_refresh_seconds": 60,
    "local_refresh_seconds": 30,
    "speedtest_down_bytes": 10_000_000,
    "speedtest_up_bytes": 2_000_000,
    "physical_interface": "",
    "vpn_interface": "",
}


def read_vnstat(
    interface: str | None,
    runner: Runner = run_command,
) -> dict[str, Any]:
    if not interface:
        return {}
    result = runner(["vnstat", "--json", "--iface", interface], timeout=8)
    payload = _decode_json(result, {})
    if not isinstance(payload, dict):
        return {}
    for item in payload.get("interfaces", []):
        if item.get("name") == interface:
            return item.get("traffic", {}) or {}
    return {}


def read_net_counters(
    interface: str | None,
    proc_path: Path = Path("/proc/net/dev"),
) -> tuple[int, int] | None:
    if not interface:
        return None
    try:
        lines = Path(proc_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if ":" not in line:
            continue
        name, values = line.split(":", 1)
        if name.strip() != interface:
            continue
        fields = values.split()
        if len(fields) >= 9:
            return int(fields[0]), int(fields[8])
    return None


def rates_from_counters(
    previous: tuple[int, int] | None,
    current: tuple[int, int] | None,
    elapsed: float,
) -> tuple[float, float]:
    if not previous or not current or elapsed <= 0:
        return 0.0, 0.0
    return (
        max(0.0, (current[0] - previous[0]) / elapsed),
        max(0.0, (current[1] - previous[1]) / elapsed),
    )


def ping_average(
    host: str | None,
    runner: Runner = run_command,
    tcp_port: int | None = None,
) -> float | None:
    if not host:
        return None
    result = runner(
        ["ping", "-n", "-c", "3", "-W", "1", host],
        timeout=6,
    )
    if not result.ok:
        return tcp_latency(host, tcp_port) if tcp_port else None
    times = [
        float(value)
        for value in re.findall(r"time=([\d.]+)\s*ms", result.stdout)
    ]
    if times:
        return sum(times) / len(times)
    return tcp_latency(host, tcp_port) if tcp_port else None


def tcp_latency(
    host: str,
    port: int,
    timeout: float = 1.0,
    attempts: int = 3,
) -> float | None:
    samples: list[float] = []
    for _ in range(attempts):
        started = time.perf_counter()
        try:
            connection = socket.create_connection((host, port), timeout=timeout)
        except OSError:
            continue
        connection.close()
        samples.append((time.perf_counter() - started) * 1000)
    return sum(samples) / len(samples) if samples else None


def _parse_curl_metric(output: str) -> tuple[float, int] | None:
    parts = output.strip().split()
    if len(parts) < 3:
        return None
    try:
        code = int(parts[0])
        speed = float(parts[1])
        size = int(float(parts[2]))
    except ValueError:
        return None
    if not 200 <= code < 300:
        return None
    return speed, size


def internet_latency(host: str | None) -> float | None:
    return ping_average(host, tcp_port=443)


def run_speedtest(
    down_bytes: int = 10_000_000,
    up_bytes: int = 2_000_000,
    runner: Runner = run_command,
    ping_fn: Callable[[str | None], float | None] = internet_latency,
) -> dict[str, Any]:
    download_url = (
        f"https://speed.cloudflare.com/__down?bytes={int(down_bytes)}"
    )
    download = runner(
        [
            "curl",
            "-fsS",
            "-L",
            "--max-time",
            "30",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code} %{speed_download} %{size_download}",
            download_url,
        ],
        timeout=35,
    )
    download_metric = _parse_curl_metric(download.stdout) if download.ok else None
    if download_metric is None:
        return {
            "download_bps": None,
            "upload_bps": None,
            "latency_ms": ping_fn("1.1.1.1"),
            "bytes_used": 0,
            "error": "download failed",
        }

    upload = runner(
        [
            "curl",
            "-fsS",
            "-L",
            "--max-time",
            "30",
            "-o",
            "/dev/null",
            "-H",
            "Content-Type: application/octet-stream",
            "--data-binary",
            "@-",
            "-w",
            "%{http_code} %{speed_upload} %{size_upload}",
            "https://speed.cloudflare.com/__up",
        ],
        timeout=35,
        input_data=b"\0" * int(up_bytes),
    )
    upload_metric = _parse_curl_metric(upload.stdout) if upload.ok else None
    if upload_metric is None:
        return {
            "download_bps": None,
            "upload_bps": None,
            "latency_ms": ping_fn("1.1.1.1"),
            "bytes_used": 0,
            "error": "upload failed",
        }

    return {
        "download_bps": download_metric[0] * 8,
        "upload_bps": upload_metric[0] * 8,
        "latency_ms": ping_fn("1.1.1.1"),
        "bytes_used": download_metric[1] + upload_metric[1],
        "error": None,
    }


def _valid_number(value: Any, default: float, minimum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def load_config(path: Path | None = None) -> tuple[dict[str, Any], str | None]:
    config = dict(DEFAULT_CONFIG)
    if path is None:
        base = Path(
            os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        )
        path = base / "npl" / "config.toml"
    path = Path(path)
    if not path.exists():
        return config, None
    try:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return config, f"Config ignored: {exc}"
    if not isinstance(loaded, dict):
        return config, "Config ignored: top-level value must be a table"

    config["monthly_budget_gb"] = _valid_number(
        loaded.get("monthly_budget_gb", config["monthly_budget_gb"]),
        float(DEFAULT_CONFIG["monthly_budget_gb"]),
        0,
    )
    for key in (
        "ip_refresh_seconds",
        "usage_refresh_seconds",
        "local_refresh_seconds",
        "speedtest_down_bytes",
        "speedtest_up_bytes",
    ):
        config[key] = int(
            _valid_number(
                loaded.get(key, config[key]),
                float(DEFAULT_CONFIG[key]),
                1,
            )
        )
    for key in ("physical_interface", "vpn_interface"):
        value = loaded.get(key, config[key])
        config[key] = value if isinstance(value, str) else config[key]
    return config, None


def _usage_block(interface: str | None, now: datetime) -> dict[str, Any]:
    traffic = read_vnstat(interface) if interface else {}
    return {
        "interface": interface,
        **usage_windows(traffic, now),
        "this_month": month_usage(traffic, now),
        "daily_series": daily_series(traffic.get("day", []), now),
        "days_available": available_days(traffic.get("day", []), now),
    }


def collect_snapshot(
    config: dict[str, Any],
    interface: str | None = None,
    now: datetime | None = None,
    include_speedtest: bool = False,
) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    preferred = interface or (config.get("physical_interface") or None)
    network = discover_network(preferred)
    configured_vpn = config.get("vpn_interface") or None
    if configured_vpn:
        network = replace(network, vpn_interface=configured_vpn)
    public = read_ip_info(bool(network.vpn_interface), now=now)
    physical = _usage_block(network.physical_interface, now)
    vpn = _usage_block(network.vpn_interface, now)
    budget_gb = float(config.get("monthly_budget_gb", 0) or 0)
    budget_limit = int(budget_gb * 1024**3) if budget_gb > 0 else None
    month_total = physical["this_month"]
    latency = {
        "gateway_ms": ping_average(network.gateway, tcp_port=53),
        "internet_ms": ping_average("1.1.1.1", tcp_port=443),
    }
    speedtest = None
    if include_speedtest:
        speedtest = run_speedtest(
            int(config["speedtest_down_bytes"]),
            int(config["speedtest_up_bytes"]),
        )
    return {
        "timestamp": now.isoformat(),
        "public": {
            "ipv4": public.ipv4,
            "ipv6": public.ipv6,
            "isp": public.isp,
            "asn": public.asn,
            "city": public.city,
            "region": public.region,
            "country": public.country,
            "vpn_active": public.vpn_active,
            "stale_seconds": public.stale_seconds,
        },
        "usage": {"physical": physical, "vpn": vpn},
        "budget": {
            "used": month_total["rx"] + month_total["tx"],
            "limit": budget_limit,
        },
        "local": {
            "hostname": network.hostname,
            "interface": network.physical_interface,
            "ipv4": network.ipv4,
            "ipv6": network.ipv6,
            "gateway": network.gateway,
            "mac": network.mac,
            "dns": network.dns,
            "ssid": network.ssid,
            "signal_dbm": network.signal_dbm,
            "rx_bitrate_mbps": network.rx_bitrate_mbps,
            "tx_bitrate_mbps": network.tx_bitrate_mbps,
        },
        "latency": latency,
        "speedtest": speedtest,
    }
