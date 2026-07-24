---
name: lab-ops
description: Dell lab host operasyonları — lane motoru, watchdog/PAUSE, süreç kontrol tuzakları, zincirler, dashboard modları. Üretim/sınav koşusu başlatma-durdurma, "lane öldü", "dashboard yanlış gösteriyor" durumlarında bunu kullan.
---

# Lab Operasyonları (Dell: ssh lab, ~/netagent)

## MUTLAK KURAL: pgrep/pkill öz-eşleşme
Uzak komut satırındaki desen kendini yakalar. Bu oturumda 4 kez ısırdı:
- Desende köşeli parantez ŞART: `pgrep -f "datagen[.]lanes"`
- pkill ile başlatma AYNI ssh satırında ASLA olmaz (pkill, satırdaki nohup
  kısmını görüp kendi oturumunu öldürür → başlatma hiç çalışmaz, ssh 255 döner)
- Durdur / temizle / başlat = ÜÇ AYRI ssh çağrısı.

## Koşu başlat/durdur
- Üretim: `queue_build` → `nohup uv run python -m datagen.lanes --lanes 2`
- Durdurma sırası: `touch traces/PAUSE` (watchdog karışmasın) → pkill (köşeli
  parantez) → `docker rm -f $(docker ps -aq --filter name=clab-netagent...)`
  (eski konteynerler kalırsa yeni deploy çakışır → grup başına 4'lü error) →
  başlat → `rm traces/PAUSE`.
- Lane sağlığı: `pgrep -fc` İKİ lane saymalı. Hız yarıya düştüyse önce
  `traces/lane*.log` son satırlarına bak (FATAL sessiz kalır — 14 saat tek
  şerit vakası). Watchdog (cron, 10dk) 0-lane durumunu kendisi toparlar;
  tek-lane durumunda sadece UYARI loglar → insan müdahalesi.

## Kuyruk mekaniği
- `write_queue` cursor'ı sıfırlar; lanes kuyruğu BAŞLANGIÇTA okur → koşu
  sırasında append İŞE YARAMAZ, yeni tur gerekir.
- rollout_id başına SON satır geçerli (ts) — tekrar koşular güvenli.
- Senaryo fire türleri: `skipped` (uygun hedef yok — yeniden koşma), `error`
  (altyapı — yeniden koş), `fail` (model yanlış — analiz et).
- Zincirler: `tools/cleanup_chain.sh` (fire tekrarı), `tools/exam_chain.sh`;
  ikisi de lanes bitişini bekler, kuyruğu yazar, başlatmayı WATCHDOG'a bırakır
  (çift başlatma imkansız).

## Dashboard (http://<dell-ip>:8931)
- Mod otomatik: en yeni kuyruk hangisiyse onu gösterir (üretim / pre_exam /
  exam). Karne modunda Kestrel koşusunu gösterir.
- Monitor CPU yerse: dosya önbelleği var (mtime+size); events alanı parse edilmez.
- Yeniden başlatma: pkill `"serve[.]monitor"` AYRI komutta; sonra setsid nohup.

## Görünmez arıza ilkesi (enjektör yazarken)
"Bu arızayı ajan HANGİ araç çıktısından görebilir?" Cevap yoksa enjekte etme
(LookupError → skipped). Üyeler: yedekli trunk, ECMP maskeli ACL, hostsuz VLAN,
subnet dışı sahte gateway. Her yeni sınıf canlı smoke'tan geçmeden üretime giremez.

## Ortam notları
- Dell IP taşınmada değişebilir: ping sweep + port 22 + `hostname`=openclaw ile
  bul; `~/.ssh/config` alias güncelle. Statik için router DHCP rezervasyonu
  (MAC 00:be:43:d4:25:b4).
- exFAT (T7) venv/symlink desteklemez → venv iç diske, model/veri T7'ye.
- Mac'te eğitim/Ollama aynı anda ÇALIŞTIRMA (24GB taşar, makine resetlenir).
