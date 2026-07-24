"""Ders kitabi dizgisi: pass trace'leri -> egitim veri seti (messages formati).

Kaynak: traces/batch_lane*.jsonl (uretim; production_ids.txt filtresi) +
traces/pilot_v2.jsonl (yeniden puanlanmis pilot). Kurallar:
  - rollout_id basina SON satir gecerli (ts sirali)
  - yalniz verdict=pass
  - "{" iceren semptom (placeholder sizintisi) ATILIR
  - ~32k token (128k karakter) ustu trace ATILIR (rapor verilir)

Donusum (events -> messages):
  - user prompt trace'te SAKLANMAZ; symptom + topo_seed'den build_prompt ile
    yeniden kurulur (guncel kural setiyle — bilinçli karar: ogrenci TEK ve en
    iyi prompt'u ogrenir, eski trace'ler de ayni prompta hizalanir).
  - assistant text + tool_use bloklari alinir; BOS thinking bloklari atlanir.
  - ToolSearch cagrilari ve tool_reference sonuclari AYIKLANIR (ogrenci araclari
    bastan gorur; ertelenmis-arac mekanizmasi ogretilmez).
  - ardisi assistant eventleri tek assistant turuna birlesir.
  - tool_result -> {"role":"tool","name":<cagrilan arac>,"content":<metin>}

Bolme: senaryo bazinda, sinif dengeli %92 train / %8 val (rng=0, deterministik).
Sinav kimlikleri (exam_ids.txt) girdide zaten yok; yine de savunma icin suzulur.

Lab host'unda: uv run python -m datagen.dataset_build [--out dataset/]
"""

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from datagen.teacher import build_prompt
from lab.topo import build_spec

TRACES = Path(__file__).parents[1] / "traces"
MAX_CHARS = 128_000          # ~32k token (4 char/token kabulu)
VAL_FRACTION = 0.08
SUBMIT_TOOL = "mcp__netagent__submit_diagnosis"


# ---------------------------------------------------------------- events -> messages

def events_to_messages(events: list[dict]) -> list[dict]:
    """Stream-json eventlerini egitim mesajlarina cevir (saf fonksiyon).

    ToolSearch tool_use'lari ve sonuclari dusurulur; bos thinking atlanir;
    ardisi assistant iceligi tek mesajda toplanir.
    """
    msgs: list[dict] = []
    id2name: dict[str, str] = {}
    skip_ids: set[str] = set()

    def last_assistant_open() -> dict | None:
        if msgs and msgs[-1]["role"] == "assistant":
            return msgs[-1]
        return None

    for e in events:
        etype = e.get("type")
        if etype == "assistant":
            for b in e.get("message", {}).get("content", []):
                btype = b.get("type")
                if btype == "thinking":
                    if (b.get("thinking") or "").strip():
                        cur = last_assistant_open() or _new_assistant(msgs)
                        cur["thinking"] = (cur.get("thinking", "") + "\n" + b["thinking"]).strip()
                elif btype == "text":
                    if (b.get("text") or "").strip():
                        cur = last_assistant_open() or _new_assistant(msgs)
                        cur["content"] = (cur.get("content", "") + "\n" + b["text"]).strip()
                elif btype == "tool_use":
                    name = b.get("name") or ""
                    if name == "ToolSearch":
                        skip_ids.add(b.get("id"))
                        continue
                    id2name[b.get("id")] = name
                    cur = last_assistant_open() or _new_assistant(msgs)
                    cur.setdefault("tool_calls", []).append(
                        {"id": b.get("id"), "name": name, "arguments": b.get("input") or {}}
                    )
        elif etype == "user":
            for b in e.get("message", {}).get("content", []):
                if b.get("type") != "tool_result":
                    continue
                tid = b.get("tool_use_id")
                if tid in skip_ids:
                    continue
                content = b.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") if isinstance(c, dict) else str(c) for c in content
                    ).strip()
                msgs.append({
                    "role": "tool",
                    "name": id2name.get(tid, "unknown"),
                    "content": str(content),
                })
    # bos assistant kaliplarini temizle (yalniz ToolSearch iceren turlar bosalmis olabilir)
    return [m for m in msgs if m["role"] != "assistant"
            or m.get("content") or m.get("tool_calls") or m.get("thinking")]


def _new_assistant(msgs: list[dict]) -> dict:
    m = {"role": "assistant"}
    msgs.append(m)
    return m


def validate_messages(msgs: list[dict]) -> str | None:
    """Kusur aciklamasi dondurur; None = temiz."""
    if not msgs:
        return "bos mesaj listesi"
    calls = [c for m in msgs if m["role"] == "assistant" for c in m.get("tool_calls", [])]
    if not any(c["name"] == SUBMIT_TOOL for c in calls):
        return "submit_diagnosis cagrisi yok"
    n_results = sum(1 for m in msgs if m["role"] == "tool")
    if n_results < len(calls) - 1:      # son submit sonucu bazen trace'te kesilir
        return f"eksik tool sonucu: {len(calls)} cagri, {n_results} sonuc"
    for m in msgs:
        if m["role"] == "assistant":
            for c in m.get("tool_calls", []):
                json.dumps(c["arguments"])   # serilesebilir olmali
    return None


# ---------------------------------------------------------------- satir -> ornek

def row_to_example(row: dict, spec_cache: dict) -> tuple[dict | None, str | None]:
    seed = row.get("topo_seed")
    if seed is None:
        return None, "topo_seed yok"
    if seed not in spec_cache:
        spec_cache[seed] = build_spec(seed)
    msgs = events_to_messages(row.get("events") or [])
    err = validate_messages(msgs)
    if err:
        return None, err
    example = {
        "scenario_id": row["scenario_id"],
        "rollout_id": row["rollout_id"],
        "fault": row["fault"],
        "topo_seed": seed,
        "messages": [
            {"role": "user", "content": build_prompt(row["symptom"], spec_cache[seed])},
            *msgs,
        ],
    }
    n_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in example["messages"])
    if n_chars > MAX_CHARS:
        return None, f"cok uzun ({n_chars // 1000}k karakter)"
    example["approx_tokens"] = n_chars // 4
    return example, None


# ---------------------------------------------------------------- yukleme + bolme

def load_pass_rows() -> list[dict]:
    prod_ids = set((TRACES / "production_ids.txt").read_text().split())
    exam_ids = set()
    exam_path = TRACES / "exam_ids.txt"
    if exam_path.exists():
        exam_ids = set(exam_path.read_text().split())

    by_rid: dict[str, dict] = {}

    def add(row):
        sid = row.get("scenario_id")
        if sid in exam_ids:                      # savunma: sinav asla egitime sizamaz
            return
        old = by_rid.get(row.get("rollout_id"))
        if old is None or (row.get("ts") or 0) >= (old.get("ts") or 0):
            by_rid[row["rollout_id"]] = row

    for p in sorted(TRACES.glob("batch_lane*.jsonl")):
        for line in p.open():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("scenario_id") in prod_ids:
                add(r)
    pilot = TRACES / "pilot_v2.jsonl"
    if pilot.exists():
        for line in pilot.open():
            try:
                add(json.loads(line))
            except ValueError:
                continue

    return [
        r for r in by_rid.values()
        if r.get("verdict") == "pass"
        and "{" not in (r.get("symptom") or "")
        and r.get("events")
    ]


def split_examples(examples: list[dict], rng: random.Random) -> tuple[list, list]:
    """Sinif dengeli, senaryo bazli split. Ayni senaryo iki tarafta olamaz
    (girdi zaten senaryo basina tek ornek — rollout dedup yukarida yapildi)."""
    by_class: dict[str, list[dict]] = defaultdict(list)
    for ex in examples:
        by_class[ex["fault"]].append(ex)
    train, val = [], []
    for cls in sorted(by_class):
        pool = sorted(by_class[cls], key=lambda e: e["scenario_id"])
        rng.shuffle(pool)
        n_val = max(1, round(len(pool) * VAL_FRACTION)) if len(pool) > 3 else 0
        val.extend(pool[:n_val])
        train.extend(pool[n_val:])
    return train, val


def main() -> int:
    ap = argparse.ArgumentParser(description="pass trace'lerinden egitim seti uret")
    ap.add_argument("--out", default="dataset")
    args = ap.parse_args()

    rows = load_pass_rows()
    # senaryo basina TEK ornek: ayni senaryonun birden fazla pass'i varsa en yenisi
    by_sid: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: r.get("ts") or 0):
        by_sid[r["scenario_id"]] = r

    spec_cache: dict = {}
    examples, drops = [], Counter()
    for r in by_sid.values():
        ex, err = row_to_example(r, spec_cache)
        if ex:
            examples.append(ex)
        else:
            drops[err.split("(")[0].strip()] += 1

    train, val = split_examples(examples, random.Random(0))

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    for name, data in (("train", train), ("val", val)):
        with (out / f"{name}.jsonl").open("w") as f:
            for ex in data:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    toks = sorted(ex["approx_tokens"] for ex in examples)
    report = {
        "girdi_pass_senaryo": len(by_sid),
        "ornek": len(examples),
        "atilan": dict(drops),
        "train": len(train), "val": len(val),
        "yaklasik_token_toplam_M": round(sum(toks) / 1e6, 1),
        "token_p50": toks[len(toks) // 2] if toks else 0,
        "token_p95": toks[int(len(toks) * 0.95)] if toks else 0,
        "sinif_dagilimi_train": dict(Counter(e["fault"] for e in train)),
        "sinif_dagilimi_val": dict(Counter(e["fault"] for e in val)),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
