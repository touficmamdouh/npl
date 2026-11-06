import unittest
from unittest.mock import patch

from collectors import CommandResult, discover_network, read_net_counters
from platform_collectors import (
    InterfaceOverrideError,
    MacOSCollector,
    NetworkSnapshot,
    collector_for_platform,
)


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, args, timeout=5, input_data=None):
        self.calls.append(args)
        key = tuple(args)
        return self.responses.get(key, CommandResult("", False, "missing"))


class TestPlatformCollectors(unittest.TestCase):
    def test_platform_selection_returns_macos_adapter(self):
        collector = collector_for_platform("darwin")
        self.assertIsInstance(collector, MacOSCollector)

    def test_macos_collector_parses_default_route_and_interface(self):
        runner = FakeRunner(
            {
                ("route", "-n", "get", "default"): CommandResult(
                    "gateway: 192.168.1.1\ninterface: en0\n", True
                ),
                ("ifconfig", "en0"): CommandResult(
                    """en0: flags=8863<UP,BROADCAST,RUNNING>\n\tether 00:11:22:33:44:55\n\tinet 192.168.1.20 netmask 0xffffff00\n""",
                    True,
                ),
                ("scutil", "--dns"): CommandResult(
                    "nameserver[0] : 192.168.1.1\nnameserver[1] : 1.1.1.1\n",
                    True,
                ),
            }
        )
        snapshot = MacOSCollector(runner=runner).discover()
        self.assertEqual(snapshot.interface, "en0")
        self.assertEqual(snapshot.gateway, "192.168.1.1")
        self.assertEqual(snapshot.ipv4, "192.168.1.20/24")
        self.assertEqual(snapshot.mac, "00:11:22:33:44:55")
        self.assertEqual(snapshot.dns, ["192.168.1.1", "1.1.1.1"])

    def test_macos_collector_uses_active_hardware_when_default_is_tunnel(self):
        runner = FakeRunner(
            {
                ("ifconfig", "-l"): CommandResult(
                    "lo0 gif0 en0 en2 utun0\n", True
                ),
                ("route", "-n", "get", "default"): CommandResult(
                    "gateway: 192.0.2.1\ninterface: gif0\n", True
                ),
                ("networksetup", "-listallhardwareports"): CommandResult(
                    "Hardware Port: Wi-Fi\nDevice: en0\n\n"
                    "Hardware Port: Ethernet\nDevice: en2\n", True
                ),
                ("ifconfig", "en0"): CommandResult(
                    "en0: flags=8863<UP,BROADCAST,RUNNING>\n"
                    "\tstatus: active\n", True
                ),
                ("ifconfig", "en2"): CommandResult(
                    "en2: flags=8863<UP,BROADCAST>\n"
                    "\tstatus: inactive\n", True
                ),
                ("ifconfig", "gif0"): CommandResult("gif0: flags=8051\n", True),
                ("scutil", "--dns"): CommandResult("", True),
                ("networksetup", "-getairportnetwork", "en0"): CommandResult(
                    "Current Wi-Fi Network: Test Network\n", True
                ),
            }
        )

        snapshot = MacOSCollector(runner=runner).discover()

        self.assertEqual(snapshot.interface, "en0")

    def test_macos_collector_falls_back_to_en0_if_hardware_lookup_fails(self):
        runner = FakeRunner(
            {
                ("ifconfig", "-l"): CommandResult(
                    "lo0 gif0 en3 en1 en0 utun0\n", True
                ),
                ("route", "-n", "get", "default"): CommandResult(
                    "interface: gif0\n", True
                ),
                ("networksetup", "-listallhardwareports"): CommandResult(
                    "", False, "unavailable"
                ),
                ("ifconfig", "en0"): CommandResult(
                    "en0: flags=8863<UP,BROADCAST,RUNNING>\n", True
                ),
                ("scutil", "--dns"): CommandResult("", True),
                ("networksetup", "-getairportnetwork", "en0"): CommandResult(
                    "", False, "unavailable"
                ),
            }
        )

        self.assertEqual(MacOSCollector(runner=runner).discover().interface, "en0")

    def test_invalid_override_does_not_fall_back_silently(self):
        runner = FakeRunner(
            {
                ("route", "-n", "get", "default"): CommandResult(
                    "interface: en0\n", True
                ),
                ("ifconfig", "-l"): CommandResult("en0 lo0\n", True),
            }
        )
        with self.assertRaises(InterfaceOverrideError):
            MacOSCollector(runner=runner).discover(preferred="typo0")

    def test_network_snapshot_keeps_optional_fields_empty(self):
        snapshot = NetworkSnapshot(hostname="host")
        self.assertIsNone(snapshot.interface)
        self.assertEqual(snapshot.dns, [])

    def test_macos_collector_parses_netstat_byte_counters(self):
        runner = FakeRunner(
            {
                ("netstat", "-ib", "-I", "en0"): CommandResult(
                    "Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll\n"
                    "en0 1500 <Link#6> 00:11:22:33:44:55 10 0 1234 20 0 5678 0\n",
                    True,
                )
            }
        )
        self.assertEqual(MacOSCollector(runner=runner).read_counters("en0"), (1234, 5678))

    def test_collectors_bridge_uses_macos_adapter(self):
        runner = FakeRunner(
            {
                ("ifconfig", "-l"): CommandResult("en0\n", True),
                ("route", "-n", "get", "default"): CommandResult(
                    "gateway: 192.168.1.1\ninterface: en0\n", True
                ),
                ("ifconfig", "en0"): CommandResult("", True),
                ("scutil", "--dns"): CommandResult("", True),
                ("networksetup", "-getairportnetwork", "en0"): CommandResult(
                    "", False
                ),
            }
        )
        with patch("sys.platform", "darwin"):
            info = discover_network(runner=runner)
        self.assertEqual(info.physical_interface, "en0")
        self.assertEqual(info.gateway, "192.168.1.1")


if __name__ == "__main__":
    unittest.main()
