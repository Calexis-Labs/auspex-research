"""Kestrel v1 egitimi — Qwen3-8B QLoRA (RunPod A100, tek seans).

Veri: /workspace/kestrel/data/{train,val}.jsonl (messages formati) +
tools-v1.json (sozlesme — arac tanimlari template'e buradan girer).
Recete (Mac'te 1.7B ile kanitlandi): chat template + tools, response-only loss,
r=32, lr 1e-4 cosine, 3 epoch, epoch basi checkpoint + val loss.
"""

import json

MAX_TOKENS = 24576
DATA = "/workspace/kestrel/data"
OUT = "/workspace/kestrel/out"

from unsloth import FastLanguageModel  # noqa: E402 (import sirasi unsloth geregi)
import torch  # noqa: E402
from datasets import Dataset  # noqa: E402
from trl import SFTConfig, SFTTrainer  # noqa: E402
from unsloth.chat_templates import train_on_responses_only  # noqa: E402

model, tokenizer = FastLanguageModel.from_pretrained(
    "unsloth/Qwen3-8B", max_seq_length=MAX_TOKENS, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(
    model, r=32, lora_alpha=64, lora_dropout=0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth", random_state=0)

contract = json.load(open(f"{DATA}/tools-v1.json"))
TOOLS = [{"type": "function", "function": {
    "name": t["name"], "description": t["description"],
    "parameters": t["parameters"]}} for t in contract["tools"]]


def to_tpl(messages):
    out = []
    for m in messages:
        if m["role"] == "assistant":
            n = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                n["tool_calls"] = [{"type": "function", "function": {
                    "name": c["name"], "arguments": c.get("arguments") or {}}}
                    for c in m["tool_calls"]]
            out.append(n)
        elif m["role"] == "tool":
            out.append({"role": "tool", "name": m.get("name", ""),
                        "content": str(m.get("content", ""))})
        else:
            out.append({"role": m["role"], "content": m.get("content", "")})
    return out


def load(name):
    texts, dropped = [], 0
    for line in open(f"{DATA}/{name}.jsonl"):
        r = json.loads(line)
        t = tokenizer.apply_chat_template(to_tpl(r["messages"]), tools=TOOLS,
                                          tokenize=False)
        if len(tokenizer(t).input_ids) > MAX_TOKENS:
            dropped += 1
            continue
        texts.append(t)
    print(f"{name}: {len(texts)} ornek ({dropped} uzun atildi)")
    return Dataset.from_dict({"text": texts})


train_ds, val_ds = load("train"), load("val")

trainer = SFTTrainer(
    model=model, tokenizer=tokenizer,
    train_dataset=train_ds, eval_dataset=val_ds,
    args=SFTConfig(
        # SFTConfig'te ad max_length — TrainingArguments'a max_seq_length
        # gecirince sessizce 1024'e dusuyordu (ilk cokusun nedeni)
        max_length=MAX_TOKENS, dataset_text_field="text", packing=False,
        output_dir=OUT, per_device_train_batch_size=1,
        gradient_accumulation_steps=8, num_train_epochs=3,
        learning_rate=1e-4, lr_scheduler_type="cosine", warmup_steps=20,
        logging_steps=10, eval_strategy="epoch", save_strategy="epoch",
        save_total_limit=3, bf16=True, optim="adamw_8bit", seed=0,
        report_to="none", load_best_model_at_end=True,
        metric_for_best_model="eval_loss", per_device_eval_batch_size=1,
    ),
)
trainer = train_on_responses_only(
    trainer,
    instruction_part="<|im_start|>user\n",
    response_part="<|im_start|>assistant\n",
)
print("egitim basliyor...")
trainer.train()
print("EGITIM BITTI — en iyi checkpoint kaydediliyor")
model.save_pretrained(f"{OUT}/kestrel_lora_best")
tokenizer.save_pretrained(f"{OUT}/kestrel_lora_best")
print("TAMAM: /workspace/kestrel/out/kestrel_lora_best")
