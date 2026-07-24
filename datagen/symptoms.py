"""TR semptom uretici — kullanici agzından yazilmis sikayetler.

Kural: cihaz adi ve kok neden ASLA gecmez; kullanicinin gorebilecegi seyler
(IP'ler, "A binasi/B binasi", "sunucu") gecebilir. hostA=10.10.0.20 (A binasi),
hostB=10.10.0.30 (B binasi); "sunucular" = loopback'ler (1.1.1.1, 3.3.3.3).

render() bank-first calisir: datagen/scenario_bank/symptoms_v1.json varsa ve
sinif oradaysa semptom bankadan cekilir; degilse TEMPLATES fallback.
"""

import json
import random
from pathlib import Path

BANK_PATH = Path(__file__).parent / "scenario_bank" / "symptoms_v1.json"

TEMPLATES: dict[str, list[str]] = {
    "interface_admin_down": [
        "Bu sabahtan beri hiçbir kullanıcı sunuculara (1.1.1.1 ve 3.3.3.3) erişemiyor. "
        "Kullanıcılar kendi aralarında dosya paylaşabiliyor ama sunucu tarafı tamamen kapalı.",
        "A binasındaki ve B binasındaki herkes sunucu erişimini kaybetti. Ofis içi ağ çalışıyor "
        "gibi görünüyor, yazıcılar ve ortak klasörler açılıyor ama 1.1.1.1'e bile ping gitmiyor.",
        "Sabah mesaiye geldiğimizde sunucularla bağlantı yoktu. Kullanıcı bilgisayarları birbirini "
        "görüyor ama veri merkezi tarafına hiçbir şey gitmiyor. Dün akşam her şey normaldi.",
    ],
    "vlan_removed_from_trunk": [
        "B binasındaki kullanıcılar (10.10.0.30 tarafı) ağda hiçbir şeye erişemiyor — ne sunuculara "
        "ne A binasındaki makinelere. A binası tamamen normal çalışıyor.",
        "10.10.0.30 adresindeki bilgisayar dahil B tarafındaki herkes ağdan koptu. Kablolar takılı, "
        "linkler yanıyor ama hiçbir yere ulaşamıyorlar. A tarafında sorun yok.",
        "B binası bu öğleden sonra tamamen ağ dışı kaldı. Aynı binadaki kullanıcılar birbirini "
        "görüyor mu emin değiliz ama A binasına ve sunuculara kesinlikle ulaşamıyorlar.",
    ],
    "wrong_host_gateway": [
        "10.10.0.30 adresli kullanıcı bilgisayarı sunuculara çıkamıyor; yan masadaki 10.10.0.20 "
        "sorunsuz çalışıyor. İkisi de aynı ağda görünüyor, birbirlerine ping atabiliyorlar.",
        "Tek bir kullanıcıda garip bir sorun var: 10.10.0.30, komşu bilgisayarlara erişebiliyor ama "
        "1.1.1.1 veya 3.3.3.3'e hiçbir şekilde ulaşamıyor. Diğer herkes normal.",
        "B binasındaki bir kullanıcı (10.10.0.30) sabahtan beri sunuculara bağlanamıyor. IP'si var, "
        "yereldeki paylaşımlar açılıyor, ama dışarıya giden her şey zaman aşımına düşüyor.",
    ],
    "acl_blocking_traffic": [
        "İzleme sistemimiz tüm sunucuları down gösteriyor — hiçbirine ping gitmiyor. Ama kullanıcılar "
        "uygulamalara girebildiklerini söylüyor. Ya izleme bozuk ya ağda tuhaf bir şey var.",
        "Kullanıcı subnet'inden (10.10.0.0/24) sunuculara ping atılamıyor, ne 1.1.1.1 ne 3.3.3.3. "
        "İlginç olan şu: uygulama trafiği çalışıyor gibi, sadece ping/teşhis trafiği ölü.",
        "Ağ ekibi dün gece bakım yapmış. Bu sabahtan beri monitoring ping alarmları çalıyor ama tek "
        "bir kullanıcı şikayeti yok. Neler olduğunu anlamamız lazım.",
    ],
    "ospf_mtu_mismatch": [
        "3.3.3.3'teki uygulama sunucusuna kimse erişemiyor; 1.1.1.1'deki diğer sunucu normal. "
        "İki binadan da denedik, sonuç aynı: 3.3.3.3 ulaşılamıyor.",
        "Öğleden sonra bir anda 3.3.3.3'e giden bağlantılar koptu. Diğer sunucular etkilenmedi. "
        "Kimse bir değişiklik yapmadığını söylüyor ama bir şey değişmiş olmalı.",
        "Kritik sunucumuz 3.3.3.3'e erişim yok, monitoring de düşürdü. 1.1.1.1 gayet sağlıklı. "
        "Fiziksel bir sorun görünmüyor, linkler up.",
    ],
}


def load_bank(path: Path = BANK_PATH) -> dict[str, list[str]]:
    """Senaryo bankasini oku: fault_class -> semptom listesi. Yoksa/bozuksa bos dict."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in data.items():
        if k.startswith("_"):                    # _meta gibi metadata anahtarlari atla
            continue
        # iki bicimi de destekle: {sinif: [...]} veya {sinif: {"symptoms": [...]}}
        pool = v.get("symptoms") if isinstance(v, dict) else v
        if isinstance(pool, list) and pool:
            out[k] = [str(s) for s in pool]
    return out


def available_classes() -> set[str]:
    """Semptomu uretilebilen siniflar: banka + sablonlarin birlesimi."""
    return set(TEMPLATES) | set(load_bank(BANK_PATH))


def render(fault_name: str, rng: random.Random) -> str:
    pool = load_bank(BANK_PATH).get(fault_name) or TEMPLATES.get(fault_name)
    if not pool:
        raise KeyError(f"semptom kaynagi yok: {fault_name!r}")
    return rng.choice(pool)


# ---------------------------------------------------------------- placeholder doldurma
#
# Banka semptomlari {host_ip} gibi placeholder'lar tasir; fill() bunlari
# ENJEKSIYONDAN SONRA, GroundTruth'u gorerek doldurur — semptomdaki degerler
# gercek etkiyle CELISMESIN (ornegin bozulan hostun IP'si semptomda gecen IP
# olsun). gt'den turetilemeyenler rng ile spec'ten cekilir.

import re as _re

_USER_NAMES = ["ahmet.kaya", "zeynep.demir", "murat.aydin", "elif.celik", "seda.yilmaz", "burak.tas"]
_APP_NAMES = ["ERP", "CRM", "dosya sunucusu", "muhasebe uygulamasi", "uretim takip sistemi"]


def fill(template: str, spec, gt=None, rng: random.Random | None = None) -> str:
    rng = rng or random.Random(0)
    gts = gt if isinstance(gt, list) else ([gt] if gt else [])
    g0 = gts[0] if gts else None
    hosts = spec.hosts
    leaves = [n for n, nd in spec.ceos_nodes.items() if nd["role"] == "leaf"]

    # gt'nin ima ettigi vlan (root_cause'lari BIZ yazdik — "vlan <id>" bicimi stabil)
    vlan = None
    if g0:
        m = _re.search(r"vlan\s*(\d+)", g0.root_cause, _re.I)
        if m:
            vid = int(m.group(1))
            vlan = next((v for v in spec.vlans if v["id"] == vid), None)

    # etkilenen host: gt.device host ise o; leaf ise ona bagli (ya da vlan'daki) bir host
    host_name = None
    if g0 and g0.device in hosts:
        host_name = g0.device
    elif hosts:
        cands = []
        if g0 and g0.device in spec.ceos_nodes:
            cands = [h for h, hh in hosts.items() if hh["attached"][0] == g0.device]
        if not cands and vlan:
            cands = [h for h, hh in hosts.items() if hh["vlan"] == vlan["id"]]
        host_name = rng.choice(sorted(cands or hosts))
    h = hosts.get(host_name) if host_name else None

    if vlan is None and h:
        vlan = next((v for v in spec.vlans if v["id"] == h["vlan"]), None)
    if vlan is None and spec.vlans:
        vlan = spec.vlans[0]

    # erisilemeyen "sunucu": kok neden bir leaf'teyse onun loopback'i en tutarli aday
    loopbacks = {d: nd["loopback_ip"] for d, nd in spec.ceos_nodes.items()}
    if g0 and g0.device in loopbacks and spec.ceos_nodes[g0.device]["role"] == "leaf":
        server_ip = loopbacks[g0.device]
    else:
        server_ip = rng.choice(sorted(loopbacks.values())) if loopbacks else "10.255.255.1"

    # ikinci sunucu: server_ip'den FARKLI bir loopback (tek loopback varsa ayni kalir)
    other_loops = sorted(v for v in loopbacks.values() if v != server_ip)
    server2_ip = rng.choice(other_loops) if other_loops else server_ip

    # komsu host: secilen hosttan farkli, tercihen ayni vlan'da
    host2_ip = "10.0.0.98"
    if h:
        same_vlan = [hh for nm, hh in hosts.items() if nm != host_name and hh["vlan"] == h["vlan"]]
        others = [hh for nm, hh in hosts.items() if nm != host_name]
        pick = rng.choice(same_vlan or others) if (same_vlan or others) else None
        if pick:
            host2_ip = pick["ip_cidr"].split("/")[0]

    sites = {f"{{site_{c}}}": f"{c.upper()} binası" for c in "abc"}
    # site etiketleri leaf sirasina sabit eslenir (banka sozlesmesi); 3. yoksa B'ye duser
    if len(leaves) < 3:
        sites["{site_c}"] = sites["{site_b}"]

    values = {
        "{host_ip}": (h["ip_cidr"].split("/")[0] if h else "10.0.0.99"),
        "{host2_ip}": host2_ip,
        "{gateway_ip}": (h["gw"] if h else (vlan["gw_ip"] if vlan else "10.0.0.1")),
        "{server_ip}": server_ip,
        "{server2_ip}": server2_ip,
        "{subnet}": (str(vlan["subnet"]) if vlan else "10.0.0.0/24"),
        "{vlan_name}": (str(vlan["name"]) if vlan else "USERS"),
        "{user_name}": rng.choice(_USER_NAMES),
        "{app_name}": rng.choice(_APP_NAMES),
        **sites,
    }
    out = template
    for k, v in values.items():
        out = out.replace(k, v)
    # bilinmeyen placeholder kalirsa kullaniciya suslu parantez sizdirma
    # (desende 0-9 SART: {server2_ip} sizintisi bu eksikten dogdu — 2026-07-16)
    return _re.sub(r"\{[a-z0-9_]+\}", "ilgili sistem", out)
