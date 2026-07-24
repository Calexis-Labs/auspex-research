import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


def _is_ospf(topo: TopoSpec) -> bool:
    # Cekirdek features'a "ospf" anahtarini koyana kadar l3 alanindan turetilir
    return bool(topo.features.get("ospf", topo.l3 == "ospf"))


@fault("ospf_hello_mismatch")
class OspfHelloMismatch:
    """Rastgele bir routed linkin TEK ucunda hello-interval 60'a cekilir:
    hello/dead timer'lari uyusmayan hello paketleri reddedilir, adjacency
    duser. Interface up/up, mtu normal — teshis 'show ip ospf neighbor'
    kaybini interface timer konfiguna baglamayi gerektirir."""

    requires: dict = {}

    def available(self, spec: TopoSpec) -> bool:
        return _is_ospf(spec)

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        if not _is_ospf(topo):
            raise ValueError("ospf_hello_mismatch yalnizca ospf dunyasina enjekte edilir (scheduler atlamali)")
        ends = []
        for a_dev, a_if, b_dev, b_if in topo.routed_links():
            ends.append((a_dev, a_if, b_dev))
            ends.append((b_dev, b_if, a_dev))
        device, intf, peer = rng.choice(ends)
        self._target = (device, intf)
        # bounce: kurulu adjacency dead-timer'a kadar dusmez; interface'i
        # sektirince yeniden pazarlik hemen basar ve timer uyusmazligindan takilir
        pe.eos_config(device, f"interface {intf}", "ip ospf hello-interval 60", "shutdown", "no shutdown")
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=(
                f"{device} {intf} OSPF hello-interval set to 60 while peer {peer} uses "
                f"default 10 — timer mismatch, hellos rejected, adjacency down"
            ),
            fix_commands=[f"interface {intf}", "no ip ospf hello-interval 60"],
            key_terms=[intf.lower(), "hello"],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf = self._target
        pe.eos_config(device, f"interface {intf}", "no ip ospf hello-interval 60", "shutdown", "no shutdown")
