import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


@fault("duplicate_ip")
class DuplicateIp:
    """Rastgele bir hosta gateway IP'si secondary olarak eklenir: host artik
    gateway'in IP'sine de ARP cevabi verir, ayni VLAN'daki trafik ARP catismasi
    yuzunden kesintili/asimetrik bozulur. Ag cihazlarinda konfig hatasi YOKTUR
    — kok neden hosttadir; ip -j addr show fazladan adresi gosterir."""

    requires: dict = {}

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        host = rng.choice(sorted(topo.hosts))
        gw = topo.hosts[host]["gw"]
        self._target = (host, gw)
        pe.host_cmd(host, f"ip addr add {gw}/32 dev eth1")
        # gratuitous ARP: switch/komsular gateway IP'sini bu hostun MAC'inde
        # ogrensin ki catisma gercekten gozlenir olsun (aksi halde sessiz kalir)
        pe.host_cmd(host, f"arping -U -c 3 -I eth1 {gw}")
        return GroundTruth(
            device=host,
            fault_class=self.name,
            root_cause=f"{host} eth1 carries duplicate ip {gw}/32 (arp conflict with the real gateway)",
            fix_commands=[f"ip addr del {gw}/32 dev eth1"],
            key_terms=[gw],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        host, gw = self._target
        pe.host_cmd(host, f"ip addr del {gw}/32 dev eth1")
