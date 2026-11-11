import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from usage_store import UsageDelta, UsageStore, period_bounds


UTC = timezone.utc


def delta(
    observed_at: datetime,
    process_key: str = "browser:/usr/bin/browser",
    name: str = "browser",
    rx_bytes: int = 100,
    tx_bytes: int = 25,
) -> UsageDelta:
    return UsageDelta(
        observed_at=observed_at,
        source="test",
        process_key=process_key,
        name=name,
        path="/usr/bin/browser",
        pid=123,
        session="123:1",
        interface="eth0",
        rx_bytes=rx_bytes,
        tx_bytes=tx_bytes,
    )


class TestUsageStore(unittest.TestCase):
    def test_initializes_schema_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.db"
            UsageStore(path).close()
            UsageStore(path).close()

            with sqlite3.connect(path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertIn("usage_samples", tables)

    def test_records_and_aggregates_positive_deltas_by_process(self):
        now = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            store = UsageStore(Path(directory) / "usage.db")
            store.record_deltas(
                [
                    delta(now),
                    delta(now + timedelta(seconds=5), rx_bytes=300, tx_bytes=50),
                    delta(
                        now + timedelta(seconds=5),
                        process_key="sync:/usr/bin/sync",
                        name="sync",
                        rx_bytes=10,
                        tx_bytes=90,
                    ),
                ]
            )

            rows = store.summarize(now - timedelta(seconds=1), now + timedelta(seconds=6), 10)

            self.assertEqual([row.name for row in rows], ["browser", "sync"])
            self.assertEqual(rows[0].rx_bytes, 400)
            self.assertEqual(rows[0].tx_bytes, 75)
            self.assertEqual(rows[0].total_bytes, 475)
            self.assertEqual(rows[1].total_bytes, 100)
            self.assertEqual(rows[0].source, "test")
            store.close()

    def test_limit_and_empty_report(self):
        now = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            store = UsageStore(Path(directory) / "usage.db")
            self.assertEqual(store.summarize(now, now + timedelta(days=1), 20), [])
            store.record_deltas(
                [
                    delta(now, process_key="a", name="a"),
                    delta(now, process_key="b", name="b", rx_bytes=200),
                ]
            )
            rows = store.summarize(now - timedelta(seconds=1), now + timedelta(seconds=1), 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].name, "b")
            store.close()

    def test_prune_removes_samples_before_cutoff(self):
        now = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            store = UsageStore(Path(directory) / "usage.db")
            store.record_deltas([delta(now - timedelta(days=91)), delta(now)])

            removed = store.prune(now - timedelta(days=90))

            self.assertEqual(removed, 1)
            rows = store.summarize(now - timedelta(days=100), now + timedelta(days=1), 20)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].total_bytes, 125)
            store.close()

    def test_period_bounds_use_local_calendar(self):
        now = datetime(2026, 11, 11, 15, 30, tzinfo=timezone(timedelta(hours=2)))

        today_start, today_end = period_bounds("today", now)
        week_start, week_end = period_bounds("week", now)
        month_start, month_end = period_bounds("month", now)

        self.assertEqual(today_start, datetime(2026, 11, 11, tzinfo=now.tzinfo).timestamp())
        self.assertEqual(today_end, now.timestamp())
        self.assertEqual(week_start, (now - timedelta(days=7)).timestamp())
        self.assertEqual(week_end, now.timestamp())
        self.assertEqual(month_start, datetime(2026, 11, 1, tzinfo=now.tzinfo).timestamp())
        self.assertEqual(month_end, now.timestamp())


if __name__ == "__main__":
    unittest.main()
