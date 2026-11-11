import unittest
import io
import tempfile
from unittest.mock import Mock, patch
from contextlib import redirect_stderr

from npl import (
    APP_VERSION,
    NplApp,
    SAMPLE_INTERVAL_SECONDS,
    build_parser,
    run_usage_record,
)
from usage_collectors import CollectorUnavailable


class TestCli(unittest.TestCase):
    def test_json_and_interface_flags(self):
        args = build_parser().parse_args(["--json", "--interface", "wlp3s0"])
        self.assertTrue(args.json)
        self.assertEqual(args.interface, "wlp3s0")

    def test_once_and_speedtest_flags_are_independent(self):
        args = build_parser().parse_args(["--once", "--speedtest"])
        self.assertTrue(args.once)
        self.assertTrue(args.speedtest)

    def test_version_constant_is_defined(self):
        self.assertEqual(APP_VERSION, "0.1.0")

    def test_dashboard_sampling_is_not_more_frequent_than_two_seconds(self):
        self.assertGreaterEqual(SAMPLE_INTERVAL_SECONDS, 2.0)

    def test_tick_does_not_redraw_when_counters_are_unchanged(self):
        app = NplApp({"local": {"interface": "lo"}, "usage": {}}, {})
        app.update_view = Mock()
        with patch("npl.read_net_counters", return_value=(100, 200)):
            app.tick()
            app.tick()

        app.update_view.assert_not_called()

    def test_usage_period_command_accepts_report_options(self):
        args = build_parser().parse_args(
            ["usage", "week", "--json", "--limit", "5", "--database", "/tmp/usage.db"]
        )

        self.assertEqual(args.usage_command, "week")
        self.assertTrue(args.json)
        self.assertEqual(args.limit, 5)
        self.assertEqual(args.database, "/tmp/usage.db")

    def test_usage_period_flag_aliases_accept_report_periods(self):
        for period in ("today", "week", "month"):
            with self.subTest(period=period):
                args = build_parser().parse_args(["usage", f"--{period}"])

                self.assertEqual(args.usage_command, period)
                self.assertEqual(args.period, period)

    def test_usage_record_reports_collector_failure(self):
        args = build_parser().parse_args(["usage", "record"])
        error_output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch(
            "npl.iter_usage_samples",
            side_effect=CollectorUnavailable("nethogs permission denied"),
        ), redirect_stderr(error_output):
            args.database = f"{directory}/usage.db"
            result = run_usage_record(args)

        self.assertEqual(result, 1)
        self.assertIn("nethogs permission denied", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
