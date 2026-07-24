import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


def _is_ospf(topo: TopoSpec) -> bool:
    # Cekirdek features'a "ospf" anahtarini koyana kadar l3 alanindan turetilir
    return bool(topo.features.get("ospf", topo.l3 == "ospf"))


@fault("ospf_passive_transit")
class OspfPassiveTransit:
    """Rastgele bir transit (routed) interface OSPF'te passive yapilir: hello
    gonderimi durur, komsu dead timer sonrasi kaybolur. Interface up/up VE
    mtu normaldir — ospf_mtu_mismatch ile karistirilabilir; ayirt edici kanit
    'router ospf' bolumundeki passive-interface satiridir."""

    requires: dict = {}

    def available(self, spec: TopoSpec) -> bool:
        return _is_ospf(spec)

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        if not _is_ospf(topo):
            raise ValueError("ospf_passive_transit yalnizca ospf dunyasina enjekte edilir (scheduler atlamali)")
        ends = []
        for a_dev, a_if, b_dev, b_if in topo.routed_links():
            ends.append((a_dev, a_if, b_dev))
            ends.append((b_dev, b_if, a_dev))
        device, intf, peer = rng.choice(ends)
        self._target = (device, intf)
        pe.eos_config(device, "router ospf 1", f"passive-interface {intf}")
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=(
                f"{device} {intf} made passive in OSPF; hellos suppressed, neighbor "
                f"{peer} lost (interface up/up, mtu normal)"
            ),
            fix_commands=["router ospf 1", f"no passive-interface {intf}"],
            key_terms=[intf.lower(), "passive"],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf = self._target
        pe.eos_config(device, "router ospf 1", f"no passive-interface {intf}")
