import random

from lab.faults import FAULTS, GroundTruth, PrivilegedExec, fault, resolve, usable
from lab.topo import TopoSpec

# meta siniflar aday olamaz
_EXCLUDE = {"no_fault", "insufficient_info", "multi_fault"}


@fault("multi_fault")
class MultiFault:
    """Registry'den requires'i uyan 2 BAGIMSIZ sinif secilir (meta siniflar
    haric), ikisi de enjekte edilir ve list[GroundTruth] doner. Ajanin ilk
    buldugu arizada durmamasini olcer. Revert ters sirayla ikisini de geri
    alir."""

    requires: dict = {}

    def available(self, spec: TopoSpec) -> bool:
        return len([n for n, f in FAULTS.items() if n not in _EXCLUDE and usable(f, spec)]) >= 2

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> list[GroundTruth]:
        topo, rng = resolve(topo, rng)
        # usable() available() predicate'lerini de kontrol eder — LookupError'lu
        # dunyalara alt-ariza atanmaz
        candidates = sorted(n for n, f in FAULTS.items() if n not in _EXCLUDE and usable(f, topo))
        picked = rng.sample(candidates, 2)
        self._active = []
        gts: list[GroundTruth] = []
        try:
            for name in picked:
                sub = FAULTS[name]
                gt = sub.inject(pe, topo, rng)
                gts.extend(gt if isinstance(gt, list) else [gt])
                self._active.append(sub)
        except Exception:
            # kismi enjeksiyon lab'i bozuk birakamaz: uygulanmislari geri al, sonra firlat
            for sub in reversed(self._active):
                try:
                    sub.revert(pe, topo)
                except Exception:
                    pass
            self._active = []
            raise
        return gts

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        topo, _ = resolve(topo, None)
        for sub in reversed(self._active):
            sub.revert(pe, topo)
