# npl

Terminal network dashboard for Linux and macOS. It shows public IPv4/IPv6 details,
separate physical and VPN usage for 24/48 hours and 7/30 days, live throughput,
an on-demand speed test, and local network information.

## Requirements

- Python 3.11 or newer
- Textual 8.2.7
- Linux: `vnstat`, `nethogs`, `ip`, `nmcli`, `iw`, `curl`, `ping`
- macOS: `curl`, `ping`, `route`, `ifconfig`, `scutil` (optional Wi-Fi data uses `networksetup`)

## One-line install

Run as your normal user, not with `sudo`:

```bash
curl -fsSL https://raw.githubusercontent.com/touficmamdouh/npl/main/install.sh | bash
```

On Linux, the installer adds missing system packages, enables `vnstat`, grants
`nethogs` the limited `cap_net_admin` and `cap_net_raw` capabilities needed for
per-process capture, creates a private virtual environment for Textual, and
links the command as `/usr/local/bin/npl`. On macOS it skips Linux package
management and installs the launcher in `~/.local/bin/npl`.

## Manual install

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
npl usage today
npl usage week --json
npl usage month --limit 10

# Flag aliases are also supported
npl usage --today
npl usage --week --json
npl usage --month --limit 10
```

Interactive keys:

- `q` quit
- `r` refresh IP, usage, and local data
- `t` speed test, confirmed by pressing `t` again
- `i` switch live throughput between physical and VPN interfaces
- `p` pause or resume live throughput
- `?` show help

## Per-process usage history

The process history starts when the recorder starts; it cannot recover usage
from before that point. Install and start the user-level recorder explicitly:

```bash
npl usage install-service
npl usage start-service
```

Then query separate local periods:

```bash
npl usage today
npl usage week
npl usage month --json
```

Use `npl usage stop-service` to stop recording and `npl usage
uninstall-service` to remove the service file. Linux uses `nethogs` and may
need packet-capture capabilities; the installer configures them automatically.
macOS uses the built-in `nettop`. NPL never starts the service automatically
and keeps the history in a local SQLite database.

## Configuration

Copy `npl.toml.example` to `~/.config/npl/config.toml` and edit it. A
`monthly_budget_gb` of `0` disables the budget bar. The speed-test defaults
consume about 12 MB per run.

## Data Sources

- Linux `vnstat --json` supplies historical usage; macOS counter samples are
  stored locally while NPL runs.
- `/proc/net/dev` on Linux and `netstat -ib` on macOS supply interface counters.
- `ipinfo.io` supplies public IP metadata.
- Cloudflare speed endpoints supply the on-demand speed test.
- `ip`, `nmcli`, `iw`, and `ping` supply local network details.
- `nethogs` on Linux and `nettop` on macOS supply per-process counters for the
  local usage history.

Physical and VPN usage are always separate and never added together. The
monthly budget uses the physical interface because it best matches the
provider quota.

On macOS, NPL records interface counter deltas locally while it runs and uses
them for usage history. History starts with the first sample and grows while
NPL is running; it cannot reconstruct traffic from before NPL began collecting.
The history is stored in `~/.local/state/npl/usage-history.json` (or under
`$XDG_STATE_HOME/npl/usage-history.json`).

When ICMP is unavailable, latency falls back to TCP connection time for the
gateway (`:53`) and `1.1.1.1` (`:443`), so the tool does not need root.

## Privacy and Safety

NPL itself runs as the normal user, starts no daemon, and opens no listening
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

## Build distributable artifacts

Install the runtime and build dependencies in a build environment:

```bash
python3 -m pip install -r requirements.txt -r requirements-build.txt
```

Build a Linux AppImage (run on Linux, with `appimagetool` available):

```bash
./packaging/build-appimage.sh
```

This produces `npl-<architecture>.AppImage`. The AppImage is Linux-only. Build the
macOS terminal executable on macOS:

```bash
./packaging/build-macos-app.sh
```

The macOS build produces a PyInstaller executable for the current Mac
architecture. Cross-compiling between Linux and macOS is not supported.

## Verify

```bash
npl --once
npl --json | python3 -m json.tool >/dev/null
```
