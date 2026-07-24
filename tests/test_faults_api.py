"""Fault API v2 sozlesmesi (cEOS'a baglanmadan):
- registry pkgutil auto-discovery ile >= 5 sinif icerir
- her sinif inject/revert/requires tasir
- sahte PrivilegedExec ile inject GroundTruth dondurur, key_terms bos degil,
  hedefler topo+rng'den secilir (hardcode yok), revert ayni hedefe doner
"""

import dataclasses
import random

import pytest

from lab.faults import FAULT_CLASSES, FAULTS, GroundTruth, matches
from lab.topo import build_spec

EXPECTED = {
    "acl_blocking_traffic",
    "interface_admin_down",
    "ospf_mtu_mismatch",
    "vlan_removed_from_trunk",
    "wrong_host_gateway",
}


class RecordingPE:
    """PrivilegedExec'in kayit tutan sahtesi — docker/FastCli'ye hic dokunmaz."""

    def __init__(self):
        self.calls: list[tuple] = []

    def eos_config(self, device: str, *lines: str) -> None:
        self.calls.append(("eos_config", device, lines))

    def host_cmd(self, device: str, command: str) -> None:
        self.calls.append(("host_cmd", device, command))


def _spec_for(fault) -> "build_spec":
    """Fault'un requires'ini karsilayan deterministik bir dunya bul."""
    for seed in range(0, 120):
        spec = build_spec(seed)
        if matches(fault.requires, spec):
            return spec
    raise AssertionError(f"requires karsilanamadi: {fault.requires}")


# ---------------------------------------------------------------- registry

def test_registry_has_expected_classes():
    assert EXPECTED <= set(FAULTS)
    assert len(FAULTS) >= 5
    # FAULT_CLASSES = ETIKET kumesi: alias enjektorler (label != name) ayri
    # satir olusturmaz (orn. link_down_far_end -> interface_admin_down)
    assert set(FAULT_CLASSES) == {f.label for f in FAULTS.values()}
    assert "link_down_far_end" not in FAULT_CLASSES
    assert "interface_admin_down" in FAULT_CLASSES


def test_every_fault_carries_v2_contract():
    for name, f in FAULTS.items():
        assert f.name == name
        assert callable(f.inject) and callable(f.revert)
        assert isinstance(f.requires, dict)


def test_groundtruth_is_frozen():
    gt = GroundTruth(device="x", fault_class="y", root_cause="z", fix_commands=["a"], key_terms=["b"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        gt.device = "hacked"


# ---------------------------------------------------------------- inject/revert (sahte pe)

@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_inject_returns_groundtruth_and_targets_exist(name):
    f = FAULTS[name]
    spec = _spec_for(f)
    pe = RecordingPE()
    gt = f.inject(pe, spec, random.Random(7))

    gts = gt if isinstance(gt, list) else [gt]
    assert gts
    for g in gts:
        assert isinstance(g, GroundTruth)
        assert g.fault_class == name
        assert g.device in set(spec.ceos_nodes) | set(spec.hosts)
        assert g.root_cause and g.fix_commands
        assert g.key_terms, "key_terms bos olamaz"
        assert all(t == t.lower() for t in g.key_terms), "key_terms kucuk harf olmali"

    assert pe.calls, "inject hicbir privileged komut gondermedi"
    n_inject_calls = len(pe.calls)
    f.revert(pe, spec)
    assert len(pe.calls) > n_inject_calls, "revert hicbir privileged komut gondermedi"

    # revert enjeksiyonla ayni cihaza gider
    assert {c[1] for c in pe.calls[n_inject_calls:]} <= {c[1] for c in pe.calls[:n_inject_calls]}


def test_targets_come_from_rng_not_hardcode():
    f = FAULTS["interface_admin_down"]
    spec = build_spec(0)
    picks = set()
    for s in range(10):
        pe = RecordingPE()
        gt = f.inject(pe, spec, random.Random(s))
        picks.add((gt.device, gt.fix_commands[0]))
        f.revert(pe, spec)
    assert len(picks) >= 2, "hedef secimi rng'den gelmiyor (hardcode suphesi)"


def test_inject_is_deterministic_for_same_rng():
    f = FAULTS["vlan_removed_from_trunk"]
    spec = _spec_for(f)
    gt1 = f.inject(RecordingPE(), spec, random.Random(3))
    gt2 = f.inject(RecordingPE(), spec, random.Random(3))
    assert gt1 == gt2


def test_key_terms_reference_spec_artifacts():
    # secilen hedefe gore kurulan key_terms spec'te gercekten var olmali
    spec = build_spec(0)
    f = FAULTS["vlan_removed_from_trunk"]
    gt = f.inject(RecordingPE(), spec, random.Random(1))
    intf_term = gt.key_terms[0]
    assert any(
        i["name"].lower() == intf_term
        for nd in spec.ceos_nodes.values()
        for i in nd["interfaces"]
    )
    vlan_term = gt.key_terms[1]
    assert vlan_term in {str(v["id"]) for v in spec.vlans}


def test_wrong_gateway_targets_a_real_host():
    spec = _spec_for(FAULTS["wrong_host_gateway"])
    pe = RecordingPE()
    gt = FAULTS["wrong_host_gateway"].inject(pe, spec, random.Random(11))
    assert gt.device in spec.hosts
    assert gt.key_terms == [spec.hosts[gt.device]["gw"]]
    assert pe.calls[0][0] == "host_cmd"                      # host yolundan, eos degil
    assert "ip route replace default via" in pe.calls[0][2]


def test_requires_matching():
    assert FAULTS["ospf_mtu_mismatch"].requires == {"static": False}
    assert FAULTS["vlan_removed_from_trunk"].requires == {"l2loop": False}
    ospf_spec = build_spec(0)
    assert matches({"static": False}, ospf_spec)
    assert not matches({"static": True}, ospf_spec)
    assert not matches({"portchannel": True}, ospf_spec)


def test_acl_block_lands_on_spine_facing_gw_leaf():
    spec = build_spec(0)
    pe = RecordingPE()
    gt = FAULTS["acl_blocking_traffic"].inject(pe, spec, random.Random(5))
    assert spec.ceos_nodes[gt.device]["role"] == "spine"
    # seed=0: vlan10 gw leaf1 -> spine1 Ethernet1
    assert gt.device == "spine1"
    assert "Ethernet1" in " ".join(gt.fix_commands)
    FAULTS["acl_blocking_traffic"].revert(pe, spec)


def test_backward_compat_call_without_topo_and_rng():
    # eski cagiranlar (smoke.py) topo/rng vermez — varsayilan spec'e duser
    pe = RecordingPE()
    gt = FAULTS["interface_admin_down"].inject(pe)
    assert isinstance(gt, GroundTruth)
    assert gt.device in {"spine1", "leaf1", "leaf2"}
    FAULTS["interface_admin_down"].revert(pe)
    assert len(pe.calls) == 2
