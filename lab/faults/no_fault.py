import random

from lab.faults import GroundTruth, PrivilegedExec, fault
from lab.topo import TopoSpec


@fault("no_fault")
class NoFault:
    """HICBIR sey degistirmez: ag sagliklidir, sikayet ag disi kaynaklidir
    (uygulama, kullanici hatasi, izleme...). Ajanin ariza UYDURMAMASINI
    olcer — dogru cevap 'ag temiz' demektir."""

    requires: dict = {}

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        return GroundTruth(
            device="none",
            fault_class=self.name,
            root_cause="ag sagliklidir; bildirilen sorun ag kaynakli degil",
            fix_commands=[],
            key_terms=[],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        pass
