"""Allowlist, salt-okunurlugun ZORLANDIGI yer — bu testler o sozlesmeyi kilitler.

Uc katman, fail-closed:
  1. charset kapisi: izinli karakter kumesi disindaki HER SEY reddedilir
  2. deny-verb kapisi: ilk token show/ping (eos) degilse red; yasakli token varsa red
  3. anchored regex: komut, tablodaki bir kalibin TAMAMINA uymali
"""

import pytest

from tools.allowlist import CanonicalCommand, CommandNotAllowed, validate_command


def rejects(os: str, cmd: str):
    with pytest.raises(CommandNotAllowed):
        validate_command(os, cmd)


def accepts(os: str, cmd: str) -> CanonicalCommand:
    return validate_command(os, cmd)


# ---------------------------------------------------------------- katman 1: charset

INJECTION_ATTEMPTS = [
    "show version | include foo",       # pipe — parse son eki SADECE transport ekler
    "show version|json",
    "show version ; reload",
    "show version;reload",
    "show version && reload",
    "show version > flash:x",
    "show version < flash:x",
    "show `reload`",
    "show $(reload)",
    "show version\nreload",
    "show version\treload",
    'show "version"',
    "show 'version'",
    "show version # yorum",
    "show ver\rsion",
]


@pytest.mark.parametrize("cmd", INJECTION_ATTEMPTS)
def test_charset_gate_kills_injection(cmd):
    rejects("eos", cmd)


def test_charset_gate_kills_non_ascii():
    rejects("eos", "show versiyon​")        # zero-width space
    rejects("eos", "show arayüz")                # non-ascii harf
    rejects("eos", "show version ")         # nbsp


def test_empty_and_whitespace_rejected():
    rejects("eos", "")
    rejects("eos", "   ")
    rejects("eos", "\n")


# ---------------------------------------------------------------- katman 2: deny-verb

WRITE_COMMANDS = [
    "configure terminal",
    "configure",
    "enable",
    "reload",
    "reload now",
    "write memory",
    "write",
    "copy running-config startup-config",
    "erase startup-config",
    "delete flash:foo",
    "bash ls",
    "clear counters",
    "shutdown",
    "no shutdown",
    "boot system flash:x",
    "event-handler foo",
]


@pytest.mark.parametrize("cmd", WRITE_COMMANDS)
def test_write_commands_rejected(cmd):
    rejects("eos", cmd)


def test_deny_is_token_based_not_substring():
    # "neighbor" icinde "no" gecer; "detail" icinde "tail"... token bazli olmali
    accepts("eos", "show ip ospf neighbor")
    accepts("eos", "show lldp neighbors")


def test_first_token_must_be_show_or_ping():
    rejects("eos", "traceroute 1.1.1.1")   # faz 0 kapsaminda degil
    rejects("eos", "dir flash:")
    rejects("eos", "terminal length 0")


# ---------------------------------------------------------------- katman 3: anchored allowlist

EOS_ALLOWED = [
    "show version",
    "show interfaces status",
    "show interfaces ethernet2",
    "show interfaces ethernet1/1",
    "show interfaces vlan10",
    "show interfaces loopback0",
    "show interfaces management0",
    "show vlan",
    "show interfaces trunk",
    "show ip interface brief",
    "show ip route",
    "show ip route 10.10.0.0/24",
    "show ip route 3.3.3.3",
    "show ip ospf neighbor",
    "show ip ospf neighbor detail",
    "show lldp neighbors",
    "show lldp neighbors detail",
    "show ip access-lists",
    "show running-config section vlan",
    "show running-config section interface ethernet2",
    "show running-config section router ospf",
    "ping 10.10.0.2",
    "ping 3.3.3.3 repeat 3",
    "ping 3.3.3.3 repeat 5 source vlan10",
]


@pytest.mark.parametrize("cmd", EOS_ALLOWED)
def test_eos_allowlist_accepts(cmd):
    got = accepts("eos", cmd)
    assert got.os == "eos"
    assert got.text == cmd


EOS_NOT_ON_LIST = [
    "show running-config",                 # TAM config yasak — sadece section
    "show running-config all",
    "show tech-support",                   # devasa cikti, kapsam disi
    "show ip ospf neighbor detail fazla",  # anchored: sonda coplik olamaz
    "show ip route 10.10.0.0/24 longer-prefixes",
    "ping 10.10.0.2 repeat 100",           # repeat 1-5 ile sinirli
    "ping 10.10.0.2 repeat 0",
    "ping 10.10.0.2 size 65000",
    "ping hostb",                          # hedef yalnizca IPv4 literal
    "show interfaces ethernet2 ethernet3",
    "show snmp",
]


@pytest.mark.parametrize("cmd", EOS_NOT_ON_LIST)
def test_eos_unlisted_rejected(cmd):
    rejects("eos", cmd)


def test_normalization_collapses_whitespace_and_case():
    got = accepts("eos", "  SHOW   Version  ")
    assert got.text == "show version"


# ---------------------------------------------------------------- linux host tablosu

LINUX_ALLOWED = [
    "ip -j addr show",
    "ip -j route show",
    "ip -j link show",
    "ping -c 3 10.10.0.1",
    "ping -c 5 -w 2 10.10.0.1",
]


@pytest.mark.parametrize("cmd", LINUX_ALLOWED)
def test_linux_allowlist_accepts(cmd):
    assert accepts("linux", cmd).os == "linux"


LINUX_REJECTED = [
    "ip addr add 10.10.0.99/24 dev eth1",
    "ip route replace default via 10.10.0.254",
    "ip link set eth1 down",
    "ip -j addr show; reboot",
    "ping -c 100 10.10.0.1",
    "ping 10.10.0.1",              # -c zorunlu (sonsuz ping yasak)
    "rm -rf /",
    "cat /etc/shadow",
    "show version",                # eos komutu linux tablosunda gecmez
]


@pytest.mark.parametrize("cmd", LINUX_REJECTED)
def test_linux_rejected(cmd):
    rejects("linux", cmd)


# ---------------------------------------------------------------- os tablolari ayri

def test_os_tables_are_isolated():
    rejects("eos", "ip -j addr show")
    rejects("linux", "show ip route")


def test_unknown_os_fails_closed():
    rejects("ios_xe", "show version")
    rejects("", "show version")
