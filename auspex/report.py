"""Teshis raporu: kok neden + kanit zinciri + onerilen duzeltme (insan uygular)."""

import json
import time


def render(trace, contract_version: str = "v1") -> str:
    d = trace.diagnosis or {}
    lines = [
        "=" * 62,
        "  AUSPEX TESHIS RAPORU",
        f"  {time.strftime('%Y-%m-%d %H:%M:%S')} | model: {trace.model} | sozlesme: {contract_version}",
        "=" * 62,
        "",
        f"Sikayet : {trace.symptom}",
        "",
    ]
    if trace.error and not d:
        lines += [f"SONUC   : TESHIS URETILEMEDI — {trace.error}", ""]
    else:
        lines += [
            f"SONUC   : {d.get('fault_class', '?')}",
            f"Cihaz   : {d.get('device', '?')}",
            f"Kok neden: {d.get('root_cause', '?')}",
            "",
            "Onerilen duzeltme (OTOMATIK UYGULANMAZ — insan onayi gerekir):",
            *[f"    {c}" for c in d.get("fix_commands", []) or ["(yok)"]],
            "",
        ]
    lines.append(f"Kanit zinciri ({trace.n_tool_calls} arac cagrisi, "
                 f"{trace.num_turns} tur, {trace.duration_s:.0f}s):")
    step = 0
    for e in trace.events:
        m = e.get("message", {})
        if m.get("role") == "assistant":
            for c in m.get("tool_calls") or []:
                fn = c.get("function", {})
                step += 1
                lines.append(f"  {step:2d}. {fn.get('name', '?').removeprefix('mcp__netagent__')}"
                             f"({json.dumps(fn.get('arguments', {}), ensure_ascii=False)[1:-1]})")
    lines += ["", "=" * 62]
    return "\n".join(lines)
