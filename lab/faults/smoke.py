"""Ariza smoke testi (canli lab gerekir, lab host'unda calisir):

her ariza icin dongu:  health YESIL -> inject -> health BOZULMALI ->
                       revert -> health tekrar YESIL

no_fault / insufficient_info bilerek bozulma URETMEZ — onlarda yalniz
"revert sonrasi saglik" beklenir. multi_fault list[GroundTruth] doner.

Kullanim (varsayilan seed=0 dunyasi ayakta olmali):
  uv run python -m lab.faults.smoke [--seed N] [ariza_adi ...]
"""

import argparse
import json
import sys
import time
from pathlib import Path

from lab import topo
from lab.deploy import health_check
from lab.faults import FAULTS, PrivilegedExec, usable
from lab.topo import build_spec

# bozulma beklenmeyen (no-op) siniflar
_NO_DEGRADE = {"no_fault", "insufficient_info"}

STATUS_PATH = Path(__file__).parents[2] / "traces" / "smoke_status.json"


def _write_status(**fields) -> None:
    """Dashboard'un okudugu canli durum dosyasi (atomik yaz)."""
    fields["updated"] = time.time()
    STATUS_PATH.parent.mkdir(exist_ok=True)
    tmp = STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(fields, ensure_ascii=False))
    tmp.replace(STATUS_PATH)


def run(names: list[str], spec) -> bool:
    pe = PrivilegedExec(spec)
    all_ok = True
    results: list[dict] = []
    total = len(names)

    def status(current: str | None, running: bool = True) -> None:
        _write_status(running=running, seed=spec.seed, total=total,
                      done=len(results), current=current, results=results)

    status(names[0] if names else None)
    for name in names:
        fault = FAULTS[name]
        status(name)
        print(f"\n=== {name} ===")

        if not usable(fault, spec):
            print("  bu dunyada uygulanamaz (requires/available), atlaniyor")
            results.append({"class": name, "result": "atlandi", "detail": "bu dunyada uygulanamaz"})
            status(name)
            continue

        base = health_check(spec, attempts=4)
        if not base.ok:
            print(f"  baseline saglikli degil, atlaniyor:\n{base.render()}")
            results.append({"class": name, "result": "FAIL", "detail": "baseline saglikli degil"})
            all_ok = False
            status(name)
            continue

        detail = ""
        try:
            gt = fault.inject(pe, spec, None)
            gts = gt if isinstance(gt, list) else [gt]
            detail = "; ".join(g.root_cause for g in gts)
            print(f"  inject edildi: {detail}")

            if name in _NO_DEGRADE:
                degraded = True                    # no-op sinif: bozulma aranmaz
                print("  (no-op sinif — bozulma beklenmiyor)")
            else:
                broken = health_check(spec, attempts=1)
                degraded = not broken.ok
                print(f"  bozulma gozlendi: {degraded}")
                if not degraded:
                    print(broken.render())
        finally:
            fault.revert(pe, spec)

        healed = health_check(spec, attempts=6)
        print(f"  revert sonrasi saglik: {healed.ok}")
        if not healed.ok:
            print(healed.render())

        ok = degraded and healed.ok
        all_ok &= ok
        results.append({
            "class": name,
            "result": "OK" if ok else "FAIL",
            "detail": detail if ok else f"bozulma={degraded}, iyilesme={healed.ok}",
        })
        status(name)
        print(f"  SONUC: {'OK' if ok else 'FAIL'}")

    status(None, running=False)
    return all_ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("faults", nargs="*")
    args = ap.parse_args()

    spec = build_spec(args.seed, name=topo.LAB_NAME)
    names = args.faults or [n for n in FAULTS if usable(FAULTS[n], spec)]
    sys.exit(0 if run(names, spec) else 1)
