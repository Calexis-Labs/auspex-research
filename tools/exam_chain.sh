#!/bin/bash
# Temizlik turu bitince SINAV kuyruguna otomatik gecis.
# Sinav: seed 400-450 (egitimde HIC kullanilmadi), 150 senaryo, k=1.
# Bu tur ayni zamanda Sonnet'in held-out BASELINE olcumudur; trace'ler
# egitime GIRMEZ (ayri dosyada kalir: queue kimlikleri exam_ids.txt'e yazilir).
set -u
cd "$HOME/netagent"
ts() { date "+%Y-%m-%d %H:%M:%S"; }

echo "$(ts) EXAM-CHAIN: temizlik turunun bitmesi bekleniyor"
while pgrep -f "datagen[.]lanes" >/dev/null; do sleep 60; done
echo "$(ts) EXAM-CHAIN: lanes bitti — sinav kuyrugu kuruluyor"
touch traces/PAUSE
uv run python -m datagen.queue_build --count 150 --seed-range 400:451 --k 1 --rng-seed 42
rc=$?
if [ $rc -eq 0 ]; then
    # sinav kimliklerini ayir: egitim veri setine sizmasin
    uv run python - <<'PY'
import json
ids = sorted({json.loads(l)["scenario_id"] for l in open("traces/queue.jsonl") if l.strip()})
open("traces/exam_ids.txt", "w").write("\n".join(ids))
print(f"sinav kimligi: {len(ids)} -> traces/exam_ids.txt")
PY
fi
rm -f traces/PAUSE
if [ $rc -ne 0 ]; then
    echo "$(ts) EXAM-CHAIN: queue_build HATA (rc=$rc) — insan mudahalesi gerekli"
    exit 1
fi
echo "$(ts) EXAM-CHAIN: tamam — lanes'i watchdog baslatacak (<=10 dk)"
