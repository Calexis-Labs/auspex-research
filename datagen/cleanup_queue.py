"""Temizlik turu kuyrugu — fire veren senaryolari duzeltilmis kod/prompt'la tekrar.

Secim kurali (senaryo bazinda, k tekrarlarin EN IYI sonucuna gore):
  - herhangi bir rollout PASS ise    -> tekrar YOK (kitapta yeri hazir)
  - en iyisi partial/fail/error ise  -> TEKRAR (yeni kural/kod sansi versin)
  - en iyisi skipped ise             -> tekrar YOK (o topolojide uretilir semptom
                                        yok; tekrar denemek bilincli cop olur)

Ayni queue satirlari aynen yeniden yazilir (ayni scenario_id -> rollout_id;
veri seti kurulurken rollout_id basina SON satir gecerli).

Kullanim (lab host, lanes DURMUSKEN): uv run python -m datagen.cleanup_queue
"""

import json
from collections import defaultdict
from pathlib import Path

TRACES = Path(__file__).parents[1] / "traces"
_RANK = {"pass": 4, "partial": 3, "fail": 2, "error": 1, "skipped": 0}


def select_retries(entries: list[dict], rows: list[dict]) -> list[dict]:
    """Tekrar kosulacak queue satirlari (saf fonksiyon — test edilir)."""
    best: dict[str, str] = {}
    for r in rows:
        sid = r.get("scenario_id")
        v = r.get("verdict", "error")
        if sid and _RANK.get(v, 1) > _RANK.get(best.get(sid, ""), -1):
            best[sid] = v
    retry_ids = {sid for sid, v in best.items() if v in ("partial", "fail", "error")}
    seen: set[tuple] = set()
    out = []
    for e in entries:
        key = (e["scenario_id"], e.get("k_index", 0))
        if e["scenario_id"] in retry_ids and key not in seen:
            seen.add(key)
            out.append(e)
    return out


def main() -> int:
    entries = [json.loads(l) for l in (TRACES / "queue.jsonl").open() if l.strip()]
    ids = {e["scenario_id"] for e in entries}
    rows = []
    for p in sorted(TRACES.glob("batch_lane*.jsonl")):
        for line in p.open():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("scenario_id") in ids:
                rows.append(r)
    retries = select_retries(entries, rows)
    if not retries:
        print("tekrar gerektiren senaryo yok — temizlik turu gereksiz")
        return 0
    # gruplar (ayni topo_seed) ardisik kalsin diye seed'e gore sirala
    retries.sort(key=lambda e: (e["topo_seed"], e["scenario_id"], e.get("k_index", 0)))
    from datagen.queue_build import write_queue
    write_queue(retries, TRACES / "queue.jsonl")
    stats = defaultdict(int)
    for e in retries:
        stats[e["fault_class"]] += 1
    print(f"temizlik kuyrugu yazildi: {len(retries)} senaryo")
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k:26s} {v}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
