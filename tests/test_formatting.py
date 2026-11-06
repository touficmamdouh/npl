import unittest
from datetime import datetime, timedelta, timezone

from formatting import format_budget, format_bytes, format_latency, format_rate, sparkline
from formatting import available_days, daily_series, month_usage, usage_windows
from formatting import render_dashboard


NOW = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)


def entry(seconds_ago, rx, tx):
    return {"timestamp": NOW.timestamp() - seconds_ago, "rx": rx, "tx": tx}


class TestFormattingPrimitives(unittest.TestCase):
    def test_format_bytes_uses_iec_units(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.0 KiB")
        self.assertEqual(format_bytes(1536), "1.5 KiB")
        self.assertEqual(format_bytes(None), "N/A")

    def test_format_rate_adds_per_second_suffix(self):
        self.assertEqual(format_rate(1024), "1.0 KiB/s")
        self.assertEqual(format_rate(None), "N/A")

    def test_format_latency_keeps_one_decimal_below_ten(self):
        self.assertEqual(format_latency(2.25), "2.2 ms")
        self.assertEqual(format_latency(27.4), "27 ms")
        self.assertEqual(format_latency(None), "N/A")

    def test_sparkline_uses_latest_values_and_scales_them(self):
        self.assertEqual(sparkline([1, 2, 3], width=3), "▁▅█")
        self.assertEqual(sparkline([], width=3), "")
        self.assertEqual(sparkline([5, 5], width=2), "▄▄")

    def test_format_budget_handles_unset_and_half_full(self):
        self.assertEqual(format_budget(0, None), "not set")
        self.assertEqual(format_budget(512, 1024, width=10), "[█████░░░░░]  50.0%")


class TestUsageAggregation(unittest.TestCase):
    def setUp(self):
        self.traffic = {
            "hour": [
                entry(3600, 100, 10),
                entry(25 * 3600, 200, 20),
                entry(49 * 3600, 400, 40),
            ],
            "day": [
                entry(0, 1000, 100),
                entry(6 * 86400, 2000, 200),
                entry(8 * 86400, 4000, 400),
                entry(31 * 86400, 8000, 800),
            ],
            "month": [
                {"timestamp": NOW.timestamp(), "rx": 5000, "tx": 500},
                {
                    "timestamp": datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp(),
                    "rx": 999,
                    "tx": 999,
                },
            ],
        }

    def test_usage_windows_sum_the_correct_ranges(self):
        result = usage_windows(self.traffic, NOW)
        self.assertEqual(result["last_24h"], {"rx": 100, "tx": 10})
        self.assertEqual(result["last_48h"], {"rx": 300, "tx": 30})
        self.assertEqual(result["last_7d"], {"rx": 3000, "tx": 300})
        self.assertEqual(result["last_30d"], {"rx": 7000, "tx": 700})

    def test_available_days_reports_capped_history_span(self):
        days = [entry(0, 1, 0), entry(6 * 86400, 1, 0), entry(8 * 86400, 1, 0)]
        self.assertEqual(available_days(days, NOW), 9)
        self.assertEqual(available_days([], NOW), 0)

    def test_month_usage_uses_current_calendar_month_only(self):
        self.assertEqual(month_usage(self.traffic, NOW), {"rx": 5000, "tx": 500})

    def test_daily_series_returns_seven_ordered_days(self):
        self.assertEqual(
            daily_series(self.traffic["day"], NOW),
            [2200, 0, 0, 0, 0, 0, 1100],
        )


class TestDashboardRendering(unittest.TestCase):
    def test_render_dashboard_contains_requested_fields(self):
        snapshot = {
            "timestamp": "2026-10-27T14:42:10+02:00",
            "public": {
                "ipv4": "203.0.113.10",
                "ipv6": "2001:db8::10",
                "isp": "Example ISP",
                "asn": "AS64500",
                "city": "Alexandria",
                "region": "Alexandria",
                "country": "EG",
                "vpn_active": True,
                "stale_seconds": 0,
            },
            "usage": {
                "physical": {
                    "interface": "wlp3s0",
                    "last_24h": {"rx": 1024, "tx": 512},
                    "last_48h": {"rx": 2048, "tx": 1024},
                    "last_7d": {"rx": 4096, "tx": 2048},
                    "last_30d": {"rx": 8192, "tx": 4096},
                    "this_month": {"rx": 512, "tx": 512},
                    "daily_series": [1, 2, 3, 4, 5, 6, 7],
                    "days_available": 27,
                },
                "vpn": {
                    "interface": "CloudflareWARP",
                    "last_24h": {"rx": 512, "tx": 256},
                    "last_48h": {"rx": 1024, "tx": 512},
                    "last_7d": {"rx": 2048, "tx": 1024},
                    "last_30d": {"rx": 4096, "tx": 2048},
                    "this_month": {"rx": 256, "tx": 256},
                    "daily_series": [1, 1, 1, 1, 1, 1, 1],
                    "days_available": 8,
                },
            },
            "budget": {"used": 512, "limit": 1024},
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
                "tx_bitrate_mbps": 300.0,
            },
            "latency": {"gateway_ms": 2.0, "internet_ms": 27.4},
            "speedtest": None,
        }
        output = render_dashboard(
            snapshot,
            samples=[(1024.0, 512.0)],
            selected_interface="wlp3s0",
        )
        self.assertIn("NPL", output)
        self.assertIn("203.0.113.10", output)
        self.assertIn("Example ISP", output)
        self.assertIn("24 hours", output)
        self.assertIn("50.0%", output)
        self.assertIn("wlp3s0", output)
        self.assertIn("1.0 KiB/s", output)
        self.assertIn("VPN exit node", output)
        self.assertIn("[t]", output)
        self.assertIn("History available", output)

    def test_render_dashboard_handles_missing_values(self):
        snapshot = {
            "timestamp": "2026-10-27T14:42:10+02:00",
            "public": {"vpn_active": False},
            "usage": {"physical": {}, "vpn": {}},
            "budget": {"used": 0, "limit": None},
            "local": {},
            "latency": {},
            "speedtest": None,
        }
        output = render_dashboard(snapshot)
        self.assertIn("N/A", output)
        self.assertIn("not set", output)

    def test_render_dashboard_formats_speedtest_as_megabits(self):
        snapshot = {
            "timestamp": "2026-10-27T14:42:10+02:00",
            "public": {"vpn_active": False},
            "usage": {"physical": {}, "vpn": {}},
            "budget": {"used": 0, "limit": None},
            "local": {},
            "latency": {},
            "speedtest": {
                "download_bps": 8_000_000,
                "upload_bps": 4_000_000,
                "latency_ms": 10.0,
                "bytes_used": 12_000_000,
                "error": None,
            },
        }
        output = render_dashboard(snapshot)
        self.assertIn("8.0 Mbit/s", output)
        self.assertIn("4.0 Mbit/s", output)


if __name__ == "__main__":
    unittest.main()
