"""TAM KARNE koşucusu — held-out sınav (seed 400+), model başına bağımsız koşu.

Master kuyruk BİR KEZ üretilir (150 soru, seed 400-450, rng 42) ve exam_ids.txt
yazılır (dataset_build bu kimlikleri eğitime asla almaz). Her model, master'ın
KENDİ KOPYASI üzerinde koşar (ayrı cursor) — iki model aynı 150 soruyu bağımsız
çözer, kuyruk paylaşılmaz.

Rollout seçimi: sonnet/opus/haiku -> teacher (claude -p, limit-bekleme dahil);
diğer her şey -> student (Ollama/Mac).

Lab host'unda:
  uv run python -m datagen.exam_run --model kestrel:v1 --lane 0
  uv run python -m datagen.exam_run --model sonnet     --lane 1
"""

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

from datagen import queue_build, student, teacher
from datagen.lanes import run_lane

TRACES = Path(__file__).parents[1] / "traces"
EXAM_DIR = TRACES / "exam"
MASTER = EXAM_DIR / "queue_master.jsonl"
TEACHER_MODELS = {"sonnet", "opus", "haiku"}


def ensure_master(count: int, seed_a: int, seed_b: int) -> None:
    if MASTER.exists():
        return
    EXAM_DIR.mkdir(exist_ok=True)
    entries = queue_build.build_queue(
        count, list(range(seed_a, seed_b)), 1, rng=random.Random(42))
    queue_build.write_queue(entries, MASTER)
    ids = sorted({e["scenario_id"] for e in entries})
    (TRACES / "exam_ids.txt").write_text("\n".join(ids))
    print(f"master sinav kuyrugu: {len(entries)} soru, {len(ids)} senaryo -> exam_ids.txt")


def pick_rollout(model: str):
    return teacher.run_rollout if model in TEACHER_MODELS else student.run_student_rollout


def main() -> int:
    ap = argparse.ArgumentParser(description="tam karne kosucusu")
    ap.add_argument("--model", required=True)
    ap.add_argument("--lane", type=int, default=0)
    ap.add_argument("--count", type=int, default=150)
    ap.add_argument("--seed-range", default="400:451")
    args = ap.parse_args()

    a, b = (int(x) for x in args.seed_range.split(":"))
    ensure_master(args.count, a, b)

    safe = args.model.replace(":", "_").replace("/", "_")
    model_dir = EXAM_DIR / safe
    model_dir.mkdir(exist_ok=True)
    q = model_dir / "queue.jsonl"
    if not q.exists():
        shutil.copy(MASTER, q)
    # yarim kalan kosu cursor'dan DEVAM eder (yeniden baslatma guvenli)

    rc = run_lane(args.lane, q, model=args.model, traces_dir=model_dir,
                  rollout=pick_rollout(args.model))

    by_rid: dict[str, dict] = {}
    for p in sorted(model_dir.glob("batch_lane*.jsonl")):
        for line in p.open():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            old = by_rid.get(r["rollout_id"])
            if old is None or (r.get("ts") or 0) >= (old.get("ts") or 0):
                by_rid[r["rollout_id"]] = r
    rows = list(by_rid.values())
    c = Counter(r["verdict"] for r in rows)
    print(json.dumps({"model": args.model, "soru": len(rows), "sonuc": dict(c)},
                     ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
