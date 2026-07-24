"""L1/L2 ariza siniflari sozlesmesi (cEOS'a baglanmadan):
- 6 yeni sinif registry'de ve v2 sozlesmesini tasir
- sahte PrivilegedExec ile inject -> GroundTruth alanlari dolu
- revert komut metinleri inject degisikliklerini kapsar (simetri kontrolu)
- hedef secimi rng'den: farkli seed farkli hedef secebilir
"""

import ipaddress
import random

import pytest

from lab.faults import FAULT_CLASSES, FAULTS, GroundTruth, matches
from lab.topo import build_spec

L2_CLASSES = [
    "access_port_wrong_vlan",
    "duplicate_ip",
    "link_down_far_end",
    "native_vlan_mismatch",
    "svi_down",
    "wrong_subnet_mask",
]

# inject'in calisabilmesi icin requires disinda gereken dunya kosullari
EXTRA = {
    "svi_down": lambda s: any(not v.get("vrrp_peers") for v in s.vlans),
}

# hedef cesitliligi testi icin en az 2 aday hedef iceren dunya kosullari
VARIETY_EXTRA = {
    "svi_down": lambda s: len([v for v in s.vlans if not v.get("vrrp_peers")]) >= 2,
    "duplicate_ip": lambda s: len(s.hosts) >= 2,
    "wrong_subnet_mask": lambda s: len(s.hosts) >= 2,
    "access_port_wrong_vlan": lambda s: len(s.access_ports()) >= 2,
}


class RecordingPE:
    """PrivilegedExec'in kayit tutan sahtesi — docker/FastCli'ye hic dokunmaz."""

    def __init__(self):
        self.calls: list[tuple] = []

    def eos_config(self, device: str, *lines: str) -> None:
        self.calls.append(("eos_config", device, lines))

    def host_cmd(self, device: str, command: str) -> None:
        self.calls.append(("host_cmd", device, command))

    def text(self, start: int = 0) -> str:
        """start'tan itibaren kayitli komutlarin duz metni — simetri kontrolu."""
        out = []
        for _, device, payload in self.calls[start:]:
            body = " / ".join(payload) if isinstance(payload, tuple) else payload
            out.append(f"{device}: {body}")
        return "\n".join(out)


def _spec_for(name: str, extra=None):
    """Fault'un requires'ini (ve varsa ek kosulu) karsilayan deterministik dunya."""
    f = FAULTS[name]
    for seed in range(0, 120):
        spec = build_spec(seed)
        if matches(f.requires, spec) and (extra is None or extra(spec)):
            return spec
    raise AssertionError(f"uygun dunya bulunamadi: {name} requires={f.requires}")


def _find_spec(pred):
    for seed in range(0, 120):
        spec = build_spec(seed)
        if pred(spec):
            return spec
    raise AssertionError("kosulu saglayan dunya bulunamadi")


def _run(name: str, spec, seed: int = 7):
    """inject + revert; (gt, pe, inject cagri sayisi) dondurur."""
    f = FAULTS[name]
    pe = RecordingPE()
    gt = f.inject(pe, spec, random.Random(seed))
    n = len(pe.calls)
    f.revert(pe, spec)
    return gt, pe, n


# ---------------------------------------------------------------- registry

def test_l2_classes_registered():
    assert set(L2_CLASSES) <= set(FAULTS)
    # teshis listesine ETIKETLER girer (alias'lar kendi adiyla degil)
    assert {FAULTS[n].label for n in L2_CLASSES} <= set(FAULT_CLASSES)
    for name in L2_CLASSES:
        f = FAULTS[name]
        assert f.name == name
        assert callable(f.inject) and callable(f.revert)
        assert isinstance(f.requires, dict)


# ---------------------------------------------------------------- genel sozlesme

@pytest.mark.parametrize("name", L2_CLASSES)
def test_inject_returns_full_groundtruth(name):
    spec = _spec_for(name, EXTRA.get(name))
    gt, pe, n = _run(name, spec)

    gts = gt if isinstance(gt, list) else [gt]
    assert gts
    for g in gts:
        assert isinstance(g, GroundTruth)
        assert g.fault_class == FAULTS[name].label
        assert g.device in set(spec.ceos_nodes) | set(spec.hosts)
        assert g.root_cause and g.fix_commands
        assert g.key_terms, "key_terms bos olamaz"
        assert all(t == t.lower() for t in g.key_terms), "key_terms kucuk harf olmali"

    assert n > 0, "inject hicbir privileged komut gondermedi"
    assert len(pe.calls) > n, "revert hicbir privileged komut gondermedi"
    # revert enjeksiyonla ayni cihaz(lar)a gider
    assert {c[1] for c in pe.calls[n:]} <= {c[1] for c in pe.calls[:n]}


@pytest.mark.parametrize("name", L2_CLASSES)
def test_inject_is_deterministic_for_same_rng(name):
    spec = _spec_for(name, EXTRA.get(name))
    f = FAULTS[name]
    gt1 = f.inject(RecordingPE(), spec, random.Random(3))
    gt2 = f.inject(RecordingPE(), spec, random.Random(3))
    assert gt1 == gt2


@pytest.mark.parametrize("name", L2_CLASSES)
def test_targets_come_from_rng_not_hardcode(name):
    spec = _spec_for(name, VARIETY_EXTRA.get(name, EXTRA.get(name)))
    f = FAULTS[name]
    picks = set()
    for s in range(12):
        pe = RecordingPE()
        gt = f.inject(pe, spec, random.Random(s))
        picks.add((gt.device, tuple(gt.fix_commands)))
        f.revert(pe, spec)
    assert len(picks) >= 2, "hedef secimi rng'den gelmiyor (hardcode suphesi)"


# ---------------------------------------------------------------- sinif bazli simetri

def test_link_down_far_end_is_alias_of_interface_admin_down():
    """Pilot dersi (0/7): iki sinif arac ciktisinda ayni gerceklik — tek etiket."""
    f = FAULTS["link_down_far_end"]
    assert f.label == "interface_admin_down"
    gt, _, _ = _run("link_down_far_end", build_spec(0))
    assert gt.fault_class == "interface_admin_down"
    assert "link_down_far_end" not in FAULT_CLASSES


def test_link_down_far_end_culprit_is_root_cause_device():
    spec = build_spec(0)
    gt, pe, n = _run("link_down_far_end", spec)

    # shutdown GT cihazinda (kok neden), semptom komsu cihazda
    kind, device, lines = pe.calls[0]
    assert kind == "eos_config" and device == gt.device
    assert "shutdown" in lines and "no shutdown" not in lines
    intf = gt.key_terms[0]
    assert f"interface {intf}" in " ".join(lines).lower()

    # secilen uc gercek bir switch-switch linkin ucudur; karsi uc root_cause'ta anilir
    eth_no = int(intf.removeprefix("ethernet"))
    link = next(
        l for l in spec.links
        if l["kind"] in ("routed", "trunk") and ((gt.device, eth_no) in (l["a"], l["b"]))
    )
    victim = l0 if (l0 := link["a"][0]) != gt.device else link["b"][0]
    assert victim in gt.root_cause
    assert victim != gt.device

    # revert ayni cihaz + ayni arayuzde no shutdown
    assert pe.calls[n][1] == gt.device
    assert "no shutdown" in pe.text(n)
    assert intf in pe.text(n).lower()


def test_native_vlan_mismatch_creates_then_deletes_vlan():
    spec = build_spec(0)
    gt, pe, n = _run("native_vlan_mismatch", spec, seed=1)

    intf, vid = gt.key_terms
    assert int(vid) not in {v["id"] for v in spec.vlans}, "yeni vlan id topolojide olmamali"
    trunk_ends = {
        (d, i.lower())
        for a, ai, b, bi in spec.trunk_links()
        for d, i in ((a, ai), (b, bi))
    }
    assert (gt.device, intf) in trunk_ends

    inject_text = pe.text(0).splitlines()[0]
    assert f"vlan {vid}" in inject_text
    assert f"switchport trunk native vlan {vid}" in inject_text

    revert_text = pe.text(n)
    assert "no switchport trunk native vlan" in revert_text
    assert f"no vlan {vid}" in revert_text, "eklenen vlan revert'te silinmeli"


def test_access_port_wrong_vlan_restores_correct_vlan():
    spec = build_spec(0)
    gt, pe, n = _run("access_port_wrong_vlan", spec)

    intf, wrong = gt.key_terms
    port = next(p for p in spec.access_ports() if p[0] == gt.device and p[1].lower() == intf)
    correct = spec.hosts[port[2]]["vlan"]
    assert int(wrong) != correct

    assert f"switchport access vlan {wrong}" in pe.text(0).splitlines()[0]
    assert f"switchport access vlan {correct}" in pe.text(n)
    assert pe.calls[n][1] == gt.device


def test_svi_down_targets_gateway_device():
    spec = build_spec(0)
    gt, pe, n = _run("svi_down", spec)

    # seed=0: tek vlan 10, gw leaf1
    assert gt.device == "leaf1"
    assert gt.key_terms == ["vlan10"]
    assert "interface Vlan10 / shutdown" in pe.text(0).splitlines()[0]
    assert "no shutdown" in pe.text(n)


def test_svi_down_avoids_vrrp_vlans():
    spec = _find_spec(
        lambda s: s.features["vrrp"] and any(not v.get("vrrp_peers") for v in s.vlans)
    )
    vrrp_vids = {v["id"] for v in spec.vlans if v.get("vrrp_peers")}
    for s in range(8):
        gt, _, _ = _run("svi_down", spec, seed=s)
        vid = int(gt.key_terms[0].removeprefix("vlan"))
        assert vid not in vrrp_vids


def test_svi_down_raises_when_only_vrrp_vlan():
    spec = _find_spec(
        lambda s: s.features["vrrp"] and all(v.get("vrrp_peers") for v in s.vlans)
    )
    with pytest.raises(LookupError):
        FAULTS["svi_down"].inject(RecordingPE(), spec, random.Random(0))


def test_duplicate_ip_adds_then_deletes_gateway_address():
    spec = build_spec(0)
    gt, pe, n = _run("duplicate_ip", spec)

    assert gt.device in spec.hosts
    gw = spec.hosts[gt.device]["gw"]
    assert gt.key_terms == [gw]
    assert pe.calls[0] == ("host_cmd", gt.device, f"ip addr add {gw}/32 dev eth1")
    assert pe.calls[n] == ("host_cmd", gt.device, f"ip addr del {gw}/32 dev eth1")


def test_wrong_subnet_mask_excludes_gateway_and_fully_reverts():
    spec = build_spec(0)
    gt, pe, n = _run("wrong_subnet_mask", spec)

    assert gt.device in spec.hosts
    h = spec.hosts[gt.device]
    # key_terms = [adres, "/prefix"] — arac ciktisinda ayri gorunen parcalar
    assert len(gt.key_terms) == 2 and gt.key_terms[1].startswith("/")
    narrow_cidr = gt.key_terms[0] + gt.key_terms[1]
    assert narrow_cidr.split("/")[0] == h["ip_cidr"].split("/")[0], "adres ayni kalmali"
    narrow_net = ipaddress.ip_network(narrow_cidr, strict=False)
    assert narrow_net.prefixlen > ipaddress.ip_network(h["ip_cidr"], strict=False).prefixlen
    assert ipaddress.ip_address(h["gw"]) not in narrow_net, "gw dar maskin disinda kalmali"

    # inject: once orijinal silinir, sonra dar mask eklenir
    assert pe.calls[0] == ("host_cmd", gt.device, f"ip addr del {h['ip_cidr']} dev eth1")
    assert pe.calls[1] == ("host_cmd", gt.device, f"ip addr add {narrow_cidr} dev eth1")

    # revert: dar mask silinir, orijinal adres ve default rota geri gelir
    revert_text = pe.text(n)
    assert f"ip addr del {narrow_cidr} dev eth1" in revert_text
    assert f"ip addr add {h['ip_cidr']} dev eth1" in revert_text
    assert f"ip route replace default via {h['gw']}" in revert_text


# ---------------------------------------------------------------- key_terms kesfedilebilirlik

def test_eos_key_terms_reference_spec_interfaces():
    # arayuz terimleri spec'te gercekten var olan arayuz adlari olmali
    spec = build_spec(0)
    all_intfs = {
        i["name"].lower() for nd in spec.ceos_nodes.values() for i in nd["interfaces"]
    }
    for name in ("link_down_far_end", "native_vlan_mismatch", "access_port_wrong_vlan", "svi_down"):
        gt, _, _ = _run(name, spec)
        assert gt.key_terms[0] in all_intfs, f"{name}: {gt.key_terms[0]} spec'te yok"


def test_host_key_terms_reference_spec_addresses():
    spec = build_spec(0)
    gt_dup, _, _ = _run("duplicate_ip", spec)
    assert gt_dup.key_terms[0] in {h["gw"] for h in spec.hosts.values()}
    gt_mask, _, _ = _run("wrong_subnet_mask", spec)
    assert gt_mask.key_terms[0].split("/")[0] in {
        h["ip_cidr"].split("/")[0] for h in spec.hosts.values()
    }


def test_wrong_gateway_bogus_is_on_link_for_narrow_masks():
    """/26 dunyasi: net+254 subnet disi kalirdi (kernel reddi, uretim 2026-07-17).
    Sahte gw her maske genisliginde subnet ICINDE olmali."""
    import ipaddress
    from types import SimpleNamespace

    spec = SimpleNamespace(hosts={
        "pc1": {"ip_cidr": "172.21.55.10/26", "gw": "172.21.55.1", "vlan": 10, "attached": ("leaf1", 3)},
    })
    pe = RecordingPE()
    gt = FAULTS["wrong_host_gateway"].inject(pe, spec, random.Random(3))
    bogus = pe.calls[0][2].split()[-1]
    net = ipaddress.ip_network("172.21.55.10/26", strict=False)
    assert ipaddress.ip_address(bogus) in net, f"{bogus} subnet disinda"
    assert bogus not in ("172.21.55.1", "172.21.55.10")
    FAULTS["wrong_host_gateway"].revert(pe, spec)
