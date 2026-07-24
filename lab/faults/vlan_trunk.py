import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


def _trunk_vlan_ids(topo: TopoSpec, device: str, intf: str) -> list[int]:
    for i in topo.ceos_nodes[device]["interfaces"]:
        if i["name"] == intf and "trunk_vlans" in i:
            return [int(v) for v in i["trunk_vlans"].split(",")]
    return []


def _leaf_positions(topo: TopoSpec) -> dict[str, int]:
    return {n: i for i, n in enumerate(d for d, nd in topo.ceos_nodes.items() if nd["role"] == "leaf")}


def _vlan_affected(topo: TopoSpec, cut: int, vid: int, pos: dict[str, int]) -> bool:
    """Trunk zinciri cut ile ikiye bolununce vid VLAN'inda gozlenir kayip var mi?

    Kayip: bir host gateway'inden ayri tarafta kalirsa YA DA ayni VLAN'daki iki
    host ayri taraflarda kalirsa.
    """
    gw_side = None
    for v in topo.vlans:
        if v["id"] == vid:
            gw_side = pos[v["gw_device"]] <= cut
    host_sides = [
        pos[h["attached"][0]] <= cut for h in topo.hosts.values() if h["vlan"] == vid
    ]
    if gw_side is not None and any(s != gw_side for s in host_sides):
        return True
    return len(set(host_sides)) > 1


@fault("vlan_removed_from_trunk")
class VlanRemovedFromTrunk:
    """Rastgele bir trunk'tan, o trunk'ta tasinan rastgele bir VLAN cikarilir:
    trunk'un otesindeki hostlar o VLAN'da gateway'e/komsulara erisimi kaybeder;
    OSPF FULL kalir. l2loop dunyalarinda yedek trunk kaybi maskeler — atlanir.

    Fallback YOK (uretim dersi 2026-07-18, 6x no_fault): gozlenir semptom
    uretmeyen (host/gw ayrismasi olmayan) hedefe enjeksiyon 'gorunmez ariza'
    demektir — model hakli olarak no_fault der, senaryo cope gider. Uygun hedef
    yoksa LookupError -> lane 'skipped' sayar."""

    requires: dict = {"l2loop": False}

    @staticmethod
    def _candidates(topo: TopoSpec) -> list[tuple[str, str, int]]:
        pos = _leaf_positions(topo)
        cands = []
        for a_dev, a_if, b_dev, b_if in topo.trunk_links():
            cut = min(pos[a_dev], pos[b_dev])
            for end_dev, end_if in ((a_dev, a_if), (b_dev, b_if)):
                for vid in _trunk_vlan_ids(topo, end_dev, end_if):
                    if _vlan_affected(topo, cut, vid, pos):
                        cands.append((end_dev, end_if, vid))
        return cands

    def available(self, spec: TopoSpec) -> bool:
        return bool(self._candidates(spec))

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        candidates = self._candidates(topo)
        if not candidates:
            raise LookupError("vlan_removed_from_trunk: gozlenir semptom uretecek (trunk, vlan) yok")
        device, intf, vid = rng.choice(candidates)
        self._target = (device, intf, vid)
        pe.eos_config(device, f"interface {intf}", f"switchport trunk allowed vlan remove {vid}")
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=f"VLAN {vid} removed from allowed list on {device} {intf} trunk",
            fix_commands=[f"interface {intf}", f"switchport trunk allowed vlan add {vid}"],
            key_terms=[intf.lower(), str(vid)],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf, vid = self._target
        pe.eos_config(device, f"interface {intf}", f"switchport trunk allowed vlan add {vid}")
