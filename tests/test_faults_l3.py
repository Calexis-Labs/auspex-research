"""L3 + ozel ariza siniflari (cEOS'a baglanmadan):
- 4 ospf sinifi yalnizca ospf dunyasini kabul eder, hedefler topo+rng'den
- static_route_missing yalnizca statik dunyada calisir
- no_fault / insufficient_info hicbir privileged komut gondermez
- multi_fault requires'i uyan 2 bagimsiz sinifi enjekte eder, ters sirayla
  geri alir
- teacher DIAGNOSTIC_PROMPT yeni kurallari icerir, FAULT_CLASSES registry'den
"""

import random

import pytest

from lab.faults import FAULT_CLASSES, FAULTS, GroundTruth
from lab.topo import build_spec

NEW = {
    "ospf_area_mismatch",
    "ospf_auth_mismatch",
    "ospf_hello_mismatch",
    "ospf_passive_transit",
    "static_route_missing",
    "no_fault",
    "insufficient_info",
    "multi_fault",
}
OSPF_FAULTS = {"ospf_area_mismatch", "ospf_auth_mismatch", "ospf_hello_mismatch", "ospf_passive_transit"}
NOOP_FAULTS = {"no_fault", "insufficient_info"}
META_FAULTS = NOOP_FAULTS | {"multi_fault"}


class RecordingPE:
    """PrivilegedExec'in kayit tutan sahtesi — docker/FastCli'ye hic dokunmaz."""

    def __init__(self):
        self.calls: list[tuple] = []

    def eos_config(self, device: str, *lines: str) -> None:
        self.calls.append(("eos_config", device, lines))

    def host_cmd(self, device: str, command: str) -> None:
        self.calls.append(("host_cmd", device, command))


def _find_spec(pred, limit: int = 120):
    for seed in range(0, limit):
        spec = build_spec(seed)
        if pred(spec):
            return spec
    raise AssertionError(f"{limit} seed icinde uygun dunya bulunamadi")


OSPF_SPEC = _find_spec(lambda s: s.l3 == "ospf")          # seed=0 zaten ospf
STATIC_SPEC = _find_spec(lambda s: s.l3 == "static")


def _routed_ends(spec) -> set[tuple[str, str]]:
    ends = set()
    for a_dev, a_if, b_dev, b_if in spec.routed_links():
        ends.add((a_dev, a_if))
        ends.add((b_dev, b_if))
    return ends


# ---------------------------------------------------------------- registry

def test_registry_and_fault_classes_include_new():
    assert NEW <= set(FAULTS)
    assert NEW <= set(FAULT_CLASSES)


def test_requires_declarations():
    from lab.faults import usable
    from lab.topo import build_spec
    ospf_world = build_spec(0)                       # seed=0 = ospf dunyasi
    for name in OSPF_FAULTS:
        # requires ile degil, available(spec) predicate'i ile kapilanirlar
        assert FAULTS[name].requires == {}
        assert usable(FAULTS[name], ospf_world)
    assert FAULTS["static_route_missing"].requires == {"static": True}
    for name in META_FAULTS:
        assert FAULTS[name].requires == {}


# ---------------------------------------------------------------- ospf siniflari

@pytest.mark.parametrize("name", sorted(OSPF_FAULTS))
def test_ospf_faults_reject_static_world(name):
    with pytest.raises(ValueError):
        FAULTS[name].inject(RecordingPE(), STATIC_SPEC, random.Random(1))


@pytest.mark.parametrize("name", sorted(OSPF_FAULTS))
def test_ospf_faults_inject_and_revert_contract(name):
    f = FAULTS[name]
    pe = RecordingPE()
    gt = f.inject(pe, OSPF_SPEC, random.Random(7))

    assert isinstance(gt, GroundTruth)
    assert gt.fault_class == name
    assert gt.device in OSPF_SPEC.ceos_nodes
    assert gt.root_cause and gt.fix_commands
    assert gt.key_terms and all(t == t.lower() for t in gt.key_terms)
    # hedef cihaz gercek bir routed link ucunun cihazi
    routed_devs = {d for d, _ in _routed_ends(OSPF_SPEC)}
    assert gt.device in routed_devs
    # ospf_area disinda key_terms[0] hedef arayuzdur (area arizasini 'area' tanimlar)
    if name != "ospf_area_mismatch":
        routed = {(d, i.lower()) for d, i in _routed_ends(OSPF_SPEC)}
        assert (gt.device, gt.key_terms[0]) in routed

    n = len(pe.calls)
    assert n >= 1, "inject hicbir privileged komut gondermedi"
    f.revert(pe, OSPF_SPEC)
    assert len(pe.calls) > n, "revert hicbir privileged komut gondermedi"
    assert {c[1] for c in pe.calls[n:]} <= {c[1] for c in pe.calls[:n]}


@pytest.mark.parametrize("name", sorted(OSPF_FAULTS))
def test_ospf_faults_deterministic_and_rng_driven(name):
    f = FAULTS[name]
    gt1 = f.inject(RecordingPE(), OSPF_SPEC, random.Random(3))
    gt2 = f.inject(RecordingPE(), OSPF_SPEC, random.Random(3))
    assert gt1 == gt2
    picks = {f.inject(RecordingPE(), OSPF_SPEC, random.Random(s)).device for s in range(10)}
    assert len(picks) >= 2, "hedef secimi rng'den gelmiyor (hardcode suphesi)"


def test_area_mismatch_rewrites_network_statement():
    pe = RecordingPE()
    gt = FAULTS["ospf_area_mismatch"].inject(pe, OSPF_SPEC, random.Random(3))
    _, device, lines = pe.calls[0]
    assert device == gt.device
    assert lines[0] == "router ospf 1"
    assert any(l.startswith("no network ") and l.endswith("area 0.0.0.0") for l in lines)
    assert any(l.startswith("network ") and not l.endswith("area 0.0.0.0") for l in lines)
    subnets = {l["subnet"] for l in OSPF_SPEC.links if l["kind"] == "routed"}
    assert any(s in " ".join(lines) for s in subnets)
    assert "area" in gt.key_terms


def test_auth_mismatch_configures_md5_on_single_end():
    pe = RecordingPE()
    gt = FAULTS["ospf_auth_mismatch"].inject(pe, OSPF_SPEC, random.Random(4))
    _, _, lines = pe.calls[0]
    assert lines[0].startswith("interface Ethernet")
    assert "ip ospf authentication message-digest" in lines
    assert any(l.startswith("ip ospf message-digest-key 1 md5 ") for l in lines)
    assert "authentication" in gt.key_terms
    FAULTS["ospf_auth_mismatch"].revert(pe, OSPF_SPEC)
    _, _, rlines = pe.calls[-1]
    assert "no ip ospf authentication message-digest" in rlines


def test_hello_mismatch_sets_60_seconds():
    pe = RecordingPE()
    gt = FAULTS["ospf_hello_mismatch"].inject(pe, OSPF_SPEC, random.Random(5))
    _, _, lines = pe.calls[0]
    assert "ip ospf hello-interval 60" in lines
    assert "no ip ospf hello-interval 60" in gt.fix_commands
    assert "hello" in gt.key_terms


def test_passive_transit_leaves_mtu_alone():
    pe = RecordingPE()
    gt = FAULTS["ospf_passive_transit"].inject(pe, OSPF_SPEC, random.Random(6))
    _, device, lines = pe.calls[0]
    assert lines[0] == "router ospf 1"
    assert lines[1].startswith("passive-interface Ethernet")
    intf = lines[1].split()[-1]
    assert (device, intf) in _routed_ends(OSPF_SPEC)
    # mtu sinifiyla ayirt edici: mtu'ya ve link durumuna dokunulmaz
    assert not any("mtu" in l or "shutdown" in l for l in lines)
    assert "passive" in gt.key_terms


# ---------------------------------------------------------------- static_route_missing

def test_static_route_missing_removes_existing_route():
    f = FAULTS["static_route_missing"]
    pe = RecordingPE()
    gt = f.inject(pe, STATIC_SPEC, random.Random(5))

    routes = {
        (d, r["prefix"], r["nexthop"])
        for d, nd in STATIC_SPEC.ceos_nodes.items()
        for r in nd["static_routes"]
    }
    _, _, prefix, nexthop = gt.fix_commands[0].split()
    assert (gt.device, prefix, nexthop) in routes
    assert gt.key_terms == [prefix]
    assert pe.calls[0] == ("eos_config", gt.device, (f"no ip route {prefix} {nexthop}",))

    f.revert(pe, STATIC_SPEC)
    assert pe.calls[-1] == ("eos_config", gt.device, (f"ip route {prefix} {nexthop}",))


def test_static_route_missing_rejects_ospf_world():
    with pytest.raises(ValueError):
        FAULTS["static_route_missing"].inject(RecordingPE(), OSPF_SPEC, random.Random(1))


def test_static_route_missing_rng_driven():
    picks = {
        FAULTS["static_route_missing"].inject(RecordingPE(), STATIC_SPEC, random.Random(s)).fix_commands[0]
        for s in range(10)
    }
    assert len(picks) >= 2


# ---------------------------------------------------------------- no_fault / insufficient_info

@pytest.mark.parametrize("name", sorted(NOOP_FAULTS))
def test_noop_faults_touch_nothing(name):
    f = FAULTS[name]
    pe = RecordingPE()
    gt = f.inject(pe, OSPF_SPEC, random.Random(1))
    assert gt.device == "none"
    assert gt.fault_class == name
    assert gt.root_cause
    assert gt.fix_commands == [] and gt.key_terms == []
    assert pe.calls == [], "no-op sinif privileged komut gonderdi"
    f.revert(pe, OSPF_SPEC)
    assert pe.calls == []


def test_no_fault_root_cause_says_healthy():
    gt = FAULTS["no_fault"].inject(RecordingPE(), OSPF_SPEC, random.Random(1))
    assert gt.root_cause == "ag sagliklidir; bildirilen sorun ag kaynakli degil"


def test_insufficient_info_asks_for_more():
    gt = FAULTS["insufficient_info"].inject(RecordingPE(), OSPF_SPEC, random.Random(1))
    assert "bilgi yetersiz" in gt.root_cause
    # v2 tasarim: sikayetin oznesi arac gorunurlugu DISINDA (no_fault ikizligi kirildi)
    assert "gorunurlugu disinda" in gt.root_cause


# ---------------------------------------------------------------- multi_fault

def test_multi_fault_injects_two_independent_classes():
    f = FAULTS["multi_fault"]
    pe = RecordingPE()
    gts = f.inject(pe, OSPF_SPEC, random.Random(7))

    assert isinstance(gts, list) and len(gts) == 2
    classes = {g.fault_class for g in gts}
    assert len(classes) == 2, "iki FARKLI sinif secilmeli"
    assert not classes & META_FAULTS
    assert pe.calls

    n = len(pe.calls)
    f.revert(pe, OSPF_SPEC)
    assert len(pe.calls) > n
    assert {c[1] for c in pe.calls[n:]} <= {c[1] for c in pe.calls[:n]}


def test_multi_fault_revert_runs_in_reverse_order():
    f = FAULTS["multi_fault"]
    for s in range(40):
        pe = RecordingPE()
        gts = f.inject(pe, OSPF_SPEC, random.Random(s))
        if gts[0].device != gts[1].device:
            break
    else:
        raise AssertionError("farkli cihazli multi ornegi bulunamadi")
    n = len(pe.calls)
    f.revert(pe, OSPF_SPEC)
    # once son enjekte edilen (gts[1]) geri alinir, en son ilki
    assert pe.calls[n][1] == gts[1].device
    assert pe.calls[-1][1] == gts[0].device


def test_multi_fault_deterministic():
    gts1 = FAULTS["multi_fault"].inject(RecordingPE(), OSPF_SPEC, random.Random(3))
    gts2 = FAULTS["multi_fault"].inject(RecordingPE(), OSPF_SPEC, random.Random(3))
    assert gts1 == gts2


def test_multi_fault_respects_requires_per_world():
    seen_ospf, seen_static = set(), set()
    for s in range(30):
        for g in FAULTS["multi_fault"].inject(RecordingPE(), OSPF_SPEC, random.Random(s)):
            seen_ospf.add(g.fault_class)
        for g in FAULTS["multi_fault"].inject(RecordingPE(), STATIC_SPEC, random.Random(s)):
            seen_static.add(g.fault_class)
    # ospf dunyasi: fallback turetimi ospf siniflarini aday yapar, statik sinifi yapmaz
    assert seen_ospf & OSPF_FAULTS
    assert "static_route_missing" not in seen_ospf
    # statik dunya: ospf siniflari aday olamaz
    assert not seen_static & OSPF_FAULTS


# ---------------------------------------------------------------- teacher entegrasyonu

def test_teacher_prompt_has_no_fault_and_insufficient_info_rules():
    from datagen.teacher import DIAGNOSTIC_PROMPT

    assert "no_fault" in DIAGNOSTIC_PROMPT
    assert "insufficient_info" in DIAGNOSTIC_PROMPT


def test_teacher_fault_classes_come_from_registry():
    from datagen import teacher

    assert set(teacher.FAULT_CLASSES) == {f.label for f in FAULTS.values()}
    rendered = teacher.DIAGNOSTIC_PROMPT.format(
        symptom="test", fault_classes=", ".join(teacher.FAULT_CLASSES),
        switches="sw1, sw2", hosts="h1",
    )
    for name in NEW:
        assert name in rendered
