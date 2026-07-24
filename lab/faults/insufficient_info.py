import random

from lab.faults import GroundTruth, PrivilegedExec, fault
from lab.topo import TopoSpec


@fault("insufficient_info")
class InsufficientInfo:
    """no_fault gibi no-op: aga dokunulmaz. Fark SEMPTOMUN OZNESINDE (v2,
    pilot dersi): eski tasarim 'mugla sikayet + saglikli ag' idi — bu no_fault
    ile etiket-ikiziydi (0/9, model hakli olarak no_fault dedi). Yeni tasarim:
    sikayetin oznesi araclarla GOZLENEMEYEN bir sistemdir (kablosuz ag, VPN,
    yazici, IP telefon, uygulama/e-posta yazilimi). Model gorebildigi agi
    dogrular (temiz), ama sikayetin kendisini test EDEMEZ — dogru cevap
    'gorunurlugum disinda; su ek bilgi/erisim gerekli' demektir.
    no_fault'tan ayrim ogrenilebilir: no_fault'ta sikayet agin kendisi
    hakkindadir ve testler yapilabilir; burada yapilamaz."""

    requires: dict = {}

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        return GroundTruth(
            device="none",
            fault_class=self.name,
            root_cause=(
                "bilgi yetersiz: sikayetin oznesi mevcut araclarin gorunurlugu "
                "disinda (orn. kablosuz/VPN/yazici/uygulama katmani); gozlenebilen "
                "ag tarafi saglikli — teshis icin ilgili sisteme erisim veya ek "
                "bilgi (etkilenen cihaz IP'si, hata mesaji, kapsam) gerekli"
            ),
            fix_commands=[],
            key_terms=[],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        pass
