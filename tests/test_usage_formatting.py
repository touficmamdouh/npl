import json
import unittest

from usage_formatting import render_usage_report
from usage_store import UsageTotal


class TestUsageFormatting(unittest.TestCase):
    def setUp(self):
        self.rows = [
            UsageTotal("browser", "browser", "/usr/bin/browser", "nethogs", 200, 100, 300),
            UsageTotal("sync", "sync", "/usr/bin/sync", "nethogs", 50, 50, 100),
        ]

    def test_text_report_has_direction_totals_and_share(self):
        output = render_usage_report(
            self.rows,
            period="today",
            source="nethogs",
            started_at="2026-11-11T10:00:00+00:00",
        )

        self.assertIn("Program", output)
        self.assertIn("RX", output)
        self.assertIn("TX", output)
        self.assertIn("Total", output)
        self.assertIn("browser", output)
        self.assertIn("75.0%", output)

    def test_json_report_has_stable_metadata_and_rows(self):
        output = render_usage_report(
            self.rows,
            period="week",
            source="nethogs",
            started_at="2026-11-04T10:00:00+00:00",
            json_output=True,
        )

        payload = json.loads(output)
        self.assertEqual(payload["period"], "week")
        self.assertEqual(payload["source"], "nethogs")
        self.assertEqual(payload["total_bytes"], 400)
        self.assertEqual(payload["rows"][0]["name"], "browser")
        self.assertEqual(payload["rows"][0]["rx_bytes"], 200)
        self.assertEqual(payload["rows"][0]["share_percent"], 75.0)

    def test_share_uses_period_total_not_displayed_limit_total(self):
        output = render_usage_report(
            self.rows[:1],
            period="today",
            source="nethogs",
            started_at=None,
            total_bytes=400,
            json_output=True,
        )

        self.assertEqual(json.loads(output)["rows"][0]["share_percent"], 75.0)

    def test_empty_report_explains_that_recording_has_not_started(self):
        output = render_usage_report(
            [],
            period="month",
            source=None,
            started_at=None,
        )

        self.assertIn("No usage data recorded", output)


if __name__ == "__main__":
    unittest.main()
