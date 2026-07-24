"""Semptom placeholder doldurma sozlesmesi.

2026-07-16 dersi: {server2_ip} bankada vardi ama fill() tanimiyordu VE kacak
deseni rakamsizdi ([a-z_]) — placeholder ciplak halde teacher'a sizdi, model
"yer tutucu doldurulmamis" diye teshis kurdu. Bu dosya o sinifi hatayi kalici
olarak yakalar: BANKADAKI HER SABLON, birden cok toplojide, kalinti birakmadan
dolmali.
"""

import random
import re

import pytest

from datagen import symptoms
from lab.faults import FAULTS, GroundTruth
from lab.topo import build_spec

BANK = symptoms.load_bank()
SPECS = [build_spec(s) for s in (0, 40, 43, 59, 123)]

_BRACE = re.compile(r"[{}]")


def _gt_for(cls: str, spec):
    """Verifier'a gerek yok — fill() icin makul bir GT ornegi uret."""
    device = sorted(spec.ceos_nodes)[0]
    return GroundTruth(device=device, fault_class=cls, root_cause=f"test {cls}",
                       fix_commands=["x"], key_terms=[])


@pytest.mark.parametrize("cls", sorted(BANK))
def test_every_bank_template_fills_clean(cls):
    for spec in SPECS:
        gt = _gt_for(cls, spec)
        for i, tpl in enumerate(BANK[cls]):
            out = symptoms.fill(tpl, spec, gt, random.Random(i))
            assert not _BRACE.search(out), (
                f"{cls}[{i}] kalinti birakti: {out[:120]!r}")


def test_server2_differs_from_server_when_possible():
    spec = build_spec(0)
    outs = {
        symptoms.fill("{server_ip} ve {server2_ip}", spec, None, random.Random(s))
        for s in range(8)
    }
    # en az bir cekiliste iki sunucu farkli olmali (spec'te >1 loopback var)
    assert any(len(set(o.split(" ve "))) == 2 for o in outs)


def test_host2_differs_from_host():
    spec = build_spec(0)
    for s in range(8):
        out = symptoms.fill("{host_ip}|{host2_ip}", spec, None, random.Random(s))
        a, b = out.split("|")
        if len(spec.hosts) >= 2:
            assert a != b


def test_unknown_placeholder_with_digits_is_scrubbed():
    spec = build_spec(0)
    out = symptoms.fill("bkz {mystery9_thing} calismiyor", spec, None, random.Random(0))
    assert "{" not in out and "ilgili sistem" in out
