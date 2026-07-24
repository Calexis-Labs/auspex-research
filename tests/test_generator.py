"""Topoloji v2 sozlesmesi:
- seed=0 Faz 0 sabit dunyasini birebir uretir (geriye uyum)
- seed>0 dunyalari gecerli, deterministik ve kaynak sinirina uygun (cEOS <= 4)
- generator ciktilari (clab YAML + startup-config) spec'le tutarli
"""

import ipaddress

import pytest
import yaml

from lab import topo
from lab.generator import build, clab_file
from lab.topo import TopoSpec, build_spec

SEEDS = list(range(1, 6))


def _find_seed(pred, limit: int = 120) -> int:
    for seed in range(1, limit):
        if pred(build_spec(seed)):
            return seed
    raise AssertionError(f"{limit} seed icinde uygun dunya bulunamadi")


# ---------------------------------------------------------------- seed=0 geriye uyum

def test_seed0_spec_matches_phase0_world():
    spec = build_spec(0)
    assert spec.name == "netagent"
    assert spec.l3 == "ospf"
    assert list(spec.ceos_nodes) == ["spine1", "leaf1", "leaf2"]
    assert list(spec.hosts) == ["hosta", "hostb"]
    assert spec.vlans == [
        {"id": 10, "name": "USERS", "subnet": "10.10.0.0/24", "gw_device": "leaf1", "gw_ip": "10.10.0.1"}
    ]
    assert spec.hosts["hosta"] == {
        "ip_cidr": "10.10.0.20/24", "gw": "10.10.0.1", "vlan": 10, "attached": ("leaf1", "Ethernet1"),
    }
    assert spec.hosts["hostb"] == {
        "ip_cidr": "10.10.0.30/24", "gw": "10.10.0.1", "vlan": 10, "attached": ("leaf2", "Ethernet1"),
    }
    assert spec.ceos_nodes["spine1"]["mgmt_ipv4"] == "192.168.121.11"
    assert spec.ceos_nodes["leaf1"]["mgmt_ipv4"] == "192.168.121.12"
    assert spec.ceos_nodes["leaf2"]["mgmt_ipv4"] == "192.168.121.13"
    assert spec.ceos_nodes["spine1"]["loopback_ip"] == "1.1.1.1"
    assert spec.ceos_nodes["leaf1"]["loopback_ip"] == "2.2.2.2"
    assert spec.ceos_nodes["leaf2"]["loopback_ip"] == "3.3.3.3"
    assert all(v is False for v in spec.features.values())


def test_seed0_helpers():
    spec = build_spec(0)
    assert spec.container_name("leaf1") == "clab-netagent-leaf1"
    assert spec.routed_links() == [
        ("leaf1", "Ethernet2", "spine1", "Ethernet1"),
        ("leaf2", "Ethernet2", "spine1", "Ethernet2"),
    ]
    assert spec.trunk_links() == [("leaf1", "Ethernet3", "leaf2", "Ethernet3")]
    assert spec.access_ports() == [
        ("leaf1", "Ethernet1", "hosta"),
        ("leaf2", "Ethernet1", "hostb"),
    ]
    inv = spec.inventory()
    assert {n: node.os for n, node in inv.items()} == {
        "spine1": "eos", "leaf1": "eos", "leaf2": "eos", "hosta": "linux", "hostb": "linux",
    }
    assert inv["leaf1"].host == "192.168.121.12"
    assert inv["hosta"].container == "clab-netagent-hosta"


def test_module_level_compat_helpers():
    # tools/mcp_server.py bu imzalari import ediyor — kirilmamali
    assert topo.container_name("leaf2") == "clab-netagent-leaf2"
    inv = topo.inventory()
    assert set(inv) == {"spine1", "leaf1", "leaf2", "hosta", "hostb"}


def test_seed0_configs_backward_compatible(tmp_path):
    build(build_spec(0), out_dir=tmp_path)
    leaf1 = (tmp_path / "configs" / "leaf1.cfg").read_text()
    assert "ip address 10.10.0.1/24" in leaf1          # SVI gateway
    assert "vlan 10" in leaf1
    assert "switchport trunk allowed vlan 10" in leaf1
    assert "ip address 10.0.1.1/30" in leaf1
    assert "router ospf 1" in leaf1
    assert "router-id 2.2.2.2" in leaf1
    assert "passive-interface Vlan10" in leaf1
    assert "network 10.10.0.0/24 area 0.0.0.0" in leaf1

    spine1 = (tmp_path / "configs" / "spine1.cfg").read_text()
    assert "ip address 10.0.1.2/30" in spine1
    assert "ip address 10.0.2.2/30" in spine1
    assert "ip address 1.1.1.1/32" in spine1

    leaf2 = (tmp_path / "configs" / "leaf2.cfg").read_text()
    assert "ip address 10.0.2.1/30" in leaf2
    assert "switchport access vlan 10" in leaf2


def test_seed0_clab_yaml(tmp_path):
    path = build(build_spec(0), out_dir=tmp_path)
    assert path == clab_file(build_spec(0), out_dir=tmp_path)
    doc = yaml.safe_load(path.read_text())
    assert doc["name"] == "netagent"
    assert doc["mgmt"]["ipv4-subnet"] == "192.168.121.0/24"
    nodes = doc["topology"]["nodes"]
    assert set(nodes) == {"spine1", "leaf1", "leaf2", "hosta", "hostb"}
    assert nodes["leaf1"]["enforce-startup-config"] is True
    assert nodes["leaf1"]["startup-config"] == "configs/leaf1.cfg"
    assert "ip addr add 10.10.0.20/24 dev eth1" in nodes["hosta"]["exec"]
    assert "ip route replace default via 10.10.0.1" in nodes["hostb"]["exec"]
    assert {"endpoints": ["leaf1:eth3", "leaf2:eth3"]} in doc["topology"]["links"]


# ---------------------------------------------------------------- seed>0 dunyalar

@pytest.mark.parametrize("seed", SEEDS)
def test_seeds_deterministic(seed):
    assert build_spec(seed) == build_spec(seed)


@pytest.mark.parametrize("seed", SEEDS)
def test_seeds_valid_world(seed):
    spec = build_spec(seed)
    assert isinstance(spec, TopoSpec)
    assert spec.l3 in ("ospf", "static")

    # kaynak siniri
    assert len(spec.ceos_nodes) <= 4
    roles = [nd["role"] for nd in spec.ceos_nodes.values()]
    assert roles.count("spine") == 1 and 2 <= roles.count("leaf") <= 3

    # vlan plani
    assert 1 <= len(spec.vlans) <= 3
    for v in spec.vlans:
        assert 10 <= v["id"] <= 999
        net = ipaddress.ip_network(v["subnet"])
        assert net.prefixlen == 24 and net.is_private
        assert ipaddress.ip_address(v["gw_ip"]) in net
        assert v["gw_device"] in spec.ceos_nodes
    assert len({v["id"] for v in spec.vlans}) == len(spec.vlans)

    # hostlar
    assert len(spec.hosts) >= 1
    vlan_by_id = {v["id"]: v for v in spec.vlans}
    for h in spec.hosts.values():
        v = vlan_by_id[h["vlan"]]
        assert ipaddress.ip_network(h["ip_cidr"], strict=False) == ipaddress.ip_network(v["subnet"])
        assert h["gw"] == v["gw_ip"]
        leaf, intf = h["attached"]
        assert spec.ceos_nodes[leaf]["role"] == "leaf"
        assert any(i["name"] == intf for i in spec.ceos_nodes[leaf]["interfaces"])

    # linkler: uclar mevcut node'lara gider, (node, eth) tekil
    endpoints = []
    known = set(spec.ceos_nodes) | set(spec.hosts)
    for l in spec.links:
        for end in (l["a"], l["b"]):
            assert end[0] in known
            endpoints.append(end)
    assert len(endpoints) == len(set(endpoints))

    # mgmt/router-id tekilligi
    mgmt_ips = [nd["mgmt_ipv4"] for nd in spec.ceos_nodes.values()]
    assert len(mgmt_ips) == len(set(mgmt_ips))
    rids = [nd["router_id"] for nd in spec.ceos_nodes.values()]
    assert len(rids) == len(set(rids))

    # ozellik bayraklari turetimlerle tutarli
    assert spec.features["multi_vlan"] == (len(spec.vlans) > 1)
    assert spec.features["static"] == (spec.l3 == "static")

    # her leaf'in spine'a routed uplink'i var
    routed_devs = {d for a, _, b, _ in spec.routed_links() for d in (a, b)}
    assert routed_devs == set(spec.ceos_nodes)


@pytest.mark.parametrize("seed", SEEDS)
def test_seeds_yaml_and_configs_render(seed, tmp_path):
    spec = build_spec(seed)
    path = build(spec, out_dir=tmp_path / str(seed))
    doc = yaml.safe_load(path.read_text())
    assert set(doc["topology"]["nodes"]) == set(spec.ceos_nodes) | set(spec.hosts)
    assert len(doc["topology"]["links"]) == len(spec.links)
    for name in spec.ceos_nodes:
        cfg = (tmp_path / str(seed) / "configs" / f"{name}.cfg").read_text()
        assert f"hostname {name}" in cfg
        if spec.l3 == "ospf":
            assert "router ospf 1" in cfg
        else:
            assert "router ospf" not in cfg


def test_portchannel_world_renders(tmp_path):
    seed = _find_seed(lambda s: s.features["portchannel"])
    spec = build_spec(seed)
    build(spec, out_dir=tmp_path)
    pc_trunks = [t for t in spec.trunk_links() if t[1] == "Port-Channel1"]
    assert len(pc_trunks) == 1
    dev = pc_trunks[0][0]
    cfg = (tmp_path / "configs" / f"{dev}.cfg").read_text()
    assert "interface Port-Channel1" in cfg
    assert "channel-group 1 mode active" in cfg
    assert cfg.count("channel-group 1 mode active") == 2      # 2 uye


def test_vrrp_world_renders(tmp_path):
    seed = _find_seed(lambda s: s.features["vrrp"])
    spec = build_spec(seed)
    build(spec, out_dir=tmp_path)
    v = spec.vlans[0]
    peers = v["vrrp_peers"]
    assert len(peers) == 2
    rendered = [(tmp_path / "configs" / f"{p}.cfg").read_text() for p in peers]
    for cfg in rendered:
        assert f"ipv4 {v['gw_ip']}" in cfg and "vrrp" in cfg
    assert any("priority-level 120" in cfg for cfg in rendered)


def test_static_world_renders(tmp_path):
    seed = _find_seed(lambda s: s.features["static"])
    spec = build_spec(seed)
    build(spec, out_dir=tmp_path)
    spine = next(n for n, nd in spec.ceos_nodes.items() if nd["role"] == "spine")
    spine_cfg = (tmp_path / "configs" / f"{spine}.cfg").read_text()
    assert "router ospf" not in spine_cfg
    for v in spec.vlans:
        assert f"ip route {v['subnet']} " in spine_cfg
    leaf = next(n for n, nd in spec.ceos_nodes.items() if nd["role"] == "leaf")
    leaf_cfg = (tmp_path / "configs" / f"{leaf}.cfg").read_text()
    assert "ip route 0.0.0.0/0 " in leaf_cfg


def test_l2loop_world_has_second_leaf_trunk():
    seed = _find_seed(lambda s: s.features["l2loop"])
    spec = build_spec(seed)
    plain_trunks = [l for l in spec.links if l["kind"] == "trunk"]
    redundant = [l for l in plain_trunks if l.get("redundant")]
    assert len(redundant) == 1
    a, b = redundant[0]["a"][0], redundant[0]["b"][0]
    # ayni cift arasinda ikinci bir L2 yol var (trunk ya da port-channel)
    others = [
        t for t in spec.trunk_links()
        if {t[0], t[2]} == {a, b} and (t[1], t[3]) != (f"Ethernet{redundant[0]['a'][1]}", f"Ethernet{redundant[0]['b'][1]}")
    ]
    assert others


def test_custom_name_and_mgmt_subnet():
    spec = build_spec(3, name="ozel", mgmt_subnet="10.99.0.0/24")
    assert spec.name == "ozel"
    assert spec.container_name("x") == "clab-ozel-x"
    assert spec.mgmt_net == "ozel-mgmt"
    for nd in spec.ceos_nodes.values():
        assert ipaddress.ip_address(nd["mgmt_ipv4"]) in ipaddress.ip_network("10.99.0.0/24")
        # vlan subnetleri mgmt ile cakismaz
    for v in spec.vlans:
        assert not ipaddress.ip_network(v["subnet"]).overlaps(ipaddress.ip_network("10.99.0.0/24"))


def test_expected_adjacencies_derived_from_spec():
    from lab.deploy import expected_adjacencies

    spec = build_spec(0)
    assert expected_adjacencies(spec) == {"spine1": 2, "leaf1": 1, "leaf2": 1}
