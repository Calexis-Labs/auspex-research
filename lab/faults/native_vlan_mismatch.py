import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


def draw_unused_vlan_id(topo: TopoSpec, rng: random.Random) -> int:
    """Topolojide OLMAYAN yeni bir vlan id ceker (1 haric; gecerli aralik 2-999)."""
    existing = {v["id"] for v in topo.vlans}
    return rng.choice([v for v in range(2, 1000) if v not in existing])


@fault("native_vlan_mismatch")
class NativeVlanMismatch:
    """Rastgele bir trunk'in TEK ucunda native vlan yeni bir id'ye cekilir
    (+ o vlan olusturulur): iki uc etiketsiz cerceveleri farkli vlanlara koyar,
    cEOS native vlan uyusmazligi loglar. show interfaces trunk iki ucta farkli
    native vlan gosterir — mismatch oradan kesfedilir."""

    requires: dict = {}
    # base topolojide trunk yalnizca etiketli VLAN tasir; native VLAN'da trafik
    # olmadigi icin uyusmazlik veri duzlemini bozmaz (yalniz log uyarisi) —
    # gozlenir semptom icin native-VLAN trafigi tasiyan topoloji gerekir (Faz 2)
    live_verified: bool = False

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        ends = []
        for a_dev, a_if, b_dev, b_if in topo.trunk_links():
            ends.append((a_dev, a_if, b_dev))
            ends.append((b_dev, b_if, a_dev))
        device, intf, peer = rng.choice(ends)
        vid = draw_unused_vlan_id(topo, rng)
        self._target = (device, intf, vid)
        pe.eos_config(
            device,
            f"vlan {vid}",
            "exit",
            f"interface {intf}",
            f"switchport trunk native vlan {vid}",
        )
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=(
                f"native vlan mismatch: {device} {intf} trunk native vlan set to {vid}, "
                f"peer {peer} still uses default native vlan 1"
            ),
            fix_commands=[f"interface {intf}", "no switchport trunk native vlan", "exit", f"no vlan {vid}"],
            key_terms=[intf.lower(), str(vid)],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf, vid = self._target
        pe.eos_config(
            device,
            f"interface {intf}",
            "no switchport trunk native vlan",
            "exit",
            f"no vlan {vid}",
        )
