import unittest
from unittest.mock import Mock, patch

from npl import APP_VERSION, NplApp, SAMPLE_INTERVAL_SECONDS, build_parser


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


if __name__ == "__main__":
    unittest.main()
