import unittest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from collectors import (
    DEFAULT_CONFIG,
    CommandResult,
    enrich_local,
    load_config,
    parse_network,
    ping_average,
    rates_from_counters,
    read_ip_info,
    read_net_counters,
    read_vnstat,
    run_speedtest,
    NetworkInfo,
    PublicIPInfo,
    collect_snapshot,
)


ADDRESS_JSON = [
    {
        "ifname": "lo",
        "address": "00:00:00:00:00:00",
        "addr_info": [
            {"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"}
        ],
    },
    {
        "ifname": "wlp3s0",
        "address": "e4:ce:8f:67:1e:bc",
        "addr_info": [
            {
                "family": "inet",
                "local": "192.168.1.46",
                "prefixlen": 24,
                "scope": "global",
            },
            {
                "family": "inet6",
                "local": "fe80::1822:a73:79ff:98ab",
                "prefixlen": 64,
                "scope": "link",
            },
        ],
    },
    {
        "ifname": "CloudflareWARP",
        "address": "00:00:00:00:00:00",
        "addr_info": [
            {
                "family": "inet",
                "local": "172.16.0.2",
                "prefixlen": 32,
                "scope": "global",
            }
        ],
    },
]

ROUTES = [
    {
        "dst": "default",
        "gateway": "192.168.1.1",
        "dev": "wlp3s0",
        "metric": 20600,
    }
]

NMCLI = "\n".join(
    [
        "wlp3s0:wifi:connected:WEA49217",
        "CloudflareWARP:tun:connected (externally):CloudflareWARP",
    ]
)

IW = "\n".join(
    [
        "Connected to b4:6e:08:a4:92:2c (on wlp3s0)",
        "\tSSID: WEA49217",
        "\tsignal: -64 dBm",
        "\trx bitrate: 78.0 MBit/s MCS 12",
        "\ttx bitrate: 300.0 MBit/s MCS 15 40MHz short GI",
    ]
)


class TestNetworkDiscovery(unittest.TestCase):
    def test_parse_network_selects_physical_and_vpn_interfaces(self):
        info = parse_network(ADDRESS_JSON, ROUTES, NMCLI, "t9-iMac")
        self.assertEqual(info.hostname, "t9-iMac")
        self.assertEqual(info.physical_interface, "wlp3s0")
        self.assertEqual(info.vpn_interface, "CloudflareWARP")
        self.assertEqual(info.gateway, "192.168.1.1")
        self.assertEqual(info.ipv4, "192.168.1.46/24")
        self.assertEqual(info.ipv6, "fe80::1822:a73:79ff:98ab/64")
        self.assertEqual(info.mac, "e4:ce:8f:67:1e:bc")

    def test_enrich_local_parses_dns_and_wifi(self):
        info = parse_network(ADDRESS_JSON, ROUTES, NMCLI, "t9-iMac")
        enriched = enrich_local(info, "8.8.8.8 | 8.8.4.4", IW)
        self.assertEqual(enriched.dns, ["8.8.8.8", "8.8.4.4"])
        self.assertEqual(enriched.ssid, "WEA49217")
        self.assertEqual(enriched.signal_dbm, -64)
        self.assertEqual(enriched.rx_bitrate_mbps, 78.0)
        self.assertEqual(enriched.tx_bitrate_mbps, 300.0)

    def test_preferred_interface_overrides_default_route(self):
        info = parse_network(
            ADDRESS_JSON,
            ROUTES,
            NMCLI,
            "t9-iMac",
            preferred="CloudflareWARP",
        )
        self.assertEqual(info.physical_interface, "CloudflareWARP")
        self.assertIsNone(info.gateway)


IP_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


class TestPublicIPInfo(unittest.TestCase):
    def test_read_ip_info_fetches_and_then_uses_cache(self):
        calls = []

        def fetcher(family):
            calls.append(family)
            if family == "4":
                return {
                    "ip": "203.0.113.10",
                    "city": "Alexandria",
                    "region": "Alexandria",
                    "country": "EG",
                    "org": "AS64500 Example ISP",
                }
            return {"ip": "2001:db8::10"}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "ip.json"
            first = read_ip_info(
                False,
                cache_path=cache_path,
                now=IP_NOW,
                fetcher=fetcher,
            )
            self.assertEqual(calls, ["4", "6"])
            self.assertEqual(first.ipv4, "203.0.113.10")
            self.assertEqual(first.ipv6, "2001:db8::10")
            self.assertEqual(first.isp, "Example ISP")
            self.assertEqual(first.asn, "AS64500")
            self.assertEqual(first.city, "Alexandria")
            self.assertEqual(first.stale_seconds, 0)

            calls.clear()
            cached = read_ip_info(
                True,
                cache_path=cache_path,
                now=IP_NOW + timedelta(minutes=5),
                fetcher=fetcher,
            )
            self.assertEqual(calls, [])
            self.assertTrue(cached.vpn_active)
            self.assertEqual(cached.ipv4, "203.0.113.10")

    def test_read_ip_info_falls_back_to_stale_cache(self):
        def fetcher(family):
            return {"ip": "203.0.113.10"} if family == "4" else None

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "ip.json"
            read_ip_info(False, cache_path=cache_path, now=IP_NOW, fetcher=fetcher)
            stale = read_ip_info(
                False,
                cache_path=cache_path,
                now=IP_NOW + timedelta(minutes=20),
                fetcher=lambda family: None,
            )
            self.assertEqual(stale.ipv4, "203.0.113.10")
            self.assertGreaterEqual(stale.stale_seconds, 600)

    def test_parse_org_without_asn_keeps_organization(self):
        def fetcher(family):
            if family == "4":
                return {"ip": "203.0.113.10", "org": "Plain Network"}
            return None

        with tempfile.TemporaryDirectory() as tmp:
            result = read_ip_info(
                False,
                cache_path=Path(tmp) / "ip.json",
                now=IP_NOW,
                fetcher=fetcher,
            )
        self.assertIsNone(result.asn)
        self.assertEqual(result.isp, "Plain Network")


class TestNetworkCollectors(unittest.TestCase):
    def test_read_vnstat_extracts_matching_interface(self):
        fixture = (Path(__file__).parent / "fixtures" / "vnstat.json").read_text()

        def runner(args, timeout=5, input_data=None):
            return CommandResult(fixture, True, "")

        traffic = read_vnstat("wlp3s0", runner=runner)
        self.assertEqual(traffic["hour"][0]["rx"], 1000)
        self.assertEqual(traffic["day"][0]["tx"], 500)
        self.assertEqual(read_vnstat("missing", runner=runner), {})

    def test_read_net_counters_parses_rx_and_tx(self):
        content = "\n".join(
            [
                "Inter-|   Receive|  Transmit",
                " face |bytes    packets|bytes    packets",
                "wlp3s0: 1000 1 0 0 0 0 0 0 2000 1 0 0 0 0 0 0",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dev"
            path.write_text(content)
            self.assertEqual(read_net_counters("wlp3s0", proc_path=path), (1000, 2000))
            self.assertIsNone(read_net_counters("missing", proc_path=path))

    def test_rates_from_counters_handles_elapsed_time(self):
        self.assertEqual(
            rates_from_counters((1000, 2000), (2000, 3000), 2.0),
            (500.0, 500.0),
        )
        self.assertEqual(
            rates_from_counters((1000, 2000), (2000, 3000), 0.0),
            (0.0, 0.0),
        )

    def test_ping_average_parses_three_replies(self):
        output = "\n".join(
            [
                "64 bytes: time=1.0 ms",
                "64 bytes: time=2.0 ms",
                "64 bytes: time=3.0 ms",
            ]
        )

        def runner(args, timeout=5, input_data=None):
            return CommandResult(output, True, "")

        self.assertEqual(ping_average("1.1.1.1", runner=runner), 2.0)
        self.assertIsNone(ping_average(None, runner=runner))

    def test_ping_average_falls_back_to_tcp_when_icmp_is_blocked(self):
        def runner(args, timeout=5, input_data=None):
            return CommandResult("", False, "missing cap_net_raw")

        with patch("collectors.tcp_latency", return_value=5.0) as tcp:
            result = ping_average("1.1.1.1", runner=runner, tcp_port=443)
        self.assertEqual(result, 5.0)
        tcp.assert_called_once_with("1.1.1.1", 443)

    def test_run_speedtest_returns_both_rates(self):
        def runner(args, timeout=5, input_data=None):
            if "__down" in args[-1]:
                return CommandResult("200 1000000 10000000", True, "")
            self.assertEqual(len(input_data), 2000000)
            return CommandResult("200 500000 2000000", True, "")

        result = run_speedtest(
            down_bytes=10000000,
            up_bytes=2000000,
            runner=runner,
            ping_fn=lambda host: 12.5,
        )
        self.assertEqual(result["download_bps"], 8000000.0)
        self.assertEqual(result["upload_bps"], 4000000.0)
        self.assertEqual(result["latency_ms"], 12.5)
        self.assertEqual(result["bytes_used"], 12000000)
        self.assertIsNone(result["error"])

    def test_run_speedtest_reports_download_failure(self):
        def runner(args, timeout=5, input_data=None):
            return CommandResult("500 0 0", True, "")

        result = run_speedtest(runner=runner, ping_fn=lambda host: None)
        self.assertIsNone(result["download_bps"])
        self.assertIsNone(result["upload_bps"])
        self.assertEqual(result["error"], "download failed")

    def test_speedtest_default_latency_uses_tcp_fallback(self):
        def runner(args, timeout=5, input_data=None):
            if "__down" in args[-1]:
                return CommandResult("200 1000000 10000000", True, "")
            return CommandResult("200 500000 2000000", True, "")

        with patch("collectors.ping_average", return_value=8.5) as ping:
            result = run_speedtest(runner=runner)
        self.assertEqual(result["latency_ms"], 8.5)
        ping.assert_called_once_with("1.1.1.1", tcp_port=443)

    def test_load_config_defaults_merges_and_reports_bad_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("monthly_budget_gb = 200\nip_refresh_seconds = 30\n")
            config, warning = load_config(path)
            self.assertEqual(config["monthly_budget_gb"], 200)
            self.assertEqual(config["ip_refresh_seconds"], 30)
            self.assertIsNone(warning)

            path.write_text("not valid = [")
            config, warning = load_config(path)
            self.assertEqual(config["monthly_budget_gb"], 0)
            self.assertIsNotNone(warning)


NOW = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)


class TestSnapshot(unittest.TestCase):
    def test_collect_snapshot_separates_physical_and_vpn_usage(self):
        network = NetworkInfo(
            hostname="t9-iMac",
            physical_interface="wlp3s0",
            vpn_interface="CloudflareWARP",
            gateway="192.168.1.1",
            ipv4="192.168.1.46/24",
            ipv6="fe80::1/64",
            mac="e4:ce:8f:67:1e:bc",
            dns=["8.8.8.8"],
            ssid="WEA49217",
            signal_dbm=-64,
            rx_bitrate_mbps=78.0,
            tx_bitrate_mbps=300.0,
        )
        public = PublicIPInfo(
            ipv4="203.0.113.10",
            ipv6="2001:db8::10",
            isp="Example ISP",
            asn="AS64500",
            city="Alexandria",
            region="Alexandria",
            country="EG",
            vpn_active=True,
            stale_seconds=0,
        )
        traffic = {
            "hour": [{"timestamp": NOW.timestamp() - 60, "rx": 100, "tx": 10}],
            "day": [{"timestamp": NOW.timestamp(), "rx": 200, "tx": 20}],
            "month": [{"timestamp": NOW.timestamp(), "rx": 300, "tx": 30}],
        }
        with patch("collectors.discover_network", return_value=network), patch(
            "collectors.read_ip_info", return_value=public
        ), patch("collectors.read_vnstat", side_effect=[traffic, {}]), patch(
            "collectors.ping_average", side_effect=[2.0, 27.0]
        ):
            snapshot = collect_snapshot(
                {
                    "monthly_budget_gb": 1,
                    "speedtest_down_bytes": 1,
                    "speedtest_up_bytes": 1,
                },
                now=NOW,
            )
        self.assertEqual(
            snapshot["usage"]["physical"]["last_24h"],
            {"rx": 100, "tx": 10},
        )
        self.assertEqual(snapshot["usage"]["vpn"]["last_24h"], {"rx": 0, "tx": 0})
        self.assertEqual(snapshot["budget"]["used"], 330)
        self.assertEqual(snapshot["budget"]["limit"], 1024**3)
        self.assertEqual(snapshot["latency"]["gateway_ms"], 2.0)
        self.assertEqual(snapshot["usage"]["physical"]["interface"], "wlp3s0")


if __name__ == "__main__":
    unittest.main()
