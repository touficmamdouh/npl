import tempfile
import unittest
from pathlib import Path

from usage_services import (
    ServiceUnavailable,
    install_usage_service,
    start_usage_service,
    stop_usage_service,
    uninstall_usage_service,
)


class TestUsageServices(unittest.TestCase):
    def test_install_linux_writes_unit_without_running_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            calls = []

            path = install_usage_service(
                system="Linux",
                home=home,
                executable="/home/test/.local/bin/npl",
                runner=lambda args: calls.append(args),
            )

            self.assertEqual(path, home / ".config/systemd/user/npl-usage.service")
            self.assertIn("ExecStart=/home/test/.local/bin/npl usage record", path.read_text())
            self.assertEqual(calls, [])

    def test_install_macos_writes_launch_agent_without_running_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            calls = []

            path = install_usage_service(
                system="Darwin",
                home=home,
                executable="/Users/test/.local/bin/npl",
                runner=lambda args: calls.append(args),
            )

            self.assertEqual(path, home / "Library/LaunchAgents/com.npl.usage.plist")
            self.assertIn("/Users/test/.local/bin/npl", path.read_text())
            self.assertEqual(calls, [])

    def test_start_and_stop_use_user_service_managers(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            install_usage_service(system="Linux", home=home, executable="/usr/bin/npl")
            calls = []

            start_usage_service(system="Linux", home=home, runner=lambda args: calls.append(args))
            stop_usage_service(system="Linux", home=home, runner=lambda args: calls.append(args))

            self.assertEqual(
                calls,
                [
                    ["systemctl", "--user", "enable", "--now", "npl-usage.service"],
                    ["systemctl", "--user", "disable", "--now", "npl-usage.service"],
                ],
            )

    def test_uninstall_removes_service_file_after_explicit_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = install_usage_service(system="Darwin", home=home, executable="/usr/bin/npl")
            calls = []

            uninstall_usage_service(
                system="Darwin",
                home=home,
                runner=lambda args: calls.append(args),
            )

            self.assertFalse(path.exists())
            self.assertEqual(calls, [["launchctl", "unload", str(path)]])

    def test_unsupported_platform_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ServiceUnavailable):
                install_usage_service(system="Windows", home=Path(directory))


if __name__ == "__main__":
    unittest.main()
