"""Install and control per-user background usage collectors."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence


class ServiceUnavailable(RuntimeError):
    """The requested user-service manager is unavailable."""


Runner = Callable[[Sequence[str]], object]


def _normalized_system(system: str | None) -> str:
    return (system or platform.system()).lower()


def _service_path(system: str, home: Path) -> Path:
    if system == "linux":
        return home / ".config" / "systemd" / "user" / "npl-usage.service"
    if system == "darwin":
        return home / "Library" / "LaunchAgents" / "com.npl.usage.plist"
    raise ServiceUnavailable(f"usage services are unsupported on {system}")


def _executable(executable: str | None) -> str:
    if executable:
        return executable
    return shutil.which("npl") or str(Path(sys.argv[0]).resolve())


def _linux_unit(executable: str) -> str:
    return f"""[Unit]
Description=NPL per-process network usage recorder

[Service]
Type=simple
ExecStart={executable} usage record
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def _macos_plist(executable: str, home: Path) -> str:
    log_path = home / "Library" / "Logs" / "npl-usage.log"
    error_path = home / "Library" / "Logs" / "npl-usage.error.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.npl.usage</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
        <string>usage</string>
        <string>record</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{error_path}</string>
</dict>
</plist>
"""


def install_usage_service(
    system: str | None = None,
    home: Path | None = None,
    executable: str | None = None,
    runner: Runner | None = None,
) -> Path:
    del runner
    system = _normalized_system(system)
    home = home or Path.home()
    path = _service_path(system, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        _linux_unit(_executable(executable))
        if system == "linux"
        else _macos_plist(_executable(executable), home)
    )
    path.write_text(content, encoding="utf-8")
    return path


def _run(args: Sequence[str], runner: Runner | None = None) -> None:
    if runner is not None:
        result = runner(args)
        if result is None:
            return
        returncode = getattr(result, "returncode", 0)
        if returncode not in (None, 0):
            raise ServiceUnavailable(f"command failed: {' '.join(args)}")
        return
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise ServiceUnavailable(f"{args[0]} is not installed") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise ServiceUnavailable(f"{' '.join(args)}: {detail}")


def start_usage_service(
    system: str | None = None,
    home: Path | None = None,
    runner: Runner | None = None,
) -> None:
    system = _normalized_system(system)
    home = home or Path.home()
    path = _service_path(system, home)
    if not path.exists():
        raise ServiceUnavailable(f"install the usage service first: {path}")
    if system == "linux":
        _run(["systemctl", "--user", "enable", "--now", "npl-usage.service"], runner)
    else:
        _run(["launchctl", "load", str(path)], runner)


def stop_usage_service(
    system: str | None = None,
    home: Path | None = None,
    runner: Runner | None = None,
) -> None:
    system = _normalized_system(system)
    home = home or Path.home()
    path = _service_path(system, home)
    if system == "linux":
        _run(["systemctl", "--user", "disable", "--now", "npl-usage.service"], runner)
    else:
        _run(["launchctl", "unload", str(path)], runner)


def uninstall_usage_service(
    system: str | None = None,
    home: Path | None = None,
    runner: Runner | None = None,
) -> None:
    system = _normalized_system(system)
    home = home or Path.home()
    path = _service_path(system, home)
    stop_usage_service(system, home, runner)
    if path.exists():
        path.unlink()

