import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from collectors import read_ip_info, run_speedtest
from formatting import available_days, daily_series, month_usage, usage_windows


class TestRobustness(unittest.TestCase):
    def test_malformed_ip_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "ip.json"
            cache.write_text(json.dumps({"timestamp": "bad", "v4": {}}))
            result = read_ip_info(
                False,
                cache_path=cache,
                now=datetime.now(timezone.utc),
                fetcher=lambda family: None,
            )
        self.assertIsNone(result.ipv4)

    def test_malformed_usage_bucket_is_skipped(self):
        result = usage_windows(
            {"hour": [{"timestamp": "bad", "rx": "bad", "tx": 2}]},
            datetime.now(timezone.utc),
        )
        self.assertEqual(result["last_24h"], {"rx": 0, "tx": 0})

    def test_all_usage_views_skip_malformed_buckets(self):
        traffic = {
            "day": [{"timestamp": "bad", "rx": "bad", "tx": 2}],
            "month": [{"timestamp": "bad", "rx": "bad", "tx": 2}],
        }
        now = datetime.now(timezone.utc)
        self.assertEqual(available_days(traffic["day"], now), 0)
        self.assertEqual(daily_series(traffic["day"], now), [0] * 7)
        self.assertEqual(month_usage(traffic, now), {"rx": 0, "tx": 0})

    def test_speedtest_rejects_oversized_upload_before_allocating(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("runner should not be called")

        result = run_speedtest(up_bytes=100_000_001, runner=runner)
        self.assertEqual(calls, [])
        self.assertEqual(result["error"], "upload size too large")


if __name__ == "__main__":
    unittest.main()
