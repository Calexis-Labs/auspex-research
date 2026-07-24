"""Auspex CLI — Kestrel'i sahada calistiran arayuz.

Kullanim (lab/musteri host'unda):
  uv run python -m auspex.cli diagnose "hosta sunuculara erisemiyor" [--model qwen3:8b]
  uv run python -m auspex.cli version

v1 dongusu datagen/student.py'daki kanitlanmis rollout'u kullanir (A1'de
auspex/core/loop.py'a damitilacak — davranis sozlesmesi ayni kalir).
Oturum kaydi egitim formatiyla ayni semada auspex_sessions/ altina yazilir.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from auspex import report as report_mod
from auspex.contract.freeze import OUT as CONTRACT_PATH

SESSIONS = Path("auspex_sessions")


def cmd_version() -> int:
    c = json.loads(CONTRACT_PATH.read_text())
    print(f"auspex v0.1 | sozlesme {c['version']} | {len(c['tools'])} arac | "
          f"sha256 {c['sha256'][:16]}")
    return 0


def cmd_diagnose(args) -> int:
    from datagen.student import run_student_rollout
    t0 = time.strftime("%Y%m%d_%H%M%S")
    print(f"Auspex: teshis basladi (model={args.model}) — salt-okunur mod, "
          "hicbir konfigurasyon degistirilmez.\n")
    trace = run_student_rollout(args.symptom, model=args.model,
                                max_turns=args.max_turns)
    print(report_mod.render(trace))
    SESSIONS.mkdir(exist_ok=True)
    out = SESSIONS / f"session_{t0}.jsonl"
    with out.open("w") as f:
        f.write(json.dumps({
            "symptom": trace.symptom, "model": trace.model,
            "diagnosis": trace.diagnosis, "error": trace.error,
            "n_tool_calls": trace.n_tool_calls, "duration_s": trace.duration_s,
            "events": trace.events, "ts": time.time(),
        }, ensure_ascii=False) + "\n")
    print(f"\noturum kaydi: {out}")
    return 0 if trace.diagnosis else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="auspex", description="Kestrel network teshis harness'i")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diagnose", help="bir sikayeti teshis et")
    d.add_argument("symptom")
    d.add_argument("--model", default="qwen3:8b")
    d.add_argument("--max-turns", type=int, default=40)
    sub.add_parser("version", help="surum + sozlesme bilgisi")
    args = ap.parse_args()
    return cmd_version() if args.cmd == "version" else cmd_diagnose(args)


if __name__ == "__main__":
    sys.exit(main())
