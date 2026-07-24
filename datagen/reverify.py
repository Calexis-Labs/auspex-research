"""Pilot trace'lerini YENI kurallarla yeniden puanla — harcanan token'i kurtar.

v2 tasarim degisiklikleri geriye donuk uygulanir:
- link_down_far_end: GT etiketi interface_admin_down olur (birlestirme).
  Model zaten dogru cihazda interface_admin_down diyordu -> artik pass.
- eski insufficient_info senaryolari (mugla semptom + saglikli ag) fiilen
  no_fault senaryosuydu -> GT no_fault olarak degerlendirilir; model no_fault
  dediyse trace GECERLI bir no_fault egitim ornegidir.

Orijinal dosyalara DOKUNMAZ; guncellenen satirlari tek dosyaya toplar.
Kullanim (lab host): uv run python -m datagen.reverify traces/batch_lane*.jsonl \
    [--out traces/pilot_v2.jsonl]
"""

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

from datagen.verifier import verify
from lab.faults import GroundTruth

# eski kayit adi -> yeni GT etiketi
_RELABEL = {"link_down_far_end": "interface_admin_down"}
# eski tasarimi no_fault'a donusen siniflar (yalniz TEKIL gt satirlarinda)
_LEGACY_TO_NO_FAULT = {"insufficient_info"}


def _fix_gt_dict(d: dict) -> dict:
    if d.get("fault_class") in _RELABEL:
        d = {**d, "fault_class": _RELABEL[d["fault_class"]]}
    return d


def reverify_row(row: dict) -> dict:
    """Satiri yeni kurallarla yeniden puanla; degismis kopyayi dondur."""
    gt_raw = row.get("ground_truth")
    if not gt_raw or row.get("verdict") in ("error", "skipped"):
        return row

    if isinstance(gt_raw, list):
        gts = [GroundTruth(**_fix_gt_dict(d)) for d in gt_raw]
        gt_arg = gts if len(gts) > 1 else gts[0]
    else:
        d = _fix_gt_dict(gt_raw)
        if row.get("fault") in _LEGACY_TO_NO_FAULT:
            # eski tasarim: ag saglikli birakilmisti -> dogru sinif no_fault
            d = {**d, "fault_class": "no_fault",
                 "root_cause": "ag sagliklidir; bildirilen sorun ag kaynakli degil (v1 insufficient_info -> no_fault donusumu)"}
        gt_arg = GroundTruth(**d)

    verdict = verify(row.get("diagnosis"), gt_arg)
    out = dict(row)
    out["orig_verdict"] = row.get("verdict")
    out["verdict"] = verdict.level
    out["verdict_reasons"] = list(verdict.reasons)
    gt_list = gt_arg if isinstance(gt_arg, list) else [gt_arg]
    out["ground_truth"] = (
        [g.__dict__ for g in gt_list] if isinstance(gt_raw, list) else gt_list[0].__dict__
    )
    if row.get("fault") in _LEGACY_TO_NO_FAULT and not isinstance(gt_raw, list):
        out["fault"] = "no_fault"
        out["relabel_note"] = "v1 insufficient_info senaryosu -> no_fault (tasarim v2)"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="pilot trace'lerini v2 kurallarla yeniden puanla")
    ap.add_argument("inputs", nargs="+", help="batch_lane*.jsonl dosyalari/glob'lari")
    ap.add_argument("--out", default="traces/pilot_v2.jsonl")
    args = ap.parse_args()

    paths: list[Path] = []
    for pattern in args.inputs:
        hit = sorted(glob.glob(pattern))
        paths.extend(Path(p) for p in hit) if hit else paths.append(Path(pattern))
    paths = [p for p in paths if p.exists()]
    if not paths:
        raise SystemExit("girdi dosyasi bulunamadi")

    rows = []
    for p in paths:
        for line in p.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))

    stats = defaultdict(lambda: {"old_pass": 0, "new_pass": 0, "n": 0, "changed": 0})
    out_rows = []
    for row in rows:
        new = reverify_row(row)
        out_rows.append(new)
        s = stats[row.get("fault", "?")]
        s["n"] += 1
        s["old_pass"] += row.get("verdict") == "pass"
        s["new_pass"] += new.get("verdict") == "pass"
        s["changed"] += new.get("verdict") != row.get("verdict")

    out_path = Path(args.out)
    out_path.parent.mkdir(exist_ok=True)
    with out_path.open("w") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    tot_n = sum(s["n"] for s in stats.values())
    tot_old = sum(s["old_pass"] for s in stats.values())
    tot_new = sum(s["new_pass"] for s in stats.values())
    print(f"{'sinif':30s} {'n':>3s} {'eski':>5s} {'yeni':>5s} {'degisen':>7s}")
    for name in sorted(stats):
        s = stats[name]
        mark = "  <-- kurtarildi" if s["new_pass"] > s["old_pass"] else ""
        print(f"{name:30s} {s['n']:3d} {s['old_pass']:5d} {s['new_pass']:5d} {s['changed']:7d}{mark}")
    print("-" * 55)
    old_pct = 100 * tot_old / tot_n if tot_n else 0
    new_pct = 100 * tot_new / tot_n if tot_n else 0
    print(f"{'TOPLAM':30s} {tot_n:3d} {tot_old:5d} {tot_new:5d}   ({old_pct:.0f}% -> {new_pct:.0f}%)")
    print(f"yazildi: {out_path} ({len(out_rows)} satir)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
