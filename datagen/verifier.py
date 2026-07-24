"""Deterministik verifier: teshis vs GroundTruth (tekil VEYA liste).

Tekil gt (ya da tek elemanli liste) — mevcut davranis birebir:
  pass    — fault_class + device + tum key_terms dogru
  partial — fault_class + device dogru, key_terms eksik (verifier sikiligini
            gozlemlemek icin ayri sayilir)
  fail    — geri kalani
  Istisna: no_fault / insufficient_info icin fault_class eslesmesi yeterli
  (device serbest) -> pass.

Coklu gt (multi_fault, len >= 2):
  pass    — HER kok neden icin sinif+cihaz teshiste geciyor
  partial — en az biri geciyor
  fail    — hicbiri gecmiyor
  Teshis tek submit oldugundan ikinci kok neden ana alanlarda olamayabilir;
  sinif/cihaz eslesmesi root_cause + fix_commands serbest metninde de aranir.
"""

from dataclasses import dataclass

from lab.faults import GroundTruth

# cihaz eslesmesi aranmayan siniflar (device="none" sozlesmesi)
_NO_DEVICE_CLASSES = {"no_fault", "insufficient_info"}


@dataclass(frozen=True)
class Verdict:
    level: str                # "pass" | "partial" | "fail"
    reasons: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.level == "pass"


import re as _re


def _norm_device(name: str) -> str:
    name = (name or "").strip().lower()
    return _re.sub(r"^clab-netagent[0-9]*-", "", name)


def _free_text(diagnosis: dict) -> str:
    return " ".join(
        [str(diagnosis.get("root_cause", "")), *map(str, diagnosis.get("fix_commands", []))]
    ).lower()


def verify(diagnosis: dict | None, gt: GroundTruth | list[GroundTruth]) -> Verdict:
    gts = list(gt) if isinstance(gt, (list, tuple)) else [gt]
    if not gts:
        return Verdict("fail", ("bos ground truth listesi",))
    if not diagnosis:
        return Verdict("fail", ("teshis yok",))
    if len(gts) == 1:
        return _verify_single(diagnosis, gts[0])
    return _verify_multi(diagnosis, gts)


def _verify_single(diagnosis: dict, gt: GroundTruth) -> Verdict:
    class_ok = str(diagnosis.get("fault_class", "")).strip().lower() == gt.fault_class

    if gt.fault_class in _NO_DEVICE_CLASSES:
        if class_ok:
            return Verdict("pass")
        return Verdict("fail", (f"fault_class: {diagnosis.get('fault_class')!r} != {gt.fault_class!r}",))

    reasons = []
    if not class_ok:
        reasons.append(f"fault_class: {diagnosis.get('fault_class')!r} != {gt.fault_class!r}")

    device_ok = _norm_device(str(diagnosis.get("device", ""))) == gt.device
    if not device_ok:
        reasons.append(f"device: {diagnosis.get('device')!r} != {gt.device!r}")

    if not (class_ok and device_ok):
        return Verdict("fail", tuple(reasons))

    haystack = _free_text(diagnosis)
    missing = [term for term in gt.key_terms if term.lower() not in haystack]
    if missing:
        return Verdict("partial", (f"anahtar terim eksik: {missing}",))
    return Verdict("pass")


def _mentioned(diagnosis: dict, gt: GroundTruth) -> bool:
    """Coklu arizada bir kok neden 'bulundu' sayilir: sinif VE cihaz, teshisin
    ana alanlarinda YA DA serbest metninde gecer."""
    text = _free_text(diagnosis)
    class_ok = (
        str(diagnosis.get("fault_class", "")).strip().lower() == gt.fault_class
        or gt.fault_class in text
    )
    device_ok = (
        _norm_device(str(diagnosis.get("device", ""))) == gt.device
        or gt.device.lower() in text
    )
    return class_ok and device_ok


def _verify_multi(diagnosis: dict, gts: list[GroundTruth]) -> Verdict:
    matched = [_mentioned(diagnosis, g) for g in gts]
    missed = [f"{g.fault_class}@{g.device}" for g, ok in zip(gts, matched) if not ok]
    if all(matched):
        return Verdict("pass")
    if any(matched):
        return Verdict("partial", (f"eksik kok neden: {missed}",))
    return Verdict("fail", (f"hicbir kok neden eslesmedi: {missed}",))
