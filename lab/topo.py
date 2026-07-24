"""Topoloji v2 — parametrik dunya uretici, tek dogruluk kaynagi.

build_spec(seed) deterministik bir TopoSpec uretir:
  seed=0  -> Faz 0 sabit topolojisi birebir (spine1/leaf1/leaf2, VLAN 10,
             10.10.0.0/24, ayni IP plani) — geriye uyum.
  seed>0  -> rastgele ama GECERLI dunyalar: 1-3 VLAN, 2-3 leaf, leaf basina
             0-2 host (toplam en az 1), rastgele hostname semasi, l3 ospf|static,
             opsiyonel portchannel / vrrp / l2loop. Toplam cEOS node <= 4.

Generator, deploy, faults ve testler hep TopoSpec uzerinden okur.
Modul seviyesindeki container_name()/inventory() varsayilan (seed=0) spec'e
delege eder — mevcut cagiranlar (tools/mcp_server.py) kirilmaz.
"""

import ipaddress
import random
from dataclasses import dataclass, field

from tools.transport import Node

LAB_NAME = "netagent"
MGMT_NET_SUFFIX = "-mgmt"
MGMT_SUBNET = "192.168.121.0/24"

# p2p routed linkler icin ayrilmis blok — rastgele VLAN subnetleri buna girmez
_P2P_BLOCK = ipaddress.ip_network("10.0.0.0/16")

# hostname semalari: (spine_fmt, leaf_fmt, host_fmt) — seed=0 daima 0. semayi alir
_SCHEMES = [
    ("spine{i}", "leaf{i}", "host{a}"),
    ("ist-core-{i:02d}", "ist-sw-{i:02d}", "ist-pc-{i:02d}"),
    ("ank-omurga-{i:02d}", "ank-kenar-{i:02d}", "ank-pc-{i:02d}"),
    ("dc1-spine-{i:02d}", "dc1-tor-{i:02d}", "dc1-srv-{i:02d}"),
]

_VLAN_NAMES = ["USERS", "OFIS", "SUNUCU", "KAMERA", "MISAFIR", "YONETIM", "DEPO", "LABNET"]


@dataclass(frozen=True)
class TopoSpec:
    """Bir lab dunyasinin tam tanimi. Alanlar sozlesme geregi sabit:

    name, seed, mgmt_subnet, l3 ("ospf"|"static"),
    features {portchannel,l2loop,vrrp,multi_vlan,static},
    vlans [{id,name,subnet,gw_device,gw_ip}],
    ceos_nodes {ad: {role,mgmt_ipv4,router_id,loopback_ip,interfaces,...}},
    hosts {ad: {ip_cidr,gw,vlan,attached:(leaf,intf)}}
    """

    name: str
    seed: int
    mgmt_subnet: str
    l3: str
    features: dict
    vlans: list
    ceos_nodes: dict
    hosts: dict
    # fiziksel kablolama: {"kind": access|routed|trunk|pc-member,
    #                      "a": (node, eth_no), "b": (node, eth_no), ...meta}
    links: list = field(default_factory=list)

    # ------------------------------------------------------------ yardimcilar

    @property
    def mgmt_net(self) -> str:
        return f"{self.name}{MGMT_NET_SUFFIX}"

    def container_name(self, node: str) -> str:
        return f"clab-{self.name}-{node}"

    def inventory(self) -> dict[str, Node]:
        inv: dict[str, Node] = {}
        for name, nd in self.ceos_nodes.items():
            inv[name] = Node(name=name, os="eos", host=nd["mgmt_ipv4"], container=self.container_name(name))
        for name in self.hosts:
            inv[name] = Node(name=name, os="linux", container=self.container_name(name))
        return inv

    def routed_links(self) -> list[tuple[str, str, str, str]]:
        """(cihazA, arayuzA, cihazB, arayuzB) — L3 p2p linkler (OSPF adjacency sayisi buradan)."""
        return [
            (l["a"][0], f"Ethernet{l['a'][1]}", l["b"][0], f"Ethernet{l['b'][1]}")
            for l in self.links
            if l["kind"] == "routed"
        ]

    def trunk_links(self) -> list[tuple[str, str, str, str]]:
        """(cihazA, arayuzA, cihazB, arayuzB) — mantiksal trunk'lar.

        Port-channel uyeleri tek bir (Port-ChannelN, Port-ChannelN) girdisine
        katlanir: trunk konfigu PC arayuzunde yasar.
        """
        out: list[tuple[str, str, str, str]] = []
        seen_pc: set[str] = set()
        for l in self.links:
            if l["kind"] == "trunk":
                out.append((l["a"][0], f"Ethernet{l['a'][1]}", l["b"][0], f"Ethernet{l['b'][1]}"))
            elif l["kind"] == "pc-member" and l["pc"] not in seen_pc:
                seen_pc.add(l["pc"])
                out.append((l["a"][0], l["pc"], l["b"][0], l["pc"]))
        return out

    def access_ports(self) -> list[tuple[str, str, str]]:
        """(cihaz, arayuz, host) — host'a bakan access portlar."""
        return [
            (l["a"][0], f"Ethernet{l['a'][1]}", l["b"][0])
            for l in self.links
            if l["kind"] == "access"
        ]


# ---------------------------------------------------------------- parametre cekimi

def _draw_vlan_subnet(rng: random.Random, taken: list, mgmt_net) -> ipaddress.IPv4Network:
    """RFC1918 icinden rastgele /24 — mgmt, p2p blogu ve onceki secimlerle cakismaz."""
    while True:
        block = rng.choice(("10", "172", "192"))
        if block == "10":
            net = ipaddress.ip_network(f"10.{rng.randint(1, 254)}.{rng.randint(0, 255)}.0/24")
        elif block == "172":
            net = ipaddress.ip_network(f"172.{rng.randint(16, 31)}.{rng.randint(0, 255)}.0/24")
        else:
            third = rng.randint(0, 255)
            if 121 <= third <= 126:      # lane mgmt bloklari — kosulsuz rezerve
                continue
            net = ipaddress.ip_network(f"192.168.{third}.0/24")
        if net.overlaps(_P2P_BLOCK) or net.overlaps(mgmt_net):
            continue
        if any(net.overlaps(t) for t in taken):
            continue
        return net


def _draw_params(seed: int, rng: random.Random, mgmt_net) -> dict:
    """Tum rastgele kararlar tek yerde — cekim sirasi sabit, determinizm garantili."""
    if seed == 0:
        return {
            "scheme": _SCHEMES[0],
            "n_leaves": 2,
            "vlan_ids": [10],
            "vlan_names": ["USERS"],
            "vlan_subnets": [ipaddress.ip_network("10.10.0.0/24")],
            "l3": "ospf",
            "portchannel": False,
            "vrrp": False,
            "l2loop": False,
            "hosts_per_leaf": [1, 1],
            "host_vlans": [10, 10],
            "gw_leaf_idx": [0],       # vlan sirasiyla gw leaf indeksi
            "vrrp_pair": None,
        }

    scheme = rng.choice(_SCHEMES)
    n_leaves = rng.randint(2, 3)
    n_vlans = rng.randint(1, 3)
    vlan_ids = sorted(rng.sample(range(10, 1000), n_vlans))
    vlan_names = rng.sample(_VLAN_NAMES, n_vlans)
    subnets: list = []
    for _ in range(n_vlans):
        subnets.append(_draw_vlan_subnet(rng, subnets, mgmt_net))
    l3 = rng.choice(("ospf", "static"))
    portchannel = rng.random() < 0.35
    vrrp = rng.random() < 0.30
    l2loop = rng.random() < 0.25

    hosts_per_leaf = [rng.randint(0, 2) for _ in range(n_leaves)]
    if sum(hosts_per_leaf) == 0:
        hosts_per_leaf[0] = 1        # dunya en az 1 host icersin (semptom uretimi icin)
    host_vlans = [rng.choice(vlan_ids) for _ in range(sum(hosts_per_leaf))]
    gw_leaf_idx = [rng.randrange(n_leaves) for _ in range(n_vlans)]
    vrrp_pair = tuple(sorted(rng.sample(range(n_leaves), 2))) if vrrp else None
    return {
        "scheme": scheme,
        "n_leaves": n_leaves,
        "vlan_ids": vlan_ids,
        "vlan_names": vlan_names,
        "vlan_subnets": subnets,
        "l3": l3,
        "portchannel": portchannel,
        "vrrp": vrrp,
        "l2loop": l2loop,
        "hosts_per_leaf": hosts_per_leaf,
        "host_vlans": host_vlans,
        "gw_leaf_idx": gw_leaf_idx,
        "vrrp_pair": vrrp_pair,
    }


# ---------------------------------------------------------------- montaj

def _host_name(fmt: str, idx: int) -> str:
    if "{a}" in fmt:
        return fmt.replace("{a}", chr(ord("a") + idx))
    return fmt.format(i=idx + 1)


def build_spec(seed: int, name: str = LAB_NAME, mgmt_subnet: str = MGMT_SUBNET) -> TopoSpec:
    """Deterministik dunya montaji: ayni seed her zaman ayni TopoSpec."""
    rng = random.Random(seed)
    mgmt = ipaddress.ip_network(mgmt_subnet)
    p = _draw_params(seed, rng, mgmt)

    spine_fmt, leaf_fmt, host_fmt = p["scheme"]
    spine = spine_fmt.format(i=1)
    leaves = [leaf_fmt.format(i=i + 1) for i in range(p["n_leaves"])]
    all_ceos = [spine, *leaves]

    # vlan plani
    vlans: list[dict] = []
    for vi, vid in enumerate(p["vlan_ids"]):
        subnet = p["vlan_subnets"][vi]
        if p["vrrp_pair"] is not None and vi == 0:
            gw_dev = leaves[p["vrrp_pair"][0]]      # birincil (yuksek oncelik)
        else:
            gw_dev = leaves[p["gw_leaf_idx"][vi]]
        vlans.append({
            "id": vid,
            "name": p["vlan_names"][vi],
            "subnet": str(subnet),
            "gw_device": gw_dev,
            "gw_ip": str(subnet.network_address + 1),
        })

    # node iskeletleri
    ceos_nodes: dict[str, dict] = {}
    for i, node in enumerate(all_ceos):
        lb = f"{i + 1}.{i + 1}.{i + 1}.{i + 1}"
        ceos_nodes[node] = {
            "role": "spine" if node == spine else "leaf",
            "mgmt_ipv4": str(mgmt.network_address + 11 + i),
            "router_id": lb,
            "loopback_ip": lb,
            "vlans": [] if node == spine else [{"id": v["id"], "name": v["name"]} for v in vlans],
            "interfaces": [],
            "ospf_networks": [],
            "ospf_passive": [],
            "static_routes": [],
        }

    links: list[dict] = []
    eth_no = {node: 0 for node in all_ceos}

    def next_eth(node: str) -> int:
        eth_no[node] += 1
        return eth_no[node]

    def add_intf(node: str, **kw) -> None:
        ceos_nodes[node]["interfaces"].append(kw)

    # 1) access portlar + hostlar
    hosts: dict[str, dict] = {}
    vlan_by_id = {v["id"]: v for v in vlans}
    host_ip_cursor = {v["id"]: 20 for v in vlans}       # .20, .30, ... (seed=0 uyumu)
    hi = 0
    for li, leaf in enumerate(leaves):
        for _ in range(p["hosts_per_leaf"][li]):
            hname = _host_name(host_fmt, hi)
            vid = p["host_vlans"][hi]
            v = vlan_by_id[vid]
            subnet = ipaddress.ip_network(v["subnet"])
            ip = str(subnet.network_address + host_ip_cursor[vid])
            host_ip_cursor[vid] += 10
            e = next_eth(leaf)
            links.append({"kind": "access", "a": (leaf, e), "b": (hname, 1), "vlan": vid})
            add_intf(leaf, name=f"Ethernet{e}", desc=f"to-{hname}", access_vlan=vid)
            hosts[hname] = {
                "ip_cidr": f"{ip}/{subnet.prefixlen}",
                "gw": v["gw_ip"],
                "vlan": vid,
                "attached": (leaf, f"Ethernet{e}"),
            }
            hi += 1

    # 2) routed uplink'ler (leaf -> spine yildizi), 10.0.k.0/30
    uplink_of: dict[str, dict] = {}
    for k, leaf in enumerate(leaves, start=1):
        le, se = next_eth(leaf), next_eth(spine)
        leaf_ip, spine_ip = f"10.0.{k}.1", f"10.0.{k}.2"
        links.append({"kind": "routed", "a": (leaf, le), "b": (spine, se), "subnet": f"10.0.{k}.0/30"})
        add_intf(leaf, name=f"Ethernet{le}", desc=f"to-{spine}", ip=f"{leaf_ip}/30")
        add_intf(spine, name=f"Ethernet{se}", desc=f"to-{leaf}", ip=f"{spine_ip}/30")
        uplink_of[leaf] = {"subnet": f"10.0.{k}.0/30", "leaf_ip": leaf_ip, "spine_ip": spine_ip}

    # 3) trunk zinciri (L2 tum leaflere yayilsin) — ilk cift istege gore port-channel
    allowed = ",".join(str(v["id"]) for v in vlans)
    pairs = list(zip(leaves, leaves[1:]))
    for pi, (a, b) in enumerate(pairs):
        if p["portchannel"] and pi == 0:
            for _ in range(2):
                ae, be = next_eth(a), next_eth(b)
                links.append({"kind": "pc-member", "a": (a, ae), "b": (b, be), "pc": "Port-Channel1"})
                add_intf(a, name=f"Ethernet{ae}", desc=f"pc1-to-{b}", channel_group=1)
                add_intf(b, name=f"Ethernet{be}", desc=f"pc1-to-{a}", channel_group=1)
            add_intf(a, name="Port-Channel1", desc=f"trunk-to-{b}", trunk_vlans=allowed)
            add_intf(b, name="Port-Channel1", desc=f"trunk-to-{a}", trunk_vlans=allowed)
        else:
            ae, be = next_eth(a), next_eth(b)
            links.append({"kind": "trunk", "a": (a, ae), "b": (b, be)})
            add_intf(a, name=f"Ethernet{ae}", desc=f"trunk-to-{b}", trunk_vlans=allowed)
            add_intf(b, name=f"Ethernet{be}", desc=f"trunk-to-{a}", trunk_vlans=allowed)

    # 4) l2loop: ilk cifte ikinci dogrudan trunk — STP devrede, biri bloklanir
    if p["l2loop"]:
        a, b = pairs[0]
        ae, be = next_eth(a), next_eth(b)
        links.append({"kind": "trunk", "a": (a, ae), "b": (b, be), "redundant": True})
        add_intf(a, name=f"Ethernet{ae}", desc=f"l2loop-trunk-to-{b}", trunk_vlans=allowed)
        add_intf(b, name=f"Ethernet{be}", desc=f"l2loop-trunk-to-{a}", trunk_vlans=allowed)

    # 5) loopback'ler
    for node in all_ceos:
        add_intf(node, name="Loopback0", ip=f"{ceos_nodes[node]['loopback_ip']}/32")

    # 6) SVI'lar (gateway'ler; vrrp'de iki leaf + VIP)
    for vi, v in enumerate(vlans):
        subnet = ipaddress.ip_network(v["subnet"])
        if p["vrrp_pair"] is not None and vi == 0:
            group = (v["id"] % 254) + 1
            peers = [leaves[j] for j in p["vrrp_pair"]]
            for pri_i, node in enumerate(peers):
                add_intf(
                    node,
                    name=f"Vlan{v['id']}",
                    desc=f"gateway-{v['name']}",
                    ip=f"{subnet.network_address + 2 + pri_i}/{subnet.prefixlen}",
                    vrrp={"group": group, "vip": v["gw_ip"], "priority": 120 - pri_i * 20},
                )
            v["vrrp_peers"] = peers
        else:
            add_intf(
                v["gw_device"],
                name=f"Vlan{v['id']}",
                desc=f"gateway-{v['name']}",
                ip=f"{v['gw_ip']}/{subnet.prefixlen}",
            )

    # 7) l3: ospf network'leri ya da statik rotalar
    svi_owners = {
        node: [i for i in ceos_nodes[node]["interfaces"] if i["name"].startswith("Vlan")]
        for node in all_ceos
    }
    if p["l3"] == "ospf":
        for node in all_ceos:
            nd = ceos_nodes[node]
            for l in links:
                if l["kind"] == "routed" and node in (l["a"][0], l["b"][0]):
                    nd["ospf_networks"].append(l["subnet"])
            nd["ospf_networks"].append(f"{nd['loopback_ip']}/32")
            for svi in svi_owners[node]:
                vid = int(svi["name"].removeprefix("Vlan"))
                nd["ospf_networks"].append(vlan_by_id[vid]["subnet"])
                nd["ospf_passive"].append(svi["name"])
    else:
        for leaf in leaves:
            ceos_nodes[leaf]["static_routes"].append(
                {"prefix": "0.0.0.0/0", "nexthop": uplink_of[leaf]["spine_ip"]}
            )
        for v in vlans:
            ceos_nodes[spine]["static_routes"].append(
                {"prefix": v["subnet"], "nexthop": uplink_of[v["gw_device"]]["leaf_ip"]}
            )
        for leaf in leaves:
            ceos_nodes[spine]["static_routes"].append(
                {"prefix": f"{ceos_nodes[leaf]['loopback_ip']}/32", "nexthop": uplink_of[leaf]["leaf_ip"]}
            )

    features = {
        "portchannel": p["portchannel"],
        "l2loop": p["l2loop"],
        "vrrp": p["vrrp_pair"] is not None,
        "multi_vlan": len(vlans) > 1,
        "static": p["l3"] == "static",
    }
    return TopoSpec(
        name=name,
        seed=seed,
        mgmt_subnet=mgmt_subnet,
        l3=p["l3"],
        features=features,
        vlans=vlans,
        ceos_nodes=ceos_nodes,
        hosts=hosts,
        links=links,
    )


# ---------------------------------------------------------------- geriye uyum

_DEFAULT_SPEC: TopoSpec | None = None


def default_spec() -> TopoSpec:
    """Varsayilan (seed=0) spec — modul seviyesi yardimcilarin dayanagi."""
    global _DEFAULT_SPEC
    if _DEFAULT_SPEC is None:
        _DEFAULT_SPEC = build_spec(0)
    return _DEFAULT_SPEC


def container_name(node: str) -> str:
    return default_spec().container_name(node)


def inventory() -> dict[str, Node]:
    return default_spec().inventory()
