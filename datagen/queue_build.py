"""Senaryo kuyrugu uretici — lane'lerin kosacagi is listesi.

Girdi: --count N (senaryo slotu), --seed-range A:B (A dahil, B haric), --k tekrar.
Her slot bir (topo_seed, fault_class) cifti; k tekrar k_index=0..k-1 satiri olur.
Semptomlar bank-first cekilir (datagen.symptoms.render: scenario_bank varsa
oradan, yoksa TEMPLATES). Siniflar topo_seed'in features'iyla eslestirilir:
build_spec(seed) + fault.requires (lab.faults.matches); uymayan sinif o seed'e
atanmaz. Ayni topo_seed'li senaryolar ARDISIK yazilir — lane ayni topolojiyi
yeniden kurmadan pesine kosar.

Cikti satiri: {scenario_id, topo_seed, fault_class, symptom, k_index}

Lab host'unda: uv run python -m datagen.queue_build --count 20 --seed-range 1:40 --k 2
"""

import argparse
import json
import random
import sys
from pathlib import Path

from datagen import symptoms
from lab.faults import FAULTS, usable
from lab.topo import build_spec

TRACES_DIR = Path(__file__).parents[1] / "traces"
DEFAULT_QUEUE = TRACES_DIR / "queue.jsonl"


def compatible_faults(spec, faults: dict) -> list[str]:
    """Spec'le kosulabilir sinif adlari: requires + available() (deterministik sira)."""
    return sorted(name for name, f in faults.items() if usable(f, spec))


def default_faults() -> dict:
    """Kuyruga girebilecek siniflar: registry ∩ semptom kaynagi ∩ canli-dogrulanmis.

    - Semptomu olmayan sinif (bankaya girmemis) kuyruga alinmaz.
    - live_verified=False sinif (base topolojide gozlenir semptom uretmeyen)
      uretime alinmaz — smoke ile kanitlanana kadar disarida.
    """
    have = symptoms.available_classes()
    return {
        name: f for name, f in FAULTS.items()
        if name in have and getattr(f, "live_verified", True)
    }


def build_queue(
    count: int,
    seeds: list[int],
    k: int,
    faults: dict | None = None,
    rng: random.Random | None = None,
    spec_of=build_spec,
    symptom_of=symptoms.render,
) -> list[dict]:
    """count slotu seed'lere sirayla dagitir; seed-major uretim ardisikligi garantiler.

    faults: ad -> obje (requires alani yeterli) — testler sahte registry verebilir;
    verilmezse default_faults() (semptomu olan gercek siniflar) kullanilir.
    """
    faults = default_faults() if faults is None else faults
    rng = rng or random.Random(0)

    usable: list[tuple[int, list[str]]] = []
    for seed in seeds:
        classes = compatible_faults(spec_of(seed), faults)
        if classes:
            usable.append((seed, classes))
    if not usable:
        raise ValueError("hicbir seed hicbir ariza sinifiyla eslesmedi")

    # slot dagilimi: seed'lere round-robin, yazim seed-major (gruplama ardisik)
    per_seed = [0] * len(usable)
    for i in range(count):
        per_seed[i % len(usable)] += 1

    entries: list[dict] = []
    slot_no = 0
    for (seed, classes), slots in zip(usable, per_seed):
        for _ in range(slots):
            fault_class = rng.choice(classes)
            slot_no += 1
            scenario_id = f"s{seed}-{fault_class}-{slot_no:04d}"
            for k_index in range(k):
                entries.append({
                    "scenario_id": scenario_id,
                    "topo_seed": seed,
                    "fault_class": fault_class,
                    "symptom": symptom_of(fault_class, rng),
                    "k_index": k_index,
                })
    return entries


def parse_seed_range(text: str) -> list[int]:
    try:
        a, b = text.split(":")
        seeds = list(range(int(a), int(b)))
    except ValueError:
        raise SystemExit(f"gecersiz --seed-range (A:B bekleniyor): {text!r}")
    if not seeds:
        raise SystemExit(f"bos seed araligi: {text!r}")
    return seeds


def write_queue(entries: list[dict], out_path: Path) -> None:
    """queue.jsonl'i yazar; eski kosunun cursor'ini sifirlar (bayat ilerleme kalmasin)."""
    out_path.parent.mkdir(exist_ok=True)
    with out_path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    cursor = out_path.with_suffix(".cursor")
    if cursor.exists():
        cursor.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(description="senaryo kuyrugu uret")
    ap.add_argument("--count", type=int, default=10, help="senaryo slotu sayisi")
    ap.add_argument("--seed-range", default="1:20", help="topo seed araligi A:B (B haric)")
    ap.add_argument("--k", type=int, default=1, help="slot basina tekrar")
    ap.add_argument("--rng-seed", type=int, default=0, help="sinif/semptom secim rng'si")
    ap.add_argument("--out", default=str(DEFAULT_QUEUE))
    args = ap.parse_args()

    faults = default_faults()
    skipped = sorted(set(FAULTS) - set(faults))
    if skipped:
        print(f"semptom kaynagi yok, kuyruk disi birakildi: {skipped}")

    entries = build_queue(
        args.count, parse_seed_range(args.seed_range), args.k,
        faults=faults, rng=random.Random(args.rng_seed),
    )
    out_path = Path(args.out)
    write_queue(entries, out_path)
    n_seeds = len({e["topo_seed"] for e in entries})
    print(f"kuyruk yazildi: {out_path} — {len(entries)} satir, "
          f"{args.count} slot, {n_seeds} topoloji")
    return 0


if __name__ == "__main__":
    sys.exit(main())
