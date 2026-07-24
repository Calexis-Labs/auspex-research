import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


def _is_ospf(topo: TopoSpec) -> bool:
    # Cekirdek features'a "ospf" anahtarini koyana kadar l3 alanindan turetilir
    return bool(topo.features.get("ospf", topo.l3 == "ospf"))


@fault("ospf_auth_mismatch")
class OspfAuthMismatch:
    """Rastgele bir routed linkin TEK ucunda md5 authentication acilir: karsi
    uc duz hello gonderdigi icin paketler dusurulur, adjacency kaybolur.
    Interface up/up, mtu normal — teshis interface'teki 'ip ospf
    authentication' satirini fark etmeyi gerektirir."""

    requires: dict = {}

    def available(self, spec: TopoSpec) -> bool:
        return _is_ospf(spec)

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        if not _is_ospf(topo):
            raise ValueError("ospf_auth_mismatch yalnizca ospf dunyasina enjekte edilir (scheduler atlamali)")
        ends = []
        for a_dev, a_if, b_dev, b_if in topo.routed_links():
            ends.append((a_dev, a_if, b_dev))
            ends.append((b_dev, b_if, a_dev))
        device, intf, peer = rng.choice(ends)
        key = f"agr{rng.randint(100, 999)}"
        self._target = (device, intf, key)
        # bounce: kurulu adjacency dead-timer'a kadar dusmez; sektirince yeniden
        # pazarlik hemen basar ve auth uyusmazligindan takilir
        pe.eos_config(
            device,
            f"interface {intf}",
            "ip ospf authentication message-digest",
            f"ip ospf message-digest-key 1 md5 {key}",
            "shutdown",
            "no shutdown",
        )
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=(
                f"{device} {intf} requires OSPF md5 authentication; peer {peer} sends "
                f"unauthenticated hellos — packets dropped, adjacency lost"
            ),
            fix_commands=[
                f"interface {intf}",
                "no ip ospf authentication message-digest",
                "no ip ospf message-digest-key 1",
            ],
            key_terms=[intf.lower(), "authentication"],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf, key = self._target
        pe.eos_config(
            device,
            f"interface {intf}",
            "no ip ospf authentication message-digest",
            "no ip ospf message-digest-key 1",
            "shutdown",
            "no shutdown",
        )
