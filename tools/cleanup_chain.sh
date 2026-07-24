#!/bin/bash
# Ana kuyruk bitince temizlik turunu OTOMATIK baslatan zincir.
# (dosya olarak calisir -> cmdline'da "datagen.lanes" gecmez, pgrep oz-eslesmez)
# Lanes'i BIZ baslatmayiz: kuyrugu yazariz, watchdog 10 dk icinde
# "kuyruk var + lane yok" gorup temiz zeminde kendisi baslatir.
set -u
cd "$HOME/netagent"
ts() { date "+%Y-%m-%d %H:%M:%S"; }

echo "$(ts) CHAIN: ana kuyrugun bitmesi bekleniyor"
while pgrep -f "datagen[.]lanes" >/dev/null; do sleep 60; done
echo "$(ts) CHAIN: lanes bitti — temizlik kuyrugu kuruluyor"
touch traces/PAUSE                      # kuyruk yazimi sirasinda watchdog karismasin
uv run python -m datagen.cleanup_queue
rc=$?
rm -f traces/PAUSE
if [ $rc -ne 0 ]; then
    echo "$(ts) CHAIN: cleanup_queue HATA (rc=$rc) — insan mudahalesi gerekli"
    exit 1
fi
echo "$(ts) CHAIN: tamam — lanes'i watchdog baslatacak (<=10 dk)"
