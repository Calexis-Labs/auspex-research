import ipaddress
import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


@fault("wrong_host_gateway")
class WrongHostGateway:
    """Rastgele bir hostun default gateway'i yanlis IP'ye cevrilir: ayni L2'deki
    komsulara ulasir ama routed hicbir yere ulasamaz. Ag cihazlarinda ariza
    YOKTUR — kirmizi ringa direncinin ilk testi."""

    requires: dict = {}

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        host = rng.choice(sorted(topo.hosts))
        h = topo.hosts[host]
        subnet = ipaddress.ip_network(h["ip_cidr"], strict=False)
        host_ip = h["ip_cidr"].split("/")[0]
        # sahte gw ON-LINK olmali: dar maskede (orn /26) net+254 subnet disina
        # duser, kernel "Nexthop has invalid gateway" der (uretim 2026-07-17).
        # Broadcast'ten geriye yuru; gercek gw ve hostun kendisi atlanir.
        ip = subnet.broadcast_address - 1
        while str(ip) in (h["gw"], host_ip) and ip > subnet.network_address:
            ip -= 1
        bogus = str(ip)
        self._target = (host, h["gw"])
        pe.host_cmd(host, f"ip route replace default via {bogus}")
        return GroundTruth(
            device=host,
            fault_class=self.name,
            root_cause=f"{host} default gateway misconfigured as {bogus} (should be {h['gw']})",
            fix_commands=[f"ip route replace default via {h['gw']}"],
            key_terms=[h["gw"]],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        host, gw = self._target
        pe.host_cmd(host, f"ip route replace default via {gw}")
