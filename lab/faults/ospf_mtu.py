import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


@fault("ospf_mtu_mismatch")
class OspfMtuMismatch:
    """Rastgele bir routed linkin rastgele ucunda MTU 1400'e cekilir: adjacency
    DBD MTU kontrolune takilip EXSTART/EXCHANGE'de asili kalir; karsi tarafin
    rotalari kaybolur. Interface up/up gorunur — teshis MTU degerini fark
    etmeyi gerektirir. Statik dunyalarda anlamsiz — requires ile atlanir."""

    requires: dict = {"static": False}

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        ends = []
        for a_dev, a_if, b_dev, b_if in topo.routed_links():
            ends.append((a_dev, a_if, b_dev))
            ends.append((b_dev, b_if, a_dev))
        device, intf, peer = rng.choice(ends)
        self._target = (device, intf)
        # mtu degisikligi adjacency'yi her surumde kendiliginden dusurmeyebilir;
        # bounce, yeniden pazarligi garantiler (interface up/up kalir)
        pe.eos_config(device, f"interface {intf}", "mtu 1400", "shutdown", "no shutdown")
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=f"{device} {intf} MTU lowered to 1400; OSPF adjacency to {peer} stuck (DBD MTU mismatch)",
            fix_commands=[f"interface {intf}", "mtu 1500"],
            key_terms=[intf.lower(), "mtu"],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf = self._target
        pe.eos_config(device, f"interface {intf}", "mtu 1500", "shutdown", "no shutdown")
