import tempfile
import unittest
from unittest.mock import patch
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
            self.assertEqual(calls, [["systemctl", "--user", "--version"]])

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
            self.assertIn("<key>KeepAlive</key>\n    <false/>", path.read_text())
            self.assertEqual(calls, [["launchctl", "help"]])

    def test_start_and_stop_use_user_service_managers(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            install_usage_service(
                system="Linux",
                home=home,
                executable="/usr/bin/npl",
                runner=lambda args: None,
            )
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
            path = install_usage_service(
                system="Darwin",
                home=home,
                executable="/usr/bin/npl",
                runner=lambda args: None,
            )
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

    def test_appimage_path_is_preferred_when_no_npl_is_on_path(self):
        with patch("usage_services.shutil.which", return_value=None), patch.dict(
            "os.environ", {"APPIMAGE": "/opt/npl/npl.AppImage"}, clear=False
        ):
            with tempfile.TemporaryDirectory() as directory:
                path = install_usage_service(
                    system="Linux",
                    home=Path(directory),
                    runner=lambda args: None,
                )
                self.assertIn("ExecStart=/opt/npl/npl.AppImage usage record", path.read_text())

    def test_install_rejects_missing_service_manager_before_writing(self):
        class FailedResult:
            returncode = 1

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with self.assertRaises(ServiceUnavailable):
                install_usage_service(
                    system="Linux",
                    home=home,
                    executable="/usr/bin/npl",
                    runner=lambda args: FailedResult(),
                )

            self.assertFalse((home / ".config/systemd/user/npl-usage.service").exists())


if __name__ == "__main__":
    unittest.main()
