import unittest

from npl import APP_VERSION, build_parser


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


if __name__ == "__main__":
    unittest.main()
