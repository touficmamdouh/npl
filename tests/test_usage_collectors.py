import tempfile
import unittest
from io import StringIO
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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

    def test_parse_nettop_ignores_trailing_empty_csv_field(self):
        rows = parse_nettop("bytes_in,bytes_out\ntime,Safari.42,2048,1024,\n")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rx_bytes, 2048)

    def test_parse_nethogs_accepts_finite_exponent_numbers(self):
        rows = parse_nethogs_trace("/usr/bin/curl/42/1000\t1e+06\t2e+06\n")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].tx_bytes, 1_000_000)
        self.assertEqual(rows[0].rx_bytes, 2_000_000)


class TestDeltaTracker(unittest.TestCase):
    def _row(
        self, rx: int, tx: int, pid: int = 42, session: str | None = None
    ) -> CumulativeProcessUsage:
        return CumulativeProcessUsage(
            source="test",
            process_key=f"curl:/usr/bin/curl:{pid}",
            name="curl",
            path="/usr/bin/curl",
            pid=pid,
            session=session or f"{pid}:1",
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
        tracker.update([self._row(100, 50, pid=42, session="old")], OBSERVED)

        rows = tracker.update([self._row(300, 100, pid=42, session="new")], OBSERVED)

        self.assertEqual(rows, [])


class _FakeProcess:
    def __init__(self, output: str):
        self.stdout = StringIO(output)
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


class TestNethogsCollector(unittest.TestCase):
    def test_reports_capture_permission_when_nethogs_exits_with_error(self):
        fake_process = _FakeProcess(
            "Failed to get interface addresses\n"
            "No devices to monitor.\n"
        )
        fake_process.returncode = 1
        with patch("usage_collectors.subprocess.Popen", return_value=fake_process):
            collector = NethogsCollector(interval=5)

            with self.assertRaisesRegex(CollectorUnavailable, "No devices to monitor"):
                collector.collect()

    def test_reuses_one_long_lived_process_for_multiple_refreshes(self):
        output = (
            "Refreshing:\n"
            "/usr/bin/curl/42/1000\t100\t200\n"
            "Refreshing:\n"
            "/usr/bin/curl/42/1000\t300\t500\n"
            "Refreshing:\n"
        )
        fake_process = _FakeProcess(output)
        with patch("usage_collectors.subprocess.Popen", return_value=fake_process) as popen:
            collector = NethogsCollector(interval=5)
            first = collector.collect()
            second = collector.collect()
            collector.close()

        self.assertEqual(first[0].tx_bytes, 100)
        self.assertEqual(second[0].rx_bytes, 500)
        popen.assert_called_once()


class TestCollectorSelection(unittest.TestCase):
    def test_selects_platform_collectors(self):
        self.assertIs(select_usage_collector("linux"), NethogsCollector)
        self.assertIs(select_usage_collector("darwin"), NettopCollector)

    def test_rejects_unsupported_platform(self):
        with self.assertRaises(CollectorUnavailable):
            select_usage_collector("windows")


if __name__ == "__main__":
    unittest.main()
