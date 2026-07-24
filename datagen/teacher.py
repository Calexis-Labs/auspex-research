"""Teacher: headless `claude -p` sarmalayicisi (API key YOK — abonelik auth).

Ajan yalnizca netagent MCP sunucusunun araclarini gorur (--strict-mcp-config +
allowlist); yerlesik araclarin tamami kapalidir. stream-json ciktisi tam trace
(arac cagrilari, sonuclar, token kullanimi) olarak toplanir.

Lab host'unda calisir: uv run python -m datagen.teacher "<semptom>"
Gereksinim: .env icinde CLAUDE_CODE_OAUTH_TOKEN (Mac'te `claude setup-token`).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from lab import topo
from lab.faults import FAULT_CLASSES
from lab.topo import build_spec

REPO_ROOT = Path(__file__).parents[1]


def _spec_from_env():
    """Lane env degiskenlerinden (yoksa seed=0) aktif dunyayi kur — mcp_server ile ayni sozlesme."""
    return build_spec(
        int(os.environ.get("NETAGENT_TOPO_SEED", "0")),
        name=os.environ.get("NETAGENT_LAB_NAME", topo.LAB_NAME),
        mgmt_subnet=os.environ.get("NETAGENT_MGMT_SUBNET", topo.MGMT_SUBNET),
    )
SUBMIT_TOOL = "mcp__netagent__submit_diagnosis"

DIAGNOSTIC_PROMPT = """Sen deneyimli bir network arıza teşhis mühendisisin. Elindeki araçlar SALT-OKUNURDUR; hiçbir konfigürasyon değiştiremezsin.

Ağ: {switches} (Arista switch) ve {hosts} (Linux kullanıcı makineleri). Cihaz adları araç çağrılarında aynen böyle kullanılır.

Disiplin:
1. Önce topolojiyi ve semptomu doğrula (get_topology, ping) — şikayeti körü körüne kabul etme. Erişim şikayetini ETKİLENEN taraftaki hosttan ping ile yeniden üret; switch CLI'ından ping farklı sonuç verebilir (switch'in kendi rotaları/kaynak IP'si farklıdır).
2. Hipotez kur, EN AZ maliyetli araçla test et; her adımda tek hipotez.
3. Kök nedeni bulduğunda submit_diagnosis'i TAM BİR KEZ çağır ve dur. fault_class şu listeden biri olmalı: {fault_classes}
   ÖNEMLİ: şikayette birden fazla BAĞIMSIZ belirti varsa (ör. hem bir kullanıcı makinesi hem bir OSPF komşuluğu), ilk kök nedeni bulunca DURMA — bulduğun arıza diğer belirtiyi açıklamıyorsa onu da ayrıca araştır. Birden çok kök neden varsa fault_class=multi_fault gönder ve root_cause'ta her birini ayrı satırda "sınıf_adı @ cihaz — açıklama" biçiminde listele; fix_commands hepsinin düzeltmesini içersin.
4. fix_commands insan onayına sunulur, asla otomatik uygulanmaz — yine de doğru ve eksiksiz yaz.
5. Uydurma: görmediğin bir değeri (interface, VLAN, IP) teşhise yazma; önce araçla doğrula.
6. Şikayet AĞIN KENDİSİ hakkındaysa (erişim, ping, yavaşlık) ve tüm kontroller sağlıklıysa fault_class=no_fault gönder — arıza UYDURMA. Ama no_fault göndermeden ÖNCE tam tarama zorunlu: TÜM switch'lerde get_interfaces + get_ospf_neighbors + get_routes kontrol et; ping'ler geçse bile down bir arayüz, eksik komşuluk veya eksik rota (bir cihazın tablosunda diğer VLAN subnet'lerine/loopback'lere giden rotanın YOKLUĞU) varsa ağ sağlıklı DEĞİLDİR (yedekli yol kesintiyi maskeleyebilir). Özellikle statik yönlendirmeli ağlarda rota tablolarını cihaz cihaz karşılaştır — silinen bir statik rota yalnızca burada görünür.
7. Şikayetin öznesi araçlarınla GÖZLEYEMEDİĞİN bir sistemse (kablosuz ağ, VPN, yazıcı, IP telefon, e-posta/uygulama yazılımı gibi bu ağın dışındaki bir bileşen) fault_class=insufficient_info gönder: görebildiğin ağ tarafını yine de doğrula, root_cause'a ağ tarafının temiz olduğunu ve hangi ek bilgiye/erişime ihtiyacın olduğunu yaz. Ama görünür ağda somut bir arıza bulursan onu raporla.
8. Bir link/trunk arızasından şüpheleniyorsan İKİ ucu da ayrı ayrı doğrula (get_vlans / get_interfaces / get_config_section her iki cihazda). Teşhisteki device, KÖK NEDENİN cihazıdır — semptomun göründüğü cihaz değil. İki uç arasında ASİMETRİK bir ayar bulursan (ör. yalnız bir uçta authentication/farklı timer/farklı area), o ayarı TAŞIYAN uç kök cihazdır — ağın geri kalanındaki linklerle karşılaştırıp hangi ucun norm dışı olduğunu doğrula. Hangi araç çıktısına dayandığını root_cause'ta belirt.

Kullanıcı şikayeti:
{symptom}"""


_LIMIT_MARKERS = ("session limit", "usage limit", "rate limit", "resets", "429",
                  "quota", "overloaded")


def is_limit_error(msg: str | None) -> bool:
    """Abonelik/oran limiti hatasi mi? (bekle-ve-tekrar dene sinyali)"""
    return bool(msg) and any(m in msg.lower() for m in _LIMIT_MARKERS)


@dataclass
class Trace:
    symptom: str
    model: str
    events: list[dict] = field(default_factory=list)
    diagnosis: dict | None = None
    n_tool_calls: int = 0
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    duration_s: float = 0.0
    num_turns: int = 0
    error: str | None = None

    @property
    def limited(self) -> bool:
        return is_limit_error(self.error)


def _claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".npm-global" / "bin" / "claude"
    if fallback.exists():
        return str(fallback)
    raise FileNotFoundError("claude CLI bulunamadi (npm install -g @anthropic-ai/claude-code)")


def _mcp_config() -> Path:
    lab = os.environ.get("NETAGENT_LAB_NAME", topo.LAB_NAME)
    path = REPO_ROOT / "lab" / "build" / f"mcp_{lab}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "netagent": {
                        "command": "uv",
                        "args": ["run", "--directory", str(REPO_ROOT), "python", "-m", "tools.mcp_server"],
                    }
                }
            }
        )
    )
    return path

DISALLOWED = (
    "Bash,Read,Write,Edit,MultiEdit,NotebookEdit,Glob,Grep,WebFetch,WebSearch,"
    "Task,TodoWrite,SlashCommand,KillShell,BashOutput"
)


def build_prompt(symptom: str, spec) -> str:
    """Teshis promptunu kur — teacher, dataset_build ve ogrenci sinav harness'i
    AYNI fonksiyonu kullanir (egitim/servis tutarliligi sart)."""
    return DIAGNOSTIC_PROMPT.format(
        symptom=symptom,
        fault_classes=", ".join(FAULT_CLASSES),
        switches=", ".join(sorted(spec.ceos_nodes)),
        hosts=", ".join(sorted(spec.hosts)) or "(yok)",
    )


def run_rollout(symptom: str, model: str = "sonnet", max_turns: int = 40, timeout_s: int = 900) -> Trace:
    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        raise RuntimeError(".env icinde CLAUDE_CODE_OAUTH_TOKEN yok — `claude setup-token` ciktisini koy")

    spec = _spec_from_env()
    prompt = build_prompt(symptom, spec)
    argv = [
        _claude_bin(),
        "-p", prompt,
        "--mcp-config", str(_mcp_config()),
        "--strict-mcp-config",
        "--allowedTools", "mcp__netagent",
        "--disallowedTools", DISALLOWED,
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        "--max-turns", str(max_turns),
    ]

    trace = Trace(symptom=symptom, model=model)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout_s, cwd=REPO_ROOT,
            env=os.environ.copy(), stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        trace.error = f"timeout ({timeout_s}s)"
        trace.duration_s = time.monotonic() - start
        return trace
    trace.duration_s = time.monotonic() - start

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        trace.events.append(event)

        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    trace.n_tool_calls += 1
                    if block.get("name") == SUBMIT_TOOL:
                        trace.diagnosis = block.get("input")
        elif event.get("type") == "result":
            trace.usage = event.get("usage", {})
            trace.cost_usd = event.get("total_cost_usd") or 0.0
            trace.num_turns = event.get("num_turns", 0)
            if event.get("is_error"):
                trace.error = str(event.get("result", "bilinmeyen hata"))[:500]

    if proc.returncode != 0 and not trace.error:
        trace.error = f"claude rc={proc.returncode}: {proc.stderr[-500:]}"
    if trace.diagnosis is None and not trace.error:
        trace.error = "submit_diagnosis hic cagrilmadi"
    return trace


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('kullanim: python -m datagen.teacher "<semptom>" [model]')
    t = run_rollout(sys.argv[1], model=sys.argv[2] if len(sys.argv) > 2 else "sonnet")
    print(json.dumps({
        "diagnosis": t.diagnosis,
        "n_tool_calls": t.n_tool_calls,
        "num_turns": t.num_turns,
        "usage": t.usage,
        "cost_usd": t.cost_usd,
        "duration_s": round(t.duration_s, 1),
        "error": t.error,
    }, indent=2, ensure_ascii=False))
