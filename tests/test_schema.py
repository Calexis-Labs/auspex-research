"""Arac katmani sozlesmesi:
- her arac SADECE allowlist'ten gecen komutlar uretir
- semalar strict (additionalProperties: false) ve deterministik sirali (prompt cache icin)
- submit_diagnosis ag cagrisi YAPMAZ
- hatalar exception degil, ajana JSON icinde "error" olarak doner
"""

import json

import pytest

from tests.fakes import FakeDriver, FakeRunner
from tools.schema import TOOL_NAMES, TOOLS, ToolExecutor
from tools.transport import HostExecTransport, Node, ReadOnlyTransport

INV = {
    "spine1": Node(name="spine1", os="eos", host="192.168.121.11"),
    "leaf1": Node(name="leaf1", os="eos", host="192.168.121.12"),
    "leaf2": Node(name="leaf2", os="eos", host="192.168.121.13"),
    "hosta": Node(name="hosta", os="linux", container="clab-netagent-hosta"),
    "hostb": Node(name="hostb", os="linux", container="clab-netagent-hostb"),
}

EXPECTED_TOOLS = [
    "get_config_section",
    "get_interfaces",
    "get_ip_interfaces",
    "get_ospf_neighbors",
    "get_routes",
    "get_topology",
    "get_vlans",
    "ping_from_device",
    "submit_diagnosis",
]


@pytest.fixture()
def rig():
    driver = FakeDriver()
    runner = FakeRunner()
    ex = ToolExecutor(
        INV,
        eos=ReadOnlyTransport(INV, driver_factory=lambda node: driver),
        host=HostExecTransport(INV, runner=runner),
    )
    return ex, driver, runner


def call(ex, name, **args) -> dict:
    return json.loads(ex.dispatch(name, args))


# ---------------------------------------------------------------- sema hijyeni

def test_tool_names_exact_and_sorted():
    assert TOOL_NAMES == EXPECTED_TOOLS                    # alfabetik = deterministik
    assert [t["name"] for t in TOOLS] == EXPECTED_TOOLS


def test_schemas_are_strict():
    for t in TOOLS:
        schema = t["input_schema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False, t["name"]
        assert t["description"], t["name"]


# ---------------------------------------------------------------- arac → komut eslemesi

def test_get_interfaces_summary_and_detail(rig):
    ex, driver, _ = rig
    call(ex, "get_interfaces", device="leaf1")
    call(ex, "get_interfaces", device="leaf1", interface="ethernet2")
    assert driver.sent == [
        "show interfaces status | json",
        "show interfaces ethernet2 | json",
    ]


def test_get_vlans_returns_vlan_db_and_trunks(rig):
    ex, driver, _ = rig
    out = call(ex, "get_vlans", device="leaf1")
    assert driver.sent == ["show vlan | json", "show interfaces trunk | json"]
    assert set(out) == {"vlans", "trunks"}


def test_get_routes_optional_prefix(rig):
    ex, driver, _ = rig
    call(ex, "get_routes", device="spine1")
    call(ex, "get_routes", device="spine1", prefix="10.10.0.0/24")
    assert driver.sent == ["show ip route | json", "show ip route 10.10.0.0/24 | json"]


def test_get_ospf_neighbors(rig):
    ex, driver, _ = rig
    call(ex, "get_ospf_neighbors", device="spine1")
    assert driver.sent == ["show ip ospf neighbor | json"]


def test_get_config_section_is_raw_text(rig):
    ex, driver, _ = rig
    driver.outputs["show running-config section router ospf"] = "router ospf 1"
    driver.default_output = "% This is an unconverted command"
    out = call(ex, "get_config_section", device="leaf2", section="router ospf")
    assert out == {"raw": "router ospf 1"}


def test_get_topology_walks_only_eos_nodes(rig):
    ex, driver, runner = rig
    out = call(ex, "get_topology")
    assert driver.sent == ["show lldp neighbors | json"] * 3
    assert runner.calls == []
    assert set(out) == {"spine1", "leaf1", "leaf2"}


def test_get_ip_interfaces_eos_vs_host(rig):
    ex, driver, runner = rig
    call(ex, "get_ip_interfaces", device="leaf1")
    assert driver.sent == ["show ip interface brief | json"]
    out = call(ex, "get_ip_interfaces", device="hosta")
    assert [c[3:] for c in runner.calls] == [
        ["ip", "-j", "addr", "show"],
        ["ip", "-j", "route", "show"],
    ]
    assert set(out) == {"addresses", "routes"}


def test_ping_eos_and_host_with_count_clamp(rig):
    ex, driver, runner = rig
    call(ex, "ping_from_device", device="leaf1", target="3.3.3.3", count=99)
    assert driver.sent == ["ping 3.3.3.3 repeat 5"]        # 99 → 5'e kirpilir
    call(ex, "ping_from_device", device="hosta", target="10.10.0.1")
    assert runner.calls[-1] == ["docker", "exec", "clab-netagent-hosta", "ping", "-c", "3", "-w", "2", "10.10.0.1"]


def test_ping_source_option(rig):
    ex, driver, _ = rig
    call(ex, "ping_from_device", device="leaf1", target="10.10.0.20", source="vlan10", count=2)
    assert driver.sent == ["ping 10.10.0.20 repeat 2 source vlan10"]


# ---------------------------------------------------------------- guvenlik davranislari

def test_submit_diagnosis_makes_no_network_calls(rig):
    ex, driver, runner = rig
    out = call(
        ex, "submit_diagnosis",
        device="leaf1", fault_class="interface_admin_down",
        root_cause="Ethernet2 admin down", fix_commands=["interface Ethernet2", "no shutdown"],
    )
    assert out["status"] == "diagnosis_recorded"
    assert out["diagnosis"]["fault_class"] == "interface_admin_down"
    assert driver.sent == [] and runner.calls == []


def test_unknown_device_returns_error_not_exception(rig):
    ex, driver, _ = rig
    out = call(ex, "get_interfaces", device="core99")
    assert "error" in out
    assert "core99" in out["error"]
    assert driver.sent == []


def test_unknown_tool_returns_error(rig):
    ex, *_ = rig
    out = call(ex, "get_secrets")
    assert "error" in out


def test_malicious_args_hit_allowlist_wall(rig):
    # sema serbest metin alsa bile transport'taki allowlist son duvar
    ex, driver, _ = rig
    out = call(ex, "get_config_section", device="leaf1", section="vlan; reload")
    assert "error" in out
    assert driver.sent == []
    out = call(ex, "get_interfaces", device="leaf1", interface="ethernet2 | include secret")
    assert "error" in out
    assert driver.sent == []
