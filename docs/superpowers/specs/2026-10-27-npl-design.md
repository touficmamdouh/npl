# NPL - Network Pulse Terminal

**Date:** 2026-10-27
**Status:** Implemented and verified
**Target:** Linux Mint 22.3 on the current machine

## 1. Purpose

NPL is a terminal dashboard that combines:

- Public IPv4/IPv6 address and geolocation data.
- Internet usage for the last 24 hours, 48 hours, 7 days, and 30 days.
- Separate usage reporting for the physical network interface and the active VPN.
- Live download/upload throughput with a short history graph.
- On-demand download, upload, and latency testing.
- Local network details, including LAN address, gateway, DNS, Wi-Fi state, and latency.
- A monthly data-budget indicator and machine-readable output for scripts.

The user runs `npl` from a terminal and sees an English-language Textual dashboard.

## 2. Non-Goals

The first version does not include:

- LAN device discovery or port scanning.
- Per-process traffic accounting.
- Traceroute.
- An IP-change history or background notification service.
- A new daemon, database, or privileged helper.
- Windows or macOS support.

These can be considered later without changing the first-version architecture.

## 3. Environment and Dependencies

The current machine provides:

- Linux Mint 22.3, Python 3.14.
- Textual 8.2.7.
- `vnstat` 2.12, active and enabled.
- `ip`, `nmcli`, `iw`, `curl`, and `ping`.
- Active Wi-Fi interface `wlp3s0` and active VPN interface `CloudflareWARP`.

The implementation uses Python's standard library plus the installed Textual package and operating-system tools. `requirements.txt` pins the Textual version. No root access is required.

## 4. Command-Line Interface

```text
npl                     Interactive dashboard
npl --once              One textual snapshot, then exit
npl --json              One JSON snapshot, then exit
npl --speedtest         Run a direct speed test, then exit
npl --interface NAME    Override the auto-detected physical interface
npl --version           Print the version
npl --help              Print help
```

The command is exposed as `/home/t9/.local/bin/npl`, a small executable wrapper around `/home/t9/npl/npl.py`. The project lives in `/home/t9/npl`.

## 5. Dashboard

```text
NPL   wlp3s0 · WEA49217   [VPN: WARP ON]                     14:42:10
────────────────────────────────────────────────────────────────────
PUBLIC IP
IPv4 104.28.228.70        IPv6 2606:4700:110:8ad9:...
ISP  Cloudflare, Inc.     ASN AS13335
City Alexandria           Region Alexandria     Country EG
! ISP/location reflect the VPN exit node while WARP is active.

DATA USAGE                 Physical (wlp3s0)       VPN (CloudflareWARP)
24 hours                   ↓ 1.2 GB  ↑ 0.3 GB      ↓ 0.9 GB  ↑ 0.2 GB
48 hours                   ↓ 2.5 GB  ↑ 0.6 GB      ↓ 1.8 GB  ↑ 0.4 GB
7 days                     ↓ 9.8 GB  ↑ 2.1 GB      ↓ 6.4 GB  ↑ 1.3 GB
30 days                    ↓ 38.2 GB ↑ 8.7 GB      ↓ 21.7 GB ↑ 4.9 GB
This month                 [████████░░] 105.9 / 200 GB
7-day usage                ▁▂▄▆█▆▄

LIVE SPEED · wlp3s0
Download  4.2 MB/s  ▁▂▄▆█▆▄▃▂▁▃▅▇█▆▄▂
Upload    0.8 MB/s  ▁▁▂▂▃▂▁▁▂▃▄▃▂▁▁▂

LOCAL NETWORK
IPv4 192.168.1.46/24      IPv6 fe80::1822:a73:79ff:98ab/64
Gateway 192.168.1.1       MAC e4:ce:8f:67:1e:bc
Wi-Fi -64 dBm · 78/300 Mbps    DNS 8.8.8.8, 8.8.4.4
Latency  gateway 2 ms · 1.1.1.1 27 ms

[q] Quit   [r] Refresh   [t] Speed test   [i] Switch interface   [p] Pause   [?] Help
```

### Key bindings

| Key | Action |
| --- | --- |
| `q` | Quit |
| `r` | Refresh public IP, usage, and local data |
| `t` | Start a speed test after an explicit confirmation |
| `i` | Switch live throughput between the physical interface and VPN |
| `p` | Pause or resume live throughput sampling |
| `?` | Show help |

The interface requires at least 80 columns by 24 rows. It displays a clear message when the terminal is smaller.

## 6. Architecture

```text
/home/t9/npl/
├── npl.py                 CLI entry point and Textual application
├── collectors.py          System/network data collection and parsing
├── formatting.py          Usage aggregation, charts, and value formatting
├── tests/
│   ├── test_collectors.py
│   ├── test_formatting.py
│   └── fixtures/          Synthetic vnstat/ip/ipinfo outputs
├── requirements.txt
├── README.md
└── npl.toml.example
```

`collectors.py` handles external commands and raw parsing. `formatting.py` contains deterministic calculations that can be tested without the network. `npl.py` owns Textual widgets, timers, key bindings, background workers, and CLI dispatch.

## 7. Data Collection and Refresh

### Interface discovery

`collectors.discover_network()` uses `ip -j route show default` and `ip -j address show` to identify:

- Active physical interface and its IPv4/IPv6 addresses.
- Default gateway.
- MAC address.
- VPN/tunnel interface, if present.

Only interface names returned by `ip` are accepted. `--interface` is validated against the same list.

### Public IP information

- IPv4 and IPv6 are queried independently with `curl -4` and `curl -6` against `https://ipinfo.io/json`.
- Each request has a 5-second timeout.
- IPv4 is the primary source for ISP, city, region, country, and coordinates.
- The `org` field is split into ASN and ISP/organization name.
- Successful responses are cached for 10 minutes in `~/.cache/npl/ip.json`.
- On failure, a stale cached response is shown with its age; otherwise the field is `N/A`.
- When a VPN interface is active, the dashboard displays a warning that ISP and location describe the VPN exit node.

### Data usage

Usage is read separately from `vnstat --json --iface <name>` for the physical interface and the VPN interface. The two values are never summed.

- 24 hours: sum hourly buckets whose timestamp is within the last 24 hours.
- 48 hours: sum hourly buckets whose timestamp is within the last 48 hours.
- 7 days: sum daily buckets whose timestamp is within the last 7 days.
- 30 days: sum daily buckets whose timestamp is within the last 30 days.
- The current partial hour/day is included, matching `vnstat` semantics.
- "This month" uses the current calendar-month bucket from `vnstat`.
- The monthly budget uses the physical interface because it best matches the provider's quota.
- The UI reports how many days of history are available when the requested 30-day window is incomplete.

The tool reads `vnstat`; it does not maintain a second usage database.

### Live throughput

- `/proc/net/dev` is sampled every second for the selected interface.
- Throughput is `(current_bytes - previous_bytes) / elapsed_seconds`.
- The dashboard keeps the latest 60 samples for sparkline-style charts.
- The default selected interface is the physical uplink. `i` switches to the VPN when available.
- Sampling stops when the dashboard is paused or closed.

### Local network

- `ip -j address show` supplies addresses and MAC.
- `ip -j route show default` supplies the gateway.
- `nmcli -g IP4.DNS device show <iface>` supplies DNS servers.
- `iw dev <iface> link` supplies SSID, frequency, signal, and RX/TX bitrates for Wi-Fi.
- Non-Wi-Fi interfaces omit Wi-Fi-specific fields.
- Latency to the gateway and `1.1.1.1` uses three ICMP packets when permitted. If ICMP is blocked, NPL falls back to three TCP connection attempts (gateway `:53`, `1.1.1.1:443`) and needs no root privileges.

### Speed test

- A speed test in the interactive dashboard starts only after the user confirms the expected data use.
- Invoking `npl --speedtest` is itself an explicit opt-in and runs the test directly.
- Default transfer sizes are 10,000,000 bytes down and 2,000,000 bytes up, about 12 MB total.
- Download: Cloudflare `https://speed.cloudflare.com/__down?bytes=<n>`.
- Upload: Cloudflare `https://speed.cloudflare.com/__up` with generated non-personal payload bytes.
- `curl` reports the effective byte rate; JSON stores bit/s and the UI displays Mbit/s. Live throughput uses binary byte units per second.
- Download timeout is 30 seconds and upload timeout is 30 seconds.
- Latency is measured separately against `1.1.1.1`, using ICMP when permitted or the TCP fallback.
- Failures, timeouts, and non-2xx responses produce a visible error instead of partial misleading results.
- The test result remains visible for the current session; it is not added to a separate history database.

## 8. Aggregation and Formatting

`formatting.py` provides tested functions for:

- Summing RX/TX pairs inside a rolling time window.
- Converting bytes to IEC units for display (`KiB`, `MiB`, `GiB`, `TiB`).
- Producing short fixed-width sparkline strings.
- Formatting percentages and the monthly budget bar.
- Formatting durations, latency, link rates, and missing values.
- Reporting available history when `vnstat` data is incomplete.

Aggregation functions accept an explicit `now` timestamp so tests are deterministic.

## 9. Configuration

The optional file is `~/.config/npl/config.toml`. Missing values use built-in defaults.

```toml
monthly_budget_gb = 0          # 0 disables the budget indicator
ip_refresh_seconds = 60
usage_refresh_seconds = 60
local_refresh_seconds = 30
speedtest_down_bytes = 10000000
speedtest_up_bytes = 2000000
physical_interface = ""        # empty means auto-detect
vpn_interface = ""             # empty means auto-detect
```

Invalid TOML or invalid values fall back to defaults and display a non-fatal warning. NPL never writes configuration on its own.

## 10. JSON Output

`npl --json` prints one JSON object and exits. The top-level shape is:

```json
{
  "timestamp": "2026-10-27T14:42:10+02:00",
  "public": {
    "ipv4": "104.28.228.70",
    "ipv6": "2606:4700:110:8ad9:f384:6900:9245:ad30",
    "isp": "Cloudflare, Inc.",
    "asn": "AS13335",
    "city": "Alexandria",
    "region": "Alexandria",
    "country": "EG",
    "vpn_active": true,
    "stale_seconds": 0
  },
  "usage": {
    "physical": {
      "interface": "wlp3s0",
      "last_24h": {"rx": 0, "tx": 0},
      "last_48h": {"rx": 0, "tx": 0},
      "last_7d": {"rx": 0, "tx": 0},
      "last_30d": {"rx": 0, "tx": 0},
      "this_month": {"rx": 0, "tx": 0},
      "daily_series": [0, 0, 0, 0, 0, 0, 0],
      "days_available": 27
    },
    "vpn": {
      "interface": "CloudflareWARP",
      "last_24h": {"rx": 0, "tx": 0},
      "last_48h": {"rx": 0, "tx": 0},
      "last_7d": {"rx": 0, "tx": 0},
      "last_30d": {"rx": 0, "tx": 0},
      "this_month": {"rx": 0, "tx": 0},
      "daily_series": [0, 0, 0, 0, 0, 0, 0],
      "days_available": 8
    }
  },
  "budget": {
    "used": 0,
    "limit": null
  },
  "local": {
    "hostname": "t9-iMac",
    "interface": "wlp3s0",
    "ipv4": "192.168.1.46/24",
    "ipv6": "fe80::1822:a73:79ff:98ab/64",
    "gateway": "192.168.1.1",
    "mac": "e4:ce:8f:67:1e:bc",
    "dns": ["8.8.8.8", "8.8.4.4"],
    "ssid": "WEA49217",
    "signal_dbm": -64,
    "rx_bitrate_mbps": 78.0,
    "tx_bitrate_mbps": 300.0
  },
  "latency": {
    "gateway_ms": 2,
    "internet_ms": 27
  },
  "speedtest": null
}
```

Unavailable values are `null` or `"N/A"` as appropriate. The JSON mode must not start the Textual UI or require an interactive terminal.

## 11. Error Handling

- Startup checks report missing `vnstat`, `ip`, `nmcli`, `iw`, `curl`, or `ping`; only the affected panel is disabled.
- A stopped `vnstat` service or empty database produces `N/A` with a reason.
- Offline operation shows stale public IP data and its age when available.
- Missing IPv6 or VPN support produces `N/A` or `VPN: OFF`.
- External commands use argument lists, no shell interpolation, finite timeouts, and explicit error capture.
- Invalid command output is treated as unavailable data rather than a crash.
- Terminal resize below the minimum size shows a readable warning.
- Speed-test failures preserve the dashboard and report the failing stage.
- The application never requests root and never opens a listening port.

## 12. Security and Privacy

- No telemetry or analytics.
- The only remote calls are to `ipinfo.io` for IP metadata, Cloudflare for speed testing, and ICMP/TCP latency probes to the configured gateway and `1.1.1.1`.
- No API keys, credentials, or personal payloads are stored.
- Speed-test upload payloads are generated bytes.
- Subprocesses are invoked without `shell=True`.
- Interface names are validated against `ip` output.
- Cache/config directories are private to the user.

## 13. Testing

Tests use `unittest` and synthetic fixtures:

- Rolling-window aggregation for 24/48 hours and 7/30 days.
- Current partial bucket handling.
- `vnstat` JSON parsing, including missing interfaces and empty traffic.
- `ip -j` parsing and interface selection.
- IPv4/IPv6 IP-info parsing and ASN/ISP extraction.
- Cache freshness and stale-cache behavior.
- Byte, rate, latency, and percentage formatting.
- Configuration defaults and invalid TOML handling.
- Speed-test output parsing and failure handling.

Verification commands:

```bash
cd /home/t9/npl
python3 -m unittest discover -s tests -v
./npl.py --once
./npl.py --json | jq .
```

A final manual check launches the interactive dashboard and confirms that timers, key bindings, and resizing work. A live speed test is run at most once because it consumes about 12 MB.

## 14. Acceptance Criteria

- IPv4, IPv6, ISP, ASN, city, region, and country are displayed.
- 24/48/7/30-day values match the corresponding `vnstat` sums and remain separated between physical and VPN interfaces.
- Live upload/download values update without freezing the UI.
- The speed test returns download, upload, and latency results or a clear failure.
- LAN, gateway, DNS, MAC, and Wi-Fi values match system tools.
- `npl --once` and `npl --json` work without an interactive terminal.
- No root privileges or additional background service are required.
- Missing data and offline operation do not crash the application.

## 15. Known Risks and Limitations

- `vnstat` history may not cover 30 days; the UI reports the shorter available range.
- With a VPN active, public ISP and location describe the exit node, not the physical ISP.
- Physical-interface totals include VPN overhead and some LAN traffic; this is the closest available approximation to provider quota.
- Speed-test results vary by server, VPN route, Wi-Fi conditions, and network load.
- Cloudflare's speed-test endpoints may be blocked on some networks; the UI reports that failure.
- Textual is an external runtime dependency, already installed on the target machine and pinned in `requirements.txt`.
