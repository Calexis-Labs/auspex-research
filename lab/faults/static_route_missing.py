import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


@fault("static_route_missing")
class StaticRouteMissing:
    """Statik dunyada rastgele bir statik rota silinir: leaf'te default rota
    kaybi tum uzak erisimi, spine'da subnet/loopback rotasi kaybi tek yonlu
    erisimi dusurur. Linkler up/up — teshis routing tablosundaki eksigi
    fark etmeyi gerektirir."""

    requires: dict = {"static": True}

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        routes = []
        for dev in sorted(topo.ceos_nodes):
            for r in topo.ceos_nodes[dev]["static_routes"]:
                routes.append((dev, r["prefix"], r["nexthop"]))
        if not routes:
            raise ValueError("static_route_missing: dunyada statik rota yok (l3=ospf; scheduler atlamali)")
        device, prefix, nexthop = rng.choice(routes)
        self._target = (device, prefix, nexthop)
        pe.eos_config(device, f"no ip route {prefix} {nexthop}")
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=f"{device} static route {prefix} via {nexthop} deleted; destinations behind it unreachable",
            fix_commands=[f"ip route {prefix} {nexthop}"],
            key_terms=[prefix],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, prefix, nexthop = self._target
        pe.eos_config(device, f"ip route {prefix} {nexthop}")
