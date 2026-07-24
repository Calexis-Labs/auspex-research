"""Tool sozlesmesini dondur: tools-v1.json — Kestrel <-> Auspex uyum garantisi.

Ilke (Auspex plani md.0): uretimdeki tool seti, egitim verisindekiyle BIREBIR
ayni olmali. Bu script tek dogruluk kaynagindan (tools/schema.py TOOLS +
mcp__netagent__ onek kurali) versiyonlu sozlesme uretir. schema.py degisir ama
sozlesme yeniden uretilmezse test_contract kirmiziya duser.

Kullanim: uv run python -m auspex.contract.freeze
"""

import hashlib
import json
import sys
from pathlib import Path

from tools.schema import TOOLS

PREFIX = "mcp__netagent__"        # datagen/student.py ve dataset ile ayni
VERSION = "v1"
OUT = Path(__file__).parent / f"tools-{VERSION}.json"


def build_contract() -> dict:
    tools = [
        {
            "name": PREFIX + t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        }
        for t in TOOLS
    ]
    body = {"version": VERSION, "prefix": PREFIX, "tools": tools}
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return {**body, "sha256": digest}


def main() -> int:
    contract = build_contract()
    OUT.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n")
    print(f"sozlesme yazildi: {OUT.name} | {len(contract['tools'])} arac | "
          f"sha256={contract['sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
