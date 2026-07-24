"""dataset_local/*.jsonl -> Qwen3 chat-template'li duz metin ({"text": ...}).

Hem MLX mini kaniti (Asama B) hem GPU egitimi (Asama C) ayni donusumu kullanir:
  - assistant.tool_calls -> OpenAI bicimi ({"type":"function","function":{...}})
  - bos thinking alanlari atilir
  - tools listesi (tools/schema.TOOLS, mcp__netagent__ onekli) template'e verilir
  - tokenizer.apply_chat_template(..., tools=...) ile TEK dogruluk kaynagi:
    servis zamaninda Ollama da ayni template'i kullanir.

Kullanim: .venv/bin/python prepare_qwen.py --limit 60 --out mlx_data
  (limit yoksa tumu; mlx_lm.lora 'text' formatini dogrudan okur)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from tools.schema import TOOLS  # noqa: E402

PREFIX = "mcp__netagent__"
MODEL_TOKENIZER = "Qwen/Qwen3-8B"

def qwen_tools() -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": PREFIX + t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        }} for t in TOOLS
    ]


def to_template_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m["role"]
        if role == "assistant":
            new = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                new["tool_calls"] = [
                    {"type": "function", "function": {
                        "name": c["name"], "arguments": c.get("arguments") or {}}}
                    for c in m["tool_calls"]
                ]
            out.append(new)
        elif role == "tool":
            out.append({"role": "tool", "name": m.get("name", ""),
                        "content": str(m.get("content", ""))})
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).parents[1] / "dataset_local"))
    ap.add_argument("--out", default=str(Path(__file__).parent / "mlx_data"))
    ap.add_argument("--limit", type=int, default=0, help="0 = tumu")
    ap.add_argument("--max-tokens", type=int, default=16384)
    args = ap.parse_args()

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL_TOKENIZER)
    tools = qwen_tools()

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    stats = {}
    for name in ("train", "val"):
        src = Path(args.data) / f"{name}.jsonl"
        rows = [json.loads(l) for l in src.open() if l.strip()]
        if args.limit:
            rows = rows[: args.limit if name == "train" else max(args.limit // 6, 4)]
        lens, kept, skipped = [], 0, 0
        # mlx_lm sozlesmesi: valid.jsonl adi
        dst = out_dir / ("valid.jsonl" if name == "val" else "train.jsonl")
        with dst.open("w") as f:
            for r in rows:
                text = tok.apply_chat_template(
                    to_template_messages(r["messages"]),
                    tools=tools, tokenize=False)
                n_tok = len(tok(text).input_ids)
                if n_tok > args.max_tokens:
                    skipped += 1
                    continue
                lens.append(n_tok)
                kept += 1
                f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
        lens.sort()
        stats[name] = {"kept": kept, "skipped_uzun": skipped,
                       "tok_p50": lens[len(lens)//2] if lens else 0,
                       "tok_max": lens[-1] if lens else 0}
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
