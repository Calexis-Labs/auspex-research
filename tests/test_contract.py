"""Sozlesme bekcisi (Auspex ilke 0):
- tools-v1.json, schema.py'dan uretilenle AYNI olmali (surumsuz degisiklik yasak)
- sozlesmedeki adlar, egitim verisinin fiili tool adlariyla ortusmeli
"""

import json
from pathlib import Path

from auspex.contract.freeze import OUT, build_contract

DATASET = Path(__file__).parents[1] / "dataset_local" / "train.jsonl"


def test_frozen_contract_matches_schema():
    assert OUT.exists(), "sozlesme uretilmemis: uv run python -m auspex.contract.freeze"
    frozen = json.loads(OUT.read_text())
    fresh = build_contract()
    assert frozen == fresh, (
        "tools/schema.py degisti ama sozlesme yeniden uretilmedi/surumlenmedi — "
        "ILKE: sozlesme degisirse model yeniden egitilir; once bunu kararlastir"
    )


def test_contract_covers_training_data_tool_names():
    if not DATASET.exists():
        import pytest
        pytest.skip("dataset_local yok (yalniz Mac'te dogrulanir)")
    contract_names = {t["name"] for t in build_contract()["tools"]}
    used = set()
    with DATASET.open() as f:
        for i, line in enumerate(f):
            if i >= 200:                      # ilk 200 ders yeterli orneklem
                break
            for m in json.loads(line)["messages"]:
                for c in m.get("tool_calls", []) or []:
                    used.add(c["name"])
    assert used, "egitim verisinde tool cagrisi bulunamadi"
    assert used <= contract_names, f"egitim verisinde sozlesme disi arac: {used - contract_names}"
