#!/bin/bash
# Lane bekcisi (cron: her 10 dk) — "sessiz olum" onlemi.
# Ders (2026-07-17): lane1 deploy cakismasinda FATAL oldu, uretim 14 saat tek
# seritle surundu ve kimse fark etmedi. Bu script:
#   - kuyruk bitmediyse ve HIC lane calismiyorsa: konteynerlari temizler,
#     lanes'i yeniden baslatir (kendi kendini iyilestirme)
#   - tek lane kaldiysa: WARNING loglar (restart YAPMAZ — calisan lane'e
#     dokunmak mgmt subnet cakismasi yaratir; mudahale insana/Claude'a kalir)
#   - traces/PAUSE dosyasi varsa hicbir sey yapmaz (bilincli durdurma bayragi)
set -u
cd "$HOME/netagent"
ts() { date "+%Y-%m-%d %H:%M:%S"; }

[ -f traces/PAUSE ] && exit 0

# kuyruk bitti mi? (cursor >= toplam grup sayisi ise bitti)
remaining=$(uv run python - <<'PY' 2>/dev/null
import json
from pathlib import Path
q = Path("traces/queue.jsonl"); c = Path("traces/queue.cursor")
if not q.exists():
    print(0); raise SystemExit
groups, prev = 0, None
for line in q.read_text().splitlines():
    if not line.strip(): continue
    sid = json.loads(line)["scenario_id"]
    if sid != prev:
        groups += 1; prev = sid
cur = int(c.read_text() or 0) if c.exists() else 0
print(max(0, groups - cur))
PY
)
remaining=${remaining:-0}
[ "$remaining" -eq 0 ] && exit 0

n=$(pgrep -fc "datagen[.]lanes" || true)
n=${n:-0}

if [ "$n" -eq 0 ]; then
    echo "$(ts) WATCHDOG: hic lane yok, kuyrukta ~$remaining grup var — YENIDEN BASLATIYORUM"
    docker ps -aq --filter name=clab-netagent | xargs -r docker rm -f >/dev/null 2>&1
    sleep 2
    nohup uv run python -m datagen.lanes --lanes 2 >> traces/prod_1100.log 2>&1 &
elif [ "$n" -le 2 ]; then
    # parent + 2 lane cocugu normalde >=3 process eder; <=2 ise bir lane dusmus olabilir
    echo "$(ts) WATCHDOG UYARI: lane process sayisi dusuk ($n) — lane loglarini kontrol et"
    tail -1 traces/lane0.log 2>/dev/null | sed "s/^/$(ts)   lane0: /"
    tail -1 traces/lane1.log 2>/dev/null | sed "s/^/$(ts)   lane1: /"
fi
exit 0
