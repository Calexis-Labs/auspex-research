"""Ogrenci rollout'u — yerel model (Ollama, Mac'te) ayni araclarla teshis yapar.

teacher.run_rollout ile AYNI arayuz: (symptom, model=...) -> Trace. Boylece
lanes.run_scenario/run_lane hic degismeden ogrenciyle calisir (deploy, inject,
verify, revert hepsi ayni boru hattindan).

Tutarlilik sozlesmeleri:
  - Prompt: teacher.build_prompt (birebir ayni metin).
  - Arac adlari: egitim setiyle ayni "mcp__netagent__X" bicimi.
  - Arac yuzeyi: tools.schema.ToolExecutor (allowlist dahil ayni yol).

Model sunucusu: NETAGENT_STUDENT_URL (varsayilan Mac Mini http://192.168.1.180:11434).
Lab host'unda calisir (araclar lab'a lokal, model LAN uzerinden).
"""

import json
import os
import time
import urllib.request

from datagen.teacher import Trace, _spec_from_env, build_prompt
from tools.schema import TOOLS, ToolExecutor
from tools.transport import HostExecTransport, ReadOnlyTransport

PREFIX = "mcp__netagent__"
SUBMIT = "submit_diagnosis"
DEFAULT_URL = "http://192.168.1.49:11434"   # Mac Mini (tasinma sonrasi; NETAGENT_STUDENT_URL ile ezilir)
MAX_NUDGES = 2

NUDGE = ("Araç çağrısı yapmadın. Teşhise devam etmek için bir araç çağır; "
         "kök nedeni bulduysan submit_diagnosis ile bitir.")


def ollama_tools() -> list[dict]:
    """schema.TOOLS -> Ollama tools formati, egitimle ayni onekli adlar."""
    return [
        {
            "type": "function",
            "function": {
                "name": PREFIX + t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOLS
    ]


def _http_chat(url: str, payload: dict, timeout_s: int) -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return json.loads(r.read())


def run_student_rollout(
    symptom: str,
    model: str = "qwen3:8b",
    max_turns: int = 60,          # think=True model cok arastiriyor; tur-emniyeti -4'te devrede
    timeout_s: int = 900,
    chat=None,
    executor: ToolExecutor | None = None,
) -> Trace:
    """Tek teshis dongusu. chat/executor parametreleri test enjeksiyonu icindir."""
    spec = _spec_from_env()
    if executor is None:
        inv = spec.inventory()
        executor = ToolExecutor(inv, eos=ReadOnlyTransport(inv), host=HostExecTransport(inv))
    url = os.environ.get("NETAGENT_STUDENT_URL", DEFAULT_URL)
    if chat is None:
        def chat(messages):
            return _http_chat(url, {
                "model": model,
                "messages": messages,
                "tools": ollama_tools(),
                "stream": False,
                # Qwen3 hibrit reasoning ACIK (model dusunerek arac cagiriyor).
                # KRITIK: Ollama modeli EGITIM sablonuyla paketlenmeli (unsloth
                # Modelfile), resmi qwen3 sablonuyla DEGIL — aksi halde model
                # 16 jeton uretip bos donuyor (2026-07-22, template uyumsuzlugu).
                # Auspex ilkesi: cikarim sablonu = egitim sablonu.
                "think": os.environ.get("NETAGENT_STUDENT_THINK", "1") == "1",
                "options": {
                    # 0 = deterministik ama fine-tune tekrar cokusune acik
                    # (kestrel 35x ping dongusu, 2026-07-22) — Qwen3 onerisi 0.6
                    "temperature": float(os.environ.get("NETAGENT_STUDENT_TEMP", "0.6")),
                    "num_ctx": int(os.environ.get("NETAGENT_STUDENT_CTX", "16384")),
                    # buyuk model 24GB Mac'e tam sigmiyorsa kismi CPU-yukleme
                    # (orn. gemma4:26b icin 24) — bos birakilirsa ollama karar verir
                    **({"num_gpu": int(os.environ["NETAGENT_STUDENT_NUM_GPU"])}
                       if os.environ.get("NETAGENT_STUDENT_NUM_GPU") else {}),
                },
                "keep_alive": "15m",
            }, timeout_s)

    trace = Trace(symptom=symptom, model=model)
    messages: list[dict] = [{"role": "user", "content": build_prompt(symptom, spec)}]
    start = time.monotonic()
    nudges = 0

    for turn in range(max_turns):
        try:
            resp = chat(messages)
        except Exception as e:
            trace.error = f"model cagrisi basarisiz (tur {turn}): {e}"[:500]
            break
        msg = resp.get("message") or {}
        messages.append(msg)
        trace.num_turns = turn + 1
        tokjs = {k: resp[k] for k in ("prompt_eval_count", "eval_count") if k in resp}
        for k, v in tokjs.items():
            trace.usage[k] = trace.usage.get(k, 0) + v

        calls = msg.get("tool_calls") or []
        if not calls:
            if trace.diagnosis is not None:
                break                                   # teshis verildi, kapanis metni
            nudges += 1
            if nudges > MAX_NUDGES:
                trace.error = "arac cagrisi yok — model teshis dongusune girmedi"
                break
            messages.append({"role": "user", "content": NUDGE})
            continue

        # tur limiti yaklasirken teshise zorla (kacak dongu emniyeti — Auspex katmani)
        if trace.diagnosis is None and turn == max_turns - 4:
            messages.append({"role": "user", "content":
                "Tur limitin dolmak üzere. Yeni araç çağırma; eldeki kanıtlarla "
                "EN OLASI teşhisi submit_diagnosis ile HEMEN gönder."})
        done = False
        for c in calls:
            fn = c.get("function") or {}
            name = (fn.get("name") or "").removeprefix(PREFIX)
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            trace.n_tool_calls += 1
            if name == SUBMIT:
                trace.diagnosis = args
                messages.append({"role": "tool", "tool_name": PREFIX + name,
                                 "content": "Teşhis kaydedildi. Oturum kapatılıyor."})
                done = True
                continue
            result = executor.dispatch(name, args)
            messages.append({"role": "tool", "tool_name": PREFIX + name, "content": str(result)})
        if done:
            break

    if trace.diagnosis is None and not trace.error:
        trace.error = f"submit_diagnosis cagrilmadi ({max_turns} tur doldu)"
    trace.duration_s = time.monotonic() - start
    trace.events = [{"type": "chat", "message": m} for m in messages]
    return trace


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit('kullanim: python -m datagen.student "<semptom>" [model]')
    t = run_student_rollout(sys.argv[1], model=sys.argv[2] if len(sys.argv) > 2 else "qwen3:8b")
    print(json.dumps({"diagnosis": t.diagnosis, "n_tool_calls": t.n_tool_calls,
                      "num_turns": t.num_turns, "usage": t.usage,
                      "duration_s": round(t.duration_s, 1), "error": t.error},
                     indent=2, ensure_ascii=False))
