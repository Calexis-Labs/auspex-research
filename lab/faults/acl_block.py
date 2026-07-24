import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec

ACL_NAME = "SEC-EDGE-IN"


@fault("acl_blocking_traffic")
class AclBlockingTraffic:
    """Rastgele bir VLAN'in gateway leaf'ine bakan spine arayuzune, o VLAN
    subnet'inden icmp'yi dusuren ingress ACL konur: kullanici subnet'inden
    loopback'lere ping olmez ama OSPF FULL ve rotalar tamdir.

    ECMP dersi (uretim 2026-07-17, 7x no_fault): gw leaf'in BIRDEN COK spine
    uplinki varsa trafik saglam yoldan dolasir, ACL gorunmez olur — model hakli
    olarak no_fault der. Bu yuzden yalniz TEK spine uplinkli gw'ler hedeftir;
    uygun vlan yoksa LookupError (lane 'skipped' sayar, cop fail uretmez)."""

    requires: dict = {}

    def available(self, spec: TopoSpec) -> bool:
        return bool(self._candidate_vlans(spec))

    @staticmethod
    def _candidate_vlans(topo: TopoSpec) -> list[dict]:
        """Gozlenir semptom sarti (v2, 2026-07-18): tek spine uplink (ECMP
        maskeleyemesin) VE vlan'da en az bir host (sikayeti yeniden uretecek
        makine olmadan ACL hicbir aractan gorunmez -> model hakli no_fault)."""
        return [
            v for v in topo.vlans
            if len(AclBlockingTraffic._spine_uplinks(topo, v["gw_device"])) == 1
            and any(h["vlan"] == v["id"] for h in topo.hosts.values())
        ]

    @staticmethod
    def _spine_uplinks(topo: TopoSpec, gw_dev: str) -> list[tuple[str, str]]:
        """gw leaf'in spine'lara bakan (spine_dev, spine_if) uclari."""
        ups = []
        for a_dev, a_if, b_dev, b_if in topo.routed_links():
            if a_dev == gw_dev and topo.ceos_nodes[b_dev]["role"] == "spine":
                ups.append((b_dev, b_if))
            elif b_dev == gw_dev and topo.ceos_nodes[a_dev]["role"] == "spine":
                ups.append((a_dev, a_if))
        return ups

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        cands = self._candidate_vlans(topo)
        if not cands:
            raise LookupError("acl_blocking_traffic: uygun vlan yok (tek uplink + hostlu sart)")
        vlan = rng.choice(cands)
        (spine_dev, spine_if), = self._spine_uplinks(topo, vlan["gw_device"])
        self._target = (spine_dev, spine_if)
        pe.eos_config(
            spine_dev,
            f"ip access-list {ACL_NAME}",
            f"10 deny icmp {vlan['subnet']} any",
            "20 permit ip any any",
            "exit",
            f"interface {spine_if}",
            f"ip access-group {ACL_NAME} in",
        )
        return GroundTruth(
            device=spine_dev,
            fault_class=self.name,
            root_cause=f"ACL {ACL_NAME} on {spine_dev} {spine_if} (in) denies icmp from {vlan['subnet']}",
            fix_commands=[f"interface {spine_if}", f"no ip access-group {ACL_NAME} in"],
            key_terms=[ACL_NAME.lower()],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        spine_dev, spine_if = self._target
        pe.eos_config(
            spine_dev,
            f"interface {spine_if}",
            f"no ip access-group {ACL_NAME} in",
            "exit",
            f"no ip access-list {ACL_NAME}",
        )
