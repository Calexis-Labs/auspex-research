---
name: kestrel-ops
description: Kestrel modelini paketleme, Ollama'ya kurma, smoke test ve sınav koşturma runbook'u. Model boş cevap veriyor / araç çağırmıyor / döngüye giriyorsa veya yeni sürüm (v1.1+) paketlenecekse bunu kullan.
---

# Kestrel Operasyonları

## DEMİR KURAL: çıkarım sözleşmesi = eğitim sözleşmesi
Üç bileşen eğitimle BİREBİR aynı olmalı, biri saparsa model bozuk davranır:
1. **Konuşma şablonu:** Ollama'ya `/Volumes/T7/kestrel/Modelfile` (unsloth'un
   ürettiği, eğitim şablonu) ile kaydet. Resmi qwen3 şablonu KULLANMA →
   model 16 jeton üretip boş döner (2026-07-22 vakası).
2. **Araç adları/şemaları:** `auspex/contract/tools-v1.json` (test korumalı).
3. **Prompt:** `datagen/teacher.build_prompt` (tek kaynak).

## Paketleme (yeni GGUF geldiğinde)
```bash
cd /Volumes/T7/kestrel && ollama create kestrel:vX -f Modelfile
```
Modelfile içinde: eğitim TEMPLATE + stop token'lar + temperature 0.6.

## Smoke test (paketleme sonrası ZORUNLU, sınavdan önce)
Eğitim setinden 6-8 GERÇEK promptla ilk araç çağrısı testi — basit tek-araç
testi YETMEZ (yanıltır; 2026-07-22'de think kararını yanlış verdirdi):
```bash
cd "/Volumes/T7/My Projects/NetworkAgent" && python3 -  # dataset_local'dan 8 prompt,
# her biri icin /api/chat think=true + tools-v1; 8/8 tool_call bekle
```

## Çalıştırma ayarları (datagen/student.py'da kalıcı)
- `think=True` şart (think=False gerçek promptta boş döner)
- `num_ctx=24576` (eğitim genişliği; 16k'da uzun teşhislerde talimat kaybı)
- `temperature=0.6` (0 → tekrar döngüsü: 35x aynı ping vakası)
- `max_turns=60` + tur-sonu emniyet uyarısı (limit-4'te "teşhisini ver")

## Sınav koşturma
- Ön sınav (12 soru, hızlı doğrulama): `uv run python -m datagen.pre_exam --model kestrel:vX`
- Tam karne (150, seed 400+): `NETAGENT_STUDENT_CTX=24576 uv run python -m datagen.exam_run --model kestrel:vX --lane 0`
- Ollama Mac'te açık olmalı: `OLLAMA_MODELS=/Volumes/T7/ollama-models OLLAMA_HOST=0.0.0.0:11434 ollama serve`
- Mac IP değişirse: `NETAGENT_STUDENT_URL` env (varsayılan student.py'da).

## Bilinen belirti → neden tablosu
| Belirti | Neden |
|---|---|
| Boş content, eval_count ~16 | Yanlış şablonla paketlenmiş |
| Gerçek promptta boş, basit testte çalışıyor | think=False |
| Aynı aracı 30+ kez çağırma | temperature=0 |
| 40 turda teşhissiz | ctx küçük (16k) veya emniyet uyarısı yok |
