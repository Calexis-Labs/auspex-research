import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


def _is_ospf(topo: TopoSpec) -> bool:
    # Cekirdek features'a "ospf" anahtarini koyana kadar l3 alanindan turetilir
    return bool(topo.features.get("ospf", topo.l3 == "ospf"))


@fault("ospf_area_mismatch")
class OspfAreaMismatch:
    """Rastgele bir routed linkin TEK ucunda p2p subnet'in network statement'i
    area 0 disina tasinir: hello'lardaki area ID uyusmaz, adjacency hic
    kurulmaz, karsi tarafin rotalari kaybolur. Interface up/up ve mtu
    normaldir — teshis iki ucun 'router ospf' konfigunu karsilastirmayi
    gerektirir."""

    requires: dict = {}

    def available(self, spec: TopoSpec) -> bool:
        return _is_ospf(spec)

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        if not _is_ospf(topo):
            raise ValueError("ospf_area_mismatch yalnizca ospf dunyasina enjekte edilir (scheduler atlamali)")
        ends = []
        for l in topo.links:
            if l["kind"] != "routed":
                continue
            a_dev, a_no = l["a"]
            b_dev, b_no = l["b"]
            ends.append((a_dev, f"Ethernet{a_no}", b_dev, l["subnet"]))
            ends.append((b_dev, f"Ethernet{b_no}", a_dev, l["subnet"]))
        device, intf, peer, subnet = rng.choice(ends)
        bad_area = f"0.0.0.{rng.randint(1, 254)}"
        self._target = (device, subnet, bad_area)
        pe.eos_config(
            device,
            "router ospf 1",
            f"no network {subnet} area 0.0.0.0",
            f"network {subnet} area {bad_area}",
        )
        return GroundTruth(
            device=device,
            fault_class=self.name,
            root_cause=(
                f"{device} {intf}: OSPF network {subnet} moved to area {bad_area}; "
                f"peer {peer} stays in area 0.0.0.0 — hello area mismatch, adjacency never forms"
            ),
            fix_commands=[
                "router ospf 1",
                f"no network {subnet} area {bad_area}",
                f"network {subnet} area 0.0.0.0",
            ],
            # arizayi tanimlayan sey area'dir; arayuz adi ikincil (ajan cogu zaman
            # 'router ospf' konfigundan tespit eder, interface'i anmayabilir)
            key_terms=["area"],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, subnet, bad_area = self._target
        pe.eos_config(
            device,
            "router ospf 1",
            f"no network {subnet} area {bad_area}",
            f"network {subnet} area 0.0.0.0",
        )
