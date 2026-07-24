"""On sinav (Asama B0): HAM aday modelleri ayni sorularla yaristir.

Seed 331-340: ne egitim (31-330) ne gercek sinav (400+) — tarafsiz ara bolge.
Ayni kuyruk her iki modele de sorulur (adil karsilastirma). Cikti kendi
dizinine yazilir (traces/pre_exam/) — uretim/egitim dosyalarina KARISMAZ.

Lab host'unda:
  uv run python -m datagen.pre_exam --model qwen3:8b
  uv run python -m datagen.pre_exam --model gemma4:26b
Kuyruk ilk cagrida uretilir; --rebuild ile tazelenir.
"""

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

from datagen import queue_build, student
from datagen.lanes import run_lane

TRACES = Path(__file__).parents[1] / "traces"
PRE_DIR = TRACES / "pre_exam"
QUEUE = PRE_DIR / "queue.jsonl"


def ensure_queue(count: int, rebuild: bool) -> None:
    if QUEUE.exists() and not rebuild:
        return
    PRE_DIR.mkdir(exist_ok=True)
    entries = queue_build.build_queue(
        count, list(range(331, 341)), 1, rng=random.Random(2026))
    queue_build.write_queue(entries, QUEUE)
    print(f"on sinav kuyrugu: {len(entries)} soru")


def main() -> int:
    ap = argparse.ArgumentParser(description="ham aday modeli on sinava sok")
    ap.add_argument("--model", required=True, help="ollama model etiketi, orn. qwen3:8b")
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    ensure_queue(args.count, args.rebuild)
    # her model ayni kuyrugu bastan kosar: cursor'u sifirla
    cursor = QUEUE.with_suffix(".cursor")
    if cursor.exists():
        cursor.unlink()

    safe = args.model.replace(":", "_").replace("/", "_")
    out_dir = PRE_DIR / safe
    out_dir.mkdir(exist_ok=True)
    rc = run_lane(0, QUEUE, model=args.model, traces_dir=out_dir,
                  rollout=student.run_student_rollout)

    rows = []
    for p in sorted(out_dir.glob("batch_lane*.jsonl")):
        rows += [json.loads(l) for l in p.open() if l.strip()]
    by_rid = {}
    for r in sorted(rows, key=lambda r: r.get("ts") or 0):
        by_rid[r["rollout_id"]] = r
    rows = list(by_rid.values())
    c = Counter(r["verdict"] for r in rows)
    n_err = sum(1 for r in rows if r.get("error"))
    tools = [r["n_tool_calls"] for r in rows if r["n_tool_calls"]]
    dur = [r["duration_s"] for r in rows if r["duration_s"]]
    print(json.dumps({
        "model": args.model,
        "soru": len(rows), "sonuc": dict(c),
        "hata_metni_olan": n_err,
        "ort_arac": round(sum(tools) / len(tools), 1) if tools else 0,
        "ort_sure_s": round(sum(dur) / len(dur), 1) if dur else 0,
    }, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
