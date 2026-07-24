---
name: gpu-training
description: RunPod A100 kiralayıp Kestrel eğitme runbook'u — pod açma, veri yükleme, unsloth QLoRA, canlı izleme, indirme ve PODu KAPATMA. Yeni model sürümü (v1.1+) eğitilecekse bunu kullan.
---

# GPU Eğitim Seansı (RunPod, tek seferde bitir)

## İlkeler
- Deneme-yanılma GPU'da OLMAZ: reçete önce Mac'te MLX mini ile kanıtlanır
  (50 örnek, loss düşüyor + format korunuyor).
- Saat ücreti işler: her adım hazır olmadan pod açılmaz; iş bitince pod SİLİNİR.

## Akış
1. Kullanıcı pod açar (A100 SXM/PCIe 80GB, PyTorch template, SSH key kayıtlı:
   `~/.ssh/runpod_netagent`). "Waiting for availability" görürsen İPTAL edip
   müsaitlik çubuğu dolu karta geç (kuyrukta bekleme + otomatik başlama tuzağı).
2. Bağlan: `ssh -i ~/.ssh/runpod_netagent -p <port> root@<ip>`
3. Kur: `pip install --break-system-packages unsloth` (PEP 668 sistem koruması
   bayraksız reddeder). torch sürüm çakışması uyarısı zararsız.
4. Yükle: `dataset_local/{train,val}.jsonl` + `auspex/contract/tools-v1.json`
   (script araçları SÖZLEŞMEDEN okur — repo bağımlılığı yok).
5. Eğitim: `train/train_kestrel.py` (kanıtlı reçete: QLoRA r=32 alpha=64,
   lr 1e-4 cosine, 3 epoch, max_length=24576, epoch-checkpoint + val,
   load_best_model_at_end, train_on_responses_only).
   **TUZAK:** TRL'de `SFTConfig(max_length=...)` kullan — TrainingArguments'a
   max_seq_length geçirirsen SESSİZCE 1024'e düşer ve maskeleme patlar.
6. İzle: nohup + log; loss dict'leri log'a düşmeyebilir → checkpoint'teki
   `trainer_state.json` log_history'den oku. Val her epoch: DÜŞÜYORSA devam,
   yükseliyorsa erken kes (en iyi checkpoint zaten saklı).
7. Paketle (pod'da, hızlı): `to_gguf.py` → unsloth `save_pretrained_gguf`
   q4_k_m. Çıktı `<isim>_gguf/` DEĞİL `<isim>_gguf_gguf/` altına düşer!
   Modelfile'ı da üretir — GGUF ile birlikte indir.
8. İndir + doğrula: scp GGUF + Modelfile + lora tgz; sha256 iki tarafta eşleşmeli.
9. **KAPAT:** `curl -X DELETE -H "Authorization: Bearer $(cat ~/.config/runpod-netagent.key)"
   https://rest.runpod.io/v1/pods/<id>` → pod listesi 0 olana kadar doğrula.

## Maliyet çıpası (v1 gerçeği)
1.100 ders × 3 epoch, A100 PCIe: eğitim ~3,5 saat + paketleme ~1 saat ≈ **$7-8**.

## Ölçülmüş oranlar
~34-38 sn/adım (batch 1 × grad_accum 8, 24k seq). 378 adım = 1004 örnek × 3 epoch.
