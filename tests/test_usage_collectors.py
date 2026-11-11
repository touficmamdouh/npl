import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from usage_collectors import (
    CollectorUnavailable,
    CumulativeProcessUsage,
    DeltaTracker,
    NethogsCollector,
    NettopCollector,
    parse_nethogs_trace,
    parse_nettop,
    select_usage_collector,
)


ROOT = Path(__file__).parents[1]
OBSERVED = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


class TestUsageParsers(unittest.TestCase):
    def test_parse_nethogs_trace_keeps_valid_process_rows(self):
        text = (ROOT / "tests/fixtures/nethogs_trace.txt").read_text()

        rows = parse_nethogs_trace(text)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].name, "curl")
        self.assertEqual(rows[0].path, "/usr/bin/curl")
        self.assertEqual(rows[0].pid, 42)
        self.assertEqual(rows[0].tx_bytes, 1000)
        self.assertEqual(rows[0].rx_bytes, 2000)
        self.assertEqual(rows[2].name, "unknown")

    def test_parse_nettop_csv_keeps_valid_process_rows(self):
        text = (ROOT / "tests/fixtures/nettop_sample.txt").read_text()

        rows = parse_nettop(text)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].name, "Safari")
        self.assertEqual(rows[0].pid, 42)
        self.assertEqual(rows[0].rx_bytes, 2048)
        self.assertEqual(rows[0].tx_bytes, 1024)


class TestDeltaTracker(unittest.TestCase):
    def _row(self, rx: int, tx: int, pid: int = 42) -> CumulativeProcessUsage:
        return CumulativeProcessUsage(
            source="test",
            process_key=f"curl:/usr/bin/curl:{pid}",
            name="curl",
            path="/usr/bin/curl",
            pid=pid,
            session=f"{pid}:1",
            interface="eth0",
            rx_bytes=rx,
            tx_bytes=tx,
        )

    def test_first_sample_sets_baseline_and_second_sample_emits_delta(self):
        tracker = DeltaTracker()

        self.assertEqual(tracker.update([self._row(100, 50)], OBSERVED), [])
        deltas = tracker.update([self._row(300, 100)], OBSERVED)

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].rx_bytes, 200)
        self.assertEqual(deltas[0].tx_bytes, 50)

    def test_counter_reset_and_process_disappearance_create_new_baselines(self):
        tracker = DeltaTracker()
        tracker.update([self._row(100, 50)], OBSERVED)

        self.assertEqual(tracker.update([self._row(10, 5)], OBSERVED), [])
        self.assertEqual(tracker.update([], OBSERVED), [])
        self.assertEqual(tracker.update([self._row(20, 10)], OBSERVED), [])

    def test_pid_reuse_does_not_mix_sessions(self):
        tracker = DeltaTracker()
        tracker.update([self._row(100, 50, pid=42)], OBSERVED)

        rows = tracker.update([self._row(300, 100, pid=43)], OBSERVED)

        self.assertEqual(rows, [])


class TestCollectorSelection(unittest.TestCase):
    def test_selects_platform_collectors(self):
        self.assertIs(select_usage_collector("linux"), NethogsCollector)
        self.assertIs(select_usage_collector("darwin"), NettopCollector)

    def test_rejects_unsupported_platform(self):
        with self.assertRaises(CollectorUnavailable):
            select_usage_collector("windows")


if __name__ == "__main__":
    unittest.main()
