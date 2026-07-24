import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.faults.native_vlan_mismatch import draw_unused_vlan_id
from lab.topo import TopoSpec


@fault("access_port_wrong_vlan")
class AccessPortWrongVlan:
    """Rastgele bir access port yanlis vlan'a tasinir — ya topolojideki baska
    bir vlan ya da hic var olmayan bir id: host kendi L2 alanindan kopar,
    gateway'e ve komsularina ulasamaz. show interfaces status / show vlan
    portun yanlis (veya inaktif) uyeligini gosterir."""

    requires: dict = {}

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        device, intf, host = rng.choice(topo.access_ports())
        correct = topo.hosts[host]["vlan"]
        # aday yanlis vlanlar: once var olmayan id cekilir (cekim sirasi sabit),
        # sonra topolojideki diger vlanlarla birlikte secime girer
        bogus = draw_unused_vlan_id(topo, rng)
        others = sorted({v["id"] for v in topo.vlans} - {correct})
        wrong = rng.choice([*others, bogus])
        self._target = (device, intf, correct)
        pe.eos_config(device, f"interface {intf}", f"switchport access vlan {wrong}")
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=(
                f"{device} {intf} access vlan changed to {wrong}; "
                f"host {host} belongs in vlan {correct}"
            ),
            fix_commands=[f"interface {intf}", f"switchport access vlan {correct}"],
            key_terms=[intf.lower(), str(wrong)],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf, correct = self._target
        pe.eos_config(device, f"interface {intf}", f"switchport access vlan {correct}")
