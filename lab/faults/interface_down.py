import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


@fault("interface_admin_down")
class InterfaceAdminDown:
    """Rastgele bir routed linkin rastgele ucu kapatilir: o link uzerinden
    tasinan routed erisim duser, L2 (trunk) trafigi calismaya devam eder."""

    requires: dict = {}

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        ends = []
        for a_dev, a_if, b_dev, b_if in topo.routed_links():
            ends.append((a_dev, a_if, b_dev))
            ends.append((b_dev, b_if, a_dev))
        device, intf, peer = rng.choice(ends)
        self._target = (device, intf)
        pe.eos_config(device, f"interface {intf}", "shutdown")
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=f"{device} {intf} (link to {peer}) administratively down (shutdown)",
            fix_commands=[f"interface {intf}", "no shutdown"],
            key_terms=[intf.lower()],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf = self._target
        pe.eos_config(device, f"interface {intf}", "no shutdown")
