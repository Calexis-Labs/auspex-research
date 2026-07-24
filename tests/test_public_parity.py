"""Public auspex-cli <-> ozel repo parite bekcisi (Sozlesme Ilkesi 0).

Public CLI'daki prompt/araclar/dongu stringleri, egitim boru hattindakiyle
BIREBIR ayni olmali — bu test, iki repo arasindaki tek koprudur ve OPSIYONEL
DEGILDIR: AUSPEX_CLI_PATH tanimliysa her koşuda calisir (Mac'te varsayilan
konum otomatik denenir).

Kosum: AUSPEX_CLI_PATH=/path/to/auspex-cli uv run pytest tests/test_public_parity.py
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_DEFAULT = Path("/Volumes/T7/My Projects/auspex-cli")
PUBLIC = Path(os.environ.get("AUSPEX_CLI_PATH") or _DEFAULT)

pytestmark = pytest.mark.skipif(
    not PUBLIC.exists(),
    reason="public auspex-cli reposu yok (AUSPEX_CLI_PATH ver)",
)


def _load_standalone(name: str, rel: str):
    """Public repodan TEK dosyayi, ozel repodaki auspex paketiyle cakismadan yukle."""
    spec = importlib.util.spec_from_file_location(name, PUBLIC / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def public_prompt():
    return _load_standalone("public_prompt", "auspex/prompt.py")


# ---------------------------------------------------------------- prompt paritesi

def test_diagnostic_prompt_is_byte_identical(public_prompt):
    from datagen.teacher import DIAGNOSTIC_PROMPT
    assert public_prompt.DIAGNOSTIC_PROMPT == DIAGNOSTIC_PROMPT


def test_fault_classes_match_lab_registry(public_prompt):
    from lab.faults import FAULT_CLASSES
    assert public_prompt.FAULT_CLASSES == list(FAULT_CLASSES), (
        "lab.faults degisti (yeni sinif?) ama public FAULT_CLASSES guncellenmedi "
        "— yeni sinif = yeni egitim turu + sozlesme surumu"
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_build_prompt_output_identical_for_lab_specs(public_prompt, seed):
    from datagen.teacher import build_prompt
    from lab.topo import build_spec
    spec = build_spec(seed)
    symptom = f"hosta sunuculara erisemiyor (seed {seed})"
    # public build_prompt ayni duck-type'i kabul eder (ceos_nodes/hosts)
    assert public_prompt.build_prompt(symptom, spec) == build_prompt(symptom, spec)


# ---------------------------------------------------------------- arac paritesi

def _public_json(code: str) -> dict:
    out = subprocess.run(
        ["uv", "run", "python", "-c", code],
        capture_output=True, text=True, cwd=PUBLIC, check=True,
    )
    return json.loads(out.stdout)


def test_tool_contract_identical():
    from auspex.contract.freeze import build_contract
    theirs = _public_json(
        "import json; from auspex.contract.freeze import build_contract; "
        "print(json.dumps(build_contract()))")
    assert theirs == build_contract(), (
        "public arac sozlesmesi ozel repodan sapmis — surumsuz degisiklik yasak"
    )


def test_ollama_tools_and_serving_params_identical():
    from datagen.student import ollama_tools
    theirs = _public_json(
        "import json; from auspex.core.ollama import ollama_tools, chat_payload; "
        "p = chat_payload('kestrel:v1', []); "
        "print(json.dumps({'tools': ollama_tools(), 'think': p['think'], "
        "'temp': p['options']['temperature'], 'ctx': p['options']['num_ctx'], "
        "'keep_alive': p['keep_alive'], 'stream': p['stream']}))")
    assert theirs["tools"] == ollama_tools()
    # sinavda dondurulan servis degerleri (ozel varsayilan 16384 DEGIL — sinav 24576 kostu)
    assert theirs == {**theirs, "think": True, "temp": 0.6, "ctx": 24576,
                      "keep_alive": "15m", "stream": False}


# ---------------------------------------------------------------- dongu stringleri

def test_loop_strings_byte_identical(monkeypatch):
    """Ozel dongunun CALISMA ANINDA urettigi mesajlar public sabitlerle ayni olmali.

    Kaynak-metin taramasi yerine dongu gercekten kosturulur: tur-limiti mesaji
    ve submit yaniti trace.events'ten yakalanir (satir bolunmesi gibi kaynak
    bicimlendirmesi pariteyi etkilemez — bayt paritesi runtime stringindedir).
    """
    from datagen import student
    monkeypatch.setenv("NETAGENT_TOPO_SEED", "0")
    loop_mod = _load_standalone_loop()
    assert loop_mod["NUDGE"] == student.NUDGE
    assert loop_mod["PREFIX"] == student.PREFIX
    assert loop_mod["MAX_NUDGES"] == student.MAX_NUDGES

    class Ex:
        def dispatch(self, name, args):
            return '{"result": "ok"}'

    def tool_call(name, **args):
        return {"function": {"name": student.PREFIX + name, "arguments": args}}

    # max_turns=5 -> tur-limiti mesaji turn==1'de eklenir; son turda submit
    turns = iter(range(5))

    def chat(messages):
        t = next(turns)
        if t < 4:
            return {"message": {"role": "assistant", "tool_calls": [tool_call("get_topology")]}}
        return {"message": {"role": "assistant", "tool_calls": [
            tool_call("submit_diagnosis", device="leaf1", fault_class="no_fault",
                      root_cause="x", fix_commands=[])]}}

    trace = student.run_student_rollout("semptom", max_turns=5, chat=chat, executor=Ex())
    user_msgs = [e["message"]["content"] for e in trace.events
                 if e["message"].get("role") == "user"]
    tool_msgs = [e["message"]["content"] for e in trace.events
                 if e["message"].get("role") == "tool"]
    assert loop_mod["TURN_LIMIT_MSG"] in user_msgs, (
        "public tur-limiti mesaji, ozel dongunun urettigiyle ayni degil")
    assert loop_mod["SUBMIT_REPLY"] in tool_msgs, (
        "public submit yaniti, ozel dongunun urettigiyle ayni degil")


def _load_standalone_loop() -> dict:
    out = subprocess.run(
        ["uv", "run", "python", "-c",
         "import json; from auspex.core import loop; from auspex.core.ollama import PREFIX; "
         "print(json.dumps({'NUDGE': loop.NUDGE, 'TURN_LIMIT_MSG': loop.TURN_LIMIT_MSG, "
         "'SUBMIT_REPLY': loop.SUBMIT_REPLY, 'PREFIX': PREFIX, 'MAX_NUDGES': loop.MAX_NUDGES}))"],
        capture_output=True, text=True, cwd=PUBLIC, check=True,
    )
    return json.loads(out.stdout)


# ---------------------------------------------------------------- modelfile paritesi

def test_modelfile_template_matches_shipped_model():
    """Public sablon, /Volumes/T7/kestrel/Modelfile'in FROM'suz govdesiyle ayni olmali."""
    shipped = Path("/Volumes/T7/kestrel/Modelfile")
    if not shipped.exists():
        pytest.skip("paketlenmis Modelfile bu makinede yok")
    body = "".join(shipped.read_text().splitlines(keepends=True)[2:])  # bos satir + FROM atla
    template = (PUBLIC / "auspex/setup/modelfile.template").read_text()
    assert template == body
