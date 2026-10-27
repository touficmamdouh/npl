# npl

Terminal network dashboard for Linux Mint. It shows public IPv4/IPv6 details,
separate physical and VPN usage for 24/48 hours and 7/30 days, live throughput,
an on-demand speed test, and local network information.

## Requirements

- Python 3.14
- Textual 8.2.7
- `vnstat`, `ip`, `nmcli`, `iw`, `curl`, `ping`

Install the Python dependency if it is missing:

```bash
python3 -m pip install --user -r requirements.txt
```

Install the command launcher:

```bash
mkdir -p ~/.local/bin
ln -sfn "$PWD/bin/npl" ~/.local/bin/npl
```

## Run

```bash
npl
npl --once
npl --json
npl --speedtest
npl --interface wlp3s0
```

Interactive keys:

- `q` quit
- `r` refresh IP, usage, and local data
- `t` speed test, confirmed by pressing `t` again
- `i` switch live throughput between physical and VPN interfaces
- `p` pause or resume live throughput
- `?` show help

## Configuration

Copy `npl.toml.example` to `~/.config/npl/config.toml` and edit it. A
`monthly_budget_gb` of `0` disables the budget bar. The speed-test defaults
consume about 12 MB per run.

## Data Sources

- `vnstat --json` supplies 24/48-hour and 7/30-day usage.
- `/proc/net/dev` supplies live throughput.
- `ipinfo.io` supplies public IP metadata.
- Cloudflare speed endpoints supply the on-demand speed test.
- `ip`, `nmcli`, `iw`, and `ping` supply local network details.

Physical and VPN usage are always separate and never added together. The
monthly budget uses the physical interface because it best matches the
provider quota.

When ICMP is unavailable, latency falls back to TCP connection time for the
gateway (`:53`) and `1.1.1.1` (`:443`), so the tool does not need root.

## Privacy and Safety

NPL requires no root privileges, starts no daemon, and opens no listening
port. It has no telemetry. It contacts only `ipinfo.io`, Cloudflare's
speed-test endpoints, and the configured gateway/`1.1.1.1` for latency.

## Limitations

- With a VPN active, public ISP and location describe the VPN exit node.
- Physical usage includes VPN overhead and some LAN traffic.
- `vnstat` history may be shorter than 30 days.
- A speed test consumes about 12 MB.
- Speed-test rates are reported in Mbit/s.
- Cloudflare's speed-test endpoints may be blocked on some networks.
- IPv6 is shown as `N/A` when the machine has no global IPv6 route.

## Verify

```bash
python3 -m unittest discover -s tests -v
npl --once
npl --json | python3 -m json.tool >/dev/null
```
