"""Salt-okunur komut allowlist'i — guvenligin ZORLANDIGI katman.

Uc kapi, fail-closed; herhangi biri dusurse komut aga hic cikmaz:
  1. charset: izinli kume disinda tek karakter bile varsa red
  2. deny-verb: ilk token os'un okuma fiili degilse red; yasakli token gecerse red
  3. anchored allowlist: komut, os tablosundaki bir kalibin TAMAMINA uymali

`| json` gibi son ekler burada ASLA kabul edilmez — onlari transport,
dogrulamadan SONRA kendisi ekler.
"""

import re
from dataclasses import dataclass


class CommandNotAllowed(Exception):
    """Komut salt-okunur allowlist'ten gecemedi."""


@dataclass(frozen=True)
class CanonicalCommand:
    os: str
    text: str


# Katman 1 — izinli karakter kumesi (whitelist; pipe/;/$/quote/unicode hepsi disarida)
_ALLOWED_CHARS = re.compile(r"^[a-z0-9 ./:_-]+$")

# Katman 2 — okuma fiilleri ve yasakli token'lar (token bazli: "neighbor" icindeki
# "no" gibi substring'ler tetiklemez)
_READ_VERBS = {
    "eos": {"show", "ping"},
    "linux": {"ip", "ping"},
    "frr_vtysh": {"show", "ping"},
}
_DENY_TOKENS = {
    "configure", "config", "enable", "reload", "write", "copy", "erase",
    "delete", "bash", "clear", "no", "shutdown", "boot", "event-handler",
    "scp", "curl", "wget", "add", "replace", "set", "del", "flush",
}

# Katman 3 — anchored kaliplar (fullmatch)
_IP = r"[0-9]{1,3}(\.[0-9]{1,3}){3}"
_IF = r"(ethernet|management|loopback|vlan|port-channel)[0-9/]{1,8}"

_ALLOWED_PATTERNS: dict[str, list[re.Pattern]] = {
    "eos": [
        re.compile(p)
        for p in [
            r"show version",
            r"show interfaces status",
            rf"show interfaces {_IF}",
            r"show vlan",
            r"show interfaces trunk",
            r"show ip interface brief",
            rf"show ip route( {_IP}(/[0-9]{{1,2}})?)?",
            r"show ip ospf neighbor( detail)?",
            r"show lldp neighbors( detail)?",
            r"show ip access-lists",
            r"show running-config section [a-z0-9 ./:_-]{1,40}",
            rf"ping {_IP}( repeat [1-5])?( source [a-z0-9/.]{{1,20}})?",
        ]
    ],
    "linux": [
        re.compile(p)
        for p in [
            r"ip -j (addr|route|link) show",
            rf"ping -c [1-5]( -w [1-5])? {_IP}",
        ]
    ],
    # FRR fallback (vtysh -c ile calisir; minimum kume)
    "frr_vtysh": [
        re.compile(p)
        for p in [
            r"show version",
            r"show interface",
            r"show ip route",
            r"show ip ospf neighbor",
        ]
    ],
}


def validate_command(os: str, raw: str) -> CanonicalCommand:
    if os not in _ALLOWED_PATTERNS:
        raise CommandNotAllowed(f"bilinmeyen os: {os!r}")

    # 1a: ham girdi ASCII olmali — nbsp/zero-width gibi karakterler normalizasyonda
    # sessizce kaybolmadan ONCE reddedilir
    if not raw.isascii():
        raise CommandNotAllowed(f"ascii disi karakter: {raw!r}")

    text = " ".join(raw.lower().split())
    if not text:
        raise CommandNotAllowed("bos komut")

    # 1b: charset
    if not _ALLOWED_CHARS.fullmatch(text):
        raise CommandNotAllowed(f"izinli karakter kumesi disinda: {raw!r}")

    # 2: deny-verb
    tokens = text.split()
    if tokens[0] not in _READ_VERBS[os]:
        raise CommandNotAllowed(f"okuma fiiliyle baslamiyor: {raw!r}")
    denied = _DENY_TOKENS.intersection(tokens)
    if denied:
        raise CommandNotAllowed(f"yasakli token {sorted(denied)}: {raw!r}")

    # 3: anchored allowlist
    for pattern in _ALLOWED_PATTERNS[os]:
        if pattern.fullmatch(text):
            return CanonicalCommand(os=os, text=text)
    raise CommandNotAllowed(f"allowlist'te yok ({os}): {raw!r}")
