"""Transport sozlesmesi:
- dogrulama HER ag temasindan once calisir (driver hic acilmaz / runner hic cagrilmaz)
- `| json` son eki transport ICINDE eklenir, JSON parse edilemezse ham metne duser
- HostExecTransport shell KULLANMAZ: argv listesi, docker exec ile
"""

import json

import pytest

from tests.fakes import FakeDriver, FakeRunner
from tools.allowlist import CommandNotAllowed
from tools.transport import HostExecTransport, Node, ReadOnlyTransport, UnknownDevice

INV = {
    "leaf1": Node(name="leaf1", os="eos", host="192.168.121.12"),
    "hosta": Node(name="hosta", os="linux", container="clab-netagent-hosta"),
}


def make_eos(driver: FakeDriver) -> ReadOnlyTransport:
    return ReadOnlyTransport(INV, driver_factory=lambda node: driver)


# ---------------------------------------------------------------- red, agdan once

def test_rejection_happens_before_any_network_io():
    driver = FakeDriver()
    t = make_eos(driver)
    with pytest.raises(CommandNotAllowed):
        t.run("leaf1", "configure terminal")
    assert driver.sent == []
    assert driver.opened is False       # baglanti hic acilmadi


def test_host_rejection_happens_before_runner():
    runner = FakeRunner()
    t = HostExecTransport(INV, runner=runner)
    with pytest.raises(CommandNotAllowed):
        t.run("hosta", "ip route replace default via 10.10.0.254")
    assert runner.calls == []


def test_unknown_device_raises_before_io():
    driver = FakeDriver()
    t = make_eos(driver)
    with pytest.raises(UnknownDevice):
        t.run("yok-boyle-cihaz", "show version")
    assert driver.sent == []


def test_eos_transport_refuses_linux_node():
    driver = FakeDriver()
    t = make_eos(driver)
    with pytest.raises(UnknownDevice):
        t.run("hosta", "ip -j addr show")   # linux node scrapli yolundan gecmez
    assert driver.sent == []


# ---------------------------------------------------------------- | json davranisi

def test_json_suffix_added_internally_and_parsed():
    driver = FakeDriver(outputs={"show vlan | json": '{"vlans": {"10": {"name": "USERS"}}}'})
    t = make_eos(driver)
    out = t.run("leaf1", "show vlan")
    assert out == {"vlans": {"10": {"name": "USERS"}}}
    assert driver.sent == ["show vlan | json"]


def test_falls_back_to_raw_when_not_json():
    driver = FakeDriver(
        outputs={
            "show running-config section vlan | json": "% This is an unconverted command",
            "show running-config section vlan": "vlan 10\n   name USERS",
        }
    )
    t = make_eos(driver)
    out = t.run("leaf1", "show running-config section vlan")
    assert out == {"raw": "vlan 10\n   name USERS"}
    assert driver.sent == [
        "show running-config section vlan | json",
        "show running-config section vlan",
    ]


def test_want_json_false_skips_suffix():
    driver = FakeDriver(outputs={"ping 3.3.3.3 repeat 3": "5 packets transmitted, 0 received"})
    t = make_eos(driver)
    out = t.run("leaf1", "ping 3.3.3.3 repeat 3", want_json=False)
    assert out == {"raw": "5 packets transmitted, 0 received"}
    assert driver.sent == ["ping 3.3.3.3 repeat 3"]


def test_pipe_in_caller_input_still_rejected():
    # son eki BIZ ekliyoruz diye cagirana pipe hakki dogmaz
    driver = FakeDriver()
    t = make_eos(driver)
    with pytest.raises(CommandNotAllowed):
        t.run("leaf1", "show vlan | json")
    assert driver.sent == []


# ---------------------------------------------------------------- host exec

def test_host_exec_builds_argv_no_shell():
    runner = FakeRunner(outputs={"docker exec clab-netagent-hosta ip -j addr show": '[{"ifname": "eth1"}]'})
    t = HostExecTransport(INV, runner=runner)
    out = t.run("hosta", "ip -j addr show")
    assert out == [{"ifname": "eth1"}]
    assert runner.calls == [["docker", "exec", "clab-netagent-hosta", "ip", "-j", "addr", "show"]]


def test_host_ping_returns_raw_text():
    runner = FakeRunner(default_output="3 packets transmitted, 3 received")
    t = HostExecTransport(INV, runner=runner)
    out = t.run("hosta", "ping -c 3 10.10.0.1")
    assert out == {"raw": "3 packets transmitted, 3 received"}


def test_host_exec_refuses_eos_node():
    runner = FakeRunner()
    t = HostExecTransport(INV, runner=runner)
    with pytest.raises(UnknownDevice):
        t.run("leaf1", "show version")
    assert runner.calls == []
