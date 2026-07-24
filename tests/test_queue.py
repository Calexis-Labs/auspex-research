"""Kuyruk + lane sozlesmesi (canli lab GEREKMEZ):
- queue_build: requires eslestirme (sahte registry), gruplama ardisikligi,
  k tekrar, determinizm, cursor sifirlama
- symptoms: bank-first render (scenario_bank varsa oradan, yoksa TEMPLATES)
- lanes saf kisimlar: group_by_seed, GroupClaimer (kilit/dispatch),
  lane kimligi, run_scenario durum makinesi (sahte health/rollout ile)
"""

import json
import random
from dataclasses import dataclass

import pytest

from datagen import symptoms
from datagen.lanes import (
    GroupClaimer,
    InfraError,
    error_row,
    group_by_seed,
    lane_env,
    lane_lab_name,
    lane_mgmt_subnet,
    lane_spec,
    load_queue,
    make_row,
    run_scenario,
)
from datagen.queue_build import build_queue, compatible_faults, parse_seed_range, write_queue
from datagen.run_batch import legacy_entries
from datagen.teacher import Trace
from datagen.verifier import Verdict
from lab.faults import FAULTS, matches
from lab.topo import build_spec

# ---------------------------------------------------------------- sahteler


class FakeFault:
    def __init__(self, requires: dict):
        self.requires = requires


FAKE_FAULTS = {
    "any_world": FakeFault({}),
    "needs_static": FakeFault({"static": True}),
    "needs_pc": FakeFault({"portchannel": True}),
    "impossible": FakeFault({"boyle_bir_feature_yok": True}),
}


def fake_symptom(fault_class: str, rng: random.Random) -> str:
    return f"sym-{fault_class}-{rng.randint(0, 9)}"


@dataclass
class FakeReport:
    ok: bool

    def render(self) -> str:
        return "(fake health report)"


class RecordingPE:
    def __init__(self):
        self.calls: list[tuple] = []

    def eos_config(self, device: str, *lines: str) -> None:
        self.calls.append(("eos_config", device, lines))

    def host_cmd(self, device: str, command: str) -> None:
        self.calls.append(("host_cmd", device, command))


def fake_trace(symptom: str) -> Trace:
    return Trace(symptom=symptom, model="fake", diagnosis={"fault_class": "x"}, n_tool_calls=2)


ENTRY = {
    "scenario_id": "s0-interface_admin_down-0001",
    "topo_seed": 0,
    "fault_class": "interface_admin_down",
    "symptom": "sunuculara erisim yok",
    "k_index": 0,
}

# eski batch satir semasi — make_row/error_row bunun ustkumesini uretmeli
LEGACY_ROW_KEYS = {
    "rollout_id", "fault", "ground_truth", "symptom", "diagnosis", "verdict",
    "verdict_reasons", "n_tool_calls", "num_turns", "usage", "cost_usd",
    "duration_s", "error", "model", "events",
}
NEW_ROW_KEYS = LEGACY_ROW_KEYS | {"scenario_id", "lane", "topo_seed", "k_index", "ts"}


# ---------------------------------------------------------------- queue_build

def test_queue_respects_requires_with_fake_registry():
    seeds = list(range(1, 16))
    entries = build_queue(
        30, seeds, k=1, faults=FAKE_FAULTS, rng=random.Random(1), symptom_of=fake_symptom,
    )
    assert entries
    for e in entries:
        spec = build_spec(e["topo_seed"])
        assert matches(FAKE_FAULTS[e["fault_class"]].requires, spec)
    assert all(e["fault_class"] != "impossible" for e in entries)


def test_compatible_faults_filters_by_features():
    spec = build_spec(0)          # tum feature'lar False
    names = compatible_faults(spec, FAKE_FAULTS)
    assert names == ["any_world"]


def test_queue_groups_same_seed_consecutively():
    entries = build_queue(
        20, list(range(1, 8)), k=2, faults=FAKE_FAULTS,
        rng=random.Random(2), symptom_of=fake_symptom,
    )
    seen_runs: list[int] = []
    for e in entries:
        if not seen_runs or seen_runs[-1] != e["topo_seed"]:
            seen_runs.append(e["topo_seed"])
    assert len(seen_runs) == len(set(seen_runs)), "ayni topo_seed ayrik iki kosuda"


def test_queue_k_repetition_and_counts():
    k = 3
    entries = build_queue(
        7, list(range(1, 6)), k=k, faults=FAKE_FAULTS,
        rng=random.Random(3), symptom_of=fake_symptom,
    )
    assert len(entries) == 7 * k
    by_sid: dict[str, list[int]] = {}
    for e in entries:
        by_sid.setdefault(e["scenario_id"], []).append(e["k_index"])
    for k_indices in by_sid.values():
        assert k_indices == list(range(k))


def test_queue_deterministic_for_same_rng():
    kw = dict(faults=FAKE_FAULTS, symptom_of=fake_symptom)
    q1 = build_queue(10, [1, 2, 3], k=2, rng=random.Random(5), **kw)
    q2 = build_queue(10, [1, 2, 3], k=2, rng=random.Random(5), **kw)
    assert q1 == q2


def test_queue_with_real_registry_matches_requires():
    entries = build_queue(12, list(range(0, 10)), k=1, rng=random.Random(0))
    available = symptoms.available_classes()
    for e in entries:
        assert matches(FAULTS[e["fault_class"]].requires, build_spec(e["topo_seed"]))
        assert e["fault_class"] in available     # semptomu olmayan sinif kuyruga giremez
        assert e["symptom"]                      # bank yoksa TEMPLATES'ten dolar


def test_default_faults_excludes_symptomless_classes():
    from datagen.queue_build import default_faults

    usable = default_faults()
    assert set(usable) <= set(FAULTS)
    assert set(usable) <= symptoms.available_classes()
    assert "interface_admin_down" in usable      # TEMPLATES'te var


def test_queue_no_compatible_seed_raises():
    with pytest.raises(ValueError):
        build_queue(5, [0], k=1, faults={"impossible": FakeFault({"yok": True})},
                    symptom_of=fake_symptom)


def test_parse_seed_range():
    assert parse_seed_range("2:5") == [2, 3, 4]
    with pytest.raises(SystemExit):
        parse_seed_range("5:5")
    with pytest.raises(SystemExit):
        parse_seed_range("abc")


def test_write_queue_resets_cursor(tmp_path):
    out = tmp_path / "queue.jsonl"
    cursor = out.with_suffix(".cursor")
    cursor.write_text("3")
    entries = [{"scenario_id": "a", "topo_seed": 1, "fault_class": "x", "symptom": "s", "k_index": 0}]
    write_queue(entries, out)
    assert not cursor.exists()
    assert load_queue(out) == entries


# ---------------------------------------------------------------- symptoms bank-first

def test_load_bank_missing_and_broken(tmp_path):
    assert symptoms.load_bank(tmp_path / "yok.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{gecersiz json")
    assert symptoms.load_bank(broken) == {}
    not_dict = tmp_path / "list.json"
    not_dict.write_text("[1,2]")
    assert symptoms.load_bank(not_dict) == {}


def test_render_prefers_bank(tmp_path, monkeypatch):
    bank = tmp_path / "symptoms_v1.json"
    bank.write_text(json.dumps({"interface_admin_down": ["bankadan semptom"]}))
    monkeypatch.setattr(symptoms, "BANK_PATH", bank)
    assert symptoms.render("interface_admin_down", random.Random(0)) == "bankadan semptom"


def test_render_falls_back_to_templates(tmp_path, monkeypatch):
    bank = tmp_path / "symptoms_v1.json"
    bank.write_text(json.dumps({"baska_sinif": ["x"]}))    # aranan sinif bankada yok
    monkeypatch.setattr(symptoms, "BANK_PATH", bank)
    out = symptoms.render("interface_admin_down", random.Random(0))
    assert out in symptoms.TEMPLATES["interface_admin_down"]
    with pytest.raises(KeyError):
        symptoms.render("hic_yok", random.Random(0))


# ---------------------------------------------------------------- lanes: saf kisimlar

def _q(seed: int, i: int) -> dict:
    return {"scenario_id": f"s{seed}-x-{i:04d}", "topo_seed": seed,
            "fault_class": "any", "symptom": "s", "k_index": 0}


def test_group_by_seed_consecutive_runs():
    entries = [_q(1, 1), _q(1, 2), _q(7, 3), _q(7, 4), _q(1, 5)]
    groups = group_by_seed(entries)
    assert [len(g) for g in groups] == [2, 2, 1]
    assert [g[0]["topo_seed"] for g in groups] == [1, 7, 1]


def test_group_claimer_hands_out_each_group_once(tmp_path):
    qp = tmp_path / "queue.jsonl"
    groups = [[_q(1, 1), _q(1, 2)], [_q(2, 3)], [_q(3, 4)]]
    a = GroupClaimer(qp, groups)
    b = GroupClaimer(qp, groups)              # ikinci lane'i taklit eder (ayni cursor)
    assert a.remaining() == 4
    got = [a.claim(), b.claim(), a.claim()]
    assert [c.index for c in got] == [0, 1, 2]
    assert got[0].group == groups[0]
    assert a.claim() is None and b.claim() is None
    assert a.remaining() == 0


def test_lane_identity():
    assert lane_lab_name(0) == "netagent0"
    assert lane_mgmt_subnet(0) == "192.168.124.0/24"
    assert lane_mgmt_subnet(2) == "192.168.126.0/24"
    spec = lane_spec(1, 5)
    assert spec.name == "netagent1"
    assert spec.mgmt_subnet == "192.168.125.0/24"
    assert spec.seed == 5
    assert lane_env(spec) == {
        "NETAGENT_LAB_NAME": "netagent1",
        "NETAGENT_TOPO_SEED": "5",
        "NETAGENT_MGMT_SUBNET": "192.168.125.0/24",
    }


def test_lane_specs_do_not_collide():
    a, b = lane_spec(0, 3), lane_spec(1, 3)
    assert a.container_name("x") != b.container_name("x")
    mgmt_a = {nd["mgmt_ipv4"] for nd in a.ceos_nodes.values()}
    mgmt_b = {nd["mgmt_ipv4"] for nd in b.ceos_nodes.values()}
    assert not mgmt_a & mgmt_b


# ---------------------------------------------------------------- run_scenario durum makinesi

def test_run_scenario_happy_path():
    spec = build_spec(0)
    pe = RecordingPE()
    row = run_scenario(
        ENTRY, spec, pe, model="fake", lane=1,
        health=lambda s, attempts=8: FakeReport(True),
        rollout=lambda symptom, model: fake_trace(symptom),
        verifier=lambda diag, gt: Verdict("pass"),
        sleep=lambda s: None,
    )
    assert set(row) == NEW_ROW_KEYS
    assert row["verdict"] == "pass"
    assert row["lane"] == 1 and row["topo_seed"] == 0
    assert row["rollout_id"] == f"{ENTRY['scenario_id']}#1"
    # inject + revert privileged yoldan gecti
    assert len(pe.calls) == 2


def test_run_scenario_baseline_unhealthy_no_inject():
    pe = RecordingPE()
    with pytest.raises(InfraError) as exc:
        run_scenario(
            ENTRY, build_spec(0), pe,
            health=lambda s, attempts=8: FakeReport(False),
            rollout=lambda symptom, model: fake_trace(symptom),
            verifier=lambda diag, gt: Verdict("pass"),
            sleep=lambda s: None,
        )
    assert exc.value.row is None
    assert pe.calls == []                     # baseline bozukken inject yapilmaz


def test_run_scenario_post_revert_unhealthy_carries_row():
    reports = iter([FakeReport(True), FakeReport(False)])
    pe = RecordingPE()
    with pytest.raises(InfraError) as exc:
        run_scenario(
            ENTRY, build_spec(0), pe,
            health=lambda s, attempts=8: next(reports),
            rollout=lambda symptom, model: fake_trace(symptom),
            verifier=lambda diag, gt: Verdict("partial", ("eksik",)),
            sleep=lambda s: None,
        )
    row = exc.value.row
    assert row is not None and row["verdict"] == "partial"
    assert len(pe.calls) == 2                 # inject + revert tamamlandi


def test_run_scenario_reverts_when_rollout_raises():
    pe = RecordingPE()

    def boom(symptom, model):
        raise RuntimeError("rollout patladi")

    with pytest.raises(RuntimeError):
        run_scenario(
            ENTRY, build_spec(0), pe,
            health=lambda s, attempts=8: FakeReport(True),
            rollout=boom,
            verifier=lambda diag, gt: Verdict("pass"),
            sleep=lambda s: None,
        )
    assert len(pe.calls) == 2                 # revert yine de calisti


def test_run_scenario_deterministic_injection_target():
    def once() -> str:
        pe = RecordingPE()
        run_scenario(
            ENTRY, build_spec(0), pe,
            health=lambda s, attempts=8: FakeReport(True),
            rollout=lambda symptom, model: fake_trace(symptom),
            verifier=lambda diag, gt: Verdict("pass"),
            sleep=lambda s: None,
        )
        return str(pe.calls)

    assert once() == once()                   # rng scenario_id+k_index'ten turetilir


def test_error_row_schema():
    row = error_row(ENTRY, 2, "deploy hatasi: x")
    assert set(row) == NEW_ROW_KEYS
    assert row["verdict"] == "error"
    assert row["lane"] == 2
    assert row["error"].startswith("deploy hatasi")


def test_make_row_handles_groundtruth_list():
    from lab.faults import GroundTruth

    gt = [GroundTruth(device="leaf1", fault_class="x", root_cause="r", fix_commands=["f"], key_terms=["k"])]
    row = make_row(ENTRY, None, gt, fake_trace("s"), Verdict("fail", ("neden",)))
    assert isinstance(row["ground_truth"], list)
    assert row["ground_truth"][0]["device"] == "leaf1"


# ---------------------------------------------------------------- run_lane iskeleti (sahte lab)

def _fake_lane_world(monkeypatch, healthy: bool = True):
    """run_lane'i canli lab olmadan kosturmak icin tum dis temaslari sahtele."""
    import datagen.lanes as lanes

    calls = {"deploy": [], "destroy": [], "wait": []}
    monkeypatch.setattr(lanes, "SETTLE_S", 0)
    monkeypatch.setattr(lanes, "PrivilegedExec", lambda spec: RecordingPE())
    monkeypatch.setattr(lanes, "run_rollout", lambda symptom, model: fake_trace(symptom))
    monkeypatch.setattr(lanes.lab_deploy, "deploy", lambda spec, *a, **k: calls["deploy"].append(spec.name))
    monkeypatch.setattr(lanes.lab_deploy, "wait_ready", lambda spec, *a, **k: calls["wait"].append(spec.name))
    monkeypatch.setattr(lanes.lab_deploy, "destroy", lambda spec, *a, **k: calls["destroy"].append(spec.name))
    monkeypatch.setattr(lanes.lab_deploy, "health_check",
                        lambda spec, attempts=8, **k: FakeReport(healthy))
    return calls


def _write_test_queue(tmp_path, seeds: list[int]) -> "Path":
    from pathlib import Path

    entries = [
        {"scenario_id": f"s{seed}-interface_admin_down-{i:04d}", "topo_seed": seed,
         "fault_class": "interface_admin_down", "symptom": "sunucu erisimi yok", "k_index": 0}
        for i, seed in enumerate(seeds)
    ]
    qp = tmp_path / "queue.jsonl"
    write_queue(entries, qp)
    return qp


def test_run_lane_waits_and_retries_on_limit(tmp_path, monkeypatch):
    """Limit hatasi: senaryo 'error' olarak kaydedilmez; beklenip AYNI senaryo
    tekrar denenir ve nihayetinde basarili satir uretilir."""
    import datagen.lanes as lanes
    from datagen.teacher import Trace
    from lab.faults import GroundTruth

    _fake_lane_world(monkeypatch, healthy=True)
    monkeypatch.setattr(lanes, "LIMIT_WAIT_S", 42)     # SETTLE_S=0'dan ayirt edilebilir sentinel
    slept = []
    monkeypatch.setattr(lanes.time, "sleep", lambda s: slept.append(s))

    # inject/revert gercek fault yerine sabit — sadece rollout limit davranisini test et
    gt = GroundTruth(device="leaf1", fault_class="interface_admin_down",
                     root_cause="r", fix_commands=["f"], key_terms=[])
    fake_fault = type("F", (), {"inject": lambda self, pe, spec, rng: gt,
                                "revert": lambda self, pe, spec: None})()
    monkeypatch.setitem(lanes.FAULTS, "interface_admin_down", fake_fault)

    calls = {"n": 0}

    def rollout(symptom, model):
        calls["n"] += 1
        if calls["n"] < 3:                      # ilk 2 cagri limit, 3.'de gecer
            return Trace(symptom=symptom, model=model, error="You've hit your session limit · resets 12:50pm")
        return Trace(symptom=symptom, model=model, diagnosis={"fault_class": "interface_admin_down", "device": "leaf1"}, n_tool_calls=3)

    monkeypatch.setattr(lanes, "run_rollout", rollout)

    qp = _write_test_queue(tmp_path, seeds=[0])
    rc = lanes.run_lane(0, qp, model="fake", traces_dir=tmp_path / "traces")
    assert rc == 0
    assert calls["n"] == 3                       # 2 limit + 1 basarili
    assert slept.count(42) == 2                    # 2 kez limit beklemesi
    out_file = next((tmp_path / "traces").glob("batch_lane0_*.jsonl"))
    rows = [json.loads(l) for l in out_file.read_text().splitlines()]
    assert len(rows) == 1                         # cop 'error' satiri YOK, tek gercek satir
    assert rows[0]["verdict"] != "error"


def test_run_lane_end_to_end_with_fakes(tmp_path, monkeypatch):
    from datagen.lanes import run_lane

    calls = _fake_lane_world(monkeypatch, healthy=True)
    qp = _write_test_queue(tmp_path, seeds=[1, 1, 2])     # 2 grup: [1,1] ve [2]
    traces = tmp_path / "traces"

    rc = run_lane(0, qp, model="fake", traces_dir=traces)
    assert rc == 0
    assert calls["deploy"] == ["netagent0", "netagent0"]  # grup basina tek deploy
    assert calls["destroy"] == ["netagent0", "netagent0"]

    out_files = list(traces.glob("batch_lane0_*.jsonl"))
    assert len(out_files) == 1
    rows = [json.loads(l) for l in out_files[0].read_text().splitlines()]
    assert len(rows) == 3
    assert all(r["lane"] == 0 for r in rows)
    assert [r["topo_seed"] for r in rows] == [1, 1, 2]
    assert all(set(r) >= NEW_ROW_KEYS for r in rows)

    status = json.loads((traces / "lane0_status.json").read_text())
    assert status["state"] == "done" and status["rows_done"] == 3
    assert (traces / "lane0.log").exists()


def test_run_lane_fatal_after_consecutive_infra_failures(tmp_path, monkeypatch):
    from datagen.lanes import run_lane

    _fake_lane_world(monkeypatch, healthy=False)          # health hicbir zaman gelmez
    qp = _write_test_queue(tmp_path, seeds=[1, 2, 3])     # 3 grup -> 3 ardisik hata
    traces = tmp_path / "traces"

    rc = run_lane(0, qp, model="fake", max_infra=3, traces_dir=traces)
    assert rc == 1
    log = (traces / "lane0.log").read_text()
    assert "FATAL" in log
    status = json.loads((traces / "lane0_status.json").read_text())
    assert status["state"] == "fatal"
    rows = [json.loads(l) for f in traces.glob("batch_lane0_*.jsonl")
            for l in f.read_text().splitlines()]
    assert rows and all(r["verdict"] == "error" for r in rows)


def test_run_lane_two_claimers_split_queue(tmp_path, monkeypatch):
    """Iki lane ayni kuyrugu paylassin: her grup tam bir kez kosulur."""
    from datagen.lanes import run_lane

    _fake_lane_world(monkeypatch, healthy=True)
    qp = _write_test_queue(tmp_path, seeds=[1, 2, 3, 4])
    traces = tmp_path / "traces"

    rc0 = run_lane(0, qp, model="fake", traces_dir=traces)
    rc1 = run_lane(1, qp, model="fake", traces_dir=traces)  # kuyruk coktan bitti
    assert rc0 == 0 and rc1 == 0
    rows = [json.loads(l) for f in traces.glob("batch_lane*.jsonl")
            for l in f.read_text().splitlines()]
    assert sorted(r["scenario_id"] for r in rows) == sorted(
        f"s{seed}-interface_admin_down-{i:04d}" for i, seed in enumerate([1, 2, 3, 4])
    )


# ---------------------------------------------------------------- run_batch geriye uyum

def test_legacy_entries_preserve_old_rollout_ids():
    names = ["interface_admin_down", "wrong_host_gateway"]
    entries = legacy_entries(names, k=2, seed=42)
    assert len(entries) == 4
    rids = [f"{e['scenario_id']}#{e['k_index'] + 1}" for e in entries]
    assert rids == [
        "interface_admin_down#1", "interface_admin_down#2",
        "wrong_host_gateway#1", "wrong_host_gateway#2",
    ]
    # semptom eski formulle ayni rng tohumundan gelir — deterministik
    assert entries == legacy_entries(names, k=2, seed=42)
    for e in entries:
        assert e["topo_seed"] == 0
