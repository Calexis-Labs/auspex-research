#!/usr/bin/env python3
"""netagent canli izleme ekrani — stdlib-only, Dell'de calisir.

Tek sayfa, duz Turkce, 4 sn'de yenilenir:
  - EN UST: "SU AN NE OLUYOR" bandi (calisan sureci pgrep ile tespit eder)
  - Canli smoke ilerlemesi (traces/smoke_status.json): kac/toplam, her sinif OK/FAIL
  - Lane kartlari (traces/lane<i>_status.json) + kuyrukta kalan
  - Uretilen trace ozeti (batch_*.jsonl): sinif bazinda gecme orani
  - Lab container durumu

Baslatma: nohup python3 serve/monitor.py >/dev/null 2>&1 &   (port 8931)
"""

import html
import json
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).parents[1]
TRACES = REPO / "traces"
SMOKE = TRACES / "smoke_status.json"
QUEUE = TRACES / "queue.jsonl"
CURSOR = TRACES / "queue.cursor"
PORT = 8931

CSS = """
*{box-sizing:border-box}
body{font-family:ui-monospace,Menlo,monospace;background:#0d1117;color:#c9d1d9;margin:0;padding:24px;max-width:1100px}
h1{font-size:17px;color:#e6edf3;margin:0 0 4px} .sub{color:#8b949e;font-size:12px;margin-bottom:20px}
h2{font-size:12px;color:#8b949e;margin:26px 0 10px;text-transform:uppercase;letter-spacing:.1em}
.now{background:linear-gradient(90deg,#132b4d,#161b22);border:1px solid #2f5a94;border-radius:10px;padding:18px 22px;margin-bottom:8px}
.now .lead{font-size:20px;color:#e6edf3;font-weight:700;line-height:1.35}
.now .detail{color:#a9c2e8;font-size:13px;margin-top:6px}
.bar{height:10px;background:#21262d;border-radius:6px;overflow:hidden;margin-top:12px}
.bar > i{display:block;height:100%;background:#3fb950}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 12px;border-bottom:1px solid #21262d}
th{color:#8b949e;font-weight:600}
.ok{color:#3fb950;font-weight:700}.bad{color:#f85149;font-weight:700}.warn{color:#d29922;font-weight:700}.muted{color:#8b949e}
.pass{color:#3fb950;font-weight:700}.partial{color:#d29922;font-weight:700}.fail,.error{color:#f85149;font-weight:700}.skipped{color:#8b949e}
.grid{display:flex;gap:14px;flex-wrap:wrap}
.lane{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px;min-width:240px;font-size:12.5px;line-height:1.7}
.lane h3{margin:0 0 6px;font-size:13px;color:#e6edf3}
.phase{display:flex;gap:8px;flex-wrap:wrap;font-size:12px}
.phase span{padding:4px 10px;border-radius:14px;border:1px solid #30363d}
.phase .done{background:#12261a;border-color:#2ea043;color:#3fb950}
.phase .active{background:#132b4d;border-color:#2f5a94;color:#79b8ff}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;margin-left:6px}
.pill.run{background:#12261a;color:#3fb950;border:1px solid #2ea043}
.pill.idle{background:#21262d;color:#8b949e;border:1px solid #30363d}
"""


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(errors="replace"))
    except (FileNotFoundError, ValueError):
        return None


def _proc_running(pattern: str) -> bool:
    try:
        return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0
    except Exception:
        return False


def load_rollouts() -> list[dict]:
    """YALNIZ aktif kuyrugun senaryolarini say — eski gun/pilot/mini-test
    dosyalari tabloya karismasin (2026-07-16: kullanici 'fail 49' diye
    endiselendi; 28'i dunku pilotun eski puanlamasiydi). Ayni rollout_id
    birden fazla dosyada varsa (yeniden kosum) SON satir gecerli."""
    # MOD SECIMI (yeni > eski): tam karne (exam/) > on sinav (pre_exam/) > uretim.
    # Karne modunda birden fazla model paralel kosar; tablo KESTREL kosusunu
    # gosterir (rollout_id'ler modeller arasi cakisir — karistirilamaz).
    candidates = [QUEUE, TRACES / "pre_exam" / "queue.jsonl",
                  TRACES / "exam" / "queue_master.jsonl"]
    existing = [p for p in candidates if p.exists()]
    active_queue = max(existing, key=lambda p: p.stat().st_mtime) if existing else QUEUE
    if active_queue.name == "queue_master.jsonl":
        subs = sorted((TRACES / "exam").glob("*/"))
        kestrel = [d for d in subs if "kestrel" in d.name]
        batch_glob = kestrel or subs or [TRACES]
    elif "pre_exam" in str(active_queue):
        batch_glob = sorted((TRACES / "pre_exam").glob("*/")) or [TRACES]
    else:
        batch_glob = [TRACES]
    current_ids: set[str] = set()
    if active_queue.exists():
        for line in active_queue.read_text(errors="replace").splitlines():
            try:
                current_ids.add(json.loads(line)["scenario_id"])
            except (ValueError, KeyError):
                pass
    by_rid: dict[str, dict] = {}
    for d in batch_glob:
        for f in sorted(Path(d).glob("batch_*.jsonl")):
            _collect(f, current_ids, by_rid)
    return list(by_rid.values())


def _collect(f: Path, current_ids: set, by_rid: dict) -> None:
    if True:
        for row in _parse_cached(f):
            if current_ids and row.get("scenario_id") not in current_ids:
                continue
            by_rid[row.get("rollout_id") or str(len(by_rid))] = row
    return list(by_rid.values())


# dosya bazli onbellek: (mtime, size) degismedikce YENIDEN PARSE ETME.
# Ders (2026-07-18): her sayfa yenilemede ~100MB jsonl bastan okununca
# monitor tek basina %45 CPU yiyordu. events alani stats icin gereksiz —
# onbellege kirpilmis satir konur (bellek de kucuk kalir).
_FILE_CACHE: dict[str, tuple[float, int, list[dict]]] = {}
_KEEP = ("rollout_id", "scenario_id", "fault", "verdict", "verdict_reasons",
         "n_tool_calls", "cost_usd", "duration_s", "error", "lane",
         "topo_seed", "k_index", "ts", "model")


def _parse_cached(f: Path) -> list[dict]:
    try:
        st = f.stat()
    except OSError:
        return []
    key = str(f)
    hit = _FILE_CACHE.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    rows = []
    for line in f.read_text(errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        rows.append({k: row.get(k) for k in _KEEP})
    _FILE_CACHE[key] = (st.st_mtime, st.st_size, rows)
    return rows


def lane_statuses() -> list[dict]:
    return [s for s in (_read_json(f) for f in sorted(TRACES.glob("lane*_status.json"))) if s]


def containers() -> list[str]:
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", "name=clab-netagent", "--format", "{{.Names}}  {{.Status}}"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return out.splitlines() if out else []
    except Exception:
        return []


# ---------------------------------------------------------------- "su an" bandi

def now_banner() -> str:
    smoke = _read_json(SMOKE)
    lanes = lane_statuses()
    lane_live = _proc_running("datagen.lanes") or any(
        s.get("state") in ("running", "deploying", "redeploying") for s in lanes)
    smoke_live = _proc_running("lab.faults.smoke") or (smoke and smoke.get("running"))
    cts = containers()

    if smoke_live and smoke:
        done, total = smoke.get("done", 0), smoke.get("total", 0) or 1
        cur = smoke.get("current") or "-"
        pct = int(100 * done / total)
        lead = f"Canlı test sürüyor: {total} arıza türünün her biri gerçek cihazlarda deneniyor"
        detail = f"şu an: <b>{html.escape(cur)}</b> &nbsp;·&nbsp; {done}/{total} tamamlandı"
        return _banner(lead, detail, pct)

    if lane_live:
        rem = _queue_remaining()
        active = [s.get("active_scenario") for s in lanes if s.get("active_scenario")]
        lead = "Veri üretimi sürüyor: yapay ağlarda arıza kurulup Claude'a teşhis ettiriliyor"
        detail = f"aktif: {html.escape(', '.join(map(str, active)) or '-')}"
        if rem:
            detail += f" &nbsp;·&nbsp; kuyrukta {rem[0]}/{rem[1]} iş kaldı"
        pct = int(100 * (rem[1] - rem[0]) / rem[1]) if rem and rem[1] else 0
        return _banner(lead, detail, pct)

    if cts:
        lead = "Lab ayakta, boşta bekliyor"
        detail = f"{len(cts)} sanal cihaz çalışıyor · yeni bir koşu başlatılmayı bekliyor"
        return _banner(lead, detail, None)

    return _banner("Şu an aktif bir koşu yok", "lab kapalı — bir sonraki adım bekleniyor", None)


def _banner(lead: str, detail: str, pct: int | None) -> str:
    bar = f'<div class=bar><i style="width:{pct}%"></i></div>' if pct is not None else ""
    return f'<div class=now><div class=lead>{lead}</div><div class=detail>{detail}</div>{bar}</div>'


# ---------------------------------------------------------------- bolumler

def _queue_remaining() -> tuple[int, int] | None:
    if not QUEUE.exists():
        return None
    groups, last, total = [], object(), 0
    for line in QUEUE.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        total += 1
        if groups and e.get("topo_seed") == last:
            groups[-1] += 1
        else:
            groups.append(1); last = e.get("topo_seed")
    try:
        idx = int((CURSOR.read_text().strip() or "0"))
    except (FileNotFoundError, ValueError):
        idx = 0
    return sum(groups[idx:]), total


_RESULT_CLS = {"OK": "ok", "FAIL": "bad", "atlandi": "muted"}


def smoke_section() -> str:
    s = _read_json(SMOKE)
    if not s:
        return ""
    live = " <span class='pill run'>çalışıyor</span>" if s.get("running") else " <span class='pill idle'>bitti</span>"
    rows = "".join(
        f"<tr><td>{html.escape(r['class'])}</td>"
        f"<td class={_RESULT_CLS.get(r['result'], 'muted')}>{html.escape(r['result'])}</td>"
        f"<td class=muted>{html.escape((r.get('detail') or '')[:70])}</td></tr>"
        for r in s.get("results", [])
    ) or "<tr><td colspan=3 class=muted>ilk arıza deneniyor…</td></tr>"
    n_ok = sum(r["result"] == "OK" for r in s.get("results", []))
    n_bad = sum(r["result"] == "FAIL" for r in s.get("results", []))
    return f"""<h2>Canlı arıza testi (seed {s.get('seed', 0)}){live}</h2>
<div class=sub>her arıza türü gerçek cihazlara kuruluyor, bozulma doğrulanıyor, geri alınıyor —
{n_ok} geçti · {n_bad} kaldı · {s.get('done',0)}/{s.get('total',0)}</div>
<div class=card><table><tr><th>arıza türü</th><th>sonuç</th><th>ayrıntı</th></tr>{rows}</table></div>"""


def lanes_section() -> str:
    lanes = lane_statuses()
    if not lanes:
        return ""
    cards = []
    for s in lanes:
        cards.append(
            f"<div class=lane><h3>Şerit {s.get('lane','?')} · {html.escape(str(s.get('state','?')))}</h3>"
            f"aktif: {html.escape(str(s.get('active_scenario') or '-'))}<br>"
            f"yazılan: {s.get('rows_done',0)} · son: <span class={s.get('last_verdict','muted')}>{html.escape(str(s.get('last_verdict','-')))}</span></div>"
        )
    return f"<h2>Üretim şeritleri</h2><div class=grid>{''.join(cards)}</div>"


def results_section(rows: list[dict]) -> str:
    if not rows:
        return "<h2>Üretilen veri</h2><div class='card muted'>henüz trace üretilmedi</div>"
    by: dict[str, dict] = {}
    for r in rows:
        c = by.setdefault(str(r.get("fault", "?")), {"pass": 0, "partial": 0, "fail": 0, "error": 0, "skipped": 0})
        c[r.get("verdict") if r.get("verdict") in c else "error"] += 1
    body = []
    for name in sorted(by):
        c = by[name]
        scored = c["pass"] + c["partial"] + c["fail"] + c["error"]
        rate = 100 * c["pass"] / scored if scored else 0
        body.append(
            f"<tr><td>{html.escape(name)}</td><td>{sum(c.values())}</td>"
            f"<td class=pass>{c['pass']}</td><td class=partial>{c['partial']}</td>"
            f"<td class=fail>{c['fail']+c['error']}</td><td class=skipped>{c['skipped']}</td>"
            f"<td>{rate:.0f}%</td></tr>")
    tp = sum(r.get("verdict") == "pass" for r in rows)
    return f"""<h2>Üretilen veri — {tp}/{len(rows)} doğru teşhis</h2>
<div class=card><table>
<tr><th>arıza türü</th><th>n</th><th>doğru</th><th>kısmi</th><th>yanlış</th><th>atlandı</th><th>başarı</th></tr>
{''.join(body)}</table></div>"""


def phase_tracker() -> str:
    return """<h2>Proje durumu</h2><div class="phase">
<span class=done>Faz 0 — demo ✓ (14/15 doğru)</span>
<span class=active>Faz 1 — 19 arıza türü + veri üretim hattı</span>
<span>Faz 2 — model eğitimi</span>
<span>Faz 3 — saha pilotu</span></div>"""


def render() -> str:
    rows = load_rollouts()
    cts = containers()
    ct_html = "<br>".join(html.escape(c) for c in cts) or "(lab kapalı)"
    return f"""<!doctype html><html lang=tr><head><meta charset=utf-8>
<meta http-equiv=refresh content=4><title>netagent izleme</title><style>{CSS}</style></head><body>
<h1>netagent — canlı izleme</h1>
<div class=sub>kapalı ağda çalışan network arıza teşhis asistanı · {time.strftime('%H:%M:%S')} · 4 sn'de yenilenir</div>
{now_banner()}
{phase_tracker()}
{smoke_section()}
{lanes_section()}
{results_section(rows)}
<h2>Lab cihazları</h2><div class=card><pre style="margin:0">{ct_html}</pre></div>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"izleme: http://0.0.0.0:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
