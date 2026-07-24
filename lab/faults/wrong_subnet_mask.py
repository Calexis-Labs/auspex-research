import ipaddress
import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


@fault("wrong_subnet_mask")
class WrongSubnetMask:
    """Rastgele bir hostun IP'si ayni adres fakat dar maskla yeniden yazilir;
    gateway yeni subnetin DISINDA kalir: host gateway'e ARP yapamaz (adres
    silinirken default rota da duser). ip -j addr show dar maski gosterir.
    Dar mask gw'yi iceriyorsa bir adim daraltilir (/30 -> /31)."""

    requires: dict = {}

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        host = rng.choice(sorted(topo.hosts))
        h = topo.hosts[host]
        ip_str = h["ip_cidr"].split("/")[0]
        gw = ipaddress.ip_address(h["gw"])
        for narrow in (30, 31):
            if gw not in ipaddress.ip_network(f"{ip_str}/{narrow}", strict=False):
                break
        else:
            raise LookupError(f"wrong_subnet_mask: {host} icin gw'yi disarida birakan dar mask yok")
        narrow_cidr = f"{ip_str}/{narrow}"
        self._target = (host, h["ip_cidr"], narrow_cidr, h["gw"])
        pe.host_cmd(host, f"ip addr del {h['ip_cidr']} dev eth1")
        pe.host_cmd(host, f"ip addr add {narrow_cidr} dev eth1")
        return GroundTruth(
            device=host,
            fault_class=self.name,
            root_cause=(
                f"{host} eth1 netmask wrong: {narrow_cidr} instead of {h['ip_cidr']}; "
                f"gateway {h['gw']} falls outside the /{narrow} subnet"
            ),
            fix_commands=[
                f"ip addr del {narrow_cidr} dev eth1",
                f"ip addr add {h['ip_cidr']} dev eth1",
                f"ip route replace default via {h['gw']}",
            ],
            # ip -j addr show adres ile prefixlen'i AYRI alanlarda verir — birlesik
            # CIDR yerine ayri ayri aranabilir parcalar
            key_terms=[ip_str, f"/{narrow}"],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        host, orig_cidr, narrow_cidr, gw = self._target
        pe.host_cmd(host, f"ip addr del {narrow_cidr} dev eth1")
        pe.host_cmd(host, f"ip addr add {orig_cidr} dev eth1")
        pe.host_cmd(host, f"ip route replace default via {gw}")
