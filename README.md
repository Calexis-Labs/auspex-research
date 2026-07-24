# netagent — Faz 0

Kapalı ağda çalışan, **salt-okunur** network arıza teşhis asistanı — çalışan demo fazı.
Bir Claude ajanı, containerlab'de canlı bir ağa enjekte edilmiş arızayı yalnızca
whitelisted araçlarla teşhis eder. Ayrıntılı mimari: proje spec'i.

## Mimari (Faz 0)

- **Lab host (Dell, `ssh lab`):** containerlab + 3× Arista cEOS (`spine1/leaf1/leaf2`) + 2 Linux host (`hosta/hostb`). Yönetim ağı `192.168.121.0/24` (mevcut Docker ağlarıyla çakışmasın diye).
- **Tool layer:** Scrapli (SSH) + `| json` native parse; allowlist **transport katmanında** zorlanır (`tools/allowlist.py`, 3 katman, fail-closed). Arıza enjeksiyonu ayrı yoldan (`docker exec` + FastCli) yapılır — ajanın SSH yüzeyi yapısal olarak salt-okunur.
- **Teacher:** headless `claude -p` + MCP (`tools/mcp_server.py`); API key yerine abonelik token'ı (`CLAUDE_CODE_OAUTH_TOKEN`).

## Kurulum durumu

Dell tarafı hazır: containerlab 0.77, sudoers (yalnız clab), network-multitool imajı, claude CLI 2.1.207.

**Manuel iki adım (bir kez):**
1. arista.com → Support → Software Download → **cEOS64-lab** tarball (ücretsiz hesap).
   `scp cEOS64-lab-*.tar.xz lab: && ssh lab "docker import cEOS64-lab-*.tar.xz ceos:lab"`
2. Mac'te `claude setup-token` → çıkan token'ı Dell'de `~/netagent/.env` içine:
   `CLAUDE_CODE_OAUTH_TOKEN=...`

## Kullanım (Mac'ten)

```bash
make test          # yerel birim testleri (ağ gerekmez)
make test-remote   # ayni testler Dell'de
make lab-deploy    # topoloji uret + deploy + hazir bekle + health check
make lab-health    # saglik kontrolu
ssh lab 'cd ~/netagent && uv run python -m lab.faults.smoke'   # 5 ariza inject/revert smoke
ssh lab 'cd ~/netagent && uv run python -m datagen.teacher "B binasi aga cikamiyor"'  # tek rollout
make run-batch     # 5 ariza x k=3 = 15 trace + ozet tablo
make lab-destroy
```

Ölçüm çıktıları `traces/batch_*.jsonl` (tam trace + verdict + token kullanımı).

## Dizin haritası

- `tools/` — allowlist, transport (scrapli / docker exec), araç şemaları, MCP sunucusu
- `lab/` — topoloji verisi (`topo.py`), üretici, deploy/health, `faults/` (5 arıza + GroundTruth)
- `datagen/` — TR semptomlar, teacher, verifier, batch runner
- `tests/` — allowlist/transport/schema sözleşme testleri (ağ gerektirmez)
