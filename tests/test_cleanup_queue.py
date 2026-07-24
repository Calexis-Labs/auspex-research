"""Temizlik turu secim kurali: pass'i olan tekrar KOSMAZ, skipped bilerek atlanir."""

from datagen.cleanup_queue import select_retries


def _e(sid, k=0, seed=1, cls="svi_down"):
    return {"scenario_id": sid, "k_index": k, "topo_seed": seed,
            "fault_class": cls, "symptom": "s"}


def _r(sid, verdict):
    return {"scenario_id": sid, "verdict": verdict}


def test_pass_scenarios_not_retried():
    entries = [_e("a"), _e("b")]
    rows = [_r("a", "pass"), _r("b", "fail")]
    assert [e["scenario_id"] for e in select_retries(entries, rows)] == ["b"]


def test_best_of_k_wins():
    # ayni senaryonun bir tekrari pass ise fail'i tekrar kosulmaz
    entries = [_e("a", k=0), _e("a", k=1)]
    rows = [_r("a", "fail"), _r("a", "pass")]
    assert select_retries(entries, rows) == []


def test_partial_and_error_are_retried_skipped_is_not():
    entries = [_e("p"), _e("e"), _e("s")]
    rows = [_r("p", "partial"), _r("e", "error"), _r("s", "skipped")]
    got = {e["scenario_id"] for e in select_retries(entries, rows)}
    assert got == {"p", "e"}


def test_duplicate_queue_lines_not_duplicated():
    entries = [_e("a"), _e("a")]  # sizinti-tekrari gibi cift satir
    rows = [_r("a", "fail")]
    assert len(select_retries(entries, rows)) == 1
