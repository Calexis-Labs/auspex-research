"""Ogrenci rollout sozlesmesi (model/ag olmadan, sahte chat ile):
- arac cagrisi -> executor.dispatch dogru ada/argumana gider, sonuc tool mesaji olur
- submit_diagnosis donguyu bitirir ve Trace.diagnosis dolar
- arac cagirmayan model 2 durtmeden sonra hata ile biter
- arac adlari egitim setiyle ayni onekte (mcp__netagent__)
"""

import pytest

from datagen.student import MAX_NUDGES, PREFIX, ollama_tools, run_student_rollout


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def dispatch(self, name, args):
        self.calls.append((name, args))
        return '{"result": "ok"}'


def _call(name, **args):
    return {"function": {"name": PREFIX + name, "arguments": args}}


def test_tool_names_are_prefixed_like_training_data():
    names = [t["function"]["name"] for t in ollama_tools()]
    assert all(n.startswith(PREFIX) for n in names)
    assert PREFIX + "submit_diagnosis" in names
    assert PREFIX + "get_topology" in names


def test_loop_dispatches_and_submits(monkeypatch):
    monkeypatch.setenv("NETAGENT_TOPO_SEED", "0")
    ex = FakeExecutor()
    script = iter([
        {"message": {"role": "assistant", "tool_calls": [_call("get_topology")]},
         "prompt_eval_count": 100, "eval_count": 20},
        {"message": {"role": "assistant", "tool_calls": [
            _call("submit_diagnosis", device="leaf1", fault_class="svi_down",
                  root_cause="x", fix_commands=["y"])]}},
    ])
    t = run_student_rollout("semptom", chat=lambda m: next(script), executor=ex)
    assert t.error is None
    assert t.diagnosis["fault_class"] == "svi_down"
    assert ex.calls == [("get_topology", {})]
    assert t.n_tool_calls == 2
    assert t.usage["prompt_eval_count"] == 100


def test_text_only_model_gets_nudged_then_fails(monkeypatch):
    monkeypatch.setenv("NETAGENT_TOPO_SEED", "0")
    n = {"count": 0}

    def chat(messages):
        n["count"] += 1
        return {"message": {"role": "assistant", "content": "hmm dusunuyorum"}}

    t = run_student_rollout("semptom", chat=chat, executor=FakeExecutor())
    assert t.diagnosis is None
    assert "arac cagrisi yok" in t.error
    assert n["count"] == MAX_NUDGES + 1


def test_string_arguments_are_parsed(monkeypatch):
    monkeypatch.setenv("NETAGENT_TOPO_SEED", "0")
    ex = FakeExecutor()
    script = iter([
        {"message": {"role": "assistant", "tool_calls": [
            {"function": {"name": PREFIX + "get_vlans",
                          "arguments": '{"device": "leaf1"}'}}]}},
        {"message": {"role": "assistant", "tool_calls": [
            _call("submit_diagnosis", device="leaf1", fault_class="no_fault",
                  root_cause="x", fix_commands=[])]}},
    ])
    t = run_student_rollout("semptom", chat=lambda m: next(script), executor=ex)
    assert ex.calls == [("get_vlans", {"device": "leaf1"})]
    assert t.diagnosis is not None


def test_exam_rollout_selection():
    from datagen import exam_run, student, teacher
    assert exam_run.pick_rollout("sonnet") is teacher.run_rollout
    assert exam_run.pick_rollout("kestrel:v1") is student.run_student_rollout
    assert exam_run.pick_rollout("qwen3:8b") is student.run_student_rollout
