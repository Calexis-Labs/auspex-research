"""Faz 0 olcum kosusu: her ariza icin k rollout — tek-lane esdegeri.

CLI geriye uyumlu (--k/--faults/--model/--seed); ic mantik lanes.run_scenario'yu
yeniden kullanir: health YESIL -> inject -> semptom -> teacher -> verify ->
revert -> health YESIL. Varsayilan (seed=0) topoloji AYAKTA olmalidir; bu komut
deploy etmez (cok-seritli kosu icin datagen.lanes kullanin).

Her rollout traces/batch_<ts>.jsonl'e tam trace ile yazilir; sonda ozet tablo.

Lab host'unda: uv run python -m datagen.run_batch --k 3
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from datagen import symptoms
from datagen.lanes import InfraError, run_scenario
from datagen.symptoms import render
from lab import topo
from lab.faults import FAULTS, PrivilegedExec

TRACES_DIR = Path(__file__).parents[1] / "traces"


def legacy_entries(names: list[str], k: int, seed: int) -> list[dict]:
    """Eski davranisin kuyruk-bicimli karsiligi: ariza basina k tekrar, seed=0 dunyasi.

    scenario_id=ariza adi oldugundan rollout_id eski "ariza#i" bicimiyle ayni kalir.
    """
    return [
        {
            "scenario_id": name,
            "topo_seed": 0,
            "fault_class": name,
            "symptom": render(name, random.Random(f"{seed}:{name}:{i}")),
            "k_index": i,
        }
        for name in names
        for i in range(k)
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3, help="ariza basina rollout")
    ap.add_argument("--faults", nargs="*", default=None, help="alt kume (vars. hepsi)")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    console = Console()
    names = args.faults or sorted(FAULTS)
    unknown = set(names) - set(FAULTS)
    if unknown:
        sys.exit(f"bilinmeyen ariza: {sorted(unknown)}")
    # semptom kaynagi olmayan sinif render'da patlamasin — disla ve raporla
    have = symptoms.available_classes()
    no_symptom = sorted(set(names) - have)
    if no_symptom:
        console.print(f"[yellow]semptom kaynagi yok, atlandi:[/] {no_symptom}")
        names = [n for n in names if n in have]
    if not names:
        sys.exit("kosulacak sinif kalmadi (semptom bankasi eksik)")

    TRACES_DIR.mkdir(exist_ok=True)
    out_path = TRACES_DIR / f"batch_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    spec = topo.default_spec()
    pe = PrivilegedExec(spec)
    rows: list[dict] = []

    with out_path.open("w") as out:
        for entry in legacy_entries(names, args.k, args.seed):
            console.rule(f"{entry['scenario_id']}#{entry['k_index'] + 1}")
            console.print(f"semptom: {entry['symptom']}")

            try:
                row = run_scenario(entry, spec, pe, model=args.model)
            except InfraError as e:
                if e.row is not None:
                    out.write(json.dumps(e.row, ensure_ascii=False) + "\n")
                    rows.append(e.row)
                console.print(f"[red]altyapi hatasi, kosu durduruldu[/]\n{e}")
                return 1

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            rows.append(row)
            verdict, err = row["verdict"], row["error"]
            console.print(
                f"[{'green' if verdict == 'pass' else 'yellow' if verdict == 'partial' else 'red'}]"
                f"{verdict}[/] — {row['n_tool_calls']} arac, {row['duration_s']}s"
                + (f", HATA: {err}" if err else "")
            )

    _summary(console, rows, out_path)
    return 0


def _out_tokens(r: dict) -> int:
    return r["usage"].get("output_tokens", 0)


def _summary(console: Console, rows: list[dict], out_path: Path) -> None:
    table = Table(title=f"Faz 0 olcumu — {out_path.name}")
    for col in ("ariza", "pass", "partial", "fail", "ort. arac", "ort. out-token", "ort. sure(s)"):
        table.add_column(col)

    def stats(subset: list[dict]) -> tuple[str, ...]:
        n = len(subset) or 1
        return (
            str(sum(r["verdict"] == "pass" for r in subset)),
            str(sum(r["verdict"] == "partial" for r in subset)),
            str(sum(r["verdict"] == "fail" for r in subset)),
            f"{sum(r['n_tool_calls'] for r in subset) / n:.1f}",
            f"{sum(_out_tokens(r) for r in subset) / n:.0f}",
            f"{sum(r['duration_s'] for r in subset) / n:.0f}",
        )

    for name in dict.fromkeys(r["fault"] for r in rows):
        table.add_row(name, *stats([r for r in rows if r["fault"] == name]))
    table.add_row("TOPLAM", *stats(rows), style="bold")
    console.print(table)

    total_cost = sum(r["cost_usd"] for r in rows)
    cache_read = sum(r["usage"].get("cache_read_input_tokens", 0) for r in rows)
    console.print(f"toplam maliyet: ${total_cost:.2f} (abonelikte 0 gorunebilir), cache_read tok: {cache_read}")
    console.print(f"trace dosyasi: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
