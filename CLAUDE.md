# NetworkAgent — Proje Hafızası

> Bu dosya projenin kalıcı hafızasıdır. Her önemli karar/sonuç sonrası GÜNCELLE.
> Kullanıcı teknik detaya boğulmak istemiyor — açıklamalar SADE Türkçe olmalı.

## Ne yapıyoruz (tek paragraf)

Kapalı ağda (internetsiz), müşteri sahasında çalışacak, **salt-okunur** bir network
arıza teşhis asistanı. Küçük bir açık model (Qwen3 8B / Gemma 4 adayı), büyük bir
öğretmen modelin (Sonnet) sanal lab'de çözdüğü binlerce arıza senaryosundan öğrenecek.
Boru hattı: sanal lab (containerlab + Arista cEOS) → arıza enjekte et → öğretmen
salt-okunur araçlarla teşhis etsin → doğrulayıcı süz → doğru izlerle küçük modeli eğit
→ sınavla puanla.

## Değişmez kurallar (GEVŞETME)

- Model HİÇBİR ZAMAN konfigürasyon değiştirmez. Salt-okunurluk `tools/allowlist.py`
  ile taşıma katmanında zorlanır (3 katman, fail-closed) — prompt ile değil.
- Arıza enjeksiyonu SADECE `PrivilegedExec` (docker exec + FastCli) ile; ajanın SSH
  yüzeyinden asla.
- Dell host'ta (openclaw@192.168.1.171, `ssh lab`) BAŞKA prod servisler var
  (postiz, nginx :80, ollama...) — dokunma. Her şey `~/netagent/` içinde izole.
  sudo yalnız `containerlab` için NOPASSWD.
- Teacher API key ile DEĞİL abonelik token'ıyla çalışır (`CLAUDE_CODE_OAUTH_TOKEN`,
  Dell'de `~/netagent/.env`). Token hassas — loglama/paylaşma.

## Mimari kısa harita

- `lab/topo.py` — seed'li parametrik topoloji (`build_spec(seed)`; seed=0 = sabit eski lab)
- `lab/faults/` — 19 arıza sınıfı; `@fault` kaydı, `inject/revert`, `GroundTruth`
- `tools/` — allowlist + scrapli transport + MCP sunucusu (teacher'ın gördüğü ~9 araç)
- `datagen/` — queue_build (kuyruk) → lanes (N paralel şerit, her biri kendi lab'ı)
  → teacher (headless `claude -p`) → verifier (deterministik puanlama)
- `datagen/scenario_bank/` — Opus'un yazdığı TR semptom bankası (placeholder'lı)
- `serve/monitor.py` — sade Türkçe dashboard: http://192.168.1.171:8931
- Mac'te geliştir → `make sync` → Dell'de çalıştır. Testler: `uv run pytest` (261 yeşil)

## Kritik dersler (tekrar yaşama)

- **Etiket-ikizi tuzağı:** Araç çıktısından ayırt EDİLEMEYEN iki duruma iki ayrı
  sınıf etiketi verme. Pilot'ta `link_down_far_end` (0/7) `interface_admin_down`'a
  birleştirildi (`label` mekanizması, `lab/faults/__init__.py`).
- **insufficient_info v2:** eski "muğlak şikayet + sağlıklı ağ" tasarımı no_fault
  ikiziydi (0/9). Yeni tasarım: şikayetin öznesi araç görünürlüğü DIŞINDA
  (wifi/VPN/yazıcı/telefon/uygulama). Ağ temiz + konu test edilemez → insufficient_info.
- Üretimden önce her yeni arıza sınıfı canlı smoke'tan geçmeli (`lab/faults/smoke.py`);
  bozulma üretmeyen sınıf `live_verified=False` ile üretim dışı kalır.
- Abonelik 5 saatte bir limite takılır; lane motoru bekleyip aynı senaryoyu tekrar
  dener (`LIMIT_WAIT_S`) — kuyruk bozulmaz, sadece yavaşlar.

## Durum (2026-07-18, akşam) — ÜRETİM TAMAMLANDI

- **1088 benzersiz senaryo, 1016'sında pass** (hedef ~1000 ✓). Sızıntılı semptomlu
  pass: 0. Kimlikler: `traces/production_ids.txt` (eğitim) / `traces/exam_ids.txt`
  (sınav, karışmaz). rollout_id tekrarında SON satır geçerli (ts sıralı).
- Temizlik turu 119 fireden 66 geri kazandı. Kalan: 32 fail + 27 partial
  (çoğu multi_fault kısmileri) + 9 skip — kitaba girmez, sorun değil.
- Sınav zinciri kurulu: temizlik bitince seed 400-450'den 150 soru, Sonnet
  baseline olarak çözecek (~8 saat). Bu trace'ler EĞİTİME GİRMEZ.
- **DERS KİTABI HAZIR (2026-07-18 gece):** `datagen/dataset_build.py` →
  Dell'de `dataset/train.jsonl` (1008) + `val.jsonl` (89) + `report.json`.
  1097 örnek, sıfır fire, ~10M token, p50 8.5k / p95 14.9k → max_seq 16k YETER
  (GPU maliyeti yarıya: tek A100 seansı ~$5-10). ToolSearch turları ayıklandı;
  thinking blokları boştu (headless CLI kaydetmiyor) → eylem-düzeyi damıtma.
  Prompt trace'ten değil `teacher.build_prompt`'tan yeniden kurulur (tek ve
  güncel prompt; öğrenci-servis aynı fonksiyonu kullanacak).
- Faz 2 planı onaylı (~/.claude/plans/): B0 ön sınav → B reçete kanıtı (MLX mini)
  → C tek RunPod A100 seansı (QLoRA, early stop) → D karne (150 soru, token yok).
- **B0 TAMAM — MODEL KARARI: Qwen3 8B (2026-07-19).** Ön sınav (12 soru, seed
  331-340, ham modeller, Mac'te Ollama + Dell'de lab): Qwen 2/12, Gemma4:26b
  3/12 → doğruluk başa baş; AMA Gemma 5/12 soruda teşhis vermeden döngüden
  çıktı (disiplinsiz), 24GB M4'e sığmadı (GPU OOM; num_gpu=24 offload gerekti),
  2x fazla araç çağırdı. Qwen: her sınavı teşhisle kapattı, 5GB, 16k ctx rahat.
  Bake-off KAPANDI. Öğrenci altyapısı: `datagen/student.py` (Ollama, öğretmenle
  aynı prompt/araç adları/verifier) + `datagen/pre_exam.py`; lanes.run_lane
  `rollout=` parametresiyle öğrenciyi de koşuyor. Ollama Mac'te T7 diskinde
  (OLLAMA_MODELS=/Volumes/T7/ollama-models, LAN: 192.168.1.180:11434).
- **B TAMAM — REÇETE KANITLANDI (2026-07-19 sabah).** Qwen3-1.7B-4bit + MLX
  LoRA, 77 ders, 50 adım: train loss 1.17→0.30, VAL 0.74→0.32 (birlikte düşüş
  = ezber yok), tool-call formatı korunmuş. Dönüştürücü: `train/prepare_qwen.py`
  (apply_chat_template + tools; GPU eğitimi de AYNISINI kullanacak).
  DERSLER: (1) Mac'te 16k ctx + Ollama açık = bellek taşması, makine yeniden
  başladı — eğitimde Ollama HEP kapalı, 12k+grad-checkpoint bile 23.8GB tepe
  yaptı; Mac'te tam eğitim İMKANSIZ (~50 saat + bellek riski). (2) Gerçek token
  sayımı char/4 tahmininden %25 uzun: p50 10.7k → GPU'da max_seq 24k olacak.
  (3) venv exFAT T7'ye kurulamaz (symlink yok) → ~/venvs/netagent-train.
  (4) Makefile sync'e --exclude dataset/ eklendi (rsync --delete Dell'deki
  dataset'i silmişti; deterministik yeniden üretildi, kayıp yok).
- SIRADA — Aşama C: kullanıcıdan RunPod hesabı + ~$25 kredi bekleniyor (ödemeye
  ben dokunmam). Hazırlık: unsloth script (max_seq 24k, QLoRA r=32, 3 epoch,
  epoch-checkpoint, val-loss early stop). Sınav (150, seed 400+) haftalık
  limit sonrası; Sonnet baseline + eğitilmiş Qwen karşılaştırmalı karne.

## Durum (2026-07-16, öğlen)

- Pilot yeniden puanlandı (`datagen/reverify.py`): %72 → %86, 14 trace kurtarıldı.
- Doğrulama turları: tur1 9/12 (internet tuzağı + tam tarama eksiği bulundu),
  düzeltmeler sonrası tur2 11/12 — tek fail bankadaki çelişkili no_fault metniydi
  (Wi-Fi özneli), 5 no_fault semptomu yeniden yazıldı. Yeni sınıflar 6/6.
- **BÜYÜK ÜRETİM ÇALIŞIYOR:** 1100 senaryo / 300 topoloji (seed 31-330), 2 lane,
  `traces/queue.jsonl` + `traces/prod_1100.log`. Tahmin: 2-3 gün (≈19 trace/saat,
  limit beklemeleri dahil). native_vlan_mismatch üretim dışı (live_verified=False).
- Seed 400+ SINAVA AYRILDI — eğitim asla dokunmaz (ezber önlemi).
- Sırada: üretim bitince sınav seti (~150, seed 400-450) + Sonnet baseline,
  sonra Qwen3 8B vs Gemma 4 fine-tune karşılaştırması.
- Maliyet gerçeği: ~$0.45/trace (API eşdeğeri; abonelikte $0 ama limitli+yavaş).

## Auspex Harness planı (2026-07-21 onaylı — ~/.claude/plans/son-bir-sorum-var-*.md)

Ürün adlandırması: **Kestrel** = eğitilen model (Qwen3 8B fine-tune), **Auspex** =
onu sahada çalıştıran ajan katmanı (Claude Code analojisi). Ana karar: Opus'un
harness planındaki F0-F3 ZATEN bizde var — iş sıfırdan yazmak değil damıtmak:
- F0 sözleşme = tools/schema.py TOOLS (A0: auspex/contract/tools-v1.json olarak
  dondur + eğitim verisiyle uyum testi; GPU beklerken yapılabilir)
- F1 ajan döngüsü = datagen/student.py (A1'de auspex/core/loop.py'a çıkarılacak)
- F2 güvenlik = tools/allowlist.py + transport.py (3 katman fail-closed)
- F3 "benchmark harness üzerinden" = pre_exam.py + run_lane(rollout=...) —
  karne Auspex döngüsünden koşulacak, yayınlanan skor model+harness bütünü
- YENİ işler: CLI (auspex diagnose), rapor (kanıt zinciri), hash-zincirli denetim
  izi, inventory.yaml, paketleme/imzalı güncelleme (A3, pilot öncesi)
- Opus planına 3 düzeltme: (1) v1 SADECE eğitimdeki 9 araç (mac/arp/log/acl
  araçları v1.5 eğitimiyle gelir), (2) TextFSM değil EOS |json (F5'te döner),
  (3) ping'siz "katı mod" ayrı eğitim turu ister, v1'de sadece bayrak.
- SIRA: yarın GPU eğitimi+karne ÖNCE; eğitim koşarken A0; A1 karneden sonra.

## TAM KARNE SONUÇLARI (2026-07-23) — R1 TAMAM

150 held-out soru (seed 400-450, 51 topoloji), aynı harness:
- **KESTREL v1: 102/150 (%68) + 9 kısmi** | **SONNET: 128/150 (%85; 6 altyapı
  hatası hariç %88)** | ham Qwen3 ön sınavda %17'ydi (150'lik koşusu sürüyor).
- Kestrel GÜÇLÜ: wrong_subnet 13/13, ospf'ler ~tam, interface_admin 6/6,
  no_fault 8/8, duplicate_ip 11/14, link_down_far_end 9/11 (SONNET'TEN İYİ: o 5/11).
- Kestrel ZAYIF (v1.1 veri reçetesi): **static_route_missing 1/8** (usta 8/8 —
  en büyük fırsat), **multi_fault 1/12+6p** (usta 8/12), **acl 3/13** (usta da
  5/13 — sınıfın kendisi zor, enjektör/senaryo gözden geçirilmeli),
  access_port 4/8. Fail tipolojisi: 31 yanlış-teşhis, 8 teşhissiz.
- Sonnet'in 6 error'u telafi koşusuyla kapatılabilir (rapor öncesi).
- Zincir: ham qwen3:8b aynı 150'ye otomatik girdi (exam_rawqwen.log).
- Sıradaki: exam_report.py → calexislabs.com yayını (noskills akışıyla) →
  Llama 3.3 8B + Granite 4.1 8B tabloya (arka planda) → v1.1 hedefli eğitim.

## KESTREL v1 EĞİTİLDİ + İLK KARNE (2026-07-22)

- RunPod A100 QLoRA Qwen3-8B, 3 epoch, val 0.51→0.47→0.46 (ezber yok). ~$8, pod
  silindi. GGUF q4 + LoRA yedegi T7'de (/Volumes/T7/kestrel/). Ollama: kestrel:v1.
- **Ön sınav (12 soru, seed 331-340): ham 2/12 → Kestrel 9 tam + 1 kısmi (~%79-83).**
  Güçlü: svi_down 2/2, wrong_host_gateway 3/3, access_port 1/1, insufficient_info,
  vlan_removed, acl(1/2). Zayıf kalan: acl (en zor sınıf, 1/2), wrong_subnet 0/1.
  Ort 31 araç/soru (think=on ile bol araştırma).
- **KRİTİK DERS — Ollama paketleme:** modeli EĞİTİM şablonuyla paketle (unsloth
  Modelfile: /Volumes/T7/kestrel/Modelfile), resmi qwen3 şablonuyla DEĞİL → aksi
  halde model 16 jeton üretip boş döner (template uyumsuzluğu). think=True şart
  (think=False gerçek teşhis promptunda boş). max_turns 60 (model çok araştırıyor).
  Hepsi datagen/student.py'da kalıcı. Bu, Auspex "sözleşme=şablon" ilkesinin kanıtı.
- SIRA: 150 soruluk tam karne (seed 400+) + Sonnet baseline → yayınlanacak skor.

## Auspex A0+A1 iskeleti CANLI DOĞRULANDI (2026-07-21 gece)

- `auspex/contract/tools-v1.json` donduruldu (9 araç, sha256); bekçi testleri:
  şema-sözleşme uyumu + eğitim verisi fiili araç adlarıyla örtüşme. 327 test yeşil.
- `auspex/cli.py` (diagnose/version) + `auspex/report.py` (kanıt zinciri) çalışıyor.
  CANLI UÇTAN UCA: ham qwen3:8b, sağlıklı seed-0 lab'de `auspex diagnose` ile
  20 araçlık tam tarama yapıp DOĞRU no_fault raporu verdi (5 dk, oturum kaydıyla).
  İlk deneme "No route to host" verdi — student.py DEFAULT_URL eski ev IP'siydi
  (.180) → .49 yapıldı; hata durumunda bile düzgün rapor+kayıt üretti (dayanıklılık).
- Kalan Auspex işi: A1 damıtma (loop.py çıkarma, backends, audit.py hash zinciri)
  karneden sonra; A2 sınavı Auspex'ten koşma; A3 paketleme pilot öncesi.

## auspex-cli AÇIK KAYNAK PAKETİ YAYINDA (2026-07-23, private repo)

- **github.com/Calexis-Labs/auspex-cli** (şimdilik PRIVATE; public'e çevirme
  kullanıcıda). v0.1.0 release: wheel + sabit adlı latest-wheel + sdist +
  install.sh/ps1 + SHA256SUMS. CI 9/9 yeşil (ubuntu/macos/windows × 3.11/3.12 +
  contract-freeze + scrub grep + shellcheck). Konum: /Volumes/T7/My Projects/auspex-cli.
- Damıtma yapıldı: prompt.py (DIAGNOSTIC_PROMPT bayt-bayt + FAULT_CLASSES literal),
  core/loop.py (student.py rollout'u; NUDGE/tur-limiti/submit stringleri bayt-bayt),
  core/ollama.py (AUSPEX_* env; varsayılan ctx **24576** = sınav değeri, temp 0.6,
  think=on), tools/{schema,allowlist,transport} vendored (creds envanterden;
  linux host SSH argv modu YENİ), inventory.yaml (parola dosyada YASAK, *_env),
  contract/runtime-v1.json (prompt/nudge/Modelfile sha256 + servis parametreleri).
- **Parite bekçisi:** tests/test_public_parity.py (BU repoda; AUSPEX_CLI_PATH ile,
  varsayılan /Volumes/T7/My Projects/auspex-cli) — prompt/TOOLS/FAULT_CLASSES/
  build_prompt(seed 0-4)/servis parametreleri birebir. Sözleşme dosyası bayt-aynı
  (sha 0fccb315...). DERS: utf-8 encoding'i her read_text/write_text'te AÇIK yaz
  (Windows cp1252 em-dash'i bozdu, CI kırmızı) + .gitattributes eol=lf.
- Dağıtım MİMARİSİ (2026-07-23 canlıya alma): calexislabs.com DNS'i
  Cloudflare'de DEĞİL (Hostinger NS → Vercel kayıtları) → R2 custom domain
  imkânsızdı. Çözüm: **calexis-dl worker'ı** (workers.dev) R2'yi servis eder:
  https://calexis-dl.oguzhankalelioglu.workers.dev (GET/HEAD + Range 206
  doğrulandı; token korumalı multipart yükleme uçları da worker'da — kaynak:
  scratchpad/dl-worker, wrangler OAuth ile deploy edildi). GGUF sha256
  7237efa7c4eb19a9... (5,027,784,160 bayt). CLI kurulum tek satırı GitHub
  Releases'tan (releases/latest/download/install.sh) — DNS'siz çalışır.
  v0.1.1: DEFAULT_MANIFEST_URL = worker URL. İLERİDE: kullanıcı zone'u
  Cloudflare'e taşırsa dl.calexislabs.com worker'a custom domain bağlanır
  (eski URL'ler çalışmaya devam eder). DİKKAT: CalexisLabs/.env.local içinde
  GEÇERSİZ CF_API_TOKEN var — wrangler'ı o dizinden ÇALIŞTIRMA (gölgeliyor).
- ERTELENEN: gerçek GGUF ile uçtan uca `auspex setup` + duman testi — ham qwen
  sınavı Mac Ollama'sını kullanırken KOŞMA (modeli evict eder); sınav bitince.
- Ham qwen ARA SKOR (101/150, 2026-07-24): **13 pass (%13)** + 4 partial —
  ön-sınav 2/12 (~%17) ile TUTARLI. Bitiş 24 Tem akşamüstü.
- **KRİTİK DERS (2026-07-24): verdict vokabüleri `pass`/`fail`/`partial`'dır,
  "correct" DEĞİL.** Skor sayarken `verdict=="pass"` kullan. Bu oturumda ad-hoc
  ssh script'lerinde "correct" arayıp ham qwen'i yanlışlıkla "%0" sandım (2 gün
  paniğe gerek yoktu). Kestrel 102/150 rakamı doğruydu (asıl pipeline "pass"
  ile hesaplamış). Skor script'i yazan HERKES verdict enum'unu verifier.py'dan
  teyit etsin.
- METODOLOJİ NOTU: ham qwen sınavı ctx=16384 (student.py default), Kestrel
  ctx=24576 ile koştu — asimetri. Ama qwen hataları çoğunlukla gerçek muhakeme
  hatası (yanlış fault_class), truncation değil; delta 13→68 sağlam. Katı parite
  istenirse qwen 24k ile yeniden koşulur (~2 gün) — muhtemelen gereksiz.

## Yarın (Çarşamba) operasyon sırası — haftalık limit yenilenince

1. Kullanıcı RunPod'da Pod açar (A100 PCIe 80GB $1.39/sa, PyTorch template,
   SSH anahtarı kayıtlı: ~/.ssh/runpod_netagent) → bağlantı satırını verir.
2. Ben: veri yükle (dataset_local/ + prepare_qwen.py mantığı) → unsloth QLoRA
   Qwen3-8B, max_seq 24k, r=32, 3 epoch, epoch-checkpoint, val-loss early stop
   → canlı izleme → en iyi checkpoint'i Mac'e indir → POD'U HEMEN KAPAT (~$6-11).
3. GPU beklerken: A0 sözleşme dondurma (token yok).
4. Sonra: LoRA merge → GGUF q4 → Ollama'ya yükle → 150 soruluk sınav (öğrenci
   token'sız) + Sonnet baseline (taze haftalık limitten) → KARNE.
NOT: Dell taşındı, yeni IP 192.168.1.51 (ssh alias 'lab' güncellendi; .171'e
dönüş için router DHCP rezervasyonu: MAC 00:be:43:d4:25:b4 — şimdilik .51).

## Faz 3 planı — "Uzmanlık müfredatı" (2026-07-21 kararı, karne SONRASI)

Kullanıcı hedefi: model sadece arıza teşhisçisi değil, TAM network uzmanı olsun
(topoloji anlama + doğru araç seçimi). Mevcut dersler bunu ÖRTÜK öğretiyor
(her trace get_topology ile başlar, 300 farklı topolojide gezinme var) ama
açık müfredat eksik. Eklenecek 4 görev ailesi — hepsi MEVCUT fabrikayla üretilir,
cevap anahtarı build_spec'ten deterministik çıkar (arıza GT mantığının aynısı):
1. Topoloji özeti/envanter QA ("bu ağı anlat", "VLAN 10 hangi portlarda")
2. Yol takibi ("hostA→sunucu trafiği hangi yoldan geçer")
3. Etki analizi ("şu link koparsa kim etkilenir")
4. Proaktif sağlık raporu (health_check'in model versiyonu)
~500-800 kısa ders (5-8 araç; arıza derslerinden ucuz) → eski+yeni karışım →
ikinci GPU seansı (~$10) → v1.5. SIRA: önce v1 eğitim+karne, bu SONRA.

## İş modeli (2026-07-16 sohbeti)

- Hedef ürün: %100 local, salt-okunur teşhis asistanı (CLI + araçlar + küçük model).
- Gelir: MRR değil **ARR** — kurulum ücreti + yıllık lisans (model güncellemeleri
  dosya/USB ile, yeni marka desteği, destek). Cihaz/lokasyon başına fiyat.
- Veri paradoksunun cevabı: müşteri verisi GEREKMİYOR — sentetik lab boru hattı
  bizim veri fabrikamız. Yeni vendor = lab'e imaj ekle, aynı hattı çalıştır.
  Opt-in anonim geri bildirim (doğru/yanlış + arıza tipi) sadece bonus.
- Ek kalemler: vendor modülleri (Cisco/Huawei paketi), appliance satışı, MSP kanalı.
- Sıralama: önce benchmark puanı (kanıt) → CLI ürünleştir → 1-2 ücretsiz pilot → satış.

## Üretim sırasında yakalanan hatalar (2026-07-16)

- **Placeholder sızıntısı:** bankada `{server2_ip}`/`{host2_ip}` vardı, `fill()`
  tanımıyordu VE kaçak-temizleme regex'i rakamsızdı (`[a-z_]`) → 55/285 şablon
  çiğ placeholder'la teacher'a gitti. Düzeltme: fill'e iki placeholder eklendi,
  regex `[a-z0-9_]` oldu, `tests/test_symptom_fill.py` her banka şablonunun 5
  toplojide kalıntısız dolduğunu zorluyor. Sızıntılı 20 senaryo kuyruk sonuna
  yeniden eklendi; veri setine girerken `"{" in symptom` satırlar atılacak +
  rollout_id tekrarında SON satır geçerli.
- **Dashboard tüm eski dosyaları sayıyordu** → kullanıcı "fail 49" diye endişelendi
  (28'i dünkü pilotun eski puanlamasıydı). load_rollouts artık yalnız aktif
  queue.jsonl'deki scenario_id'leri sayar + rollout_id dedup.
- **ssh üzerinden pkill/pgrep öz-eşleşme tuzağı:** desen kendi komut satırını
  yakalar → `pgrep -f "datagen[.]lanes"` gibi köşeli parantez hilesi ŞART.
  DAHA SİNSİSİ: pkill ile başlatma AYNI ssh satırındaysa, pkill deseni satırın
  nohup kısmındaki düz "datagen.lanes" yazısını yakalayıp kendi oturumunu
  öldürür → başlatma hiç çalışmaz. KURAL: durdurma ve başlatma AYRI ssh çağrısı.
- **Lane ölümü sessiz kalabiliyor:** lane1, 16'sında 12:56'daki deploy
  çakışmasında FATAL olup 14 saat boyunca üretim tek şeritte sürdü — hız
  düşüklüğü limite yoruldu. KONTROL: `pgrep -fc` İKİ lane saymalı; hız yarıya
  düşerse önce lane loglarının son satırına bak.
- **Dar maske + sabit .254 tuzağı:** wrong_host_gateway sahte gw'yi net+254
  seçiyordu; /26'da subnet dışı → kernel reddi → multi_fault inject patladı.
  Artık broadcast'ten geriye yürüyerek subnet İÇİNDEN seçiyor (test var).
- **acl ECMP maskelemesi:** çift-spine dünyada ACL tek yola konunca trafik
  sağlam yoldan dolaşır → model haklı olarak no_fault der. acl artık yalnız
  tek-uplink gw hedefler; uygun hedef yoksa LookupError → lane "skipped".
- **acl v2 — hostsuz VLAN da görünmez arıza** (2026-07-18): seçilen VLAN'da hiç
  host yoksa şikayeti yeniden üretecek makine yok → ACL hiçbir araçtan
  gözlenmez. Aday VLAN artık "tek uplink + en az 1 host" ister.
- **GENEL İLKE — "görünmez arıza" ailesi:** her enjektör kendine sormalı:
  "bu arızayı ajan HANGI araç çıktısından görebilir?" Cevap yoksa enjekte etme
  (LookupError -> skipped). Şimdiye kadarki üyeler: link_down yedekli trunk,
  vlan_removed fallback'i, acl ECMP, acl hostsuz VLAN, native_vlan (Faz2).
- **Otomatik zincir:** `tools/cleanup_chain.sh` ana kuyruğun bitmesini bekler,
  `datagen/cleanup_queue.py` ile fire senaryoları (best-of-k pass olmayanlar,
  skipped hariç) yeni kuyruğa yazar; lanes'i watchdog başlatır (çift-başlatma
  riski yok). Bilinçli duraklatma: `traces/PAUSE` dosyası.

## Öğretmen prompt dersleri (kural değişiklikleri)

- "internet" kelimesi lab'de tuzak: lab'in internet çıkışı yok; internete değinen
  semptomlar modeli rota-arızası uydurmaya itiyor. Semptomlarda ve kural
  örneklerinde internet TEMASI KULLANMA.
- no_fault öncesi tam tarama zorunlu (kural 6): yedekli yol kesintiyi maskeler;
  ping'ler geçse bile down arayüz / eksik OSPF komşusu taraması yapılmalı.

## Kullanıcı tercihleri

- Açıklamalar sade, jargonsuz Türkçe; benzetmelerle anlat (çırak/usta, sınav/karne).
- Para/token israfına duyarlı — üretimden önce doğrula, çöp veri üretme.
- Kararlar kullanıcıya sorulur ama seçenek bombardımanı yapma: tek net öneri + gerekçe.
