import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


@fault("svi_down")
class SviDown:
    """Vrrp'siz bir VLAN'in gateway SVI'si kapatilir: o VLAN'daki hostlar
    gateway'e ve routed hedeflere ulasamaz, L2 komsuluk calismaya devam eder.
    show ip interface brief SVI'yi admin down gosterir. Vrrp'li vlanlarda
    yedek gateway semptomu maskeler — onlar aday degildir."""

    requires: dict = {}

    def available(self, spec: TopoSpec) -> bool:
        """Vrrp'siz en az bir vlan olmali — yoksa scheduler bu sinifi bu dunyaya atamaz."""
        return any(not v.get("vrrp_peers") for v in spec.vlans)

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        candidates = [v for v in topo.vlans if not v.get("vrrp_peers")]
        if not candidates:
            raise LookupError("svi_down: vrrp'siz vlan yok — senaryo bu dunyada atlanmali")
        vlan = rng.choice(candidates)
        device = vlan["gw_device"]
        intf = f"Vlan{vlan['id']}"
        self._target = (device, intf)
        pe.eos_config(device, f"interface {intf}", "shutdown")
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=f"{device} {intf} (gateway SVI for vlan {vlan['id']}) administratively down",
            fix_commands=[f"interface {intf}", "no shutdown"],
            key_terms=[intf.lower()],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf = self._target
        pe.eos_config(device, f"interface {intf}", "no shutdown")
