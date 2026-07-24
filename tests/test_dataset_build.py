"""Ders kitabi dizgisi sozlesmesi:
- ToolSearch cagrisi + tool_reference sonucu AYIKLANIR
- bos thinking atlanir, dolu thinking korunur
- ardisi assistant eventleri tek tura birlesir
- tool_result dogru arac adina eslesir
- submit_diagnosis olmayan trace reddedilir
- split: sinif dengeli, iki taraf kesisimsiz
"""

import random

from datagen.dataset_build import (
    SUBMIT_TOOL,
    events_to_messages,
    split_examples,
    validate_messages,
)


def _a(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


def _tu(name, tid, **kw):
    return {"type": "tool_use", "name": name, "id": tid, "input": kw}


def _tr(tid, content):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": content}]}}


def test_toolsearch_stripped_and_results_mapped():
    events = [
        _a({"type": "thinking", "thinking": " "}),                 # bos -> atla
        _a(_tu("ToolSearch", "t1", query="mcp")),
        _tr("t1", [{"type": "tool_reference", "tool_name": "x"}]),
        _a(_tu("mcp__netagent__get_topology", "t2")),
        _tr("t2", '{"result": "ok"}'),
        _a({"type": "text", "text": "Teshis tamam."},
           _tu(SUBMIT_TOOL, "t3", device="leaf1", fault_class="svi_down")),
        _tr("t3", "kabul"),
    ]
    msgs = events_to_messages(events)
    names = [(m["role"], m.get("name") or [c["name"] for c in m.get("tool_calls", [])]) for m in msgs]
    assert ("assistant", ["mcp__netagent__get_topology"]) in names
    assert not any("ToolSearch" in str(n) for _, n in names)
    tools = [m for m in msgs if m["role"] == "tool"]
    assert [t["name"] for t in tools] == ["mcp__netagent__get_topology", SUBMIT_TOOL]
    assert validate_messages(msgs) is None


def test_consecutive_assistant_events_merge():
    events = [
        _a({"type": "text", "text": "Once bakalim."}),
        _a(_tu("mcp__netagent__get_vlans", "t1", device="leaf1")),
        _tr("t1", "sonuc"),
        _a(_tu(SUBMIT_TOOL, "t2")),
        _tr("t2", "ok"),
    ]
    msgs = events_to_messages(events)
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "Once bakalim."
    assert msgs[0]["tool_calls"][0]["name"] == "mcp__netagent__get_vlans"
    # text + tool_use TEK mesajda; sonra tool sonucu
    assert msgs[1]["role"] == "tool"


def test_nonempty_thinking_preserved():
    events = [
        _a({"type": "thinking", "thinking": "hipotez: gateway yanlis"}),
        _a(_tu(SUBMIT_TOOL, "t1")),
        _tr("t1", "ok"),
    ]
    msgs = events_to_messages(events)
    assert msgs[0].get("thinking") == "hipotez: gateway yanlis"


def test_missing_submit_rejected():
    events = [_a(_tu("mcp__netagent__ping_from_device", "t1")), _tr("t1", "ok")]
    assert validate_messages(events_to_messages(events)) is not None


def test_split_is_class_balanced_and_disjoint():
    exs = [{"scenario_id": f"s{i}-{cls}", "fault": cls, "approx_tokens": 10}
           for cls in ("a_cls", "b_cls") for i in range(20)]
    train, val = split_examples(exs, random.Random(0))
    tids = {e["scenario_id"] for e in train}
    vids = {e["scenario_id"] for e in val}
    assert not (tids & vids)
    assert len(val) == 4                      # 20*0.08=1.6 -> round=2 per sinif
    from collections import Counter
    assert Counter(e["fault"] for e in val) == {"a_cls": 2, "b_cls": 2}


def test_tiny_class_gets_no_val():
    exs = [{"scenario_id": f"s{i}-c", "fault": "c_cls", "approx_tokens": 10} for i in range(3)]
    train, val = split_examples(exs, random.Random(0))
    assert len(val) == 0 and len(train) == 3
