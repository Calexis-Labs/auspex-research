"""Ariza kayit defteri — API v2.

Sozlesme:
  @fault("sinif_adi") dekoratoru sinifa uygulanir; sinif alanlari:
    requires: dict = {}                          # topo.features'a karsi eslesir
    inject(self, pe, topo, rng) -> GroundTruth | list[GroundTruth]
    revert(self, pe, topo) -> None
  Hedef cihaz/port SECIMI topo+rng'den yapilir (hardcode yok); revert icin
  gereken durum self'e saklanir.

FAULTS, pkgutil ile lab/faults/ altindaki TUM modulleri otomatik import ederek
dolar; FAULT_CLASSES = list(FAULTS).

Enjeksiyon PrivilegedExec ile yapilir (lab host'unda docker exec + FastCli).
Ajanin kullandigi SSH/scrapli yuzeyi bu yola HIC dokunmaz — salt-okunurluk
yapisal olarak korunur. GroundTruth projenin en degerli varligi: hem
verifier'in referansi hem ileride RL odul fonksiyonunun temeli.
"""

import importlib
import pkgutil
import random
import subprocess
from dataclasses import dataclass, field

from lab import topo as _topo_mod
from lab.topo import TopoSpec


@dataclass(frozen=True)
class GroundTruth:
    device: str
    fault_class: str
    root_cause: str
    fix_commands: list[str]
    # ajanin ARAC CIKTILARINDAN kesfedebilecegi anahtar terimler (kucuk harf)
    key_terms: list[str] = field(default_factory=list)


class PrivilegedExec:
    """SADECE ariza enjeksiyonu/geri alma icin yazma yolu. Lab host'unda calisir.

    Cihaz adlari spec.container_name() ile cozulur; spec verilmezse varsayilan
    (seed=0) topoloji kullanilir.
    """

    def __init__(self, spec: TopoSpec | None = None):
        self.spec = spec or _topo_mod.default_spec()

    def _run(self, argv: list[str]) -> str:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"enjeksiyon komutu basarisiz: {argv}\n{proc.stdout}{proc.stderr}")
        return proc.stdout

    def eos_config(self, device: str, *lines: str) -> None:
        script = "\n".join(["configure", *lines, "end"])
        self._run(["docker", "exec", self.spec.container_name(device), "FastCli", "-p", "15", "-c", script])

    def host_cmd(self, device: str, command: str) -> None:
        self._run(["docker", "exec", self.spec.container_name(device), *command.split()])


def resolve(topo: TopoSpec | None, rng: random.Random | None) -> tuple[TopoSpec, random.Random]:
    """Gecis donemi yardimcisi: eski cagiranlar (topo/rng vermeyen) varsayilani alir."""
    return topo or _topo_mod.default_spec(), rng or random.Random(0)


def matches(requires: dict, spec: TopoSpec) -> bool:
    """Scheduler eslesmesi: requires'taki her ozellik spec.features ile ayni olmali."""
    return all(spec.features.get(k) == v for k, v in requires.items())


def usable(fault_obj, spec: TopoSpec) -> bool:
    """requires eslesir VE (varsa) sinifin kendi available(spec) predicate'i gecer.

    requires kaba ozellik filtresi; available() ozellik bayragiyla ifade
    edilemeyen kosullar icin (orn. svi_down: vrrp'siz en az bir vlan)."""
    if not matches(getattr(fault_obj, "requires", {}), spec):
        return False
    avail = getattr(fault_obj, "available", None)
    return bool(avail(spec)) if callable(avail) else True


FAULTS: dict[str, object] = {}


def fault(name: str):
    """Sinifi kayit defterine ekler; sinif inject/revert/requires sozlesmesini tasir."""

    def wrap(cls):
        cls.name = name
        if not hasattr(cls, "requires"):
            cls.requires = {}
        # Teshis ETIKETI. Varsayilan: kayit adi. Bazi enjektorler baska bir
        # sinifin etiketini tasir (orn. link_down_far_end -> interface_admin_down):
        # senaryo cesitliligi kalir ama arac ciktilarindan ayirt EDILEMEYEN iki
        # duruma iki ayri etiket verilmez (pilot dersi: etiket-ikizi = 0/7).
        if not hasattr(cls, "label"):
            cls.label = name
        # canli cEOS'ta gozlenir bozulma urettigi smoke ile dogrulandi mi?
        # False = registry'de kalir (Faz 2 zengin topoloji) ama varsayilan
        # uretime girmez. Base topolojide semptom uretmeyenler icin.
        if not hasattr(cls, "live_verified"):
            cls.live_verified = True
        FAULTS[name] = cls()
        return cls

    return wrap


def _discover() -> None:
    """lab/faults/ altindaki tum modulleri import et — @fault yan etkisiyle kayit."""
    for mod in sorted(m.name for m in pkgutil.iter_modules(__path__)):
        if mod.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{mod}")


_discover()
# Teacher'in gorecegi/teshis edecegi sinif listesi: kayit adlari degil ETIKETLER.
# Alias enjektorler (label != name) burada ayri satir olusturmaz.
FAULT_CLASSES = sorted({f.label for f in FAULTS.values()})
